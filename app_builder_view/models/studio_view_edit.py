# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One row per view edit, holding the arch as it was before -- and after.

View edits are live -- there is no reload to batch behind, so there is no
pending tray and no Apply. That is the honest design, but it means a mistake is
immediately everybody's mistake, on a shared database. Undo is what makes that
bargain fair rather than merely fast; redo is what makes undo safe to reach
for, since an undo that cannot itself be taken back is a second way to lose
work.

Storing the whole previous arch rather than an inverse operation is deliberate.
An inverse has to be derived per operation type and is wrong in the cases that
matter most -- removing a node whose attributes came from three inheriting
views, say -- whereas restoring bytes is exact for every operation the editor
has now and every one it grows later. Arch strings are small; correctness here
is worth more than the storage. The arch *after* is kept for the same reason:
redo puts back exactly what the edit produced, not a replay of it.

The stack is per base view, not per user. Two people editing one form share
one history, and the entries say who made each change so that undoing
somebody else's edit is a decision rather than a surprise.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StudioViewEdit(models.Model):
    _name = "studio.view.edit"
    _inherit = ["studio.security.mixin"]
    _description = "Studio View Edit"
    _order = "id desc"

    view_id = fields.Many2one(
        "ir.ui.view",
        required=False,
        ondelete="set null",
        index=True,
        help="The view that was written -- the patch, when editing a foreign "
        "view, and the view itself when the package owns it. Empty once "
        "undoing the edit that created the patch has removed it; redo then "
        "recreates the patch and fills this in again.",
    )
    base_view_id = fields.Many2one(
        "ir.ui.view",
        required=True,
        ondelete="cascade",
        index=True,
        help="The view the user was looking at, which is what the editor "
        "undoes against.",
    )
    package_id = fields.Many2one("studio.package", required=True, ondelete="cascade")
    summary = fields.Char(readonly=True)
    arch_before = fields.Text(
        readonly=True,
        help="The written view's arch before this edit. Empty when the edit "
        "created the view, in which case undoing removes it.",
    )
    arch_after = fields.Text(
        readonly=True,
        help="The written view's arch as this edit left it, which is what "
        "redo puts back.",
    )
    created_view = fields.Boolean(
        readonly=True,
        help="Whether this edit brought the written view into existence.",
    )
    undone = fields.Boolean(default=False, readonly=True)
    superseded = fields.Boolean(
        default=False,
        readonly=True,
        help="An undone edit that a later edit has made unreachable: redoing "
        "it would have to discard that later edit, so it is no longer offered.",
    )

    @api.model
    def record(
        self, base_view, target, package, summary, arch_before, created, arch_after=None
    ):
        """Remember what a view looked like before an edit, and after.

        A new edit ends the redo tail. Whatever was undone before it could
        only be put back over the top of the new edit, and "redo" silently
        throwing away the last thing you did is the opposite of what the word
        promises -- so those entries are marked superseded and stay in the
        table as a record of what happened.
        """
        self.sudo().search(
            [
                ("base_view_id", "=", base_view.id),
                ("undone", "=", True),
                ("superseded", "=", False),
            ]
        ).write({"superseded": True})
        return self.sudo().create(
            {
                "view_id": target.id,
                "base_view_id": base_view.id,
                "package_id": package.id,
                "summary": summary,
                "arch_before": arch_before or "",
                "arch_after": arch_after or "",
                "created_view": created,
            }
        )

    @api.model
    def history_for(self, base_view_id, limit=20):
        """What has been done to this view, newest first."""
        self._assert_studio_user()
        entries = self.sudo().search(
            [("base_view_id", "=", base_view_id), ("undone", "=", False)],
            limit=limit,
        )
        return [
            {"id": e.id, "summary": e.summary, "created_view": e.created_view}
            for e in entries
        ]

    def _entry(self):
        return {
            "id": self.id,
            "summary": self.summary,
            "author": self.create_uid.display_name,
        }

    @api.model
    def stack_for(self, base_view_id):
        """Both stacks for a view, and the version the client should hold.

        Undo is newest first. Redo is *most recently undone* first, which in
        id order is the oldest: undo only ever takes the newest live edit, so
        the entries still eligible for redo are always the tail of the history
        and the one to put back next is the earliest of them. The version
        travels with the stacks so that a client refreshing its buttons also
        refreshes what its next edit will be checked against.
        """
        self._assert_studio_user()
        domain = [("base_view_id", "=", base_view_id)]
        undo = self.sudo().search(domain + [("undone", "=", False)])
        redo = self.sudo().search(
            domain + [("undone", "=", True), ("superseded", "=", False)],
            order="id asc",
        )
        return {
            "undo": [e._entry() for e in undo],
            "redo": [e._entry() for e in redo],
            "arch_version": self.env["studio.view.editor"].arch_version(base_view_id),
        }

    def _redoable(self):
        """The one entry of this base view that redo may put back next."""
        return self.sudo().search(
            [
                ("base_view_id", "=", self.base_view_id.id),
                ("undone", "=", True),
                ("superseded", "=", False),
            ],
            order="id asc",
            limit=1,
        )

    def action_undo(self, expected_arch_version=None):
        """Put the view back as it was, and write the package out again.

        Only the most recent edit can be undone, and that restriction is not
        laziness: restoring an older arch would silently discard every edit made
        after it, which is the opposite of what "undo" promises.

        ``expected_arch_version`` is checked first, like any other mutation:
        an undo aimed at a view somebody else has since edited would take back
        *their* change, not the one on the button.
        """
        self._assert_studio_manager()
        self.ensure_one()
        editor = self.env["studio.view.editor"]
        editor._assert_arch_version(self.base_view_id, expected_arch_version)
        latest = self.sudo().search(
            [("base_view_id", "=", self.base_view_id.id), ("undone", "=", False)],
            limit=1,
        )
        if latest != self:
            raise UserError(
                _(
                    "Only the most recent change can be undone -- putting an "
                    "older version back would quietly throw away everything "
                    "done since."
                )
            )

        package = self.package_id
        view = self.view_id or self.env["studio.view.editor"]._find_extension(
            self.base_view_id, package
        )
        self.undone = True
        if not view:
            # Somebody removed the written view by other means. There is
            # nothing to put back, and the edit's effect is already gone, so
            # marking it undone is the truthful state -- and it keeps the stack
            # from being stuck on an entry that can never be undone.
            return True
        if self.created_view:
            # The edit brought the patch into being, so undoing it means the
            # patch should stop existing rather than becoming an empty one that
            # still loads. This row survives it -- view_id is set null rather
            # than cascaded -- because redo needs to know what to recreate.
            view.unlink()
        else:
            view.write({"arch": self.arch_before})
        if package.writable:
            package.action_write_files()
        return True

    def action_redo(self, expected_arch_version=None):
        """Put an undone edit back, and write the package out again.

        Only the most recently undone edit that no later edit has superseded:
        redoing an older one would put its arch over the top of everything
        undone after it, which is the same silent discard undo refuses.

        When the edit was the one that created the patch, undoing it removed
        the patch entirely, so redo brings the extension back through the same
        path that made it the first time and fills it with the arch this edit
        left behind -- byte for byte, not a replay.
        """
        self._assert_studio_manager()
        self.ensure_one()
        editor = self.env["studio.view.editor"]
        base_view = self.base_view_id
        editor._assert_arch_version(base_view, expected_arch_version)
        if self._redoable() != self:
            raise UserError(
                _(
                    "Only the most recently undone change can be redone -- and "
                    "not once a newer change has been made over it."
                )
            )

        package = self.package_id
        # The patch is shared by every edit of this (view, package), so undoing
        # the edit that created it emptied view_id on *all* of them. A later
        # redo may already have brought it back; take that one before making
        # another.
        view = self.view_id or editor._find_extension(base_view, package)
        if not view:
            if not self.created_view:
                raise UserError(
                    _(
                        "The view this change was made to no longer exists, so "
                        "the change cannot be put back."
                    )
                )
            view = editor._get_or_create_extension(
                base_view, package, write_files=False
            )
        self.view_id = view
        view.write({"arch": self.arch_after})
        self.undone = False
        if package.writable:
            package.action_write_files()
        return True

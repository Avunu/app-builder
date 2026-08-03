# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One row per view edit, holding the arch as it was before.

View edits are live -- there is no reload to batch behind, so there is no
pending tray and no Apply. That is the honest design, but it means a mistake is
immediately everybody's mistake, on a shared database. Undo is what makes that
bargain fair rather than merely fast.

Storing the whole previous arch rather than an inverse operation is deliberate.
An inverse has to be derived per operation type and is wrong in the cases that
matter most -- removing a node whose attributes came from three inheriting
views, say -- whereas restoring bytes is exact for every operation the editor
has now and every one it grows later. Arch strings are small; correctness here
is worth more than the storage.
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
        required=True,
        ondelete="cascade",
        index=True,
        help="The view that was written -- the patch, when editing a foreign "
        "view, and the view itself when the package owns it.",
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
    created_view = fields.Boolean(
        readonly=True,
        help="Whether this edit brought the written view into existence.",
    )
    undone = fields.Boolean(default=False, readonly=True)

    @api.model
    def record(self, base_view, target, package, summary, arch_before, created):
        """Remember what a view looked like before an edit."""
        return self.sudo().create(
            {
                "view_id": target.id,
                "base_view_id": base_view.id,
                "package_id": package.id,
                "summary": summary,
                "arch_before": arch_before or "",
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

    def action_undo(self):
        """Put the view back as it was, and write the package out again.

        Only the most recent edit can be undone, and that restriction is not
        laziness: restoring an older arch would silently discard every edit made
        after it, which is the opposite of what "undo" promises.
        """
        self._assert_studio_manager()
        self.ensure_one()
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

        view = self.view_id
        # Read before any unlink: this row cascades off view_id, so removing
        # the patch takes the history entry with it and anything read from
        # `self` afterwards raises MissingError.
        package = self.package_id
        self.undone = True
        if self.created_view:
            # The edit brought the patch into being, so undoing it means the
            # patch should stop existing rather than becoming an empty one that
            # still loads.
            view.unlink()
        else:
            view.write({"arch": self.arch_before})
        if package.writable:
            package.action_write_files()
        return True

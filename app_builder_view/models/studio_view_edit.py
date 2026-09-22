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

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    # Only for annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.addons.base.models.ir_ui_view import View
    from odoo.addons.app_builder_base.models.studio_package import StudioPackage

    # `studio_view_edit.py` <-> `studio_view_editor.py`: a real circular
    # reference (TYPING.md's own dependency map), this -- the shallower --
    # side converted first, the same resolution `studio_package.py`'s own two
    # circular pairs already established. `studio.view.editor` therefore
    # stays a plain `self.env[...]` lookup at every call site, cast to this
    # `TYPE_CHECKING`-only class rather than looked up through
    # `typed.model()` -- that helper reads `cls._name` at *runtime*, which
    # needs a real binding this migration does not want to create across an
    # open cycle. Relative, not `odoo.addons.app_builder_view....`: this file
    # and `studio_view_editor.py` are both in this same addon, and a same-
    # addon import must stay relative or it resolves under a different
    # pyright module identity (see `studio_package.py`'s own `TYPE_CHECKING`
    # block for the traced, first-hand version of this).
    from .studio_view_editor import StudioViewEditor


class HistoryEntryJSON(TypedDict):
    """One entry of ``history_for``'s own list, newest first."""

    id: int
    summary: str
    created_view: bool


class UndoRedoEntryJSON(TypedDict):
    """One entry of ``_entry()``'s own dict, as ``stack_for`` embeds it in
    both its ``undo`` and ``redo`` lists -- a different shape than
    ``history_for``'s own (``author`` instead of ``created_view``), not the
    same wire type under a different name."""

    id: int
    summary: str
    author: str


class StackForJSON(TypedDict):
    """Both stacks and the version the client should hold, as ``stack_for``
    returns them."""

    undo: list[UndoRedoEntryJSON]
    redo: list[UndoRedoEntryJSON]
    arch_version: str


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
        self,
        base_view: View,
        target: View,
        package: StudioPackage,
        summary: str,
        arch_before: str | None,
        created: bool,
        arch_after: str | None = None,
    ) -> StudioViewEdit:
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
        vals = {
            "view_id": target.id,
            "base_view_id": base_view.id,
            "package_id": package.id,
            "summary": summary,
            "arch_before": arch_before or "",
            "arch_after": arch_after or "",
            "created_view": created,
        }
        # `@api.model_create_multi` (`odoo/api.py`) is a bare passthrough
        # decorator that does not widen `create()`'s own declared `list
        # [ValuesType]`-only signature to also cover the single-dict calling
        # form it genuinely accepts at runtime -- the documented stub gap
        # (see `studio_package.py:_sync_file_records`), kept as the exact
        # original single-dict call rather than rewritten to `create([vals])`.
        return self.sudo().create(vals)  # pyright: ignore[reportArgumentType]

    @api.model
    def history_for(self, base_view_id: int, limit: int = 20) -> list[HistoryEntryJSON]:
        """What has been done to this view, newest first."""
        typed.security(self)._assert_studio_user()
        entries = self.sudo().search(
            [("base_view_id", "=", base_view_id), ("undone", "=", False)],
            limit=limit,
        )
        return [
            {
                # `.id` is declared `IdType | Literal[False]` on `BaseModel`
                # itself (`odoo/models.py`) -- `NewId` covers an unsaved
                # record, never the case for a row just fetched by `search`.
                # Same "true by construction" cast as `studio_record_surface
                # .py`'s own `cast("int", record.id)`.
                "id": cast("int", e.id),
                # `summary` is not itself `required=True` (declared type `str
                # | Literal[False]`, the usual Char shape), but this file's
                # only writer -- `record()`, above -- always passes a real
                # `str` straight through with no `or ""` fallback, so it is
                # never actually the `Literal[False]` an unwritten Char reads
                # as. Same "true by construction, not provable from the
                # field's own declared type" cast as `studio_package.py`'s
                # required-field reads.
                "summary": cast("str", e.summary),
                "created_view": e.created_view,
            }
            for e in entries
        ]

    def _entry(self) -> UndoRedoEntryJSON:
        return {
            # Same `IdType | Literal[False]` -> `int` cast as `history_for`'s
            # own `e.id` above.
            "id": cast("int", self.id),
            "summary": cast("str", self.summary),
            # `create_uid` is added to every model at registry setup
            # (`models.py:_add_magic_fields`), never as a real class
            # attribute `BaseModel`/`Model` declares -- invisible to pyright
            # on `self` the same way `studio_record_surface.py`'s own
            # `record["active"]` documents for a field only some concrete
            # models carry. Subscripted, not `self.create_uid`, for the same
            # reason: `BaseModel.__getitem__`'s `str` overload is declared
            # `-> Any`, so this sidesteps the missing-attribute error
            # entirely rather than casting a read that would not type-check
            # in the first place.
            "author": cast("str", self["create_uid"].display_name),
        }

    @api.model
    def stack_for(self, base_view_id: int) -> StackForJSON:
        """Both stacks for a view, and the version the client should hold.

        Undo is newest first. Redo is *most recently undone* first, which in
        id order is the oldest: undo only ever takes the newest live edit, so
        the entries still eligible for redo are always the tail of the history
        and the one to put back next is the earliest of them. The version
        travels with the stacks so that a client refreshing its buttons also
        refreshes what its next edit will be checked against.
        """
        typed.security(self)._assert_studio_user()
        domain = [("base_view_id", "=", base_view_id)]
        undo = self.sudo().search(domain + [("undone", "=", False)])
        redo = self.sudo().search(
            domain + [("undone", "=", True), ("superseded", "=", False)],
            order="id asc",
        )
        editor = cast("StudioViewEditor", self.env["studio.view.editor"])
        return {
            "undo": [e._entry() for e in undo],
            "redo": [e._entry() for e in redo],
            "arch_version": editor.arch_version(base_view_id),
        }

    def _redoable(self) -> StudioViewEdit:
        """The one entry of this base view that redo may put back next."""
        return self.sudo().search(
            [
                ("base_view_id", "=", cast("View", self.base_view_id).id),
                ("undone", "=", True),
                ("superseded", "=", False),
            ],
            order="id asc",
            limit=1,
        )

    def action_undo(self, expected_arch_version: str | None = None) -> bool:
        """Put the view back as it was, and write the package out again.

        Only the most recent edit can be undone, and that restriction is not
        laziness: restoring an older arch would silently discard every edit made
        after it, which is the opposite of what "undo" promises.

        ``expected_arch_version`` is checked first, like any other mutation:
        an undo aimed at a view somebody else has since edited would take back
        *their* change, not the one on the button.
        """
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        editor = cast("StudioViewEditor", self.env["studio.view.editor"])
        editor._assert_arch_version(
            cast("View", self.base_view_id), expected_arch_version
        )
        latest = self.sudo().search(
            [
                ("base_view_id", "=", cast("View", self.base_view_id).id),
                ("undone", "=", False),
            ],
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

        package = cast("StudioPackage", self.package_id)
        view = cast("View", self.view_id) or cast(
            "StudioViewEditor", self.env["studio.view.editor"]
        )._find_extension(cast("View", self.base_view_id), package)
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

    def action_redo(self, expected_arch_version: str | None = None) -> bool:
        """Put an undone edit back, and write the package out again.

        Only the most recently undone edit that no later edit has superseded:
        redoing an older one would put its arch over the top of everything
        undone after it, which is the same silent discard undo refuses.

        When the edit was the one that created the patch, undoing it removed
        the patch entirely, so redo brings the extension back through the same
        path that made it the first time and fills it with the arch this edit
        left behind -- byte for byte, not a replay.
        """
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        editor = cast("StudioViewEditor", self.env["studio.view.editor"])
        base_view = cast("View", self.base_view_id)
        editor._assert_arch_version(base_view, expected_arch_version)
        if self._redoable() != self:
            raise UserError(
                _(
                    "Only the most recently undone change can be redone -- and "
                    "not once a newer change has been made over it."
                )
            )

        package = cast("StudioPackage", self.package_id)
        # The patch is shared by every edit of this (view, package), so undoing
        # the edit that created it emptied view_id on *all* of them. A later
        # redo may already have brought it back; take that one before making
        # another.
        view = cast("View", self.view_id) or editor._find_extension(base_view, package)
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

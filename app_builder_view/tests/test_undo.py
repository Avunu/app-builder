# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Undo, which is what makes live editing a fair bargain.

There is no Apply in the view editor because a view needs no reload, so an
edit is everybody's edit the moment it is made. That is honest, but only
tolerable if it can be taken back.

Restoring the previous arch wholesale, rather than inverting the operation, is
the point worth testing: it is exact for every operation the editor has and
every one it grows, including the ones whose inverse is ambiguous. Redo is
held to the same standard: it puts back the bytes the edit produced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.exceptions import BuilderStaleView
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_view_edit import BuilderViewEdit
from ..models.builder_view_editor import BuilderViewEditor

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs this at runtime, the same bargain every converted
    # model file's own `TYPE_CHECKING` block makes. `builder_package_id` is a
    # field from `builder.owned.mixin`, composed onto `ir.ui.view` only at the
    # registry level (`_inherit`), never as a real Python base of `View` --
    # same reasoning as `builder_view_editor.py`'s own uses of this cast.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )

LIST_ARCH = """
<list string="Demo">
    <field name="x_name"/>
</list>
"""


@tagged("post_install", "-at_install")
class TestUndo(BuilderCase):
    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.history = typed.model(self.env, BuilderViewEdit)
        self.package = self.make_package(name="x_undo_pkg")
        model_vals: dict[str, object] = {
            "name": "Undo Demo",
            "model": "x_undo_demo",
            "field_id": [
                Command.create(
                    {
                        "name": "x_name",
                        "ttype": "char",
                        "field_description": "Name",
                    }
                )
            ],
        }
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "builder.undo.test",
            "model": "x_undo_demo",
            "type": "list",
            "arch": LIST_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]
        # Owned by somebody else, so edits become patches -- the case where
        # undoing has to remove the patch rather than empty it.
        self.make_package(name="x_undo_owner").builder_capture(self.view)

    def _set(self, attrs):
        found = self.editor.locate_target(cast("int", self.view.id), {"kind": "root"})
        # `locate_target`'s own `LocateTargetJSON` is a `found`-discriminated
        # union (`builder_view_editor.py`); the root of a freshly created list
        # view always resolves, so this narrows rather than branches. `is
        # True`, not a bare truthy check: pyright only narrows a TypedDict
        # union on an explicit comparison against the discriminant's literal.
        assert found["found"] is True
        return self.editor.apply_operation(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {
                "type": "set_attributes",
                "xpath": found["xpath"],
                "position": "attributes",
                "attrs": attrs,
            },
        )

    # -- recording ---------------------------------------------------------

    def test_an_edit_is_recorded_with_a_readable_summary(self):
        self._set({"editable": "top"})
        entries = self.history.history_for(cast("int", self.view.id))
        self.assertEqual(len(entries), 1)
        self.assertIn("editable", entries[0]["summary"])

    def test_history_is_newest_first(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        entries = self.history.history_for(cast("int", self.view.id))
        self.assertIn("multi_edit", entries[0]["summary"])

    # -- undoing -----------------------------------------------------------

    def test_undoing_the_first_edit_removes_the_patch_entirely(self):
        """The edit brought the patch into being, so undoing it should leave no
        patch rather than an empty one that still loads."""
        self._set({"editable": "top"})
        patch = typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        self.assertTrue(patch)

        entry = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        entry.action_undo()

        self.assertFalse(
            typed.model(self.env, View).search([("inherit_id", "=", self.view.id)]),
            "an emptied patch would still be loaded and still be wrong",
        )

    def test_undoing_a_later_edit_restores_the_previous_arch(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        patch = typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        self.assertIn("multi_edit", cast("str", patch.arch))

        entry = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        entry.action_undo()

        patch.invalidate_recordset()
        self.assertNotIn("multi_edit", cast("str", patch.arch))
        self.assertIn("editable", cast("str", patch.arch), "the earlier edit survives")

    def test_an_undone_edit_leaves_the_history(self):
        self._set({"editable": "top"})
        entry = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        entry.action_undo()
        self.assertEqual(self.history.history_for(cast("int", self.view.id)), [])

    def test_only_the_most_recent_edit_can_be_undone(self):
        """Restoring an older arch would silently discard everything done
        since, which is the opposite of what undo promises."""
        self._set({"editable": "top"})
        first = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        self._set({"multi_edit": "1"})

        with raises(self, UserError) as caught:
            first.action_undo()
        self.assertIn("most recent", str(caught.exception))

    def test_undo_twice_walks_back_two_edits(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        for _ in range(2):
            entries = self.history.history_for(cast("int", self.view.id))
            self.history.browse(entries[0]["id"]).action_undo()
        self.assertFalse(
            typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        )

    def test_undo_against_a_stale_version_is_refused(self):
        """An undo aimed at a view somebody else has since edited would take
        back their change, not the one on the button."""
        self._set({"editable": "top"})
        entry = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        # Not `assertRaises`: Odoo's wraps the block in a savepoint that is
        # rolled back on the exception, so "nothing was undone" would hold
        # whatever the undo had done before refusing.
        try:
            entry.action_undo(expected_arch_version="not-what-the-server-has")
        except BuilderStaleView:  # pylint: disable=except-pass
            pass
        else:
            self.fail("a stale version has to be refused")
        self.assertFalse(entry.undone)
        patch = typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        self.assertIn("editable", cast("str", patch.arch), "nothing was undone")

    def test_undo_with_the_current_version_goes_through(self):
        self._set({"editable": "top"})
        entry = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        version = self.editor.arch_version(cast("int", self.view.id))
        entry.action_undo(expected_arch_version=version)
        self.assertTrue(entry.undone)

    # -- redoing -----------------------------------------------------------

    def _patch(self):
        return typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])

    def _latest(self):
        return self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )

    def test_undo_then_redo_restores_the_arch_byte_for_byte(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        after = self._patch().arch
        entry = self._latest()
        entry.action_undo()
        self._patch().invalidate_recordset()
        self.assertNotIn(
            "multi_edit", cast("str", self._patch().arch), "sanity: undone"
        )

        entry.action_redo()

        self._patch().invalidate_recordset()
        self.assertEqual(self._patch().arch, after)
        self.assertFalse(entry.undone)
        self.assertEqual(len(self.history.history_for(cast("int", self.view.id))), 2)

    def test_redo_after_undoing_the_creating_edit_recreates_the_patch(self):
        """Undoing the first edit removes the patch entirely, which used to
        cascade this row away and make redo impossible. Now the row survives
        with no view, and redo brings the extension back with the same arch.
        """
        self._set({"editable": "top"})
        old_patch = self._patch()
        old_id, after = old_patch.id, old_patch.arch
        entry = self._latest()
        entry.action_undo()
        self.assertFalse(self._patch(), "sanity: the patch is gone")
        self.assertTrue(entry.exists(), "the row must outlive the patch")
        self.assertFalse(entry.view_id)

        entry.action_redo()

        patch = self._patch()
        self.assertTrue(patch, "the extension is back")
        self.assertNotEqual(patch.id, old_id)
        self.assertEqual(patch.arch, after)
        self.assertEqual(entry.view_id, patch)
        self.assertEqual(
            cast("BuilderOwnedMixin", patch).builder_package_id, self.package
        )
        self.assertIn("editable", self.view.get_combined_arch())

    def test_a_new_edit_after_an_undo_supersedes_the_redo_tail(self):
        """Redo over the top of a newer edit would silently discard it, which
        is the same thing undo refuses to do."""
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        undone = self._latest()
        undone.action_undo()
        self.assertEqual(
            [
                e["id"]
                for e in self.history.stack_for(cast("int", self.view.id))["redo"]
            ],
            [undone.id],
            "sanity: redoable before the new edit",
        )

        self._set({"limit": "40"})

        self.assertEqual(self.history.stack_for(cast("int", self.view.id))["redo"], [])
        self.assertTrue(undone.superseded)
        with raises(self, UserError) as caught:
            undone.action_redo()
        self.assertIn("newer change", str(caught.exception))

    def test_redo_puts_back_the_most_recently_undone_first(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        second = self._latest()
        second.action_undo()
        first = self._latest()
        first.action_undo()

        stack = self.history.stack_for(cast("int", self.view.id))
        self.assertEqual([e["id"] for e in stack["redo"]], [first.id, second.id])
        with raises(self, UserError):
            second.action_redo()
        first.action_redo()
        second.action_redo()
        self.assertEqual(len(self.history.history_for(cast("int", self.view.id))), 2)

    def test_redo_against_a_stale_version_is_refused(self):
        self._set({"editable": "top"})
        entry = self._latest()
        entry.action_undo()
        try:
            entry.action_redo(expected_arch_version="stale")
        except BuilderStaleView:  # pylint: disable=except-pass
            pass
        else:
            self.fail("a stale version has to be refused")
        self.assertTrue(entry.undone)
        self.assertFalse(self._patch(), "nothing was redone")

    def test_the_stack_names_who_made_each_change(self):
        """The stack is per view, not per user: undoing somebody else's edit
        should be a decision, not a surprise."""
        self._set({"editable": "top"})
        stack = self.history.stack_for(cast("int", self.view.id))
        self.assertEqual(len(stack["undo"]), 1)
        self.assertEqual(stack["undo"][0]["author"], self.env.user.display_name)
        self.assertIn("editable", stack["undo"][0]["summary"])
        self.assertEqual(
            stack["arch_version"], self.editor.arch_version(cast("int", self.view.id))
        )

    # -- guarded like everything else --------------------------------------

    def test_a_plain_user_cannot_undo(self):
        self._set({"editable": "top"})
        entry = self.history.browse(
            self.history.history_for(cast("int", self.view.id))[0]["id"]
        )
        outsider_vals: dict[str, object] = {
            "name": "Nosy",
            "login": "undo_outsider",
            "groups_id": [(6, 0, [typed.ref(self.env, "base.group_user").id])],
        }
        outsider = self.env["res.users"].create(outsider_vals)  # pyright: ignore[reportArgumentType]
        with raises(self, AccessError):
            entry.with_user(outsider).sudo(False).action_undo()

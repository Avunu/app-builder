# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Undo, which is what makes live editing a fair bargain.

There is no Apply in the view editor because a view needs no reload, so an
edit is everybody's edit the moment it is made. That is honest, but only
tolerable if it can be taken back.

Restoring the previous arch wholesale, rather than inverting the operation, is
the point worth testing: it is exact for every operation the editor has and
every one it grows, including the ones whose inverse is ambiguous.
"""

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

LIST_ARCH = """
<list string="Demo">
    <field name="x_name"/>
</list>
"""


@tagged("post_install", "-at_install")
class TestUndo(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.history = self.env["studio.view.edit"]
        self.package = self.make_package(name="x_undo_pkg")
        self.env["ir.model"].create(
            {
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
        )
        self.view = self.env["ir.ui.view"].create(
            {
                "name": "studio.undo.test",
                "model": "x_undo_demo",
                "type": "list",
                "arch": LIST_ARCH,
            }
        )
        # Owned by somebody else, so edits become patches -- the case where
        # undoing has to remove the patch rather than empty it.
        self.make_package(name="x_undo_owner").studio_capture(self.view)

    def _set(self, attrs):
        found = self.editor.locate_target(self.view.id, {"kind": "root"})
        return self.editor.apply_operation(
            self.view.id,
            self.package.id,
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
        entries = self.history.history_for(self.view.id)
        self.assertEqual(len(entries), 1)
        self.assertIn("editable", entries[0]["summary"])

    def test_history_is_newest_first(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        entries = self.history.history_for(self.view.id)
        self.assertIn("multi_edit", entries[0]["summary"])

    # -- undoing -----------------------------------------------------------

    def test_undoing_the_first_edit_removes_the_patch_entirely(self):
        """The edit brought the patch into being, so undoing it should leave no
        patch rather than an empty one that still loads."""
        self._set({"editable": "top"})
        patch = self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)])
        self.assertTrue(patch)

        entry = self.history.browse(self.history.history_for(self.view.id)[0]["id"])
        entry.action_undo()

        self.assertFalse(
            self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)]),
            "an emptied patch would still be loaded and still be wrong",
        )

    def test_undoing_a_later_edit_restores_the_previous_arch(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        patch = self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)])
        self.assertIn("multi_edit", patch.arch)

        entry = self.history.browse(self.history.history_for(self.view.id)[0]["id"])
        entry.action_undo()

        patch.invalidate_recordset()
        self.assertNotIn("multi_edit", patch.arch)
        self.assertIn("editable", patch.arch, "the earlier edit survives")

    def test_an_undone_edit_leaves_the_history(self):
        self._set({"editable": "top"})
        entry = self.history.browse(self.history.history_for(self.view.id)[0]["id"])
        entry.action_undo()
        self.assertEqual(self.history.history_for(self.view.id), [])

    def test_only_the_most_recent_edit_can_be_undone(self):
        """Restoring an older arch would silently discard everything done
        since, which is the opposite of what undo promises."""
        self._set({"editable": "top"})
        first = self.history.browse(self.history.history_for(self.view.id)[0]["id"])
        self._set({"multi_edit": "1"})

        with self.assertRaises(UserError) as caught:
            first.action_undo()
        self.assertIn("most recent", str(caught.exception))

    def test_undo_twice_walks_back_two_edits(self):
        self._set({"editable": "top"})
        self._set({"multi_edit": "1"})
        for _ in range(2):
            entries = self.history.history_for(self.view.id)
            self.history.browse(entries[0]["id"]).action_undo()
        self.assertFalse(
            self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)])
        )

    # -- guarded like everything else --------------------------------------

    def test_a_plain_user_cannot_undo(self):
        self._set({"editable": "top"})
        entry = self.history.browse(self.history.history_for(self.view.id)[0]["id"])
        outsider = self.env["res.users"].create(
            {
                "name": "Nosy",
                "login": "undo_outsider",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            entry.with_user(outsider).sudo(False).action_undo()

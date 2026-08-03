# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Reordering, which is a move and not a delete-and-recreate.

Core's ``position="move"`` extracts the node and re-inserts it, so attributes
contributed by *other* inheriting views travel with it. Recreating the node
instead would silently drop them, and the loss would only show up on whichever
database happened to have the other module installed.
"""

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

LIST_ARCH = """
<list string="Demo">
    <field name="x_name"/>
    <field name="x_when"/>
    <field name="x_note"/>
</list>
"""


@tagged("post_install", "-at_install")
class TestMoveNode(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.package = self.make_package(name="x_move_pkg")
        self.env["ir.model"].create(
            {
                "name": "Move Demo",
                "model": "x_move_demo",
                "field_id": [
                    Command.create(
                        {"name": "x_name", "ttype": "char", "field_description": "Name"}
                    ),
                    Command.create(
                        {"name": "x_when", "ttype": "date", "field_description": "When"}
                    ),
                    Command.create(
                        {"name": "x_note", "ttype": "char", "field_description": "Note"}
                    ),
                ],
            }
        )
        self.view = self.env["ir.ui.view"].create(
            {
                "name": "studio.move.test",
                "model": "x_move_demo",
                "type": "list",
                "arch": LIST_ARCH,
            }
        )

    def _columns(self):
        root = etree.fromstring(self.view.get_combined_arch().encode())
        return [f.get("name") for f in root.findall("field")]

    def _move(self, source, target, position="before"):
        return self.editor.move_node(
            self.view.id,
            self.package.id,
            {"kind": "column", "name": source},
            {"kind": "column", "name": target},
            position,
        )

    # -- owned views: rewritten in place -----------------------------------

    def test_a_column_moves_before_another(self):
        self.package.studio_capture(self.view)
        self.assertEqual(self._columns(), ["x_name", "x_when", "x_note"])
        self._move("x_note", "x_when")
        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_name", "x_note", "x_when"])

    def test_a_column_moves_after_another(self):
        self.package.studio_capture(self.view)
        self._move("x_name", "x_note", position="after")
        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_when", "x_note", "x_name"])

    def test_the_column_is_moved_not_duplicated(self):
        self.package.studio_capture(self.view)
        self._move("x_note", "x_name")
        self.view.invalidate_recordset()
        self.assertEqual(
            len([c for c in self._columns() if c == "x_note"]),
            1,
            "a recreate would leave the original behind",
        )

    # -- foreign views: the move is expressed as a patch --------------------

    def test_moving_in_a_foreign_view_writes_a_patch(self):
        self.make_package(name="x_move_owner").studio_capture(self.view)
        self._move("x_note", "x_name")
        patch = self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)])
        self.assertTrue(patch)
        self.assertIn('position="move"', patch.arch)
        # And the combined result is the reordering the user asked for.
        self.assertEqual(self._columns()[0], "x_note")

    def test_the_base_view_is_untouched_by_a_move(self):
        self.make_package(name="x_move_owner2").studio_capture(self.view)
        before = self.view.arch
        self._move("x_note", "x_name")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, before)

    # -- refusals ----------------------------------------------------------

    def test_moving_a_node_relative_to_itself_is_refused(self):
        self.package.studio_capture(self.view)
        with self.assertRaises(UserError):
            self._move("x_name", "x_name")

    def test_an_unaddressable_end_is_refused(self):
        self.package.studio_capture(self.view)
        with self.assertRaises(UserError) as caught:
            self._move("x_name", "x_nonexistent")
        self.assertIn("not a node the builder can address", str(caught.exception))

    def test_an_invalid_position_is_refused(self):
        self.package.studio_capture(self.view)
        with self.assertRaises(UserError):
            self._move("x_name", "x_note", position="inside")

    def test_a_move_is_undoable_like_any_other_edit(self):
        self.package.studio_capture(self.view)
        self._move("x_note", "x_name")
        self.view.invalidate_recordset()
        self.assertEqual(self._columns()[0], "x_note")

        history = self.env["studio.view.edit"]
        entry = history.browse(history.history_for(self.view.id)[0]["id"])
        entry.action_undo()

        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_name", "x_when", "x_note"])

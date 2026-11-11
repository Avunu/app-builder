# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Reordering, which is a move and not a delete-and-recreate.

Core's ``position="move"`` extracts the node and re-inserts it, so attributes
contributed by *other* inheriting views travel with it. Recreating the node
instead would silently drop them, and the loss would only show up on whichever
database happened to have the other module installed.
"""

from __future__ import annotations

from typing import cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_view_edit import BuilderViewEdit
from ..models.builder_view_editor import BuilderViewEditor

LIST_ARCH = """
<list string="Demo">
    <field name="x_name"/>
    <field name="x_when"/>
    <field name="x_note"/>
</list>
"""


@tagged("post_install", "-at_install")
class TestMoveNode(BuilderCase):
    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.package = self.make_package(name="x_move_pkg")
        model_vals: dict[str, object] = {
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
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "builder.move.test",
            "model": "x_move_demo",
            "type": "list",
            "arch": LIST_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]

    def _columns(self):
        root = etree.fromstring(self.view.get_combined_arch().encode())
        return [f.get("name") for f in root.findall("field")]

    def _move(self, source, target, position="before"):
        return self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "column", "name": source},
            {"kind": "column", "name": target},
            position,
        )

    # -- owned views: rewritten in place -----------------------------------

    def test_a_column_moves_before_another(self):
        self.package.builder_capture(self.view)
        self.assertEqual(self._columns(), ["x_name", "x_when", "x_note"])
        self._move("x_note", "x_when")
        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_name", "x_note", "x_when"])

    def test_a_column_moves_after_another(self):
        self.package.builder_capture(self.view)
        self._move("x_name", "x_note", position="after")
        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_when", "x_note", "x_name"])

    def test_the_column_is_moved_not_duplicated(self):
        self.package.builder_capture(self.view)
        self._move("x_note", "x_name")
        self.view.invalidate_recordset()
        self.assertEqual(
            len([c for c in self._columns() if c == "x_note"]),
            1,
            "a recreate would leave the original behind",
        )

    # -- foreign views: the move is expressed as a patch --------------------

    def test_moving_in_a_foreign_view_writes_a_patch(self):
        self.make_package(name="x_move_owner").builder_capture(self.view)
        self._move("x_note", "x_name")
        patch = typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        self.assertTrue(patch)
        self.assertIn('position="move"', cast("str", patch.arch))
        # And the combined result is the reordering the user asked for.
        self.assertEqual(self._columns()[0], "x_note")

    def test_the_base_view_is_untouched_by_a_move(self):
        self.make_package(name="x_move_owner2").builder_capture(self.view)
        before = self.view.arch
        self._move("x_note", "x_name")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, before)

    # -- refusals ----------------------------------------------------------

    def test_moving_a_node_relative_to_itself_is_refused(self):
        self.package.builder_capture(self.view)
        with raises(self, UserError):
            self._move("x_name", "x_name")

    def test_an_unaddressable_end_is_refused(self):
        self.package.builder_capture(self.view)
        with raises(self, UserError) as caught:
            self._move("x_name", "x_nonexistent")
        self.assertIn("not a node the builder can address", str(caught.exception))

    def test_an_invalid_position_is_refused(self):
        self.package.builder_capture(self.view)
        with raises(self, UserError):
            self._move("x_name", "x_note", position="replace")

    def test_moving_inside_the_root_makes_it_the_last_column(self):
        """Core plants its sentinel at the end of the target, so `inside` is
        "append" -- the same in 18, 19 and master."""
        self.package.builder_capture(self.view)
        self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "column", "name": "x_name"},
            {"kind": "root"},
            "inside",
        )
        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_when", "x_note", "x_name"])

    def test_a_move_is_undoable_like_any_other_edit(self):
        self.package.builder_capture(self.view)
        self._move("x_note", "x_name")
        self.view.invalidate_recordset()
        self.assertEqual(self._columns()[0], "x_note")

        history = typed.model(self.env, BuilderViewEdit)
        entry = history.browse(history.history_for(cast("int", self.view.id))[0]["id"])
        entry.action_undo()

        self.view.invalidate_recordset()
        self.assertEqual(self._columns(), ["x_name", "x_when", "x_note"])


FORM_ARCH = """
<form string="Demo">
    <sheet>
        <notebook>
            <page string="Main" name="page_main">
                <group name="g_left">
                    <field name="x_name"/>
                    <field name="x_when"/>
                </group>
                <group name="g_right"/>
            </page>
        </notebook>
    </sheet>
</form>
"""


@tagged("post_install", "-at_install")
class TestMoveInside(BuilderCase):
    """Moving *into* a container, which a drop on an empty group asks for.

    `inside` appends: there is no "inside, at index n" in core, so anything
    between two children is a before/after on one of them. And a node cannot
    go into its own subtree -- core would extract it, target and all, then
    try to insert it into what it just removed, and lxml refuses with a bare
    exception rather than a sentence.
    """

    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.package = self.make_package(name="x_move_in_pkg")
        model_vals: dict[str, object] = {
            "name": "Move Inside Demo",
            "model": "x_move_in_demo",
            "field_id": [
                Command.create(
                    {"name": "x_name", "ttype": "char", "field_description": "Name"}
                ),
                Command.create(
                    {"name": "x_when", "ttype": "date", "field_description": "When"}
                ),
            ],
        }
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "builder.move.inside.test",
            "model": "x_move_in_demo",
            "type": "form",
            "arch": FORM_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(self.view)

    def _group(self, name):
        root = etree.fromstring(self.view.get_combined_arch().encode())
        group = root.find(".//group[@name='%s']" % name)
        return [child.get("name") for child in group]

    def test_a_field_moved_inside_an_empty_group_becomes_its_child(self):
        self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "field", "name": "x_when"},
            {"kind": "group", "name": "g_right"},
            "inside",
        )
        self.view.invalidate_recordset()
        self.assertEqual(self._group("g_right"), ["x_when"])
        self.assertEqual(self._group("g_left"), ["x_name"], "moved, not copied")

    def test_a_field_moved_inside_its_own_group_goes_last(self):
        """Append semantics, pinned: a drop into a container the node is
        already in is a reorder to the end, not a no-op."""
        self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "field", "name": "x_name"},
            {"kind": "group", "name": "g_left"},
            "inside",
        )
        self.view.invalidate_recordset()
        self.assertEqual(self._group("g_left"), ["x_when", "x_name"])

    def test_moving_a_page_into_a_group_it_contains_is_refused(self):
        with raises(self, UserError) as caught:
            self.editor.move_node(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {"kind": "page", "name": "page_main"},
                {"kind": "group", "name": "g_left"},
                "inside",
            )
        self.assertIn("into itself", str(caught.exception))

    def test_the_ancestor_guard_also_covers_raw_locators(self):
        """apply_operation takes xpaths straight from a caller, so the guard
        has to hold there too rather than only where descriptors are resolved.
        """
        # Not `assertRaises`: Odoo's wraps the block in a savepoint that is
        # rolled back on the exception, and "untouched" would then hold
        # whatever the operation had written before refusing.
        try:
            self.editor.apply_operation(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {
                    "type": "move_node",
                    "xpath": "//page[@name='page_main']",
                    "target_xpath": "//group[@name='g_left']",
                    "position": "inside",
                },
            )
        except UserError as caught:
            self.assertIn("into itself", str(caught))
        else:
            self.fail("a move into the node's own subtree has to be refused")
        self.view.invalidate_recordset()
        self.assertEqual(self._group("g_left"), ["x_name", "x_when"], "untouched")

    def test_moving_a_group_into_its_own_page_is_allowed(self):
        """The page is the group's ancestor, not its descendant: this is a
        legitimate reorder to the end of the page."""
        self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "g_left"},
            {"kind": "page", "name": "page_main"},
            "inside",
        )
        self.view.invalidate_recordset()
        root = etree.fromstring(self.view.get_combined_arch().encode())
        page = root.find(".//page[@name='page_main']")
        self.assertEqual([g.get("name") for g in page], ["g_right", "g_left"])

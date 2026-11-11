# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A field's label, where the form draws none.

The form compiler labels a field only as a direct child of an inner group.
A field dropped on the sheet, in a tab or into columns renders bare, so a
Label typed in the properties panel changes the arch and nothing on the
screen. The canvas table says where each field's label comes from, and the
builder's answer for a field without one is core's own: a ``<label for>``
before it -- added by one call, taken away by removing the label's node,
and carried along when the field moves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_view_edit import BuilderViewEdit
from ..models.builder_view_editor import BuilderViewEditor

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime. `canvas()` and the
    # `DropSuccessJSON` shape `drop_at()` returns on its non-stale branch
    # are declared on `builder_view_canvas.py`'s own pure `_inherit =
    # "builder.view.editor"` extension -- the same `_name`, a different,
    # unrelated Python class from `BuilderViewEditor` above (`typed.py`'s
    # own `model()`-vs-`_inherit` gap), aliased on import the same way
    # `builder_view_new_field.py`'s own `BuilderViewEditorCanvas` is.
    from ..models.builder_view_canvas import (
        BuilderViewEditor as BuilderViewEditorCanvas,
    )
    from ..models.builder_view_editor import DropSuccessJSON
    from ..tools.canvas_stamp import FieldLabel

FORM_ARCH = """
<form string="Label Demo">
    <sheet>
        <group name="outer">
            <group name="left">
                <field name="x_name"/>
            </group>
            <group name="right"/>
        </group>
        <field name="x_note" placeholder="Notes..."/>
        <notebook name="nb">
            <page string="More" name="page_more">
                <field name="x_when"/>
            </page>
        </notebook>
    </sheet>
</form>
"""


@tagged("post_install", "-at_install")
class TestShowLabel(BuilderCase):
    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.package = self.make_package(name="x_label_pkg")
        model_vals: dict[str, object] = {
            "name": "Label Demo",
            "model": "x_label_demo",
            "field_id": [
                Command.create(
                    {"name": "x_name", "ttype": "char", "field_description": "Name"}
                ),
                Command.create(
                    {"name": "x_note", "ttype": "html", "field_description": "Note"}
                ),
                Command.create(
                    {"name": "x_when", "ttype": "date", "field_description": "When"}
                ),
            ],
        }
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "builder.label.test",
            "model": "x_label_demo",
            "type": "form",
            "arch": FORM_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]

    # -- helpers -------------------------------------------------------------

    def _canvas(self):
        return cast("BuilderViewEditorCanvas", self.editor).canvas(
            cast("int", self.view.id)
        )

    def _node(self, name, canvas=None):
        canvas = canvas or self._canvas()
        return next(
            (t, n)
            for t, n in canvas["nodes"].items()
            if n["name"] == name and n["tag"] == "field"
        )

    def _show(self, name):
        canvas = self._canvas()
        token, _node = self._node(name, canvas)
        return self.editor.show_label_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "node", "token": token, "arch_version": canvas["arch_version"]},
        )

    def _combined(self):
        self.view.invalidate_recordset()
        return etree.fromstring(self.view.get_combined_arch().encode())

    def _label_before(self, root, name):
        field = root.find(".//field[@name='%s']" % name)
        previous = field.getprevious()
        return (
            previous is not None
            and previous.tag == "label"
            and previous.get("for") == name
        )

    # -- the table says where a label comes from ------------------------------

    def test_the_canvas_says_where_each_label_comes_from(self):
        canvas = self._canvas()
        _token, in_group = self._node("x_name", canvas)
        self.assertEqual(cast("FieldLabel", in_group["label"])["by"], "group")
        _token, on_sheet = self._node("x_note", canvas)
        self.assertEqual(
            on_sheet["label"],
            {"shown": False, "by": None, "token": None, "in_group": False},
        )
        _token, in_page = self._node("x_when", canvas)
        self.assertFalse(cast("FieldLabel", in_page["label"])["shown"])

    # -- owned view: the label is written into the arch ------------------------

    def test_a_sheet_field_is_given_a_label_before_it(self):
        self.package.builder_capture(self.view)
        self._show("x_note")
        root = self._combined()
        self.assertTrue(self._label_before(root, "x_note"))
        # The primary arch itself, since the package owns the view.
        self.assertIn('<label for="x_note"', cast("str", self.view.arch))
        # And the table now knows the label, and which node it is.
        canvas = self._canvas()
        _token, node = self._node("x_note", canvas)
        label = cast("FieldLabel", node["label"])
        self.assertEqual(label["by"], "label")
        self.assertEqual(canvas["nodes"][cast("str", label["token"])]["tag"], "label")
        self.assertEqual(
            canvas["nodes"][cast("str", label["token"])]["string"], "x_note"
        )

    def test_the_label_is_taken_away_by_removing_its_node(self):
        self.package.builder_capture(self.view)
        self._show("x_note")
        canvas = self._canvas()
        _token, node = self._node("x_note", canvas)
        label = cast("FieldLabel", node["label"])
        self.editor.remove_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {
                "kind": "node",
                "token": label["token"],
                "arch_version": canvas["arch_version"],
            },
        )
        root = self._combined()
        self.assertFalse(root.xpath("//label[@for='x_note']"))
        self.assertFalse(cast("FieldLabel", self._node("x_note")[1]["label"])["shown"])

    def test_a_second_label_is_refused(self):
        self.package.builder_capture(self.view)
        self._show("x_note")
        with raises(self, UserError) as caught:
            self._show("x_note")
        self.assertIn("already has a label", str(caught.exception))
        self.assertEqual(len(self._combined().xpath("//label[@for='x_note']")), 1)

    def test_only_a_field_takes_a_label(self):
        self.package.builder_capture(self.view)
        canvas = self._canvas()
        token = next(t for t, n in canvas["nodes"].items() if n["name"] == "nb")
        with raises(self, UserError) as caught:
            self.editor.show_label_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {
                    "kind": "node",
                    "token": token,
                    "arch_version": canvas["arch_version"],
                },
            )
        self.assertIn("Only a field", str(caught.exception))

    def test_giving_a_label_is_one_history_entry_that_undoes(self):
        self.package.builder_capture(self.view)
        self._show("x_note")
        history = typed.model(self.env, BuilderViewEdit)
        entries = history.history_for(cast("int", self.view.id))
        self.assertEqual(len(entries), 1)
        self.assertIn("label", entries[0]["summary"])
        history.browse(entries[0]["id"]).action_undo()
        self.assertFalse(self._combined().xpath("//label[@for='x_note']"))

    # -- foreign view: the label is a patch --------------------------------------

    def test_on_a_foreign_view_the_label_is_an_inheriting_patch(self):
        self.make_package(name="x_label_owner").builder_capture(self.view)
        before = self.view.arch
        self._show("x_note")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, before, "the base view is not rewritten")
        patch = typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        self.assertTrue(patch)
        self.assertIn('<label for="x_note"', cast("str", patch.arch))
        self.assertIn('position="before"', cast("str", patch.arch))
        self.assertTrue(self._label_before(self._combined(), "x_note"))

    def test_a_label_taken_away_on_a_foreign_view_can_be_given_again(self):
        """The extension keeps both the label it added and the removal of
        it; what counts is the combined arch, where there is none."""
        self.make_package(name="x_label_owner2").builder_capture(self.view)
        self._show("x_note")
        canvas = self._canvas()
        _token, node = self._node("x_note", canvas)
        label = cast("FieldLabel", node["label"])
        self.editor.remove_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {
                "kind": "node",
                "token": label["token"],
                "arch_version": canvas["arch_version"],
            },
        )
        self.assertFalse(self._combined().xpath("//label[@for='x_note']"))
        self._show("x_note")
        self.assertEqual(len(self._combined().xpath("//label[@for='x_note']")), 1)
        self.assertTrue(cast("FieldLabel", self._node("x_note")[1]["label"])["shown"])

    # -- a field's label follows the field --------------------------------------

    def _drop(self, anchor_name, position, payload):
        canvas = self._canvas()
        token, _node = self._node(anchor_name, canvas)
        return cast(
            "DropSuccessJSON",
            self.editor.drop_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {"token": token, "position": position},
                payload,
                expected_arch_version=canvas["arch_version"],
            ),
        )

    def test_a_field_dropped_where_no_label_is_drawn_is_given_one(self):
        self.package.builder_capture(self.view)
        result = self._drop(
            "x_note", "after", {"kind": "existing_field", "name": "x_when"}
        )
        root = self._combined()
        self.assertTrue(self._label_before(root, "x_when"))
        self.assertEqual(root.find(".//field[@name='x_when']").getparent().tag, "sheet")
        dropped = result["canvas"]["nodes"][cast("str", result["select"])]
        self.assertEqual(cast("FieldLabel", dropped["label"])["by"], "label")
        # One edit: the label came with the field.
        history = cast("dict[str, list[object]]", result["history"])
        self.assertEqual(len(history["undo"]), 1)

    def test_a_field_dropped_in_a_group_gets_no_label_of_its_own(self):
        self.package.builder_capture(self.view)
        self._drop("x_name", "after", {"kind": "existing_field", "name": "x_when"})
        root = self._combined()
        self.assertFalse(root.xpath("//label[@for='x_when']"))
        _token, node = self._node("x_when")
        self.assertEqual(cast("FieldLabel", node["label"])["by"], "group")

    def test_a_field_dropped_in_the_header_stays_bare(self):
        self.package.builder_capture(self.view)
        self.view.write(
            {"arch": FORM_ARCH.replace("<sheet>", "<header name='head'/><sheet>")}
        )
        canvas = self._canvas()
        head = next(t for t, n in canvas["nodes"].items() if n["name"] == "head")
        self.editor.drop_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"token": head, "position": "inside"},
            {"kind": "existing_field", "name": "x_when"},
            expected_arch_version=canvas["arch_version"],
        )
        self.assertFalse(self._combined().xpath("//label[@for='x_when']"))

    def test_a_field_a_group_labelled_keeps_a_label_when_it_leaves(self):
        self.package.builder_capture(self.view)
        self._drop(
            "x_note", "after", {"kind": "move", "token": self._node("x_name")[0]}
        )
        root = self._combined()
        sheet = root.find("sheet")
        self.assertEqual(
            [(c.tag, c.get("name") or c.get("for")) for c in sheet],
            [
                ("group", "outer"),
                ("field", "x_note"),
                ("label", "x_name"),
                ("field", "x_name"),
                ("notebook", "nb"),
            ],
        )

    def test_a_labelled_field_moved_into_a_group_drops_its_label(self):
        """The group draws one; a `<label for>` carried along would double it."""
        self.package.builder_capture(self.view)
        self._show("x_note")
        self._drop(
            "x_name", "after", {"kind": "move", "token": self._node("x_note")[0]}
        )
        root = self._combined()
        self.assertFalse(root.xpath("//label[@for='x_note']"))
        left = root.find(".//group[@name='left']")
        self.assertEqual([c.get("name") for c in left], ["x_name", "x_note"])
        self.assertEqual(
            cast("FieldLabel", self._node("x_note")[1]["label"])["by"], "group"
        )

    def test_removing_a_field_removes_its_own_label(self):
        self.package.builder_capture(self.view)
        self._show("x_note")
        canvas = self._canvas()
        token, _node = self._node("x_note", canvas)
        self.editor.remove_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "node", "token": token, "arch_version": canvas["arch_version"]},
        )
        root = self._combined()
        self.assertFalse(root.xpath("//field[@name='x_note']"))
        self.assertFalse(root.xpath("//label[@for='x_note']"))

    # -- the label moves with its field ---------------------------------------

    def test_a_moved_field_takes_its_label_along(self):
        self.package.builder_capture(self.view)
        self._show("x_note")
        canvas = self._canvas()
        source, _n = self._node("x_note", canvas)
        target, _n = self._node("x_when", canvas)
        self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "node", "token": source, "arch_version": canvas["arch_version"]},
            {"kind": "node", "token": target, "arch_version": canvas["arch_version"]},
            "after",
        )
        root = self._combined()
        page = root.find(".//page[@name='page_more']")
        self.assertEqual(
            [(c.tag, c.get("name") or c.get("for")) for c in page],
            [("field", "x_when"), ("label", "x_note"), ("field", "x_note")],
        )
        self.assertFalse(
            root.xpath("//sheet/label"), "nothing is left behind on the sheet"
        )

    def test_a_field_moved_before_its_own_label_is_just_a_move(self):
        """The label is the target: it stays put, the field goes before it."""
        self.package.builder_capture(self.view)
        self._show("x_note")
        canvas = self._canvas()
        source, node = self._node("x_note", canvas)
        label = cast("FieldLabel", node["label"])
        self.editor.move_node(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "node", "token": source, "arch_version": canvas["arch_version"]},
            {
                "kind": "node",
                "token": label["token"],
                "arch_version": canvas["arch_version"],
            },
            "before",
        )
        root = self._combined()
        sheet = root.find("sheet")
        tags = [(c.tag, c.get("name") or c.get("for")) for c in sheet]
        self.assertIn(("field", "x_note"), tags)
        self.assertEqual(len(root.xpath("//label[@for='x_note']")), 1)

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One drop, one call, one write.

A drop is the console's whole vocabulary: an existing field, a palette
component or a node of the view, put before, after or inside a node the
pointer was over. What has to hold is that the drop lands exactly where the
pointer said, that a drop the view cannot take is refused with a sentence
before anything is minted, that the disk is written once and last, and that
a stale gesture costs nothing.
"""

import os
from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase
from odoo.addons.app_builder_view.exceptions import (
    StudioConfirmRequired,
    StudioStaleView,
)

FORM_ARCH = """
<form string="Drop Demo">
    <header name="head"/>
    <sheet>
        <group name="outer">
            <group name="left">
                <field name="x_name"/>
                <field name="x_when"/>
            </group>
            <group name="right"/>
        </group>
        <notebook name="nb">
            <page string="Main" name="page_main">
                <field name="x_note"/>
            </page>
        </notebook>
    </sheet>
</form>
"""

# A field declared at the root loads a value for the template and renders
# nothing; the same field dropped into the card is the one to select.
KANBAN_ARCH = """
<kanban>
    <field name="x_when"/>
    <templates>
        <t t-name="card">
            <main>
                <field name="x_name"/>
            </main>
        </t>
    </templates>
</kanban>
"""


def _snapshot(root):
    files = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as handle:
                files[os.path.relpath(path, root)] = handle.read()
    return files


@tagged("post_install", "-at_install")
class TestDropAt(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.history = self.env["studio.view.edit"]
        self.package = self.make_package(name="x_drop_pkg")
        self.model = self.env["ir.model"].create(
            {
                "name": "Drop Demo",
                "model": "x_drop_demo",
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
                    Command.create(
                        {"name": "x_extra", "ttype": "char", "field_description": "Ex"}
                    ),
                ],
            }
        )
        self.view = self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.test",
                "model": "x_drop_demo",
                "type": "form",
                "arch": FORM_ARCH,
            }
        )
        self.package.studio_capture(self.view)

    # -- helpers -------------------------------------------------------------

    def _canvas(self):
        return self.editor.canvas(self.view.id)

    def _token(self, name, canvas=None):
        canvas = canvas or self._canvas()
        return next(t for t, n in canvas["nodes"].items() if n["name"] == name)

    def _drop(self, anchor, position, payload, version=None):
        canvas = self._canvas()
        return self.editor.drop_at(
            self.view.id,
            self.package.id,
            {"token": self._token(anchor, canvas), "position": position},
            payload,
            expected_arch_version=version or canvas["arch_version"],
        )

    def _combined(self):
        self.view.invalidate_recordset()
        return etree.fromstring(self.view.get_combined_arch().encode())

    def _children(self, name):
        node = self._combined().find(".//*[@name='%s']" % name)
        return [c.get("name") for c in node if isinstance(c.tag, str)]

    def _field(self, name):
        return {"kind": "existing_field", "name": name}

    def _component(self, component, **values):
        return {"kind": "component", "component": component, "values": values}

    def _move(self, name, canvas=None):
        return {"kind": "move", "token": self._token(name, canvas)}

    # -- existing fields -----------------------------------------------------

    def test_an_existing_field_lands_before_a_sibling(self):
        result = self._drop("x_when", "before", self._field("x_extra"))
        self.assertFalse(result["stale"])
        self.assertEqual(self._children("left"), ["x_name", "x_extra", "x_when"])
        self.assertEqual(
            result["canvas"]["nodes"][result["select"]]["name"],
            "x_extra",
            "the answer names what landed",
        )
        self.assertEqual(result["history"]["undo"][0]["summary"], "added x_extra")

    def test_an_existing_field_lands_after_a_sibling(self):
        self._drop("x_name", "after", self._field("x_extra"))
        self.assertEqual(self._children("left"), ["x_name", "x_extra", "x_when"])

    def test_an_existing_field_lands_inside_an_empty_group(self):
        result = self._drop("right", "inside", self._field("x_extra"))
        self.assertEqual(self._children("right"), ["x_extra"])
        self.assertEqual(result["canvas"]["nodes"][result["select"]]["kind"], "field")

    def test_a_field_arrives_with_its_attributes(self):
        payload = dict(self._field("x_extra"), attrs={"widget": "char_emojis"})
        self._drop("right", "inside", payload)
        field = self._combined().find(".//field[@name='x_extra']")
        self.assertEqual(field.get("widget"), "char_emojis")

    def test_a_field_the_model_lacks_is_refused(self):
        with self.assertRaises(UserError) as caught:
            self._drop("right", "inside", self._field("x_nope"))
        self.assertIn("not a field of", str(caught.exception))

    # -- components --------------------------------------------------------

    def test_columns_is_one_group_with_two_and_one_history_entry(self):
        result = self._drop("nb", "before", self._component("columns"))
        sheet = self._combined().find("sheet")
        tags = [(c.tag, c.get("name")) for c in sheet if isinstance(c.tag, str)]
        outer = tags[1]
        self.assertEqual(outer[0], "group")
        self.assertTrue(outer[1].startswith("studio_group_"))
        columns = self._children(outer[1])
        self.assertEqual(len(columns), 2)
        self.assertTrue(all(c.startswith("studio_group_") for c in columns))
        self.assertEqual(len(result["history"]["undo"]), 1)
        self.assertEqual(result["canvas"]["nodes"][result["select"]]["name"], outer[1])
        self.assertEqual(
            result["canvas"]["nodes"][result["select"]]["orientation"], "row"
        )

    def test_a_notebook_arrives_with_a_tab(self):
        result = self._drop("outer", "after", self._component("notebook"))
        notebooks = self._combined().findall(".//notebook")
        self.assertEqual(len(notebooks), 2)
        new = notebooks[0]
        self.assertTrue(new.get("name").startswith("studio_notebook_"))
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].tag, "page")
        self.assertTrue(new[0].get("name").startswith("studio_page_"))
        selected = result["canvas"]["nodes"][result["select"]]
        self.assertEqual(selected["kind"], "notebook")

    def test_a_separator_lands_where_dropped(self):
        payload = self._component("separator", string="Rule")
        result = self._drop("x_name", "after", payload)
        left = self._combined().find(".//group[@name='left']")
        self.assertEqual([c.tag for c in left], ["field", "separator", "field"])
        self.assertEqual(left[1].get("string"), "Rule")
        selected = result["canvas"]["nodes"][result["select"]]
        self.assertEqual(selected["kind"], "separator")

    def test_a_label_is_static_text_that_validates(self):
        """A bare <label> needs a `for`; the validator's own suggestion is a
        node classed o_form_label, so that is what lands."""
        result = self._drop("x_when", "after", self._component("label", string="Hint"))
        left = self._combined().find(".//group[@name='left']")
        label = left[2]
        self.assertEqual(label.tag, "div")
        self.assertEqual(label.get("class"), "o_form_label")
        self.assertEqual(label.text, "Hint")
        node = result["canvas"]["nodes"][result["select"]]
        self.assertEqual(node["kind"], "label")
        self.assertEqual(node["string"], "Hint")

    def test_a_tab_goes_into_a_notebook(self):
        result = self._drop("nb", "inside", self._component("page", string="More"))
        self.assertEqual(len(self._children("nb")), 2)
        self.assertEqual(self._children("nb")[0], "page_main")
        self.assertEqual(result["canvas"]["nodes"][result["select"]]["string"], "More")

    def test_a_tab_beside_a_tab_lands_there(self):
        self._drop("page_main", "before", self._component("page", string="First"))
        pages = self._combined().findall(".//notebook[@name='nb']/page")
        self.assertEqual([p.get("string") for p in pages], ["First", "Main"])

    def _refused(self, exception, call, *args, **kwargs):
        """Run ``call`` and hand back the ``exception`` it raised.

        Not ``assertRaises``: Odoo's wraps the block in a savepoint that is
        rolled back on the exception, so an "arch unchanged" check after it
        would pass whatever the editor had written first.
        """
        try:
            call(*args, **kwargs)
        except exception as err:
            return err
        self.fail("%s was expected" % exception.__name__)

    def test_a_tab_dropped_on_a_group_is_refused(self):
        before = self.view.arch
        disk = _snapshot(self.package.root_path)
        err = self._refused(
            UserError, self._drop, "left", "inside", self._component("page")
        )
        self.assertEqual(str(err), "A tab can only live in a notebook.")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, before)
        self.assertEqual(self.history.history_for(self.view.id), [])
        self.assertEqual(_snapshot(self.package.root_path), disk)

    def test_a_field_cannot_be_dropped_into_a_notebook(self):
        with self.assertRaises(UserError) as caught:
            self._drop("nb", "inside", self._field("x_extra"))
        self.assertEqual(str(caught.exception), "A field cannot be dropped here.")

    def test_a_refusal_names_the_target_in_words_the_user_knows(self):
        """No "into a html", no "into a root": internal kinds get ordinary
        words, and a block of markup is simply "here"."""
        refusal = self.editor._drop_refusal
        self.assertEqual(
            refusal("field", {"container": False, "kind": "html"}),
            "A field cannot be dropped here.",
        )
        self.assertEqual(
            refusal("field", {"container": False, "kind": "field"}),
            "A field cannot be dropped into a field.",
        )
        self.assertEqual(
            refusal("group", {"container": False, "kind": "button_box"}),
            "A group cannot be dropped into a button box.",
        )
        self.assertEqual(
            refusal("separator", {"container": True, "kind": "root"}),
            "A separator cannot be dropped here.",
        )

    def test_beside_the_root_is_refused(self):
        canvas = self._canvas()
        with self.assertRaises(UserError) as caught:
            self.editor.drop_at(
                self.view.id,
                self.package.id,
                {"token": canvas["root"], "position": "after"},
                self._field("x_extra"),
            )
        self.assertIn("beside the view itself", str(caught.exception))

    def test_a_button_runs_a_server_action(self):
        action = self.env["ir.actions.server"].create(
            {
                "name": "Ping",
                "model_id": self.model.id,
                "state": "code",
                "code": "pass",
            }
        )
        # The action names the model, and the file the package writes has
        # to name it by xmlid too.
        self.package._assign(self.model)
        self.package._assign(self.model.field_id)
        self.package._assign(action)
        result = self._drop(
            "head", "inside", self._component("button", action_id=action.id)
        )
        button = self._combined().find("header/button")
        self.assertEqual(button.get("type"), "action")
        self.assertTrue(button.get("name").startswith("x_drop_pkg."), "by xmlid")
        self.assertEqual(result["canvas"]["nodes"][result["select"]]["kind"], "button")

    def test_a_new_field_drop_needs_a_label(self):
        """The one thing every new field needs; the rest is in test_new_field."""
        with self.assertRaises(UserError) as caught:
            self._drop("right", "inside", {"kind": "new_field", "values": {}})
        self.assertIn("needs a label", str(caught.exception))

    # -- moves ---------------------------------------------------------------

    def test_a_move_before_a_sibling_in_another_group(self):
        result = self._drop("x_name", "before", self._move("x_note"))
        self.assertEqual(self._children("left"), ["x_note", "x_name", "x_when"])
        self.assertEqual(self._children("page_main"), [], "moved, not copied")
        self.assertEqual(result["canvas"]["nodes"][result["select"]]["name"], "x_note")

    def test_a_move_after_a_sibling(self):
        self._drop("x_when", "after", self._move("x_name"))
        self.assertEqual(self._children("left"), ["x_when", "x_name"])

    def test_a_move_inside_an_empty_group(self):
        self._drop("right", "inside", self._move("x_when"))
        self.assertEqual(self._children("right"), ["x_when"])
        self.assertEqual(self._children("left"), ["x_name"])

    def test_a_move_into_its_own_subtree_is_refused(self):
        with self.assertRaises(UserError) as caught:
            self._drop("left", "inside", self._move("outer"))
        self.assertIn("into itself", str(caught.exception))

    def test_a_move_the_container_does_not_take_is_refused(self):
        with self.assertRaises(UserError) as caught:
            self._drop("x_name", "after", self._move("page_main"))
        self.assertEqual(str(caught.exception), "A tab can only live in a notebook.")

    def test_what_the_table_says_is_not_movable_is_not_moved(self):
        """The form accepts a sheet, so ACCEPTS alone would let the sheet be
        dragged above the header; the table says it stays, and the server
        holds the client to that."""
        canvas = self._canvas()
        sheet = next(t for t, n in canvas["nodes"].items() if n["kind"] == "sheet")
        self.assertFalse(canvas["nodes"][sheet]["movable"])
        disk = _snapshot(self.package.root_path)
        err = self._refused(
            UserError,
            self.editor.drop_at,
            self.view.id,
            self.package.id,
            {"token": self._token("head", canvas), "position": "before"},
            {"kind": "move", "token": sheet},
            expected_arch_version=canvas["arch_version"],
        )
        self.assertEqual(
            str(err), "The sheet stays where it is; it is not something to move."
        )
        self.assertEqual(self.history.history_for(self.view.id), [])
        self.assertEqual(_snapshot(self.package.root_path), disk)

    def test_a_field_a_kanban_declares_at_its_root_is_not_movable(self):
        view = self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.kanban",
                "model": "x_drop_demo",
                "type": "kanban",
                "arch": KANBAN_ARCH,
            }
        )
        self.package.studio_capture(view)
        canvas = self.editor.canvas(view.id)
        declared = self._token("x_when", canvas)
        self.assertFalse(canvas["nodes"][declared]["dom"])
        main = next(t for t, n in canvas["nodes"].items() if n["tag"] == "main")
        with self.assertRaises(UserError) as caught:
            self.editor.drop_at(
                view.id,
                self.package.id,
                {"token": main, "position": "inside"},
                {"kind": "move", "token": declared},
            )
        self.assertIn("not something to move", str(caught.exception))

    # -- the guards ------------------------------------------------------------

    def test_a_stale_version_returns_the_fresh_canvas_and_writes_nothing(self):
        disk = _snapshot(self.package.root_path)
        arch = self.view.arch
        result = self._drop(
            "right", "inside", self._field("x_extra"), version="something-older"
        )
        self.assertTrue(result["stale"])
        self.assertIn("nodes", result["canvas"])
        self.assertNotIn("select", result)
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, arch)
        self.assertEqual(self.history.history_for(self.view.id), [])
        self.assertEqual(_snapshot(self.package.root_path), disk)

    def test_a_stale_version_carried_by_the_target_is_honoured(self):
        canvas = self._canvas()
        result = self.editor.drop_at(
            self.view.id,
            self.package.id,
            {
                "token": self._token("right", canvas),
                "position": "inside",
                "arch_version": "something-older",
            },
            self._field("x_extra"),
        )
        self.assertTrue(result["stale"])
        self.assertEqual(self.history.history_for(self.view.id), [])

    def test_a_stale_token_descriptor_is_refused_by_every_mutator(self):
        """A token is an ordinal, and a stale one resolves on the current
        tree to *some* node -- the wrong one. The version a token
        descriptor carries is the claim, whether or not the caller also
        passed one, and it is checked before anything is written."""
        canvas = self._canvas()
        stale = {
            "kind": "node",
            "token": self._token("x_when", canvas),
            "arch_version": "something-older",
        }
        current = {"kind": "node", "token": self._token("right", canvas)}
        disk = _snapshot(self.package.root_path)
        arch = self.view.arch
        calls = [
            (
                self.editor.apply_at,
                stale,
                {
                    "type": "set_attributes",
                    "position": "attributes",
                    "attrs": {"string": "Later"},
                },
            ),
            (self.editor.remove_at, stale),
            (self.editor.add_field_at, stale, "x_extra"),
            (self.editor.add_container_at, stale, "group"),
            # A tab is the one entry point that re-anchors on the notebook
            # itself when the token is not one; the claim must be settled
            # before that second, versionless descriptor is minted.
            (self.editor.add_container_at, stale, "page"),
            (self.editor.move_node, stale, current, "inside"),
            (self.editor.move_node, current, stale, "after"),
        ]
        for call, *args in calls:
            self._refused(StudioStaleView, call, self.view.id, self.package.id, *args)
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, arch)
        self.assertEqual(self.history.history_for(self.view.id), [])
        self.assertEqual(_snapshot(self.package.root_path), disk)

    def test_a_current_token_descriptor_goes_through_without_a_kwarg(self):
        canvas = self._canvas()
        self.editor.apply_at(
            self.view.id,
            self.package.id,
            {
                "kind": "node",
                "token": self._token("x_when", canvas),
                "arch_version": canvas["arch_version"],
            },
            {
                "type": "set_attributes",
                "position": "attributes",
                "attrs": {"string": "Later"},
            },
        )
        when = self._combined().find(".//field[@name='x_when']")
        self.assertEqual(when.get("string"), "Later")

    def test_the_disk_is_written_once_at_the_end(self):
        Package = self.env.registry["studio.package"]
        original = Package.action_write_files
        with patch.object(
            Package, "action_write_files", autospec=True, side_effect=original
        ) as spy:
            self._drop("nb", "before", self._component("columns"))
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.package.state, "synced")

    def test_nothing_written_carries_a_token(self):
        self._drop("right", "inside", self._field("x_extra"))
        self._drop("nb", "before", self._component("columns"))
        self.view.invalidate_recordset()
        self.assertNotIn("o_studio_", self.view.arch)
        self.assertNotIn("o_studio_", self.view.get_combined_arch())
        for content in _snapshot(self.package.root_path).values():
            self.assertNotIn("o_studio_", content)
        for content in self.package._render_files().values():
            self.assertNotIn("o_studio_", content)

    def test_the_selected_token_is_the_node_the_drop_produced(self):
        """The kanban declares x_when at its root, where it has no DOM to
        outline; dropped into the card it becomes a second node of that
        name, and that is the one to select."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.kanban",
                "model": "x_drop_demo",
                "type": "kanban",
                "arch": KANBAN_ARCH,
            }
        )
        self.package.studio_capture(view)
        canvas = self.editor.canvas(view.id)
        main = next(t for t, n in canvas["nodes"].items() if n["tag"] == "main")
        result = self.editor.drop_at(
            view.id,
            self.package.id,
            {"token": main, "position": "inside"},
            self._field("x_when"),
            expected_arch_version=canvas["arch_version"],
        )
        selected = result["canvas"]["nodes"][result["select"]]
        self.assertEqual(selected["name"], "x_when")
        self.assertTrue(selected["selectable"])
        self.assertEqual(result["canvas"]["nodes"][selected["parent"]]["tag"], "main")

    def test_the_selected_token_prefers_the_container_dropped_into(self):
        nodes = {
            "n0": {"name": None, "tag": "form", "parent": None, "selectable": True},
            "n1": {"name": "left", "tag": "group", "parent": "n0", "selectable": True},
            "n2": {"name": "x", "tag": "field", "parent": "n1", "selectable": True},
            "n3": {"name": "right", "tag": "group", "parent": "n0", "selectable": True},
            "n4": {"name": "x", "tag": "label", "parent": "n3", "selectable": True},
            "n5": {"name": "x", "tag": "field", "parent": "n3", "selectable": True},
        }
        named = self.editor._token_named
        self.assertEqual(named(nodes, "x", "field", within=("group", "right")), "n5")
        self.assertEqual(named(nodes, "x", "field", within=("group", "left")), "n2")
        self.assertEqual(named(nodes, "x", "field"), "n2", "first in order otherwise")
        self.assertEqual(named(nodes, "x", "label"), "n4")
        self.assertIsNone(named(nodes, "nope"))

    def test_a_drop_into_the_card_of_an_owned_kanban_another_module_extends(self):
        """The card is `<t t-name="card">` -- no name -- and the owned path
        checks a positional locator against what it expected to find; the
        template name is the card's identity, so the check has one."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.kanban",
                "model": "x_drop_demo",
                "type": "kanban",
                "arch": KANBAN_ARCH,
            }
        )
        self.package.studio_capture(view)
        self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.kanban.other",
                "model": "x_drop_demo",
                "inherit_id": view.id,
                "mode": "extension",
                "arch": """<xpath expr="//main" position="inside">
                    <field name="x_note"/></xpath>""",
            }
        )
        canvas = self.editor.canvas(view.id)
        card = next(t for t, n in canvas["nodes"].items() if n["kind"] == "card")
        result = self.editor.drop_at(
            view.id,
            self.package.id,
            {"token": card, "position": "inside"},
            self._field("x_extra"),
            expected_arch_version=canvas["arch_version"],
        )
        self.assertEqual(result["canvas"]["nodes"][result["select"]]["name"], "x_extra")
        view.invalidate_recordset()
        self.assertIn('<field name="x_extra"/>', view.arch)
        template = etree.fromstring(view.arch.encode()).find(".//t[@t-name='card']")
        self.assertEqual([c.tag for c in template], ["main", "field"])

    def test_a_foreign_view_gets_a_patch_without_tokens(self):
        view = self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.foreign",
                "model": "x_drop_demo",
                "type": "form",
                "arch": FORM_ARCH,
            }
        )
        self.make_package(name="x_drop_owner").studio_capture(view)
        canvas = self.editor.canvas(view.id)
        token = next(t for t, n in canvas["nodes"].items() if n["name"] == "right")
        result = self.editor.drop_at(
            view.id,
            self.package.id,
            {"token": token, "position": "inside"},
            self._field("x_extra"),
            expected_arch_version=canvas["arch_version"],
        )
        patch_view = self.env["ir.ui.view"].search([("inherit_id", "=", view.id)])
        self.assertEqual(patch_view.studio_package_id, self.package)
        self.assertNotIn("o_studio_", patch_view.arch)
        self.assertIn("x_extra", patch_view.arch)
        self.assertEqual(result["canvas"]["source"]["view_id"], patch_view.id)
        self.assertFalse(result["canvas"]["source"]["owned"])

    # -- removing --------------------------------------------------------------

    def test_removing_a_full_container_needs_force(self):
        """The first ask is refused with a signal the client can match --
        a class of its own, with the count in its context -- and nothing
        is written; the second, with force, removes."""
        canvas = self._canvas()
        anchor = {"kind": "node", "token": self._token("left", canvas)}
        disk = _snapshot(self.package.root_path)
        err = self._refused(
            StudioConfirmRequired,
            self.editor.remove_at,
            self.view.id,
            self.package.id,
            anchor,
        )
        self.assertTrue(issubclass(StudioConfirmRequired, UserError))
        self.assertEqual(
            str(err), "Remove this group and the 2 fields in it? Confirm to proceed."
        )
        self.assertEqual(
            err.context, {"confirm_required": True, "count": 2, "fields": 2}
        )
        self.assertIsNotNone(self._combined().find(".//group[@name='left']"))
        self.assertEqual(self.history.history_for(self.view.id), [])
        self.assertEqual(_snapshot(self.package.root_path), disk)

        self.editor.remove_at(self.view.id, self.package.id, anchor, force=True)
        self.assertIsNone(self._combined().find(".//group[@name='left']"))

    def test_removing_a_container_of_containers_counts_elements(self):
        canvas = self._canvas()
        self.editor.remove_at(
            self.view.id,
            self.package.id,
            {"kind": "node", "token": self._token("x_note", canvas)},
        )
        canvas = self._canvas()
        err = self._refused(
            StudioConfirmRequired,
            self.editor.remove_at,
            self.view.id,
            self.package.id,
            {"kind": "node", "token": self._token("nb", canvas)},
        )
        self.assertEqual(
            str(err), "Remove this notebook and the element in it? Confirm to proceed."
        )
        self.assertEqual(err.context["fields"], 0)

    def test_removing_a_leaf_needs_no_force(self):
        anchor = {"kind": "node", "token": self._token("x_when")}
        self.editor.remove_at(self.view.id, self.package.id, anchor)
        self.assertEqual(self._children("left"), ["x_name"])

    def test_a_field_with_a_subview_is_a_leaf(self):
        """What is under a one2many is another model's view, not nodes the
        user can see or select; the field goes without a question."""
        self.env["ir.model.fields"].create(
            {
                "name": "x_tags",
                "ttype": "many2many",
                "relation": "res.partner",
                "field_description": "Tags",
                "model_id": self.model.id,
            }
        )
        view = self.env["ir.ui.view"].create(
            {
                "name": "studio.drop.sub",
                "model": "x_drop_demo",
                "type": "form",
                "arch": """<form><sheet><group name="g">
                    <field name="x_tags"><list><field name="name"/>
                    <field name="email"/></list></field>
                    <field name="x_name"/></group></sheet></form>""",
            }
        )
        self.package.studio_capture(view)
        canvas = self.editor.canvas(view.id)
        token = self._token("x_tags", canvas)
        self.editor.remove_at(
            view.id, self.package.id, {"kind": "node", "token": token}
        )
        view.invalidate_recordset()
        self.assertNotIn("x_tags", view.arch)
        self.assertIn("x_name", view.arch)

    def test_what_the_table_says_is_not_removable_is_not_removed(self):
        canvas = self._canvas()
        sheet = next(t for t, n in canvas["nodes"].items() if n["kind"] == "sheet")
        self.assertFalse(canvas["nodes"][sheet]["removable"])
        for anchor in ({"kind": "node", "token": sheet}, {"kind": "sheet"}):
            err = self._refused(
                UserError,
                self.editor.remove_at,
                self.view.id,
                self.package.id,
                anchor,
                force=True,
            )
            self.assertIn("The sheet stays where it is", str(err))
        self.assertIsNotNone(self._combined().find("sheet"))

    # -- token anchors on the click-to-add entry points ------------------------

    def test_a_token_for_a_container_means_inside_it(self):
        """The legacy kinds say what they are; a token says nothing, so the
        table decides -- a group takes a child, a field a sibling."""
        canvas = self._canvas()
        sheet = next(t for t, n in canvas["nodes"].items() if n["kind"] == "sheet")
        self.editor.add_container_at(
            self.view.id, self.package.id, {"kind": "node", "token": sheet}, "group"
        )
        names = [c.get("name") for c in self._combined().find("sheet")]
        self.assertEqual(names[:2], ["outer", "nb"])
        self.assertTrue(names[2].startswith("studio_group_"))

        canvas = self._canvas()
        self.editor.add_field_at(
            self.view.id,
            self.package.id,
            {"kind": "node", "token": self._token("right", canvas)},
            "x_extra",
        )
        self.assertEqual(self._children("right"), ["x_extra"])

        canvas = self._canvas()
        self.editor.add_field_at(
            self.view.id,
            self.package.id,
            {"kind": "node", "token": self._token("x_name", canvas)},
            "x_note",
        )
        self.assertEqual(self._children("left"), ["x_name", "x_note", "x_when"])

    def test_a_token_for_a_notebook_takes_the_tab(self):
        self._drop("outer", "after", self._component("notebook"))
        canvas = self._canvas()
        new = next(
            n["name"]
            for n in canvas["nodes"].values()
            if n["kind"] == "notebook" and n["name"] != "nb"
        )
        self.editor.add_container_at(
            self.view.id,
            self.package.id,
            {"kind": "node", "token": self._token(new, canvas)},
            "page",
            "Second",
        )
        self.assertEqual(len(self._children("nb")), 1, "the other notebook")
        pages = self._combined().findall(".//notebook[@name='%s']/page" % new)
        self.assertEqual([p.get("string") for p in pages], ["New tab", "Second"])

    def test_a_token_descriptor_works_everywhere_a_descriptor_does(self):
        canvas = self._canvas()
        found = self.editor.locate_target(
            self.view.id,
            {
                "kind": "node",
                "token": self._token("x_note", canvas),
                "arch_version": canvas["arch_version"],
            },
        )
        self.assertTrue(found["found"])
        self.assertEqual(found["xpath"], "//field[@name='x_note']")
        self.editor.add_field_at(
            self.view.id,
            self.package.id,
            {"kind": "node", "token": self._token("right", canvas)},
            "x_extra",
            position="inside",
        )
        self.assertEqual(self._children("right"), ["x_extra"])

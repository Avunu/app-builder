# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""View editing: inheriting views, never replacements."""

import os

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestViewEditor(StudioCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_view_pkg")
        self.editor = self.env["studio.view.editor"]
        self.base_view = self.env.ref("base.view_partner_form")

    def test_edit_creates_an_inheriting_view_not_a_rewrite(self):
        """The whole point: never mutate the view another module declares."""
        original_arch = self.base_view.arch
        result = self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        extension = self.env["ir.ui.view"].browse(result["view_id"])

        self.assertEqual(extension.inherit_id, self.base_view)
        self.assertEqual(extension.mode, "extension")
        self.assertEqual(extension.priority, 99)
        self.assertEqual(
            self.base_view.arch, original_arch, "the base view must be untouched"
        )
        self.assertIn('name="ref"', extension.arch)

    def test_edit_is_written_to_source(self):
        self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        source_path = os.path.join(
            self.package.root_path, "views/res_partner_views.xml"
        )
        self.assertTrue(os.path.isfile(source_path))
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('ref="base.view_partner_form"', source)
        self.assertIn('<field name="ref"/>', source)

    def test_repeated_edits_collect_in_one_extension_view(self):
        """One record with several xpaths reads far better than N records."""
        first = self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        second = self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "lang",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        self.assertEqual(first["view_id"], second["view_id"])
        extension = self.env["ir.ui.view"].browse(second["view_id"])
        root = etree.fromstring(extension.arch.encode())
        self.assertEqual(len(root.findall("xpath")), 2)

    def test_combined_arch_contains_the_edit(self):
        """Proof the edit actually reaches what a user sees."""
        self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        combined = etree.fromstring(self.base_view.get_combined_arch().encode())
        names = {n.get("name") for n in combined.iter("field")}
        self.assertIn("ref", names)

    def test_set_attributes_merges_rather_than_duplicating(self):
        self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "set_attributes",
                "xpath": "//field[@name='function']",
                "attrs": {"string": "Job Title"},
            },
        )
        result = self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "set_attributes",
                "xpath": "//field[@name='function']",
                "attrs": {"string": "Role", "readonly": "1"},
            },
        )
        extension = self.env["ir.ui.view"].browse(result["view_id"])
        root = etree.fromstring(extension.arch.encode())
        xpaths = root.findall("xpath")
        self.assertEqual(len(xpaths), 1, "attribute edits must merge into one xpath")
        attributes = {a.get("name"): a.text for a in xpaths[0].findall("attribute")}
        self.assertEqual(attributes["string"], "Role")
        self.assertEqual(attributes["readonly"], "1")

    def test_remove_node_is_idempotent(self):
        first = self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {"type": "remove_node", "xpath": "//field[@name='function']"},
        )
        self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {"type": "remove_node", "xpath": "//field[@name='function']"},
        )
        extension = self.env["ir.ui.view"].browse(first["view_id"])
        root = etree.fromstring(extension.arch.encode())
        self.assertEqual(len(root.findall("xpath")), 1)

    def test_invalid_xpath_is_rejected_with_a_useful_error(self):
        """Odoo's own validator runs over the combined arch, so bad edits fail."""
        with self.assertRaises(UserError):
            self.editor.apply_operation(
                self.base_view.id,
                self.package.id,
                {
                    "type": "add_field",
                    "name": "ref",
                    "xpath": "//field[@name='does_not_exist_anywhere']",
                    "position": "after",
                },
            )

    def test_nonexistent_field_is_rejected(self):
        with self.assertRaises(UserError):
            self.editor.apply_operation(
                self.base_view.id,
                self.package.id,
                {
                    "type": "add_field",
                    "name": "x_not_a_real_field",
                    "xpath": "//field[@name='function']",
                    "position": "after",
                },
            )

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(UserError):
            self.editor.apply_operation(
                self.base_view.id, self.package.id, {"type": "drop_database"}
            )

    def test_get_addable_fields_excludes_present_ones(self):
        fields = self.editor.get_addable_fields("res.partner", self.base_view.id)
        names = {f["name"] for f in fields}
        self.assertNotIn(
            "function", names, "a field already on the form is not addable again"
        )
        self.assertTrue(names, "there should still be something left to add")

    def test_get_view_nodes_returns_a_pickable_tree(self):
        """The client must never require a hand-typed xpath."""
        nodes = self.editor.get_view_nodes(self.base_view.id)
        self.assertTrue(nodes)
        self.assertEqual(nodes[0]["tag"], "form")
        self.assertEqual(nodes[0]["depth"], 0)
        self.assertTrue(any(n["is_field"] for n in nodes))
        self.assertTrue(any(n["container"] for n in nodes))
        self.assertTrue(all(n["xpath"] for n in nodes), "every node needs an xpath")

    def test_named_nodes_get_identifying_xpaths(self):
        """//field[@name='x'] survives a sibling insert; //div[3] does not."""
        nodes = self.editor.get_view_nodes(self.base_view.id)
        # 'vat' is on the sheet and nowhere else in the partner form, so the
        # bare predicate is unambiguous and is what the picker should emit.
        vat = next(n for n in nodes if n["is_field"] and n["label"] == "vat")
        self.assertEqual(vat["xpath"], "//field[@name='vat']")

    def test_ambiguous_names_are_qualified_by_their_parent(self):
        """A bare predicate is only a locator while exactly one node answers it.

        ``res.partner``'s form carries ``function`` three times: once on the
        sheet and twice inside the inline ``child_ids`` subviews, which are a
        different view of a different arch grafted in by
        ``_postprocess_tag_field``. Emitting ``//field[@name='function']`` for
        all three means ``locate_node`` takes whichever comes first, so an edit
        aimed at a subview column silently patches the sheet.
        """
        nodes = self.editor.get_view_nodes(self.base_view.id)
        functions = [n for n in nodes if n["is_field"] and n["label"] == "function"]
        self.assertGreater(len(functions), 1, "fixture assumes a repeated name")
        paths = {n["xpath"] for n in functions}
        self.assertEqual(
            len(paths), len(functions), "each occurrence needs its own path"
        )
        self.assertNotIn("//field[@name='function']", paths)

    def test_node_xpaths_are_usable_as_operation_targets(self):
        """A picked xpath must actually resolve, or the picker is a lie."""
        nodes = self.editor.get_view_nodes(self.base_view.id)
        target = next(n for n in nodes if n["xpath"] == "//field[@name='vat']")
        self.editor.apply_operation(
            self.base_view.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "ref",
                "xpath": target["xpath"],
                "position": "after",
            },
        )
        combined = etree.fromstring(self.base_view.get_combined_arch().encode())
        self.assertIn("ref", {n.get("name") for n in combined.iter("field")})

    def test_get_view_nodes_rejects_a_missing_view(self):
        with self.assertRaises(UserError):
            self.editor.get_view_nodes(0)

    def test_get_editable_views_returns_primary_views(self):
        views = self.editor.get_editable_views("res.partner")
        self.assertTrue(views)
        self.assertTrue(any(v["type"] == "form" for v in views))

    def test_edit_on_a_custom_model_view(self):
        """End to end on a model the studio itself created."""
        self.env["studio.model.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "View Demo",
                "model": "x_view_demo",
            }
        ).action_create()
        self.env["ir.model.fields"].create(
            {
                "name": "x_note",
                "field_description": "Note",
                "ttype": "text",
                "model_id": self.env["ir.model"]._get("x_view_demo").id,
            }
        )
        form = self.env["ir.ui.view"].search(
            [("model", "=", "x_view_demo"), ("type", "=", "form")], limit=1
        )
        self.editor.apply_operation(
            form.id,
            self.package.id,
            {
                "type": "add_field",
                "name": "x_note",
                "xpath": "//field[@name='x_name']",
                "position": "after",
            },
        )
        combined = etree.fromstring(form.get_combined_arch().encode())
        names = {n.get("name") for n in combined.iter("field")}
        self.assertIn("x_note", names)

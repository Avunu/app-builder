# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""View editing: inheriting views, never replacements."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_view_editor import BuilderViewEditor

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_model import IrModelFields


@tagged("post_install", "-at_install")
class TestViewEditor(BuilderCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_view_pkg")
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.base_view = cast("View", typed.ref(self.env, "base.view_partner_form"))

    def test_edit_creates_an_inheriting_view_not_a_rewrite(self):
        """The whole point: never mutate the view another module declares."""
        original_arch = self.base_view.arch
        result = self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        extension = typed.model(self.env, View).browse(result["view_id"])

        self.assertEqual(extension.inherit_id, self.base_view)
        self.assertEqual(extension.mode, "extension")
        self.assertEqual(extension.priority, 99)
        self.assertEqual(
            self.base_view.arch, original_arch, "the base view must be untouched"
        )
        self.assertIn('name="ref"', cast("str", extension.arch))

    def test_edit_is_written_to_source(self):
        self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        source_path = os.path.join(
            cast("str", self.package.root_path), "views/res_partner_views.xml"
        )
        self.assertTrue(os.path.isfile(source_path))
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('ref="base.view_partner_form"', source)
        self.assertIn('<field name="ref"/>', source)

    def test_repeated_edits_collect_in_one_extension_view(self):
        """One record with several xpaths reads far better than N records."""
        first = self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        second = self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {
                "type": "add_field",
                "name": "lang",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        self.assertEqual(first["view_id"], second["view_id"])
        extension = typed.model(self.env, View).browse(second["view_id"])
        root = etree.fromstring(cast("str", extension.arch).encode())
        self.assertEqual(len(root.findall("xpath")), 2)

    def test_combined_arch_contains_the_edit(self):
        """Proof the edit actually reaches what a user sees."""
        self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
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
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {
                "type": "set_attributes",
                "xpath": "//field[@name='function']",
                "attrs": {"string": "Job Title"},
            },
        )
        result = self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {
                "type": "set_attributes",
                "xpath": "//field[@name='function']",
                "attrs": {"string": "Role", "readonly": "1"},
            },
        )
        extension = typed.model(self.env, View).browse(result["view_id"])
        root = etree.fromstring(cast("str", extension.arch).encode())
        xpaths = root.findall("xpath")
        self.assertEqual(len(xpaths), 1, "attribute edits must merge into one xpath")
        attributes = {a.get("name"): a.text for a in xpaths[0].findall("attribute")}
        self.assertEqual(attributes["string"], "Role")
        self.assertEqual(attributes["readonly"], "1")

    def test_remove_node_is_idempotent(self):
        first = self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {"type": "remove_node", "xpath": "//field[@name='function']"},
        )
        self.editor.apply_operation(
            cast("int", self.base_view.id),
            cast("int", self.package.id),
            {"type": "remove_node", "xpath": "//field[@name='function']"},
        )
        extension = typed.model(self.env, View).browse(first["view_id"])
        root = etree.fromstring(cast("str", extension.arch).encode())
        self.assertEqual(len(root.findall("xpath")), 1)

    def test_invalid_xpath_is_rejected_with_a_useful_error(self):
        """Odoo's own validator runs over the combined arch, so bad edits fail."""
        with raises(self, UserError):
            self.editor.apply_operation(
                cast("int", self.base_view.id),
                cast("int", self.package.id),
                {
                    "type": "add_field",
                    "name": "ref",
                    "xpath": "//field[@name='does_not_exist_anywhere']",
                    "position": "after",
                },
            )

    def test_nonexistent_field_is_rejected(self):
        with raises(self, UserError):
            self.editor.apply_operation(
                cast("int", self.base_view.id),
                cast("int", self.package.id),
                {
                    "type": "add_field",
                    "name": "x_not_a_real_field",
                    "xpath": "//field[@name='function']",
                    "position": "after",
                },
            )

    def test_unknown_operation_is_rejected(self):
        with raises(self, UserError):
            self.editor.apply_operation(
                cast("int", self.base_view.id),
                cast("int", self.package.id),
                {"type": "drop_database"},
            )

    def test_edit_on_a_custom_model_view(self):
        """End to end on a model the builder itself owns.

        Builds the model directly rather than through the wizard: the wizard
        now writes Python and reloads the package, which commits -- so it
        cannot run inside a TransactionCase at all. That path is covered by
        tests/e2e/probe_scaffold.py.
        """
        model_vals: dict[str, object] = {
            "name": "View Demo",
            "model": "x_view_demo",
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
        model = typed.model(self.env, IrModel).create(model_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(
            [
                model,
                cast("IrModelFields", model.field_id).filtered(
                    lambda f: f.state == "manual"
                ),
            ]
        )
        view_vals: dict[str, object] = {
            "name": "x_view_demo.form",
            "model": "x_view_demo",
            "arch": (
                '<form string="View Demo"><sheet><group>'
                '<field name="x_name"/>'
                "</group></sheet></form>"
            ),
        }
        view = self.env["ir.ui.view"].create(view_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(view)
        field_vals: dict[str, object] = {
            "name": "x_note",
            "field_description": "Note",
            "ttype": "text",
            "model_id": typed.model(self.env, IrModel)._get("x_view_demo").id,
        }
        self.env["ir.model.fields"].create(field_vals)  # pyright: ignore[reportArgumentType]
        form = typed.model(self.env, View).search(
            [("model", "=", "x_view_demo"), ("type", "=", "form")], limit=1
        )
        self.editor.apply_operation(
            cast("int", form.id),
            cast("int", self.package.id),
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

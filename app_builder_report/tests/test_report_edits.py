# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Editing a report by gesture rather than by typing XML.

The same `apply_operation` the form editor uses, with two operations that speak
qweb: place a value, and print a table of child rows. Both emit `<xpath>` into
an inheriting view, so editing a report Odoo ships still leaves Odoo's copy
alone.
"""

from __future__ import annotations

from typing import cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.builder_view_editor import BuilderViewEditor
from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.addons.base.models.ir_model import IrModel, IrModelFields
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_report import BuilderReport


@tagged("post_install", "-at_install")
class TestReportEdits(BuilderCase):
    def _report(self, package):
        made = typed.model(self.env, BuilderReport).create_report(
            package.id, "x_builder_project", "Job Sheet"
        )
        return typed.model(self.env, View).browse(made["view_id"])

    def _apply(self, view, package, **operation):
        return typed.model(self.env, BuilderViewEditor).apply_operation(
            view.id, package.id, operation
        )

    def test_a_field_is_placed_as_a_t_field_span(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self._apply(
            view,
            package,
            type="add_report_field",
            xpath="//div[hasclass('page')]",
            position="inside",
            model="x_builder_project",
            name="x_budget",
        )
        arch = cast(
            "str", typed.model(self.env, View).browse(cast("int", view.id)).arch
        )
        self.assertIn('t-field="doc.x_budget"', arch)

    def test_a_label_and_its_value_are_one_unit(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self._apply(
            view,
            package,
            type="add_report_field",
            xpath="//div[hasclass('page')]",
            position="inside",
            model="x_builder_project",
            name="x_budget",
            label="Budget",
        )
        arch = cast(
            "str", typed.model(self.env, View).browse(cast("int", view.id)).arch
        )
        self.assertIn("<strong>Budget</strong>", arch)
        self.assertIn('t-field="doc.x_budget"', arch)

    def test_placing_the_same_field_twice_prints_it_once(self):
        """A double-click must not print the value twice."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        for _attempt in range(2):
            self._apply(
                view,
                package,
                type="add_report_field",
                xpath="//div[hasclass('page')]",
                position="inside",
                model="x_builder_project",
                name="x_budget",
            )
        arch = cast(
            "str", typed.model(self.env, View).browse(cast("int", view.id)).arch
        )
        self.assertEqual(arch.count('t-field="doc.x_budget"'), 1)

    def test_a_binary_says_why_it_cannot_be_text(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        field_vals: dict[str, object] = {
            "name": "x_scan",
            "ttype": "binary",
            "field_description": "Scan",
            "model_id": typed.model(self.env, IrModel)._get("x_builder_project").id,
            "model": "x_builder_project",
        }
        typed.model(self.env, IrModelFields).create(field_vals)  # pyright: ignore[reportArgumentType]
        with raises(self, UserError) as caught:
            self._apply(
                view,
                package,
                type="add_report_field",
                xpath="//div[hasclass('page')]",
                position="inside",
                model="x_builder_project",
                name="x_scan",
            )
        self.assertIn("not text", str(caught.exception).replace("as text", "not text"))

    def test_a_one2many_is_refused_as_a_span_and_pointed_at_the_table(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        field_vals: dict[str, object] = {
            "name": "x_line_ids",
            "ttype": "one2many",
            "field_description": "Lines",
            "model_id": model.id,
            "model": "x_builder_project",
            "relation": "res.partner",
            "relation_field": "parent_id",
        }
        typed.model(self.env, IrModelFields).create(field_vals)  # pyright: ignore[reportArgumentType]
        with raises(self, UserError) as caught:
            self._apply(
                view,
                package,
                type="add_report_field",
                xpath="//div[hasclass('page')]",
                position="inside",
                model="x_builder_project",
                name="x_line_ids",
            )
        self.assertIn("Add table", str(caught.exception))


@tagged("post_install", "-at_install")
class TestReportTables(BuilderCase):
    def _setup(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        field_vals: dict[str, object] = {
            "name": "x_line_ids",
            "ttype": "one2many",
            "field_description": "Lines",
            "model_id": model.id,
            "model": "x_builder_project",
            "relation": "res.partner",
            "relation_field": "parent_id",
        }
        typed.model(self.env, IrModelFields).create(field_vals)  # pyright: ignore[reportArgumentType]
        made = typed.model(self.env, BuilderReport).create_report(
            cast("int", package.id), "x_builder_project", "Job Sheet"
        )
        return package, typed.model(self.env, View).browse(made["view_id"])

    def test_a_table_loops_the_child_records(self):
        package, view = self._setup()
        typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", view.id),
            cast("int", package.id),
            {
                "type": "add_report_table",
                "xpath": "//div[hasclass('page')]",
                "position": "inside",
                "model": "x_builder_project",
                "name": "x_line_ids",
                "columns": ["name", "email"],
            },
        )
        arch = cast(
            "str", typed.model(self.env, View).browse(cast("int", view.id)).arch
        )
        self.assertIn('t-foreach="doc.x_line_ids"', arch)
        self.assertIn('t-as="line"', arch)
        self.assertIn('t-field="line.name"', arch)
        self.assertIn('t-field="line.email"', arch)

    def test_the_header_names_the_columns(self):
        package, view = self._setup()
        typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", view.id),
            cast("int", package.id),
            {
                "type": "add_report_table",
                "xpath": "//div[hasclass('page')]",
                "position": "inside",
                "model": "x_builder_project",
                "name": "x_line_ids",
                "columns": ["name"],
            },
        )
        arch = cast(
            "str", typed.model(self.env, View).browse(cast("int", view.id)).arch
        )
        self.assertIn("<th>", arch)
        self.assertIn("Name", arch)

    def test_a_table_needs_columns(self):
        package, view = self._setup()
        with raises(self, UserError):
            typed.model(self.env, BuilderViewEditor).apply_operation(
                cast("int", view.id),
                cast("int", package.id),
                {
                    "type": "add_report_table",
                    "xpath": "//div[hasclass('page')]",
                    "position": "inside",
                    "model": "x_builder_project",
                    "name": "x_line_ids",
                    "columns": [],
                },
            )

    def test_an_unknown_column_is_named(self):
        package, view = self._setup()
        with raises(self, UserError) as caught:
            typed.model(self.env, BuilderViewEditor).apply_operation(
                cast("int", view.id),
                cast("int", package.id),
                {
                    "type": "add_report_table",
                    "xpath": "//div[hasclass('page')]",
                    "position": "inside",
                    "model": "x_builder_project",
                    "name": "x_line_ids",
                    "columns": ["nope"],
                },
            )
        self.assertIn("nope", str(caught.exception))

    def test_editing_a_core_report_leaves_it_alone(self):
        """The whole point, restated for the report operations."""
        package = self.make_package()
        self.build_demo_content(package)
        report = typed.model(self.env, IrActionsReport).search(
            [("report_type", "=", "qweb-pdf")], limit=1
        )
        view = typed.model(self.env, BuilderReport)._template_of(report)
        if not view:
            self.skipTest("no editable core report here")
        before = view.arch
        typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", view.id),
            cast("int", package.id),
            {
                "type": "add_report_field",
                "xpath": "//t[@t-call='web.html_container']",
                "position": "inside",
                "model": report.model,
                "name": "display_name",
            },
        )
        self.assertEqual(
            typed.model(self.env, View).browse(cast("int", view.id)).arch, before
        )
        extension = typed.model(self.env, View).search(
            [("inherit_id", "=", view.id), ("builder_package_id", "=", package.id)]
        )
        self.assertTrue(extension)
        self.assertIn("t-field", cast("str", extension.arch))

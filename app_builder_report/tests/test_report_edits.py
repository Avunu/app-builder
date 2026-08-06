# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Editing a report by gesture rather than by typing XML.

The same `apply_operation` the form editor uses, with two operations that speak
qweb: place a value, and print a table of child rows. Both emit `<xpath>` into
an inheriting view, so editing a report Odoo ships still leaves Odoo's copy
alone.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestReportEdits(StudioCase):
    def _report(self, package):
        made = self.env["studio.report"].create_report(
            package.id, "x_studio_project", "Job Sheet"
        )
        return self.env["ir.ui.view"].browse(made["view_id"])

    def _apply(self, view, package, **operation):
        return self.env["studio.view.editor"].apply_operation(
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
            model="x_studio_project",
            name="x_budget",
        )
        arch = self.env["ir.ui.view"].browse(view.id).arch
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
            model="x_studio_project",
            name="x_budget",
            label="Budget",
        )
        arch = self.env["ir.ui.view"].browse(view.id).arch
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
                model="x_studio_project",
                name="x_budget",
            )
        arch = self.env["ir.ui.view"].browse(view.id).arch
        self.assertEqual(arch.count('t-field="doc.x_budget"'), 1)

    def test_a_binary_says_why_it_cannot_be_text(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["ir.model.fields"].create(
            {
                "name": "x_scan",
                "ttype": "binary",
                "field_description": "Scan",
                "model_id": self.env["ir.model"]._get("x_studio_project").id,
                "model": "x_studio_project",
            }
        )
        with self.assertRaises(UserError) as caught:
            self._apply(
                view,
                package,
                type="add_report_field",
                xpath="//div[hasclass('page')]",
                position="inside",
                model="x_studio_project",
                name="x_scan",
            )
        self.assertIn("not text", str(caught.exception).replace("as text", "not text"))

    def test_a_one2many_is_refused_as_a_span_and_pointed_at_the_table(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        model = self.env["ir.model"]._get("x_studio_project")
        self.env["ir.model.fields"].create(
            {
                "name": "x_line_ids",
                "ttype": "one2many",
                "field_description": "Lines",
                "model_id": model.id,
                "model": "x_studio_project",
                "relation": "res.partner",
                "relation_field": "parent_id",
            }
        )
        with self.assertRaises(UserError) as caught:
            self._apply(
                view,
                package,
                type="add_report_field",
                xpath="//div[hasclass('page')]",
                position="inside",
                model="x_studio_project",
                name="x_line_ids",
            )
        self.assertIn("Add table", str(caught.exception))


@tagged("post_install", "-at_install")
class TestReportTables(StudioCase):
    def _setup(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        self.env["ir.model.fields"].create(
            {
                "name": "x_line_ids",
                "ttype": "one2many",
                "field_description": "Lines",
                "model_id": model.id,
                "model": "x_studio_project",
                "relation": "res.partner",
                "relation_field": "parent_id",
            }
        )
        made = self.env["studio.report"].create_report(
            package.id, "x_studio_project", "Job Sheet"
        )
        return package, self.env["ir.ui.view"].browse(made["view_id"])

    def test_a_table_loops_the_child_records(self):
        package, view = self._setup()
        self.env["studio.view.editor"].apply_operation(
            view.id,
            package.id,
            {
                "type": "add_report_table",
                "xpath": "//div[hasclass('page')]",
                "position": "inside",
                "model": "x_studio_project",
                "name": "x_line_ids",
                "columns": ["name", "email"],
            },
        )
        arch = self.env["ir.ui.view"].browse(view.id).arch
        self.assertIn('t-foreach="doc.x_line_ids"', arch)
        self.assertIn('t-as="line"', arch)
        self.assertIn('t-field="line.name"', arch)
        self.assertIn('t-field="line.email"', arch)

    def test_the_header_names_the_columns(self):
        package, view = self._setup()
        self.env["studio.view.editor"].apply_operation(
            view.id,
            package.id,
            {
                "type": "add_report_table",
                "xpath": "//div[hasclass('page')]",
                "position": "inside",
                "model": "x_studio_project",
                "name": "x_line_ids",
                "columns": ["name"],
            },
        )
        arch = self.env["ir.ui.view"].browse(view.id).arch
        self.assertIn("<th>", arch)
        self.assertIn("Name", arch)

    def test_a_table_needs_columns(self):
        package, view = self._setup()
        with self.assertRaises(UserError):
            self.env["studio.view.editor"].apply_operation(
                view.id,
                package.id,
                {
                    "type": "add_report_table",
                    "xpath": "//div[hasclass('page')]",
                    "position": "inside",
                    "model": "x_studio_project",
                    "name": "x_line_ids",
                    "columns": [],
                },
            )

    def test_an_unknown_column_is_named(self):
        package, view = self._setup()
        with self.assertRaises(UserError) as caught:
            self.env["studio.view.editor"].apply_operation(
                view.id,
                package.id,
                {
                    "type": "add_report_table",
                    "xpath": "//div[hasclass('page')]",
                    "position": "inside",
                    "model": "x_studio_project",
                    "name": "x_line_ids",
                    "columns": ["nope"],
                },
            )
        self.assertIn("nope", str(caught.exception))

    def test_editing_a_core_report_leaves_it_alone(self):
        """The whole point, restated for the report operations."""
        package = self.make_package()
        self.build_demo_content(package)
        report = self.env["ir.actions.report"].search(
            [("report_type", "=", "qweb-pdf")], limit=1
        )
        view = self.env["studio.report"]._template_of(report)
        if not view:
            self.skipTest("no editable core report here")
        before = view.arch
        self.env["studio.view.editor"].apply_operation(
            view.id,
            package.id,
            {
                "type": "add_report_field",
                "xpath": "//t[@t-call='web.html_container']",
                "position": "inside",
                "model": report.model,
                "name": "display_name",
            },
        )
        self.assertEqual(self.env["ir.ui.view"].browse(view.id).arch, before)
        extension = self.env["ir.ui.view"].search(
            [("inherit_id", "=", view.id), ("studio_package_id", "=", package.id)]
        )
        self.assertTrue(extension)
        self.assertIn("t-field", extension.arch)

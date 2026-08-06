# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rendering a report for the editor, and resolving a click back to the arch."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestReportPreview(StudioCase):
    def _report(self, package):
        made = self.env["studio.report"].create_report(
            package.id, "x_studio_project", "Job Sheet"
        )
        return self.env["ir.ui.view"].browse(made["view_id"])

    def _placed(self, package, view, name="x_budget"):
        self.env["studio.view.editor"].apply_operation(
            view.id,
            package.id,
            {
                "type": "add_report_field",
                "xpath": "//div[hasclass('page')]",
                "position": "inside",
                "model": "x_studio_project",
                "name": name,
            },
        )

    def test_the_preview_renders_the_report(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_studio_project"].create({"x_name": "Bridge survey"})
        result = self.env["studio.report"].preview_html(view.id)
        self.assertFalse(result["reason"])
        self.assertIn("Job Sheet", result["html"])
        self.assertIn("Bridge survey", result["html"])

    def test_the_preview_brands_its_fields(self):
        """Base brands `t-field` and nothing else, and the attribute is
        `data-oe-expression` -- node-level `data-oe-xpath` belongs to website."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_studio_project"].create({"x_name": "Bridge survey"})
        html = self.env["studio.report"].preview_html(view.id)["html"]
        self.assertIn("data-oe-expression", html)
        self.assertIn("doc.display_name", html)

    def test_a_report_with_nothing_to_draw_says_so(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self.env["x_studio_project"].search([]).unlink()
        result = self.env["studio.report"].preview_html(view.id)
        self.assertEqual(result["html"], "")
        self.assertIn("preview this on", result["reason"])

    def test_a_click_resolves_to_a_locator(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self._placed(package, view)
        found = self.env["studio.report"].locate_expression(view.id, "doc.x_budget")
        self.assertTrue(found["found"])
        self.assertIn("t-field='doc.x_budget'", found["xpath"])

    def test_the_locator_survives_a_second_field(self):
        """Two spans, and the one clicked has to be the one located."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        self._placed(package, view, "x_budget")
        self._placed(package, view, "x_name")
        for name in ("x_budget", "x_name"):
            found = self.env["studio.report"].locate_expression(
                view.id, "doc.%s" % name
            )
            self.assertTrue(found["found"])
            self.assertIn(name, found["xpath"])

    def test_an_expression_we_cannot_point_at_says_why(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        found = self.env["studio.report"].locate_expression(view.id, "doc.nope")
        self.assertFalse(found["found"])
        self.assertIn("cannot point at", found["reason"])

    def test_the_body_anchor_is_the_page(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        anchor = self.env["studio.report"].body_anchor(view.id)
        self.assertTrue(anchor["found"])
        self.assertIn("page", anchor["xpath"])

    def test_the_anchor_is_usable_as_an_operation_target(self):
        """The point of it: add something without having clicked anything."""
        package = self.make_package()
        self.build_demo_content(package)
        view = self._report(package)
        anchor = self.env["studio.report"].body_anchor(view.id)
        self.env["studio.view.editor"].apply_operation(
            view.id,
            package.id,
            {
                "type": "add_report_field",
                "xpath": anchor["xpath"],
                "position": anchor["position"],
                "model": "x_studio_project",
                "name": "x_budget",
            },
        )
        self.assertIn(
            't-field="doc.x_budget"', self.env["ir.ui.view"].browse(view.id).arch
        )

    def test_a_form_view_is_not_a_report(self):
        package = self.make_package()
        self.build_demo_content(package)
        form = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        with self.assertRaises(UserError):
            self.env["studio.report"].preview_html(form.id)

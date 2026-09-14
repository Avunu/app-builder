# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Reports as a record pane: a report made whole from a layout, a core
report shown with its template editable and its patch resettable."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

MODEL = "x_studio_project"


@tagged("post_install", "-at_install")
class TestReportSurface(StudioCase):
    def setUp(self):
        super().setUp()
        self.Surface = self.env["studio.report"]
        self.package = self.make_package()
        self.build_demo_content(self.package)

    def test_the_templates_are_the_layouts(self):
        keys = [t["key"] for t in self.Surface.templates(MODEL)]
        self.assertIn("external", keys)
        self.assertIn("internal", keys)
        self.assertTrue(all(t["needs"] == ["name"] for t in self.Surface.templates()))

    def test_a_report_is_made_whole_from_a_layout(self):
        row = self.Surface.create_record(
            MODEL, self.package.id, {"name": "Job Sheet"}, template="internal"
        )
        report = self.env["ir.actions.report"].browse(row["id"])
        self.assertEqual(report.model, MODEL)
        self.assertTrue(row["view_id"])
        self.assertTrue(row["owned"] and row["editable"])
        self.assertIn("print", [b["key"] for b in row["badges"]])
        self.assertIn("template", row["sentence"])
        files = self.package._render_files()
        self.assertIn("Job Sheet", files["report/x_studio_project_reports.xml"])
        with self.assertRaises(UserError):
            self.Surface.create_record(
                MODEL, self.package.id, {"name": "Job Sheet"}, template="external"
            )
        with self.assertRaises(UserError):
            self.Surface.create_record(
                MODEL, self.package.id, {"name": "Other"}, template="nope"
            )

    def test_the_print_menu_and_groups_are_rows(self):
        row = self.Surface.create_record(
            MODEL, self.package.id, {"name": "Job Sheet"}, template="external"
        )
        report = self.env["ir.actions.report"].browse(row["id"])
        self.assertTrue(report.binding_model_id)
        described = self.Surface.describe(row["id"], self.package.id)
        self.assertTrue(described["values"]["in_print_menu"])
        self.Surface.write_record(
            row["id"],
            {"in_print_menu": False, "groups": [self.env.ref("base.group_user").id]},
            self.package.id,
        )
        self.assertFalse(report.binding_model_id)
        self.assertIn(self.env.ref("base.group_user"), report.groups_id)
        rendered = self.package._render_files()["report/x_studio_project_reports.xml"]
        self.assertIn("base.group_user", rendered)

    def test_a_core_report_is_shown_with_its_patch_and_reset(self):
        report = self.env["ir.actions.report"].search(
            [("report_type", "=", "qweb-pdf")], limit=1
        )
        if not report:
            self.skipTest("no qweb report installed here")
        view = self.Surface._template_of(report)
        if not view:
            self.skipTest("that report's template is not a view")
        rows = {r["id"]: r for r in self.Surface.rows(report.model, self.package.id)}
        row = rows[report.id]
        self.assertFalse(row["editable"])
        self.assertEqual(row["view_id"], view.id)
        self.assertFalse(row["patched"])
        self.assertIn("layout you can edit", row["reason"])
        with self.assertRaises(UserError):
            self.Surface.write_record(report.id, {"name": "Mine"}, self.package.id)
        self.env["studio.view.editor"].apply_operation(
            view.id,
            self.package.id,
            {
                "type": "set_attributes",
                "xpath": "//t[@t-call='web.html_container']",
                "position": "attributes",
                "attrs": {"data-studio": "1"},
            },
        )
        described = self.Surface.describe(report.id, self.package.id)
        self.assertTrue(described["row"]["patched"])
        self.assertIn("reset_layout", [a["key"] for a in described["actions"]])
        self.Surface.run(report.id, "reset_layout", self.package.id)
        self.assertFalse(self.Surface._patch_of(report, self.package))
        self.assertFalse(
            self.Surface.describe(report.id, self.package.id)["row"]["patched"]
        )

    def test_remove_takes_the_template_along(self):
        row = self.Surface.create_record(
            MODEL, self.package.id, {"name": "Gone"}, template="blank"
        )
        view_id = row["view_id"]
        self.Surface.remove_record(row["id"], self.package.id, force=True)
        self.assertFalse(self.env["ir.ui.view"].browse(view_id).exists())
        self.assertNotIn("Gone", "".join(self.package._render_files().values()))

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Reports as a record pane: a report made whole from a layout, a core
report shown with its template editable and its patch resettable."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.builder_view_editor import BuilderViewEditor
from odoo.addons.base.models.ir_actions_report import IrActionsReport

from ..models.builder_report import BuilderReport as BuilderReportBase
from ..models.builder_report_surface import BuilderReport

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_record_surface import (
        BuilderRecordSurface,
        RecordActionJSON,
    )
    from odoo.addons.base.models.ir_actions import IrActions

    from ..models.builder_report_surface import ReportRowJSON

MODEL = "x_builder_project"


@tagged("post_install", "-at_install")
class TestReportSurface(BuilderCase):
    def setUp(self):
        super().setUp()
        self.Surface = typed.model(self.env, BuilderReport)
        self.package = self.make_package()
        self.build_demo_content(self.package)

    def test_the_templates_are_the_layouts(self):
        keys = [t["key"] for t in self.Surface.templates(MODEL)]
        self.assertIn("external", keys)
        self.assertIn("internal", keys)
        self.assertTrue(all(t["needs"] == ["name"] for t in self.Surface.templates()))

    def test_a_report_is_made_whole_from_a_layout(self):
        row = self.Surface.create_record(
            MODEL,
            cast("int", self.package.id),
            {"name": "Job Sheet"},
            template="internal",
        )
        report = typed.model(self.env, IrActionsReport).browse(row["id"])
        self.assertEqual(report.model, MODEL)
        self.assertTrue(row["view_id"])
        self.assertTrue(row["owned"] and row["editable"])
        self.assertIn("print", [b["key"] for b in row["badges"]])
        self.assertIn("template", row["sentence"])
        files = self.package._render_files()
        self.assertIn("Job Sheet", files["report/x_builder_project_reports.xml"])
        with raises(self, UserError):
            self.Surface.create_record(
                MODEL,
                cast("int", self.package.id),
                {"name": "Job Sheet"},
                template="external",
            )
        with raises(self, UserError):
            self.Surface.create_record(
                MODEL, cast("int", self.package.id), {"name": "Other"}, template="nope"
            )

    def test_the_print_menu_and_groups_are_rows(self):
        row = self.Surface.create_record(
            MODEL,
            cast("int", self.package.id),
            {"name": "Job Sheet"},
            template="external",
        )
        report = typed.model(self.env, IrActionsReport).browse(row["id"])
        self.assertTrue(cast("IrActions", report).binding_model_id)
        described = cast("BuilderRecordSurface", self.Surface).describe(
            row["id"], cast("int", self.package.id)
        )
        self.assertTrue(cast("dict[str, object]", described["values"])["in_print_menu"])
        cast("BuilderRecordSurface", self.Surface).write_record(
            row["id"],
            {
                "in_print_menu": False,
                "groups": [typed.ref(self.env, "base.group_user").id],
            },
            cast("int", self.package.id),
        )
        self.assertFalse(cast("IrActions", report).binding_model_id)
        self.assertIn(typed.ref(self.env, "base.group_user"), report.groups_id)
        rendered = self.package._render_files()["report/x_builder_project_reports.xml"]
        self.assertIn("base.group_user", rendered)

    def test_a_core_report_is_shown_with_its_patch_and_reset(self):
        report = typed.model(self.env, IrActionsReport).search(
            [("report_type", "=", "qweb-pdf")], limit=1
        )
        if not report:
            self.skipTest("no qweb report installed here")
        view = typed.model(self.env, BuilderReportBase)._template_of(report)
        if not view:
            self.skipTest("that report's template is not a view")
        rows = {
            r["id"]: r
            for r in cast(
                "list[ReportRowJSON]",
                cast("BuilderRecordSurface", self.Surface).rows(
                    cast("str", report.model), cast("int", self.package.id)
                ),
            )
        }
        row = rows[cast("int", report.id)]
        self.assertFalse(row["editable"])
        self.assertEqual(row["view_id"], view.id)
        self.assertFalse(row["patched"])
        self.assertIn("layout you can edit", row["reason"])
        with raises(self, UserError):
            cast("BuilderRecordSurface", self.Surface).write_record(
                cast("int", report.id), {"name": "Mine"}, cast("int", self.package.id)
            )
        typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", view.id),
            cast("int", self.package.id),
            {
                "type": "set_attributes",
                "xpath": "//t[@t-call='web.html_container']",
                "position": "attributes",
                "attrs": {"data-builder": "1"},
            },
        )
        described = cast("BuilderRecordSurface", self.Surface).describe(
            cast("int", report.id), cast("int", self.package.id)
        )
        self.assertTrue(cast("ReportRowJSON", described["row"])["patched"])
        self.assertIn(
            "reset_layout",
            [a["key"] for a in cast("list[RecordActionJSON]", described["actions"])],
        )
        cast("BuilderRecordSurface", self.Surface).run(
            cast("int", report.id), "reset_layout", cast("int", self.package.id)
        )
        self.assertFalse(self.Surface._patch_of(report, self.package))
        self.assertFalse(
            cast(
                "ReportRowJSON",
                cast("BuilderRecordSurface", self.Surface).describe(
                    cast("int", report.id), cast("int", self.package.id)
                )["row"],
            )["patched"]
        )

    def test_remove_takes_the_template_along(self):
        row = self.Surface.create_record(
            MODEL, cast("int", self.package.id), {"name": "Gone"}, template="blank"
        )
        view_id = row["view_id"]
        self.Surface.remove_record(row["id"], cast("int", self.package.id), force=True)
        self.assertFalse(self.env["ir.ui.view"].browse(view_id).exists())
        self.assertNotIn("Gone", "".join(self.package._render_files().values()))

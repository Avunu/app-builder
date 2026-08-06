# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Driving the report editor the way a person does.

The operations had unit tests and no caller for a day: written, tested,
committed and described as gestures while nothing in the browser could invoke
either one. No server-side test could see that, which is the whole reason this
file exists.
"""

import tempfile

from odoo import Command
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestReportEditorTour(HttpCase):
    def test_a_report_can_be_edited_by_clicking_it(self):
        package = self.env["studio.package"].create(
            {
                "name": "x_tour_report_pkg",
                "display_name_": "Tour Reports",
                "root_path": tempfile.mkdtemp(prefix="studio-tour-report-"),
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_report_pkg", "state": "installed"}
        )
        self.env.ref("base.user_admin").groups_id |= self.env.ref(
            "app_builder_base.group_studio_manager"
        )

        # A manual model, so the report has a field of its own to print and a
        # record to draw. res.partner would work too, but its fields are core's
        # and the point here is a report over something the studio made.
        model = self.env["ir.model"].create(
            {
                "name": "Tour Job",
                "model": "x_tour_job",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_name",
                            "ttype": "char",
                            "field_description": "Name",
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_budget",
                            "ttype": "float",
                            "field_description": "Budget",
                        }
                    ),
                ],
            }
        )
        self.env["ir.model.access"].create(
            {
                "name": "x_tour_job all",
                "model_id": model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            }
        )
        # The report binds to its model by xmlid, so the model has to be the
        # package's before a report over it can be written to source.
        package.studio_capture(model)
        self.env["x_tour_job"].create({"x_name": "Bridge survey"})
        made = self.env["studio.report"].create_report(
            package.id, "x_tour_job", "Job Sheet"
        )

        # Start where a person starts -- the report list -- so the tour walks
        # the whole path, including the Edit Layout button that is the only
        # thing connecting a report to the editor.
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Reports",
                "res_model": "ir.actions.report",
                "view_mode": "list,form",
                "domain": "[('report_name', '=', %r)]" % made["report_name"],
            }
        )
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_report_editor_tour",
            login="admin",
        )

        # What the tour saw on screen, asserted against what was written.
        arch = self.env["ir.ui.view"].browse(made["view_id"]).arch
        self.assertIn('t-field="doc.x_budget"', arch)
        self.assertIn("Budget", arch)
        self.assertIn(
            't-field="doc.x_budget"',
            "".join(package._render_files().values()),
            "and it reached the source file, not just the database",
        )

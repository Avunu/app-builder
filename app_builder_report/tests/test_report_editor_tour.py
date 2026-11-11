# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Driving the report editor the way a person does.

The operations had unit tests and no caller for a day: written, tested,
committed and described as gestures while nothing in the browser could invoke
either one. No server-side test could see that, which is the whole reason this
file exists.
"""

import tempfile
from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.tests import tagged

from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
from odoo.addons.app_builder_base.tests.common import BuilderHttpCase
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_report import BuilderReport

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.base.models.res_users import Groups, Users


@tagged("post_install", "-at_install")
class TestReportEditorTour(BuilderHttpCase):
    def test_a_report_can_be_edited_by_clicking_it(self):
        # `@api.model_create_multi`'s own stub gap (TYPING.md's "Known
        # traps"): every single-dict `.create(vals)` below needs its own
        # named local so the `# pyright: ignore[reportArgumentType]` lands
        # on the `create()` call's own line, same idiom `common.py`'s own
        # `build_demo_content` already established.
        package_vals: dict[str, object] = {
            "name": "x_tour_report_pkg",
            "display_name_": "Tour Reports",
            "root_path": tempfile.mkdtemp(prefix="builder-tour-report-"),
            "auto_commit": "off",
        }
        package = typed.model(self.env, BuilderPackage).create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {
            "name": "x_tour_report_pkg",
            "state": "installed",
        }
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        admin = cast("Users", typed.ref(self.env, "base.user_admin"))
        # `groups_id`'s own plain string comodel reads as a messy union
        # (`Field.__get__`'s own generic left unresolved) -- same idiom 6
        # cast as any other relational field read, applied to the read half
        # of `|=` since the write half (`Field.__set__`) is unannotated and
        # needs none.
        admin.groups_id = cast("Groups", admin.groups_id) | typed.ref(
            self.env, "app_builder_base.group_builder_manager"
        )

        # A manual model, so the report has a field of its own to print and a
        # record to draw. res.partner would work too, but its fields are core's
        # and the point here is a report over something the builder made.
        model_vals: dict[str, object] = {
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
        model = self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        access_vals: dict[str, object] = {
            "name": "x_tour_job all",
            "model_id": model.id,
            "group_id": typed.ref(self.env, "base.group_user").id,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        }
        self.env["ir.model.access"].create(access_vals)  # pyright: ignore[reportArgumentType]
        # The report binds to its model by xmlid, so the model has to be the
        # package's before a report over it can be written to source.
        package.builder_capture(model)
        job_vals: dict[str, object] = {"x_name": "Bridge survey"}
        self.env["x_tour_job"].create(job_vals)  # pyright: ignore[reportArgumentType]

        # Start where a person starts -- the model's list, the cog, the
        # console -- so the tour walks the whole path: the Reports pane, a
        # report made from a layout, and Edit layout on its card, which is
        # the only thing connecting a report to the editor.
        action_vals: dict[str, object] = {
            "name": "Tour Jobs",
            "res_model": "x_tour_job",
            "view_mode": "list,form",
        }
        action = self.env["ir.actions.act_window"].create(action_vals)  # pyright: ignore[reportArgumentType]
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_report_editor_tour",
            login="admin",
        )
        report = typed.model(self.env, IrActionsReport).search(
            [("model", "=", "x_tour_job"), ("name", "=", "Job Sheet")]
        )
        self.assertEqual(len(report), 1)
        # `builder_package_id` is added to `ir.actions.report` by
        # `builder.owned.mixin` (registry-level `_inherit`, never a real
        # Python base class of `IrActionsReport`) -- same cast idiom
        # `builder_report.py`'s own `_row()` uses for the identical field.
        self.assertEqual(cast("BuilderOwnedMixin", report).builder_package_id, package)
        made = {
            "view_id": cast(
                "int", typed.model(self.env, BuilderReport)._template_of(report).id
            )
        }

        # What the tour saw on screen, asserted against what was written.
        arch = cast("str", typed.model(self.env, View).browse(made["view_id"]).arch)
        self.assertIn('t-field="doc.x_budget"', arch)
        self.assertIn("Budget", arch)
        self.assertIn(
            't-field="doc.x_budget"',
            "".join(package._render_files().values()),
            "and it reached the source file, not just the database",
        )

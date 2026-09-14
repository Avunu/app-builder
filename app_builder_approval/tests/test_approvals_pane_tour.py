# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Approvals pane's gate header, driven on a model that is not gated.

Turning the gate on reloads the server, which a tour cannot sit through;
``test_approval.py`` pins what the enable writes, and this pins what the
person sees before pressing it.
"""

import tempfile

from odoo.tests import HttpCase, tagged

from odoo.addons.app_builder_base.tests.common import join_groups


@tagged("post_install", "-at_install")
class TestApprovalsPaneTour(HttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")

    def test_the_gate_comes_before_the_rules(self):
        self.env["studio.package"].create(
            {
                "name": "x_tour_appr_pkg",
                "display_name_": "Tour Approvals",
                "root_path": tempfile.mkdtemp(prefix="studio-tour-"),
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_appr_pkg", "state": "installed"}
        )
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_approvals_pane_tour",
            login="admin",
        )
        self.assertNotIn(
            "tier.validation",
            self.env["res.partner"]._inherit_module,
            "the tour must not have switched the gate on",
        )

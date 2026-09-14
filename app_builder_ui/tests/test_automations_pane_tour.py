# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Automations pane, driven: New from a template, the steps edited
from the sidebar, the rule switched off -- and the file afterwards."""

import os
import tempfile

from odoo.tests import HttpCase, tagged

from odoo.addons.app_builder_base.tests.common import join_groups


@tagged("post_install", "-at_install")
class TestAutomationsPaneTour(HttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        self.addCleanup(self.env["base.automation"]._unregister_hook)

    def test_an_automation_is_made_and_edited_from_the_pane(self):
        root = tempfile.mkdtemp(prefix="studio-tour-")
        package = self.env["studio.package"].create(
            {
                "name": "x_tour_auto_pkg",
                "display_name_": "Tour Automations",
                "root_path": root,
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_auto_pkg", "state": "installed"}
        )
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        # The tour starts from an empty pane: no partner automations may exist.
        self.env["base.automation"].search(
            [("model_id.model", "=", "res.partner")]
        ).unlink()
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_automations_pane_tour",
            login="admin",
        )
        rule = (
            self.env["base.automation"]
            .with_context(active_test=False)
            .search([("name", "=", "Tour Set Field")])
        )
        self.assertEqual(len(rule), 1)
        self.assertFalse(rule.active)
        self.assertEqual(rule.studio_package_id, package)
        self.assertEqual(rule.filter_domain, "[('is_company', '=', True)]")
        self.assertEqual(rule.action_server_ids.mapped("state"), ["code"])
        path = os.path.join(root, "data", "res_partner_automation.xml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Tour Set Field", content)
        self.assertIn('name="active"', content)
        self.assertNotIn("object_write", content)

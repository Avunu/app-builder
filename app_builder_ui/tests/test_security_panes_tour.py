# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Access Control and Filter Rules panes, driven; the files afterwards."""

import os
import tempfile

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioHttpCase, join_groups
from odoo.addons.app_builder_base.tools import compat


@tagged("post_install", "-at_install")
class TestSecurityPanesTour(StudioHttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        self.addCleanup(self.env["base.automation"]._unregister_hook)

    def test_a_line_and_a_rule_are_made_from_the_panes(self):
        root = tempfile.mkdtemp(prefix="studio-tour-")
        package = self.env["studio.package"].create(
            {
                "name": "x_tour_sec_pkg",
                "display_name_": "Tour Security",
                "root_path": root,
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_sec_pkg", "state": "installed"}
        )
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        group = self.env["res.groups"].create({"name": "Tour Group"})
        self.env["ir.model.data"].create(
            {
                "module": "x_tour_sec_pkg",
                "name": "group_tour",
                "model": "res.groups",
                "res_id": group.id,
            }
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
            "app_builder_security_panes_tour",
            login="admin",
        )
        access = self.env["ir.model.access"].search([("group_id", "=", group.id)])
        self.assertEqual(len(access), 1)
        self.assertEqual(access.model_id.model, "res.partner")
        self.assertTrue(access.perm_read and access.perm_write)
        self.assertFalse(access.perm_create or access.perm_unlink)
        self.assertEqual(access.studio_package_id, package)
        with open(
            os.path.join(root, "security", "ir.model.access.csv"), encoding="utf-8"
        ) as handle:
            csv = handle.read()
        self.assertIn("group_tour", csv)
        rule = self.env["ir.rule"].search([("name", "=", "Tour Own Records")])
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule[compat.groups_field(self.env, "ir.rule")], group)
        self.assertIn("create_uid", rule.domain_force)
        self.assertEqual(rule.studio_package_id, package)
        with open(
            os.path.join(root, "security", "res_partner_security.xml"),
            encoding="utf-8",
        ) as handle:
            xml = handle.read()
        self.assertIn("Tour Own Records", xml)
        self.assertIn("group_tour", xml)

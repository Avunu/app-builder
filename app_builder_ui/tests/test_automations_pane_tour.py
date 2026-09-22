# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Automations pane, driven: New from a template, the steps edited
from the sidebar, the rule switched off -- and the file afterwards."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, cast

from odoo.tests import tagged

from odoo.addons.base_automation.models.base_automation import BaseAutomation
from odoo.addons.app_builder_base.tests.common import StudioHttpCase, join_groups
from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_actions import IrActionsServer
    from odoo.addons.base.models.res_users import Users
    from odoo.addons.app_builder_base.models.studio_owned_mixin import StudioOwnedMixin


@tagged("post_install", "-at_install")
class TestAutomationsPaneTour(StudioHttpCase):
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
        package_vals: dict[str, object] = {
            "name": "x_tour_auto_pkg",
            "display_name_": "Tour Automations",
            "root_path": root,
            "auto_commit": "off",
        }
        package = self.env["studio.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {
            "name": "x_tour_auto_pkg",
            "state": "installed",
        }
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        join_groups(
            cast("Users", typed.ref(self.env, "base.user_admin")),
            ["app_builder_base.group_studio_manager"],
        )
        # The tour starts from an empty pane: no partner automations may exist.
        self.env["base.automation"].search(
            [("model_id.model", "=", "res.partner")]
        ).unlink()
        action_vals: dict[str, object] = {
            "name": "Tour Contacts",
            "res_model": "res.partner",
            "view_mode": "list,form",
        }
        action = self.env["ir.actions.act_window"].create(action_vals)  # pyright: ignore[reportArgumentType]
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_automations_pane_tour",
            login="admin",
        )
        rule = (
            typed.model(self.env, BaseAutomation)
            .with_context(active_test=False)
            .search([("name", "=", "Tour Set Field")])
        )
        self.assertEqual(len(rule), 1)
        self.assertFalse(rule.active)
        # studio_package_id lives on studio.owned.mixin, _inherit-composed
        # into base.automation -- invisible to pyright on the real class.
        self.assertEqual(cast("StudioOwnedMixin", rule).studio_package_id, package)
        self.assertEqual(rule.filter_domain, "[('is_company', '=', True)]")
        self.assertEqual(
            cast("IrActionsServer", rule.action_server_ids).mapped("state"), ["code"]
        )
        path = os.path.join(root, "data", "res_partner_automation.xml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Tour Set Field", content)
        self.assertIn('name="active"', content)
        self.assertNotIn("object_write", content)

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Approvals pane's gate header, driven on a model that is not gated.

Turning the gate on reloads the server, which a tour cannot sit through;
``test_approval.py`` pins what the enable writes, and this pins what the
person sees before pressing it.
"""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING, cast

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioHttpCase, join_groups
from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    from odoo.addons.base.models.res_users import Users


@tagged("post_install", "-at_install")
class TestApprovalsPaneTour(StudioHttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")

    def test_the_gate_comes_before_the_rules(self):
        package_vals: dict[str, object] = {
            "name": "x_tour_appr_pkg",
            "display_name_": "Tour Approvals",
            "root_path": tempfile.mkdtemp(prefix="studio-tour-"),
            "auto_commit": "off",
        }
        self.env["studio.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {
            "name": "x_tour_appr_pkg",
            "state": "installed",
        }
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        join_groups(
            cast("Users", typed.ref(self.env, "base.user_admin")),
            ["app_builder_base.group_studio_manager"],
        )
        action_vals: dict[str, object] = {
            "name": "Tour Contacts",
            "res_model": "res.partner",
            "view_mode": "list,form",
        }
        action = self.env["ir.actions.act_window"].create(action_vals)  # pyright: ignore[reportArgumentType]
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_approvals_pane_tour",
            login="admin",
        )
        self.assertNotIn(
            "tier.validation",
            # `_inherit_module`'s own stub gap is the identical one
            # `studio_approval.py`'s own `_empty_state` already documents.
            self.env["res.partner"]._inherit_module,  # pyright: ignore[reportAttributeAccessIssue]
            "the tour must not have switched the gate on",
        )

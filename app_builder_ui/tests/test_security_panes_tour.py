# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Access Control and Filter Rules panes, driven; the files afterwards."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, cast

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderHttpCase, join_groups
from odoo.addons.app_builder_base.tools import compat, typed
from odoo.addons.base.models.ir_model import IrModelAccess
from odoo.addons.base.models.ir_rule import IrRule

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.base.models.ir_model import IrModel
    from odoo.addons.base.models.res_users import Users


@tagged("post_install", "-at_install")
class TestSecurityPanesTour(BuilderHttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        self.addCleanup(self.env["base.automation"]._unregister_hook)

    def test_a_line_and_a_rule_are_made_from_the_panes(self):
        root = tempfile.mkdtemp(prefix="builder-tour-")
        package_vals: dict[str, object] = {
            "name": "x_tour_sec_pkg",
            "display_name_": "Tour Security",
            "root_path": root,
            "auto_commit": "off",
        }
        package = self.env["builder.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {
            "name": "x_tour_sec_pkg",
            "state": "installed",
        }
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        join_groups(
            cast("Users", typed.ref(self.env, "base.user_admin")),
            ["app_builder_base.group_builder_manager"],
        )
        group_vals: dict[str, object] = {"name": "Tour Group"}
        group = self.env["res.groups"].create(group_vals)  # pyright: ignore[reportArgumentType]
        data_vals: dict[str, object] = {
            "module": "x_tour_sec_pkg",
            "name": "group_tour",
            "model": "res.groups",
            "res_id": group.id,
        }
        self.env["ir.model.data"].create(data_vals)  # pyright: ignore[reportArgumentType]
        action_vals: dict[str, object] = {
            "name": "Tour Contacts",
            "res_model": "res.partner",
            "view_mode": "list,form",
        }
        action = self.env["ir.actions.act_window"].create(action_vals)  # pyright: ignore[reportArgumentType]
        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_security_panes_tour",
            login="admin",
        )
        access = typed.model(self.env, IrModelAccess).search(
            [("group_id", "=", group.id)]
        )
        self.assertEqual(len(access), 1)
        self.assertEqual(cast("IrModel", access.model_id).model, "res.partner")
        self.assertTrue(access.perm_read and access.perm_write)
        self.assertFalse(access.perm_create or access.perm_unlink)
        self.assertEqual(cast("BuilderOwnedMixin", access).builder_package_id, package)
        with open(
            os.path.join(root, "security", "ir.model.access.csv"), encoding="utf-8"
        ) as handle:
            csv = handle.read()
        self.assertIn("group_tour", csv)
        rule = typed.model(self.env, IrRule).search([("name", "=", "Tour Own Records")])
        self.assertEqual(len(rule), 1)
        self.assertEqual(rule[compat.groups_field(self.env, "ir.rule")], group)
        self.assertIn("create_uid", cast("str", rule.domain_force))
        self.assertEqual(cast("BuilderOwnedMixin", rule).builder_package_id, package)
        with open(
            os.path.join(root, "security", "res_partner_security.xml"),
            encoding="utf-8",
        ) as handle:
            xml = handle.read()
        self.assertIn("Tour Own Records", xml)
        self.assertIn("group_tour", xml)

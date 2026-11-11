# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Menu pane, driven: a submenu made under the package's app, moved
above its sibling, renamed -- and menus.xml afterwards."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, cast

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderHttpCase, join_groups
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModel

from ..models.builder_menu_surface import BuilderMenu

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.base.models.ir_actions import IrActionsActWindow
    from odoo.addons.base.models.ir_ui_menu import IrUiMenu
    from odoo.addons.base.models.res_users import Users


@tagged("post_install", "-at_install")
class TestMenuPaneTour(BuilderHttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        self.addCleanup(self.env["base.automation"]._unregister_hook)

    def test_a_submenu_is_made_moved_and_renamed_from_the_pane(self):
        root = tempfile.mkdtemp(prefix="builder-tour-")
        package_vals: dict[str, object] = {
            "name": "x_tour_menu_pkg",
            "display_name_": "Tour Menus",
            "root_path": root,
            "auto_commit": "off",
        }
        package = self.env["builder.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {
            "name": "x_tour_menu_pkg",
            "state": "installed",
        }
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        join_groups(
            cast("Users", typed.ref(self.env, "base.user_admin")),
            ["app_builder_base.group_builder_manager"],
        )
        Surface = typed.model(self.env, BuilderMenu)
        app = Surface.create_record(
            # `model_name` is declared `str`, but `_template_values` (the
            # only place a template-driven `create_record` reads it) never
            # looks at it -- it dispatches on `template` alone. `False`
            # marks that on purpose, same as `test_menu_surface.py`'s own
            # (unconverted) calls.
            False,  # pyright: ignore[reportArgumentType]
            cast("int", package.id),
            {"name": "Tour Fixture App"},
            template="app",
        )
        users = typed.model(self.env, IrModel)._get("res.users")
        Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", package.id),
            {
                "name": "Tour Fixture Sub",
                "parent_id": app["id"],
                "opens_model": users.id,
            },
            template="submenu",
        )
        action_vals: dict[str, object] = {
            "name": "Tour Contacts",
            "res_model": "res.partner",
            "view_mode": "list,form",
        }
        action = self.env["ir.actions.act_window"].create(action_vals)  # pyright: ignore[reportArgumentType]
        self.start_tour(
            "/odoo/action-%s" % action.id, "app_builder_menu_pane_tour", login="admin"
        )
        menu = cast(
            "IrUiMenu", self.env["ir.ui.menu"].search([("name", "=", "Tour Contacts")])
        )
        self.assertEqual(len(menu), 1)
        self.assertEqual(cast("IrUiMenu", menu.parent_id).id, app["id"])
        self.assertEqual(
            cast("IrActionsActWindow", menu.action).res_model, "res.partner"
        )
        self.assertEqual(cast("BuilderOwnedMixin", menu).builder_package_id, package)
        sub = cast(
            "IrUiMenu",
            self.env["ir.ui.menu"].search([("name", "=", "Tour Fixture Sub")]),
        )
        self.assertLess(menu.sequence, sub.sequence)
        self.assertEqual((menu.sequence, sub.sequence), (10, 20))
        with open(os.path.join(root, "views", "menus.xml"), encoding="utf-8") as handle:
            xml = handle.read()
        self.assertIn("Tour Contacts", xml)
        self.assertNotIn("Tour People", xml)
        self.assertIn("Tour Fixture App", xml)

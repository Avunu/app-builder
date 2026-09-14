# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Menu pane, driven: a submenu made under the package's app, moved
above its sibling, renamed -- and menus.xml afterwards."""

import os
import tempfile

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioHttpCase, join_groups


@tagged("post_install", "-at_install")
class TestMenuPaneTour(StudioHttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        self.addCleanup(self.env["base.automation"]._unregister_hook)

    def test_a_submenu_is_made_moved_and_renamed_from_the_pane(self):
        root = tempfile.mkdtemp(prefix="studio-tour-")
        package = self.env["studio.package"].create(
            {
                "name": "x_tour_menu_pkg",
                "display_name_": "Tour Menus",
                "root_path": root,
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_menu_pkg", "state": "installed"}
        )
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        Surface = self.env["studio.menu"]
        app = Surface.create_record(
            False, package.id, {"name": "Tour Fixture App"}, template="app"
        )
        users = self.env["ir.model"]._get("res.users")
        Surface.create_record(
            False,
            package.id,
            {
                "name": "Tour Fixture Sub",
                "parent_id": app["id"],
                "opens_model": users.id,
            },
            template="submenu",
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )
        self.start_tour(
            "/odoo/action-%s" % action.id, "app_builder_menu_pane_tour", login="admin"
        )
        menu = self.env["ir.ui.menu"].search([("name", "=", "Tour Contacts")])
        self.assertEqual(len(menu), 1)
        self.assertEqual(menu.parent_id.id, app["id"])
        self.assertEqual(menu.action.res_model, "res.partner")
        self.assertEqual(menu.studio_package_id, package)
        sub = self.env["ir.ui.menu"].search([("name", "=", "Tour Fixture Sub")])
        self.assertLess(menu.sequence, sub.sequence)
        self.assertEqual((menu.sequence, sub.sequence), (10, 20))
        with open(os.path.join(root, "views", "menus.xml"), encoding="utf-8") as handle:
            xml = handle.read()
        self.assertIn("Tour Contacts", xml)
        self.assertNotIn("Tour People", xml)
        self.assertIn("Tour Fixture App", xml)

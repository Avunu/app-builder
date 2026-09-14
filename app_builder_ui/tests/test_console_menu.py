# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Studio menu's one entry: the console, on its Home.

The cog item and the systray know what the user is looking at; a menu does
not. The entry opens the console's Home, which chooses the package the
user last had open and offers the way in from there. Pinned here rather
than in ``app_builder_view`` so the checks live beside the other panes.
"""

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestConsoleMenu(StudioCase):
    def setUp(self):
        super().setUp()
        installed = self.env["ir.module.module"].search_count(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not installed:
            self.skipTest("app_builder_view is not installed")

    def _run(self):
        return self.env.ref("app_builder_view.studio_console_action").run()

    def test_the_menu_opens_the_consoles_home(self):
        """No view in hand: Home, full screen, and the console told why."""
        self.make_package()
        action = self._run()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["target"], "fullscreen")
        self.assertEqual(action["params"]["pane"], "home")
        self.assertEqual(action["params"]["opened_from"], "menu")
        # No model is chosen for the user: Home is the place to choose one.
        self.assertNotIn("res_model", action["params"])

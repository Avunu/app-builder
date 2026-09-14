# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Studio menu's Console entry, which has no view in hand.

The cog item and the systray know what the user is looking at; a menu does
not. The entry is a server action so that it can pick a starting point at
click time -- the first model the suggested package owns that has a form --
and fall back to Contacts when there is none. Pinned here rather than in
``app_builder_view`` so the checks live beside the other console tabs.
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

    def test_the_menu_opens_the_console_on_contacts_by_default(self):
        """Nothing owned yet: Contacts, which every database has a form for."""
        self.make_package()
        action = self._run()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["target"], "fullscreen")
        self.assertEqual(action["params"]["model"], "res.partner")
        self.assertEqual(action["params"]["view_type"], "form")
        # The console says why Contacts is on screen when nobody asked for it.
        self.assertEqual(action["params"]["opened_from"], "menu")
        # Also in the context, so the console survives a reload of its URL.
        self.assertEqual(action["context"]["model"], "res.partner")

    def test_the_menu_prefers_a_model_the_package_owns(self):
        """A builder opening the console from the menu is most likely here
        for their own model, so that is where it opens when there is one."""
        package = self.make_package()
        self.build_demo_content(package)
        action = self._run()
        self.assertEqual(action["params"]["model"], "x_studio_project")
        self.assertEqual(action["params"]["view_type"], "form")

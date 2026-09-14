# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The console's tabs, used the way a person does.

The unit tests prove the actions are scoped. They cannot tell you whether the
tab is *there* -- registered into the console's top bar by an addon the
console never imports -- nor whether the breadcrumb brings the user back to a
console that survived the round trip. Those are the two things this drives.
"""

import tempfile

from odoo.tests import HttpCase, tagged

from odoo.addons.app_builder_base.tests.common import join_groups


@tagged("post_install", "-at_install")
class TestConsoleTabsTour(HttpCase):
    def setUp(self):
        super().setUp()
        # The console lives in app_builder_view, which this addon does not
        # depend on: without it the tabs have nowhere to appear and the tour
        # has nothing to drive.
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        # base_automation patches create/write onto the target model class
        # with its own patcher, which the leak detector does not recognise;
        # see TestStudioUi.setUp.
        self.addCleanup(self.env["base.automation"]._unregister_hook)

    def _package(self, name, label):
        # Exactly one writable package, so editing_context can suggest it
        # without the console having to ask which one to record into.
        package = self.env["studio.package"].create(
            {
                "name": name,
                "display_name_": label,
                "root_path": tempfile.mkdtemp(prefix="studio-tour-"),
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create({"name": name, "state": "installed"})
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        return package

    def test_the_automations_pane_lists_the_models_rules_inside_the_console(self):
        """Automations of the model on the canvas, and only those, as a pane
        of the console; the canvas intact when the Views tab is clicked."""
        self._package("x_tour_tabs_pkg", "Tour Tabs")
        partner_model = self.env["ir.model"]._get("res.partner")
        other_model = self.env["ir.model"]._get("res.users")
        self.env["base.automation"].create(
            [
                {
                    "name": "Tour Partner Rule",
                    "model_id": partner_model.id,
                    "trigger": "on_create",
                },
                {
                    "name": "Tour Other Rule",
                    "model_id": other_model.id,
                    "trigger": "on_create",
                },
            ]
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
            "app_builder_console_tabs_tour",
            login="admin",
        )

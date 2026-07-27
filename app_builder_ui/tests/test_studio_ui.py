# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Menus, actions, access rules and automations, captured to source."""

import os

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestStudioUi(StudioCase):
    def setUp(self):
        super().setUp()
        # base_automation._register_hook monkeypatches create/write onto the
        # target model class using its own patcher, which Odoo's leak detector
        # (TransactionCase.check_attrs) does not recognise the way it does
        # mock.patch. Cleanups run LIFO and check_attrs was registered by
        # TransactionCase.setUp, so unregistering here runs first and leaves the
        # model classes clean.
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        self.package = self.make_package(name="x_ui_pkg")
        self.model = self.env["ir.model"].create(
            {
                "name": "UI Demo",
                "model": "x_ui_demo",
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_name",
                            "field_description": "Name",
                            "ttype": "char",
                        },
                    )
                ],
            }
        )
        self.package.studio_capture(
            [self.model, self.model.field_id.filtered(lambda f: f.state == "manual")]
        )

    def _source(self, relative):
        path = os.path.join(self.package.root_path, relative)
        self.assertTrue(os.path.isfile(path), "expected %s" % relative)
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_menu_wizard_writes_action_and_menu(self):
        self.env["studio.menu.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "UI Demo Records",
                "model_id": self.model.id,
            }
        ).action_create()
        views = self._source("views/x_ui_demo_views.xml")
        self.assertIn('model="ir.actions.act_window"', views)
        self.assertIn("x_ui_demo", views)
        # Menus all live in one file so parents precede children; see
        # IrUiMenuSerializer._target_file.
        menus = self._source("views/menus.xml")
        self.assertIn('model="ir.ui.menu"', menus)

    def test_menu_references_its_action_by_ref(self):
        """A reference field must still serialize as a portable xmlid."""
        self.env["studio.menu.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "Reffed",
                "model_id": self.model.id,
            }
        ).action_create()
        source = self._source("views/menus.xml")
        self.assertIn('<field name="action" ref=', source)

    def test_access_wizard_writes_csv(self):
        self.env["studio.access.wizard"].create(
            {
                "package_id": self.package.id,
                "model_id": self.model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_unlink": False,
            }
        ).action_create()
        source = self._source("security/ir.model.access.csv")
        self.assertIn("model_x_ui_demo", source)
        self.assertIn("base.group_user", source)
        self.assertTrue(source.rstrip().endswith(",1,1,1,0"))

    def test_automation_wizard_writes_and_runs(self):
        self.env["studio.automation.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "Shout on create",
                "model_id": self.model.id,
                "trigger": "on_create",
                "code": "for r in records:\n    r['x_name'] = (r.x_name or '').upper()",
            }
        ).action_create()

        source = self._source("data/x_ui_demo_automation.xml")
        self.assertIn('model="ir.actions.server"', source)
        self.assertIn('model="base.automation"', source)

        # And it is a live automation, not just a file.
        record = self.env["x_ui_demo"].create({"x_name": "quiet"})
        self.assertEqual(record.x_name, "QUIET")

    def test_automation_secret_is_not_committed(self):
        """webhook_uuid differs per database and must never reach source."""
        self.env["studio.automation.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "Webhooked",
                "model_id": self.model.id,
                "trigger": "on_create",
                "code": "pass",
            }
        ).action_create()
        source = self._source("data/x_ui_demo_automation.xml")
        self.assertNotIn("webhook_uuid", source)

    def test_rule_is_written_to_security(self):
        rule = self.env["ir.rule"].create(
            {
                "name": "own records only",
                "model_id": self.model.id,
                "domain_force": "[('create_uid', '=', user.id)]",
            }
        )
        self.package.studio_capture(rule)
        source = self._source("security/x_ui_demo_security.xml")
        self.assertIn("create_uid", source)

    def test_everything_round_trips(self):
        """The full UI surface must survive serialize -> wipe -> reload."""
        self.env["studio.menu.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "RT Menu",
                "model_id": self.model.id,
            }
        ).action_create()
        self.env["studio.access.wizard"].create(
            {
                "package_id": self.package.id,
                "model_id": self.model.id,
                "group_id": self.env.ref("base.group_user").id,
            }
        ).action_create()
        self.env["studio.automation.wizard"].create(
            {
                "package_id": self.package.id,
                "name": "RT Automation",
                "model_id": self.model.id,
                "trigger": "on_create",
                "code": "pass",
            }
        ).action_create()

        before = self.package._render_files()
        self.wipe_package_records(self.package)
        self.load_rendered(self.package, before)
        after = self.package._render_files()
        for path in sorted(set(before) | set(after)):
            self.assertEqual(before.get(path), after.get(path), "changed %s" % path)

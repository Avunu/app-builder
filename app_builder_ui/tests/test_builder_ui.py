# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Menus, actions, access rules and automations, captured to source."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

from odoo.tests import tagged

from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.models.builder_security_surfaces import (
    BuilderAccessSurface,
)
from odoo.addons.app_builder_base.tests.common import BuilderCase
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_actions import IrActionsServer
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base_automation.models.base_automation import BaseAutomation

from ..models.builder_automation import BuilderAutomation
from ..models.builder_graduate_code import BuilderGraduateCode
from ..models.builder_menu_surface import BuilderMenu

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime -- the same bargain every other
    # Phase 1c file's own `TYPE_CHECKING` block makes. `IrActionsServer`/
    # `IrModel`/`BaseAutomation`/`BuilderPackageModel`/`BuilderAccessSurface`/
    # `BuilderAutomation`/`BuilderGraduateCode`/`BuilderMenu` are real,
    # top-level imports instead (above): `typed.model()` reads `cls._name`
    # at runtime. `create_record`/`builder_package_id` live on mixins
    # (`builder.record.surface`/`builder.owned.mixin`), registry-composed
    # into the classes above rather than real Python bases of them -- the
    # same gap `typed.py`'s own `security()`/`serializer()` document.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.app_builder_base.models.builder_record_surface import (
        BuilderRecordSurface,
    )
    from odoo.addons.base.models.ir_model import IrModelFields


@tagged("post_install", "-at_install")
class TestBuilderUi(BuilderCase):
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
        model_vals: dict[str, object] = {
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
        self.model = typed.model(self.env, IrModel).create(model_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(
            [
                self.model,
                cast("IrModelFields", self.model.field_id).filtered(
                    lambda f: f.state == "manual"
                ),
            ]
        )

    def _source(self, relative):
        path = os.path.join(cast("str", self.package.root_path), relative)
        self.assertTrue(os.path.isfile(path), "expected %s" % relative)
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    # The surfaces the console's panes call: a menu with its action, an
    # access line, an automation with its step -- each written the moment
    # it exists.

    def _menu(self, name):
        surface = cast("BuilderRecordSurface", typed.model(self.env, BuilderMenu))
        return surface.create_record(
            # `model_name` is declared `str`, but `_template_values` (the
            # only place a template-driven `create_record` reads it) never
            # looks at it -- it dispatches on `template` alone. `False`
            # marks that on purpose, the same as `test_menu_pane_tour.py`'s
            # own already-converted calls.
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": name, "opens_model": self.model.id},
            template="app",
        )

    def _access(self, **values):
        surface = cast(
            "BuilderRecordSurface", typed.model(self.env, BuilderAccessSurface)
        )
        return surface.create_record(
            "x_ui_demo",
            cast("int", self.package.id),
            {"group_id": typed.ref(self.env, "base.group_user").id, **values},
            template="full",
        )

    def _automation(self, name, code):
        surface = cast("BuilderRecordSurface", typed.model(self.env, BuilderAutomation))
        return surface.create_record(
            "x_ui_demo",
            cast("int", self.package.id),
            {"name": name, "trigger": "on_create", "steps.0.code": code},
            template="run_code",
        )

    def test_a_menu_writes_action_and_menu(self):
        self._menu("UI Demo Records")
        views = self._source("views/x_ui_demo_views.xml")
        self.assertIn('model="ir.actions.act_window"', views)
        self.assertIn("x_ui_demo", views)
        # Menus all live in one file so parents precede children; see
        # IrUiMenuSerializer._target_file.
        menus = self._source("views/menus.xml")
        self.assertIn('model="ir.ui.menu"', menus)

    def test_menu_references_its_action_by_ref(self):
        """A reference field must still serialize as a portable xmlid."""
        self._menu("Reffed")
        source = self._source("views/menus.xml")
        self.assertIn('<field name="action" ref=', source)

    def test_an_access_line_writes_csv(self):
        self._access(perm_unlink=False)
        source = self._source("security/ir.model.access.csv")
        self.assertIn("model_x_ui_demo", source)
        self.assertIn("base.group_user", source)
        self.assertTrue(source.rstrip().endswith(",1,1,1,0"))

    def test_an_automation_writes_and_runs(self):
        self._automation(
            "Shout on create",
            "for r in records:\n    r['x_name'] = (r.x_name or '').upper()",
        )
        source = self._source("data/x_ui_demo_automation.xml")
        self.assertIn('model="ir.actions.server"', source)
        self.assertIn('model="base.automation"', source)

        # And it is a live automation, not just a file.
        record_vals: dict[str, object] = {"x_name": "quiet"}
        record = self.env["x_ui_demo"].create(record_vals)  # pyright: ignore[reportArgumentType]
        self.assertEqual(cast("Any", record).x_name, "QUIET")

    def test_automation_secret_is_not_committed(self):
        """webhook_uuid differs per database and must never reach source."""
        self._automation("Webhooked", "pass")
        source = self._source("data/x_ui_demo_automation.xml")
        self.assertNotIn("webhook_uuid", source)

    def test_rule_is_written_to_security(self):
        rule_vals: dict[str, object] = {
            "name": "own records only",
            "model_id": self.model.id,
            "domain_force": "[('create_uid', '=', user.id)]",
        }
        rule = self.env["ir.rule"].create(rule_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(rule)
        source = self._source("security/x_ui_demo_security.xml")
        self.assertIn("create_uid", source)

    def test_everything_round_trips(self):
        """The full UI surface must survive serialize -> wipe -> reload."""
        self._menu("RT Menu")
        self._access()
        self._automation("RT Automation", "pass")

        before = self.package._render_files()
        self.wipe_package_records(self.package)
        self.load_rendered(self.package, before)
        after = self.package._render_files()
        for path in sorted(set(before) | set(after)):
            self.assertEqual(before.get(path), after.get(path), "changed %s" % path)


@tagged("post_install", "-at_install")
class TestAutomationSurface(BuilderCase):
    """The builder's job here is scope, ownership and findability.

    Not a better form: `base.automation`'s own is trigger-aware in a way that
    took years to get right, and a second copy would drift from it on the first
    release and be wrong in ways nobody could see.
    """

    def test_the_action_is_scoped_to_the_model(self):
        self.make_package()
        action = typed.model(self.env, BuilderAutomation).action_open(
            model_name="res.partner"
        )
        model = typed.model(self.env, IrModel)._get("res.partner")
        self.assertIn(("model_id", "=", model.id), action["domain"])
        self.assertEqual(action["context"]["default_model_id"], model.id)

    def test_the_webhook_action_defaults_the_trigger(self):
        self.make_package()
        action = typed.model(self.env, BuilderAutomation).action_open(webhooks=True)
        self.assertIn(("trigger", "=", "on_webhook"), action["domain"])
        self.assertEqual(action["context"]["default_trigger"], "on_webhook")

    def test_one_writable_package_is_not_worth_asking_about(self):
        package = self.make_package()
        action = typed.model(self.env, BuilderAutomation).action_open()
        self.assertEqual(action["context"]["builder_package_id"], package.id)

    def test_a_real_choice_is_not_guessed(self):
        """Two packages and picking one would put the rule in the wrong addon,
        which is only discovered at review time."""
        self.make_package(name="x_builder_one")
        self.make_package(name="x_builder_two")
        action = typed.model(self.env, BuilderAutomation).action_open()
        self.assertFalse(action["context"]["builder_package_id"])

    def test_the_consoles_choice_is_taken_over_a_guess(self):
        """The console has picked a package already; the tab passes it and
        the automation made from the list is written into that one."""
        self.make_package(name="x_builder_one")
        two = self.make_package(name="x_builder_two")
        self.build_demo_content(two)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        action = typed.model(self.env, BuilderAutomation).action_open(
            model_name="x_builder_project",
            webhooks=True,
            package_id=cast("int", two.id),
        )
        self.assertEqual(action["context"]["builder_package_id"], two.id)
        hook_vals: dict[str, object] = {"name": "Console hook", "model_id": model.id}
        automation = (
            typed.model(self.env, BaseAutomation)
            .with_context(**action["context"])
            .create(hook_vals)  # pyright: ignore[reportArgumentType]
        )
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        self.assertEqual(automation.trigger, "on_webhook")
        self.assertEqual(cast("BuilderOwnedMixin", automation).builder_package_id, two)

    def test_a_rule_created_in_context_lands_in_source(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        automation_vals: dict[str, object] = {
            "name": "Captured",
            "model_id": model.id,
            "trigger": "on_create",
        }
        automation = (
            typed.model(self.env, BaseAutomation)
            .with_context(builder_package_id=package.id)
            .create(automation_vals)  # pyright: ignore[reportArgumentType]
        )
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        self.assertEqual(
            cast("BuilderOwnedMixin", automation).builder_package_id, package
        )
        self.assertIn("Captured", "".join(package._render_files().values()))

    def test_nothing_is_captured_without_a_package_in_context(self):
        """Ordinary use of Settings → Technical must be unaffected."""
        package = self.make_package()
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        untouched_vals: dict[str, object] = {
            "name": "Untouched",
            "model_id": model.id,
            "trigger": "on_create",
        }
        automation = typed.model(self.env, BaseAutomation).create(untouched_vals)  # pyright: ignore[reportArgumentType]
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        self.assertFalse(cast("BuilderOwnedMixin", automation).builder_package_id)


@tagged("post_install", "-at_install")
class TestGraduateCode(BuilderCase):
    """`ir.actions.server.code` is a text column evaluated by safe_eval.

    Nothing imports it, so no linter reads it, no test covers it and no reviewer
    sees it in a diff. Odoo Studio's answer is that this is how automations are.
    A builder whose output is source code should be able to hand it over.
    """

    def _action(self, package, model_name="x_builder_project", code="record.write({})"):
        action_vals: dict[str, object] = {
            "name": "Escalate",
            "model_id": typed.model(self.env, IrModel)._get(model_name).id,
            "state": "code",
            "code": code,
        }
        action = (
            typed.model(self.env, IrActionsServer)
            .with_context(builder_package_id=package.id)
            .create(action_vals)  # pyright: ignore[reportArgumentType]
        )
        return action

    def test_the_body_becomes_a_method_and_the_action_calls_it(self):
        package = self.make_package()
        self.build_demo_content(package)
        action = self._action(package, model_name="res.partner")
        result = typed.model(self.env, BuilderGraduateCode).graduate(
            cast("int", action.id), apply=False
        )
        self.assertTrue(result["method"].startswith("_builder_"))
        self.assertEqual(action.code, "(records or record).%s()" % result["method"])
        entry = typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", "res.partner")],
            limit=1,
        )
        source = cast("str", package._read_source(cast("str", entry.python_path)))
        self.assertIn("def %s(self):" % result["method"], source)
        self.assertIn("record.write({})", source)

    def test_a_model_the_package_does_not_own_gets_an_extension(self):
        """Most automations run on sale.order and its neighbours, which is the
        case that needed ModelSpec.extends before this could exist at all."""
        package = self.make_package()
        action = self._action(package, model_name="res.partner")
        typed.model(self.env, BuilderGraduateCode).graduate(
            cast("int", action.id), apply=False
        )
        entry = typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", "res.partner")], limit=1
        )
        self.assertTrue(entry.extends)
        source = cast("str", package._read_source(cast("str", entry.python_path)))
        self.assertIn('_inherit = "res.partner"', source)
        self.assertNotIn("_name =", source)

    def test_graduating_twice_is_refused_rather_than_nested(self):
        package = self.make_package()
        action = self._action(package, model_name="res.partner")
        typed.model(self.env, BuilderGraduateCode).graduate(
            cast("int", action.id), apply=False
        )
        self.assertIn(
            "already calls",
            typed.model(self.env, BuilderGraduateCode).can_graduate(action),
        )

    def test_two_actions_with_one_name_get_two_methods(self):
        package = self.make_package()
        graduate = typed.model(self.env, BuilderGraduateCode).graduate

        def promote():
            action = self._action(package, model_name="res.partner")
            return graduate(cast("int", action.id), apply=False)

        first, second = promote(), promote()
        self.assertNotEqual(first["method"], second["method"])

    def test_extending_a_model_pulls_in_the_module_that_declares_it(self):
        """Otherwise the package installs here and fails on a database without
        that module — design finding 4 all over again."""
        package = self.make_package()
        typed.model(self.env, BuilderGraduateCode).graduate(
            cast("int", self._action(package, model_name="res.partner").id),
            apply=False,
        )
        import ast

        manifest = ast.literal_eval(package._render_files()["__manifest__.py"])
        self.assertIn("base", manifest["depends"])

    def test_the_extension_file_is_imported(self):
        """An unimported class is silently inert, which is the worst failure
        available: everything still loads."""
        package = self.make_package()
        typed.model(self.env, BuilderGraduateCode).graduate(
            cast("int", self._action(package, model_name="res.partner").id),
            apply=False,
        )
        init = cast("str", package._read_source("models/__init__.py"))
        self.assertIn("res_partner", init)

    def test_an_unowned_action_says_why_not(self):
        package = self.make_package()
        self.build_demo_content(package)
        action_vals: dict[str, object] = {
            "name": "Loose",
            "model_id": typed.model(self.env, IrModel)._get("x_builder_project").id,
            "state": "code",
            "code": "pass",
        }
        action = typed.model(self.env, IrActionsServer).create(action_vals)  # pyright: ignore[reportArgumentType]
        self.assertIn(
            "builder package",
            typed.model(self.env, BuilderGraduateCode).can_graduate(action),
        )

    def test_a_non_code_action_has_nothing_to_promote(self):
        package = self.make_package()
        self.build_demo_content(package)
        action = self._action(package)
        action.state = "object_write"
        self.assertIn(
            "Execute Code",
            typed.model(self.env, BuilderGraduateCode).can_graduate(action),
        )

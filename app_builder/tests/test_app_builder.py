# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The umbrella addon: that installing it installs a builder.

``app_builder`` has no code of its own. It is a manifest whose ``depends`` is
the product -- the one name somebody installs to get the engine, the model
builder, the view editor, the UI surfaces and the reports together. Which makes
the manifest the thing that can be wrong: a dependency dropped from it, or an
addon that stops loading under it, and every test in every other addon still
passes because each installs itself.
"""

from __future__ import annotations

from typing import Any, cast

from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged

from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_module import Module

#: What installing "App Builder" has to bring with it.
PARTS = (
    "app_builder_base",
    "app_builder_model",
    "app_builder_view",
    "app_builder_ui",
    "app_builder_report",
)

#: One model from each part that the console calls over RPC. If the addon is
#: installed but its Python did not load, this is what is missing.
SURFACES = {
    "app_builder_base": "builder.package",
    "app_builder_model": "builder.app",
    "app_builder_view": "builder.view.editor",
    "app_builder_ui": "builder.graduate.code",
    "app_builder_report": "builder.report",
}


@tagged("post_install", "-at_install")
class TestAppBuilder(TransactionCase):
    def test_the_manifest_depends_on_every_part(self):
        manifest = get_manifest("app_builder")
        self.assertTrue(manifest["application"])
        self.assertEqual(sorted(manifest["depends"]), sorted(PARTS))

    def test_installing_it_installs_every_part(self):
        names = ["app_builder", *PARTS]
        modules = typed.model(self.env, Module).search([("name", "in", names)])
        self.assertEqual(
            {module.name: module.state for module in modules},
            dict.fromkeys(names, "installed"),
        )

    def test_every_part_loaded_its_models(self):
        for part, model in SURFACES.items():
            self.assertIn(model, self.env, "%s did not load %s" % (part, model))

    def test_the_builder_menu_opens_the_console(self):
        """The one entry the app has: a root menu from the engine, pointed at
        the console by the view editor. Either half missing is an app with
        nothing to click."""
        # `Any`: two records read through `env.ref`, whose own return is the
        # bare `BaseModel` -- the fields read below are `ir.ui.menu`'s and
        # `ir.actions.server`'s, checked by running them rather than by type.
        menu = cast("Any", typed.ref(self.env, "app_builder_base.menu_builder_root"))
        action = cast(
            "Any", typed.ref(self.env, "app_builder_view.builder_console_action")
        )
        self.assertEqual(menu.action, action)
        opened = action.with_context(active_model="builder.view.editor").run()
        self.assertEqual(opened["type"], "ir.actions.client")
        self.assertEqual(opened["tag"], "app_builder_console")

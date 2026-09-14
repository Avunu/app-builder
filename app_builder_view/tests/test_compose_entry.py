# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Where "Compose" goes: the console, on a view the model has."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestComposeEntry(StudioCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_compose_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project"])
        self.package_model = self.package.model_ids.filtered(
            lambda m: m.model == "x_studio_project"
        )

    def _views(self, view_type):
        return self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", view_type)]
        )

    def test_compose_opens_the_console_on_the_models_form(self):
        """A Python model with a form is composed by dropping fields onto
        that form, so Compose lands in the console, full-screen, on the
        Views pane of its package; the console keeps that in its own URL."""
        action = self.package_model.action_compose()
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["target"], "fullscreen")
        self.assertEqual(action["params"]["pane"], "views")
        self.assertEqual(action["params"]["res_model"], "x_studio_project")
        self.assertEqual(action["params"]["view_type"], "form")
        self.assertEqual(action["params"]["package_id"], self.package.id)
        self.assertNotIn("context", action)

    def test_without_a_form_the_console_opens_on_what_the_model_has(self):
        """The class is edited from the View tab whatever the canvas shows,
        so a list will do; only a model with no view at all is refused, with
        a sentence rather than an error about a missing arch."""
        self.env["ir.ui.view"].create(
            {
                "name": "x_studio_project.list.compose",
                "model": "x_studio_project",
                "type": "list",
                "arch": "<list><field name='x_name'/></list>",
            }
        )
        self._views("form").unlink()
        action = self.package_model.action_compose()
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["params"]["view_type"], "list")
        for view_type in ("list", "kanban", "search"):
            self._views(view_type).unlink()
        with self.assertRaises(UserError, msg="no view to open on"):
            self.package_model.action_compose()

    def test_the_engine_alone_says_what_it_is_missing(self):
        """Without the override the engine has no builder to open, and it
        says which addon carries one rather than failing on an unknown tag."""
        Model = self.env.registry["studio.package.model"]
        for cls in Model.__mro__:
            if cls.__module__.endswith("app_builder_base.models.studio_package_model"):
                with self.assertRaises(UserError):
                    cls.action_compose(self.package_model)
                break
        else:
            self.fail("the engine's action_compose was not found on the MRO")

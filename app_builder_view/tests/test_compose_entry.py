# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Where "Compose" goes once there is a console to go to."""

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

    def test_compose_opens_the_console_on_the_models_form(self):
        """A Python model with a form is composed by dropping fields onto
        that form, so Compose lands in the console, full-screen, carrying
        the model both in params and context so a reload finds it again."""
        action = self.package_model.action_compose()
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["target"], "fullscreen")
        self.assertEqual(action["params"]["model"], "x_studio_project")
        self.assertEqual(action["params"]["view_type"], "form")
        self.assertEqual(action["context"]["model"], "x_studio_project")

    def test_the_field_list_is_still_one_click_away(self):
        """The composer is the view of what the class *is*, and it keeps its
        own door."""
        action = self.package_model.action_compose_fields()
        self.assertEqual(action["tag"], "app_builder_composer")
        self.assertTrue(action["params"]["draft_id"])

    def test_a_model_with_no_form_falls_back_to_the_composer(self):
        """Nothing to drop onto means nothing to open the console on."""
        self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")]
        ).unlink()
        action = self.package_model.action_compose()
        self.assertEqual(action["tag"], "app_builder_composer")

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Surfacing the models that still need adopting.

The interesting case is not the package-built model -- that one was always
listed. It is the model somebody made by hand in Settings -> Technical, which
belongs to no package at all: nothing in the product mentioned it, and
``action_adopt`` refuses a model its package does not own, so there was no
path to adopting it whatsoever.
"""

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestAdoptWizard(StudioCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_adopt_pkg")

    def _manual_model(self, model_name, label="Loose"):
        return self.env["ir.model"].create(
            {
                "name": label,
                "model": model_name,
                "field_id": [
                    Command.create(
                        {
                            "name": "x_name",
                            "ttype": "char",
                            "field_description": "Name",
                        }
                    )
                ],
            }
        )

    def _wizard(self, **values):
        return self.env["studio.adopt.wizard"].create(
            {"package_id": self.package.id, **values}
        )

    # -- what shows up ----------------------------------------------------

    def test_a_model_belonging_to_no_package_is_still_offered(self):
        loose = self._manual_model("x_loose_model")
        wizard = self._wizard()
        self.assertIn(
            loose,
            wizard.available_model_ids,
            "a hand-made model had no way to be adopted at all",
        )

    def test_a_model_already_owned_in_python_is_not_offered(self):
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project"])
        wizard = self._wizard()
        self.assertNotIn(
            "x_studio_project",
            wizard.available_model_ids.mapped("model"),
            "adopting twice would regenerate a class over the developer's file",
        )

    def test_the_count_says_how_many_are_not_in_this_package_yet(self):
        self._manual_model("x_loose_one")
        self._manual_model("x_loose_two", label="Loose Two")
        wizard = self._wizard()
        self.assertGreaterEqual(wizard.unowned_count, 2)

    def test_the_preview_shows_the_class_that_would_be_written(self):
        loose = self._manual_model("x_preview_model")
        wizard = self._wizard(model_ids=[Command.set(loose.ids)])
        wizard._onchange_model_ids()
        self.assertIn("class", wizard.preview)
        self.assertIn("x_preview_model", wizard.preview)
        self.assertIn("x_name", wizard.preview)

    # -- adopting ---------------------------------------------------------

    def test_adopting_captures_a_loose_model_into_the_chosen_package(self):
        loose = self._manual_model("x_capture_me")
        wizard = self._wizard(model_ids=[Command.set(loose.ids)])
        wizard.action_adopt()
        self.assertIn("x_capture_me", self.package._owned_model_names())
        entry = self.package.model_ids.filtered(lambda m: m.model == "x_capture_me")
        self.assertEqual(entry.source, "python")

    def test_adopting_a_loose_model_writes_its_class(self):
        loose = self._manual_model("x_written_model")
        wizard = self._wizard(model_ids=[Command.set(loose.ids)])
        wizard.action_adopt()
        entry = self.package.model_ids.filtered(lambda m: m.model == "x_written_model")
        source = self.package._read_source(entry.python_path)
        self.assertIsNotNone(source, "adoption must leave a file behind")
        self.assertIn("x_name", source)

    def test_nothing_selected_is_refused(self):
        wizard = self._wizard()
        with self.assertRaises(UserError):
            wizard.action_adopt()

    def test_a_plain_user_cannot_adopt(self):
        """Adoption writes Python into an addons path, so it is exactly the
        kind of thing an ordinary user must not be able to reach by RPC."""
        loose = self._manual_model("x_guarded_model")
        wizard = self._wizard(model_ids=[Command.set(loose.ids)])
        outsider = self.env["res.users"].create(
            {
                "name": "Nosy",
                "login": "adopt_outsider",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            wizard.with_user(outsider).sudo(False).action_adopt()

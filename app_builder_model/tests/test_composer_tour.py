# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The composer, in a real browser.

OWL compiles its templates in the client, so nothing short of a browser proves
the composer renders at all -- a template typo is invisible to every Python
test in this suite. The tour is about shape rather than styling: open it, stage
a field, see it in the tray, discard it.

The fixture builds a manual model directly rather than through the wizard,
because the wizard reloads the package and that commits.
"""

import shutil
import tempfile

import odoo.tests
from odoo import Command


@odoo.tests.tagged("post_install", "-at_install")
class TestComposerTour(odoo.tests.HttpCase):
    def test_composer_renders_and_stages_a_field(self):
        root = tempfile.mkdtemp(prefix="studio-tour-")
        self.addCleanup(shutil.rmtree, root, True)
        package = self.env["studio.package"].create(
            {
                "name": "x_tour_pkg",
                "display_name_": "Tour Package",
                "root_path": root,
                "auto_commit": "off",
            }
        )
        # Adoption refuses a package Odoo has not installed, and rightly so:
        # it only imports Python for installed modules.
        self.env["ir.module.module"].create(
            {"name": "x_tour_pkg", "state": "installed"}
        )
        model = self.env["ir.model"].create(
            {
                "name": "Tour Model",
                "model": "x_tour_model",
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
        # A real scaffolded app always has one, and without it the model is
        # invisible to everybody -- including the preview.
        access = self.env["ir.model.access"].create(
            {
                "name": "x_tour_model all",
                "model_id": model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
            }
        )
        package.studio_capture(
            [model, model.field_id.filtered(lambda f: f.state == "manual"), access]
        )
        package.action_write_files()
        package.action_adopt(["x_tour_model"])
        package_model = package.model_ids.filtered(lambda m: m.model == "x_tour_model")
        self.assertEqual(package_model.source, "python")

        # The tour opens the composer from the models list, which is the path
        # a user takes -- and exercises the entry point as well as the client.

        self.start_tour(
            "/odoo/action-app_builder_model.studio_package_model_action",
            "app_builder_composer_tour",
            login="admin",
        )

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The model and field builders, and their capture-to-source behaviour."""

import os

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestModelBuilder(StudioCase):
    def test_wizard_builds_a_working_model_and_writes_source(self):
        package = self.make_package(name="x_builder_demo")
        wizard = self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Builder Project",
                "model": "x_builder_project",
            }
        )
        wizard.action_create()

        # The model is live in this transaction, with no upgrade cycle.
        self.assertIn("x_builder_project", self.env)
        record = self.env["x_builder_project"].create({"x_name": "First"})
        self.assertEqual(record.x_name, "First")

        # ...and it exists as source.
        root = package.root_path
        self.assertTrue(
            os.path.isfile(os.path.join(root, "models/x_builder_project.xml"))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(root, "views/x_builder_project_views.xml"))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(root, "security/ir.model.access.csv"))
        )

    def test_wizard_rejects_non_x_prefixed_model(self):
        package = self.make_package(name="x_builder_reject")
        wizard = self.env["studio.model.wizard"].create(
            {"package_id": package.id, "name": "Bad", "model": "bad_model"}
        )
        with self.assertRaises(UserError):
            wizard.action_create()

    def test_onchange_slugifies_the_technical_name(self):
        wizard = self.env["studio.model.wizard"].new({"name": "My Great Thing"})
        wizard._onchange_name()
        self.assertEqual(wizard.model, "x_my_great_thing")

    def test_field_wizard_creates_a_stored_compute(self):
        package = self.make_package(name="x_field_demo")
        self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Field Demo",
                "model": "x_field_demo_model",
                "add_views": False,
                "add_menu": False,
            }
        ).action_create()
        model = self.env["ir.model"]._get("x_field_demo_model")

        self.env["studio.field.wizard"].create(
            {
                "package_id": package.id,
                "model_id": model.id,
                "name": "x_shout",
                "field_description": "Shout",
                "ttype": "char",
                "store": True,
                "compute": (
                    "for r in self:\n    r['x_shout'] = (r.x_name or '').upper()"
                ),
                "depends": "x_name",
            }
        ).action_create()

        record = self.env["x_field_demo_model"].create({"x_name": "quiet"})
        self.assertEqual(
            record.x_shout, "QUIET", "a compute defined as data must actually compute"
        )

    def test_field_wizard_requires_relation_for_relational_types(self):
        package = self.make_package(name="x_rel_demo")
        self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Rel Demo",
                "model": "x_rel_demo_model",
                "add_views": False,
                "add_menu": False,
            }
        ).action_create()
        model = self.env["ir.model"]._get("x_rel_demo_model")
        wizard = self.env["studio.field.wizard"].create(
            {
                "package_id": package.id,
                "model_id": model.id,
                "name": "x_partner_id",
                "field_description": "Partner",
                "ttype": "many2one",
            }
        )
        with self.assertRaises(UserError):
            wizard.action_create()

    def test_package_ownership_is_readable_from_the_record(self):
        package = self.make_package(name="x_owner_demo")
        self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Owner Demo",
                "model": "x_owner_demo_model",
                "add_views": False,
                "add_menu": False,
            }
        ).action_create()
        model = self.env["ir.model"]._get("x_owner_demo_model")
        self.assertEqual(model.studio_package_id, package)

    def test_graduate_wizard_previews_the_source(self):
        package = self.make_package(name="x_grad_wizard")
        self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Grad Demo",
                "model": "x_grad_demo",
                "add_views": False,
                "add_menu": False,
            }
        ).action_create()
        model = self.env["ir.model"]._get("x_grad_demo")
        wizard = self.env["studio.graduate.wizard"].create(
            {"package_id": package.id, "model_ids": [(6, 0, model.ids)]}
        )
        wizard._onchange_model_ids()
        self.assertIn("class XGradDemo", wizard.preview)
        self.assertIn("x_name = fields.Char", wizard.preview)

    def test_graduate_wizard_only_offers_owned_ungraduated_models(self):
        package = self.make_package(name="x_grad_avail")
        self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Avail Demo",
                "model": "x_avail_demo",
                "add_views": False,
                "add_menu": False,
            }
        ).action_create()
        wizard = self.env["studio.graduate.wizard"].create({"package_id": package.id})
        wizard._compute_available_model_ids()
        offered = wizard.available_model_ids.mapped("model")
        self.assertIn("x_avail_demo", offered)
        self.assertNotIn("res.partner", offered, "only models we own are graduable")

        package.action_graduate(["x_avail_demo"])
        wizard._compute_available_model_ids()
        self.assertNotIn(
            "x_avail_demo",
            wizard.available_model_ids.mapped("model"),
            "an already-graduated model must not be offered again",
        )

    def test_base_model_cannot_be_captured(self):
        """Python-declared records belong to the module that declares them."""
        package = self.make_package(name="x_capture_guard")
        partner_model = self.env["ir.model"]._get("res.partner")
        with self.assertRaises(UserError):
            partner_model.studio_package_id = package

    def test_new_field_inherits_its_model_package(self):
        """A field added later must not be left out of the source tree."""
        package = self.make_package(name="x_inherit_pkg")
        self.env["studio.model.wizard"].create(
            {
                "package_id": package.id,
                "name": "Inherit Demo",
                "model": "x_inherit_demo",
                "add_views": False,
                "add_menu": False,
            }
        ).action_create()
        model = self.env["ir.model"]._get("x_inherit_demo")

        field = self.env["ir.model.fields"].create(
            {
                "name": "x_extra",
                "field_description": "Extra",
                "ttype": "char",
                "model_id": model.id,
            }
        )
        self.assertEqual(field.studio_package_id, package)
        with open(
            os.path.join(package.root_path, "models/x_inherit_demo.xml"),
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        self.assertIn("x_extra", source)

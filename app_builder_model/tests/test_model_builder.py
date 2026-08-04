# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The model and field builders, and their capture-to-source behaviour."""

import os

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase
from odoo.addons.app_builder_base.tools import scaffold


@tagged("post_install", "-at_install")
class TestModelBuilder(StudioCase):
    def make_manual_model(self, package, model_name, label="Demo"):
        """A manual model, made directly.

        The wizard builds Python and reloads the package, which commits -- so
        it cannot be used as a fixture inside a TransactionCase. These tests
        are about the *field* builder and about ownership, so a plain manual
        model is the right stand-in.
        """
        model = self.env["ir.model"].create(
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
        package.studio_capture(
            [model, model.field_id.filtered(lambda f: f.state == "manual")]
        )
        return model

    def test_the_wizard_derives_a_clean_technical_name(self):
        """No x_ prefix: a Python-defined model has no such requirement, and
        the name is what users see in filters and domains."""
        package = self.make_package(name="x_naming_demo")
        wizard = self.env["studio.model.wizard"].new(
            {"package_id": package.id, "name": "My Great Thing"}
        )
        wizard._onchange_name()
        self.assertEqual(wizard.model, "naming_demo.my_great_thing")
        self.assertNotIn("x_", wizard.model)

    def test_the_derived_name_follows_the_package(self):
        first = self.make_package(name="x_alpha_pkg")
        second = self.make_package(name="x_beta_pkg")
        wizard = self.env["studio.model.wizard"].new(
            {"package_id": first.id, "name": "Job"}
        )
        wizard._onchange_name()
        self.assertEqual(wizard.model, "alpha_pkg.job")
        wizard.package_id = second
        wizard._onchange_package_id()
        self.assertEqual(wizard.model, "beta_pkg.job")

    def test_the_wizard_refuses_a_read_only_package(self):
        """Production runs read-only from the store; say so rather than
        failing somewhere deeper."""
        package = self.make_package(name="x_ro_demo", root_path="/proc/nonwritable")
        wizard = self.env["studio.model.wizard"].create(
            {"package_id": package.id, "name": "Nope"}
        )
        with self.assertRaises(UserError):
            wizard.action_create()

    def test_scaffold_options_map_from_the_wizard_checkboxes(self):
        """What the dialog offers has to reach the spec, or the checkboxes lie."""
        spec = scaffold.scaffold_spec(
            "demo.job",
            "Demo Job",
            scaffold.ScaffoldOptions(
                chatter=True, activities=True, stage=True, user=True, reference=True
            ),
        )
        names = spec.field_names
        for expected in ("name", "state", "user_id", "reference"):
            self.assertIn(expected, names)
        self.assertEqual(spec.inherit, ("mail.thread", "mail.activity.mixin"))
        self.assertEqual(spec.sequence_field, "reference")

    # The wizard's actual build -- write the class, install, reload, then make
    # the views against the live model -- commits and rebuilds the registry, so
    # it cannot run in a TransactionCase at all. It is covered end to end by
    # app_builder_base/tests/e2e/probe_scaffold.py, which also checks the thing
    # that matters most: that a plain internal user can see the result.

    def test_field_wizard_creates_a_stored_compute(self):
        package = self.make_package(name="x_field_demo")
        model = self.make_manual_model(package, "x_field_demo_model", "Field Demo")

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
        model = self.make_manual_model(package, "x_rel_demo_model", "Rel Demo")
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
        model = self.make_manual_model(package, "x_owner_demo_model", "Owner Demo")
        self.assertEqual(model.studio_package_id, package)

    def test_adopt_wizard_previews_the_source(self):
        package = self.make_package(name="x_grad_wizard")
        model = self.make_manual_model(package, "x_grad_demo", "Grad Demo")
        wizard = self.env["studio.adopt.wizard"].create(
            {"package_id": package.id, "model_ids": [(6, 0, model.ids)]}
        )
        wizard._onchange_model_ids()
        self.assertIn("class XGradDemo", wizard.preview)
        self.assertIn("x_name = fields.Char", wizard.preview)

    def test_adopt_wizard_only_offers_owned_unpython_models(self):
        package = self.make_package(name="x_grad_avail")
        self.make_manual_model(package, "x_avail_demo", "Avail Demo")
        wizard = self.env["studio.adopt.wizard"].create({"package_id": package.id})
        wizard._compute_available_model_ids()
        offered = wizard.available_model_ids.mapped("model")
        self.assertIn("x_avail_demo", offered)
        self.assertNotIn("res.partner", offered, "only models we own can be adopted")

        package.action_adopt(["x_avail_demo"])
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
        model = self.make_manual_model(package, "x_inherit_demo", "Inherit Demo")

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


@tagged("post_install", "-at_install")
class TestRelatedAndComputed(StudioCase):
    """Two things the spec could always express and the composer could not.

    `FieldSpec` has carried `related`, `compute`, `compute_body` and `depends`
    since the beginning, and `pycodegen` renders all four — including promoting
    a compute body to a real method with a real `@api.depends`. The gap was
    entirely in the picker, which is why `app_builder_model/readme` claimed
    coverage the composer did not have.
    """

    def _draft_for_demo(self):
        """A draft over the demo model, or a skip when it is not managed here."""
        package = self.make_package()
        self.build_demo_content(package)
        entry = self.env["studio.package.model"].search(
            [("model", "=", "x_studio_project")], limit=1
        )
        if not entry:
            self.skipTest("the demo model is not package-managed here")
        return self.env["studio.model.draft"].open_for(entry)

    def test_a_related_path_reports_the_type_it_lands_on(self):
        draft = self._draft_for_demo()
        found = draft.resolve_related("x_partner_id.email")
        self.assertTrue(found["ok"])
        self.assertEqual(found["ttype"], "char")

    def test_a_broken_path_names_the_step_that_failed(self):
        draft = self._draft_for_demo()
        found = draft.resolve_related("x_partner_id.nope")
        self.assertFalse(found["ok"])
        self.assertIn("nope", found["reason"])

    def test_following_a_non_relation_is_refused(self):
        draft = self._draft_for_demo()
        found = draft.resolve_related("x_name.anything")
        self.assertFalse(found["ok"])
        self.assertIn("not a relation", found["reason"])

    def test_a_compute_body_gets_its_method_name(self):
        """Derived, not asked for: two answers to "what is this method called"
        is how a graduated field stops being found."""
        values = self.env["studio.model.draft"]._resolve_computed(
            {
                "name": "x_total",
                "ttype": "float",
                "compute_body": "for rec in self:\n    rec.x_total = 1",
                "depends": "x_budget, x_name",
            }
        )
        self.assertEqual(values["compute"], "_compute_x_total")
        self.assertEqual(values["depends"], ("x_budget", "x_name"))

    def test_clearing_the_body_clears_the_compute(self):
        """A spec keeping the method name would declare one the generator has
        nothing to write."""
        values = self.env["studio.model.draft"]._resolve_computed(
            {"name": "x_total", "ttype": "float", "compute_body": "  "}
        )
        self.assertIsNone(values["compute"])
        self.assertEqual(values["depends"], ())

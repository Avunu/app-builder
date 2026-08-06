# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The model and field builders, and their capture-to-source behaviour."""

import os

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase
from odoo.addons.app_builder_base.tools import modelspec, scaffold


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
        package = self.make_package(name="x_ro_demo", root_path=self.unwritable_path())
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


@tagged("post_install", "-at_install")
class TestFeatureViews(StudioCase):
    """A feature that asks for a view has to be able to get one."""

    def test_every_feature_view_has_a_scaffold(self):
        """`Feature.views` is a promise. Nothing else checks it can be kept."""
        missing = sorted(
            {
                view_type
                for feature in scaffold.FEATURES
                for view_type in feature.views
                if view_type not in scaffold.SCAFFOLD_BUILDERS
            }
        )
        self.assertFalse(
            missing, "features ask for views the builder cannot make: %s" % missing
        )

    def test_the_editors_list_and_the_builders_agree(self):
        """These were two lists and they had drifted -- eight against three."""
        editor = set(self.env["studio.view.editor"].VIEW_SCAFFOLDS)
        registry = set(scaffold.SCAFFOLD_BUILDERS) - {"search"}
        self.assertEqual(editor, registry)

    def test_pipeline_stages_asks_for_a_kanban(self):
        options = scaffold.ScaffoldOptions.from_keys(["stage"])
        self.assertIn("kanban", options.view_types)

    def test_date_and_calendar_asks_for_a_calendar(self):
        options = scaffold.ScaffoldOptions.from_keys(["date"])
        self.assertIn("calendar", options.view_types)


@tagged("post_install", "-at_install")
class TestWizardCoversTheRegistry(StudioCase):
    def test_the_wizard_offers_every_feature(self):
        """A feature added to the registry and forgotten here is simply never
        offered, which is the kind of gap nothing complains about."""
        wizard = self.env["studio.model.wizard"]
        missing = [
            key
            for key in scaffold.WIZARD_FEATURES
            if "add_%s" % key not in wizard._fields
        ]
        self.assertFalse(
            missing,
            "the New Model wizard has no checkbox for: %s" % ", ".join(missing),
        )

    def test_the_wizard_offers_nothing_the_registry_lacks(self):
        wizard = self.env["studio.model.wizard"]
        stray = [
            name[len("add_") :]
            for name in wizard._fields
            if name.startswith("add_")
            and name[len("add_") :] not in scaffold.FEATURES_BY_KEY
        ]
        self.assertFalse(stray, "no such feature: %s" % ", ".join(stray))


@tagged("post_install", "-at_install")
class TestCompanionModels(StudioCase):
    """Tags and Lines -- the two documented features that are not a column.

    A tag is a record shared across many parents; a line is a record owned by
    one. Both need a model of their own, which is why they could not be added
    to the registry as another boolean and were the last two missing.
    """

    def _options(self, **flags):
        return scaffold.ScaffoldOptions.from_keys(flags.keys())

    def test_tags_produce_a_tag_model_the_parent_points_at(self):
        specs = scaffold.companion_specs("x_demo_job", "Job", self._options(tags=True))
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].name, "x_demo_job_tag")
        names = {f.name for f in specs[0].fields}
        self.assertEqual(names, {"name", "color"})

        parent = scaffold.scaffold_spec("x_demo_job", "Job", self._options(tags=True))
        tag_field = next(f for f in parent.fields if f.name == "tag_ids")
        self.assertEqual(tag_field.ttype, "many2many")
        self.assertEqual(tag_field.comodel, "x_demo_job_tag")

    def test_a_tag_name_is_unique(self):
        """A tag's label is the whole record, so two with one name are a
        duplicate rather than two things."""
        specs = scaffold.companion_specs("x_demo_job", "Job", self._options(tags=True))
        self.assertTrue(specs[0].sql_constraints)
        self.assertIn("unique(name)", specs[0].sql_constraints[0].definition)

    def test_lines_produce_a_child_model_that_points_back(self):
        specs = scaffold.companion_specs("x_demo_job", "Job", self._options(lines=True))
        self.assertEqual(specs[0].name, "x_demo_job_line")
        back = next(f for f in specs[0].fields if f.ttype == "many2one")
        self.assertEqual(back.comodel, "x_demo_job")
        self.assertEqual(back.ondelete, "cascade", "a line without a parent is orphan")
        self.assertTrue(back.required)

        parent = scaffold.scaffold_spec("x_demo_job", "Job", self._options(lines=True))
        lines = next(f for f in parent.fields if f.name == "line_ids")
        self.assertEqual(lines.ttype, "one2many")
        self.assertEqual(lines.inverse_name, back.name)

    def test_a_one_word_app_gets_a_valid_inverse_name(self):
        """A generated model is named `<package>.<slug>`, so splitting the
        inverse on "_" produced `pkg.job_id` -- a field name with a dot in it.
        Two-word labels hid it, because their slug has an underscore to split
        on, and every test and the e2e probe used one."""
        for model_name in ("alpha_pkg.job", "studio.job", "studio_demo.workshop_job"):
            specs = scaffold.companion_specs(
                model_name, "Job", self._options(lines=True)
            )
            back = next(f for f in specs[0].fields if f.ttype == "many2one")
            self.assertNotIn(".", back.name, "%s produced %s" % (model_name, back.name))
            parent = scaffold.scaffold_spec(
                model_name, "Job", self._options(lines=True)
            )
            lines = next(f for f in parent.fields if f.name == "line_ids")
            self.assertEqual(lines.inverse_name, back.name, "both sides must agree")

    def test_a_one_word_app_with_lines_validates(self):
        spec = scaffold.scaffold_spec("alpha_pkg.job", "Job", self._options(lines=True))
        companion = scaffold.companion_specs(
            "alpha_pkg.job", "Job", self._options(lines=True)
        )[0]
        self.assertFalse(modelspec.validate_spec(companion, taken_model_names=set()))
        self.assertFalse(modelspec.validate_spec(spec, taken_model_names=set()))

    def test_neither_feature_builds_a_companion_when_off(self):
        self.assertEqual(
            scaffold.companion_specs("x_demo_job", "Job", self._options()), []
        )

    # Building one is an e2e probe, not a unit test: create_app installs a
    # module and reloads Python, and `action_apply` commits -- both unreachable
    # from a TransactionCase. See tests/e2e/probe_scaffold.py, which asserts
    # both companions land in the registry, carry an access rule, and are
    # written to source.

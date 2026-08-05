# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approvals, as generated source.

The engine gates a *state transition*, not a button. Odoo Studio asks "which
button?" and base_tier_validation answers "which state change?" — the impedance
mismatch is the whole design constraint, and these tests pin the places where
being wrong about it would produce a rule that silently never fires.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestEnableApprovals(StudioCase):
    def _package(self):
        package = self.make_package()
        self.build_demo_content(package)
        return package

    def test_enabling_writes_the_mixin_and_its_configuration(self):
        package = self._package()
        self.env["studio.approval"].enable(
            package.id,
            "res.partner",
            state_field="type",
            state_from=["contact"],
            state_to=["invoice"],
            apply=False,
        )
        entry = self.env["studio.package.model"].search(
            [("package_id", "=", package.id), ("model", "=", "res.partner")], limit=1
        )
        source = package._read_source(entry.python_path)
        self.assertIn('_inherit = ["res.partner", "tier.validation"]', source)
        self.assertIn('_state_field = "type"', source)
        # Double quotes: `canonical_source` normalises them so that ruff, which
        # formats generated packages, does not rewrite the file and report the
        # package as drifted with nothing changed.
        self.assertIn('_state_to = ["invoice"]', source)
        self.assertIn('_state_from = ["contact"]', source)
        self.assertIn("_tier_validation_manual_config = False", source)

    def test_enabling_also_writes_the_model_picker(self):
        """base returns [] from _get_tier_validation_model_names, so without
        this the mixin works and the rule cannot be created."""
        package = self._package()
        self.env["studio.approval"].enable(
            package.id,
            "res.partner",
            state_field="type",
            state_from=["contact"],
            state_to=["invoice"],
            apply=False,
        )
        entry = self.env["studio.package.model"].search(
            [("package_id", "=", package.id), ("model", "=", "tier.definition")],
            limit=1,
        )
        self.assertTrue(entry, "tier.definition was never extended")
        source = package._read_source(entry.python_path)
        self.assertIn("_get_tier_validation_model_names", source)
        self.assertIn("res.partner", source)

    def test_a_rule_with_no_destination_is_refused(self):
        """The engine gates a transition; without one there is nothing to gate."""
        package = self._package()
        with self.assertRaises(UserError) as caught:
            self.env["studio.approval"].enable(
                package.id, "res.partner", state_field="type", state_to=[], apply=False
            )
        self.assertIn("state change, not a button", str(caught.exception))

    def test_a_model_with_no_such_field_is_refused(self):
        package = self._package()
        with self.assertRaises(UserError) as caught:
            self.env["studio.approval"].enable(
                package.id,
                "res.partner",
                state_field="no_such_field",
                state_to=["x"],
                apply=False,
            )
        self.assertIn("status field", str(caught.exception))

    def test_a_value_the_field_does_not_have_is_refused(self):
        """A rule naming a value that does not exist never fires, which looks
        exactly like approvals being switched off."""
        package = self._package()
        with self.assertRaises(UserError) as caught:
            self.env["studio.approval"].enable(
                package.id,
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["not_a_value"],
                apply=False,
            )
        self.assertIn("not_a_value", str(caught.exception))

    def test_a_transition_to_itself_is_refused(self):
        package = self._package()
        with self.assertRaises(UserError) as caught:
            self.env["studio.approval"].enable(
                package.id,
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["contact"],
                apply=False,
            )
        self.assertIn("both sides", str(caught.exception))

    def test_enabling_twice_is_refused(self):
        package = self._package()
        for _i in range(1):
            self.env["studio.approval"].enable(
                package.id,
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["invoice"],
                apply=False,
            )
        with self.assertRaises(UserError) as caught:
            self.env["studio.approval"].enable(
                package.id,
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["invoice"],
                apply=False,
            )
        self.assertIn("already", str(caught.exception))

    def test_candidate_state_fields_offers_selections_with_values(self):
        self.make_package()
        found = self.env["studio.approval"].candidate_state_fields("res.partner")
        by_name = {entry["name"]: entry for entry in found}
        self.assertIn("type", by_name)
        self.assertTrue(by_name["type"]["values"])


@tagged("post_install", "-at_install")
class TestRuleSerialization(StudioCase):
    def test_a_rule_is_written_to_source(self):
        package = self.make_package()
        self.build_demo_content(package)
        rule = self.env["tier.definition"].create(
            {
                "name": "Two eyes",
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "review_type": "individual",
                "reviewer_id": self.env.ref("base.user_admin").id,
                "sequence": 10,
            }
        )
        package._assign(rule)
        emitted = "".join(package._render_files().values())
        self.assertIn("Two eyes", emitted)
        self.assertIn("tier.definition", emitted)

    def test_the_matching_column_is_not_emitted(self):
        """`model` is a stored related of model_id.model with no inverse: a data
        file cannot set it, and setting model_id fills it."""
        serializer = self.env["studio.serializer.tier.definition"]
        self.assertIn("model", serializer._ignored_fields())
        self.assertNotIn("model", serializer._emitted_fields())

    def test_reviews_are_never_serialized(self):
        """tier.review is one database's in-flight approvals, holding integer
        res_ids and user ids. Nothing in it survives a fresh install."""
        known = self.env["studio.serializer"]._serializable_models()
        self.assertNotIn("tier.review", known)

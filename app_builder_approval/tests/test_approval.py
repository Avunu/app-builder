# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approvals, as generated source.

The engine gates a *state transition*, not a button. Odoo Studio asks "which
button?" and base_tier_validation answers "which state change?" — the impedance
mismatch is the whole design constraint, and these tests pin the places where
being wrong about it would produce a rule that silently never fires.
"""

from __future__ import annotations

from typing import cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.models.builder_serializer import BuilderSerializer
from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModel

from ..models.builder_approval import BuilderApproval


@tagged("post_install", "-at_install")
class TestEnableApprovals(BuilderCase):
    def _package(self):
        package = self.make_package()
        self.build_demo_content(package)
        return package

    def test_enabling_writes_the_mixin_and_its_configuration(self):
        package = self._package()
        typed.model(self.env, BuilderApproval).enable(
            cast("int", package.id),
            "res.partner",
            state_field="type",
            state_from=["contact"],
            state_to=["invoice"],
            apply=False,
        )
        entry = typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", "res.partner")], limit=1
        )
        # `python_path` is compute-only and declared `str | Literal[False]`
        # like any Char (same invariant cast as `builder_package_model.py`'s
        # own real read sites); `_read_source` returns `str | None` but this
        # source was just written above, so it is never `None` here.
        source = cast("str", package._read_source(cast("str", entry.python_path)))
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
        typed.model(self.env, BuilderApproval).enable(
            cast("int", package.id),
            "res.partner",
            state_field="type",
            state_from=["contact"],
            state_to=["invoice"],
            apply=False,
        )
        entry = typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", "tier.definition")],
            limit=1,
        )
        self.assertTrue(entry, "tier.definition was never extended")
        # Same `python_path`/`_read_source` cast as above.
        source = cast("str", package._read_source(cast("str", entry.python_path)))
        self.assertIn("_get_tier_validation_model_names", source)
        self.assertIn("res.partner", source)

    def test_a_rule_with_no_destination_is_refused(self):
        """The engine gates a transition; without one there is nothing to gate."""
        package = self._package()
        with raises(self, UserError) as caught:
            typed.model(self.env, BuilderApproval).enable(
                cast("int", package.id),
                "res.partner",
                state_field="type",
                state_to=[],
                apply=False,
            )
        self.assertIn("state change, not a button", str(caught.exception))

    def test_a_model_with_no_such_field_is_refused(self):
        package = self._package()
        with raises(self, UserError) as caught:
            typed.model(self.env, BuilderApproval).enable(
                cast("int", package.id),
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
        with raises(self, UserError) as caught:
            typed.model(self.env, BuilderApproval).enable(
                cast("int", package.id),
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["not_a_value"],
                apply=False,
            )
        self.assertIn("not_a_value", str(caught.exception))

    def test_a_transition_to_itself_is_refused(self):
        package = self._package()
        with raises(self, UserError) as caught:
            typed.model(self.env, BuilderApproval).enable(
                cast("int", package.id),
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
            typed.model(self.env, BuilderApproval).enable(
                cast("int", package.id),
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["invoice"],
                apply=False,
            )
        with raises(self, UserError) as caught:
            typed.model(self.env, BuilderApproval).enable(
                cast("int", package.id),
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["invoice"],
                apply=False,
            )
        self.assertIn("already", str(caught.exception))

    def test_candidate_state_fields_offers_selections_with_values(self):
        self.make_package()
        found = typed.model(self.env, BuilderApproval).candidate_state_fields(
            "res.partner"
        )
        by_name = {entry["name"]: entry for entry in found}
        self.assertIn("type", by_name)
        self.assertTrue(by_name["type"]["values"])


@tagged("post_install", "-at_install")
class TestRuleSerialization(BuilderCase):
    def test_a_rule_is_written_to_source(self):
        package = self.make_package()
        self.build_demo_content(package)
        vals: dict[str, object] = {
            "name": "Two eyes",
            "model_id": typed.model(self.env, IrModel)._get("res.partner").id,
            "review_type": "individual",
            "reviewer_id": typed.ref(self.env, "base.user_admin").id,
            "sequence": 10,
        }
        rule = self.env["tier.definition"].create(vals)  # pyright: ignore[reportArgumentType]
        package._assign(rule)
        emitted = "".join(package._render_files().values())
        self.assertIn("Two eyes", emitted)
        self.assertIn("tier.definition", emitted)

    def test_the_matching_column_is_not_emitted(self):
        """`model` is a stored related of model_id.model with no inverse: a data
        file cannot set it, and setting model_id fills it."""
        serializer = typed.serializer(self.env["builder.serializer.tier.definition"])
        self.assertIn("model", serializer._ignored_fields())
        self.assertNotIn("model", serializer._emitted_fields())

    def test_reviews_are_never_serialized(self):
        """tier.review is one database's in-flight approvals, holding integer
        res_ids and user ids. Nothing in it survives a fresh install."""
        known = typed.model(self.env, BuilderSerializer)._serializable_models()
        self.assertNotIn("tier.review", known)


@tagged("post_install", "-at_install")
class TestApprovalSurface(BuilderCase):
    """The console's Approvals tab: scope, ownership and findability.

    Not a form of our own -- the engine's form knows which reviewer kinds
    exist and which fields can name one -- so the builder's part is the list
    being the model's and a rule made from it being the package's.
    """

    def test_the_action_is_scoped_to_the_model(self):
        """The domain names the model, on the stored column the engine itself
        matches on, and the picker defaults to it."""
        package = self.make_package()
        action = typed.model(self.env, BuilderApproval).action_open(
            model_name="res.partner"
        )
        model = typed.model(self.env, IrModel)._get("res.partner")
        self.assertEqual(action["res_model"], "tier.definition")
        self.assertIn(("model", "=", "res.partner"), action["domain"])
        self.assertEqual(action["context"]["default_model_id"], model.id)
        self.assertEqual(action["context"]["builder_package_id"], package.id)

    def test_no_model_means_every_rule(self):
        self.make_package()
        action = typed.model(self.env, BuilderApproval).action_open()
        self.assertEqual(action["domain"], [])
        self.assertNotIn("default_model_id", action["context"])

    def test_the_consoles_package_is_the_one_a_rule_lands_in(self):
        """Two writable packages: nothing to guess, but the console has
        chosen already, and a rule made from its tab goes into that one."""
        self.make_package(name="x_builder_one")
        two = self.make_package(name="x_builder_two")
        self.build_demo_content(two)
        self.assertFalse(
            typed.model(self.env, BuilderApproval).action_open()["context"][
                "builder_package_id"
            ]
        )
        action = typed.model(self.env, BuilderApproval).action_open(
            model_name="res.partner", package_id=cast("int", two.id)
        )
        self.assertEqual(action["context"]["builder_package_id"], two.id)
        vals: dict[str, object] = {
            "name": "Console eyes",
            "model_id": action["context"]["default_model_id"],
            "review_type": "individual",
            "reviewer_id": typed.ref(self.env, "base.user_admin").id,
        }
        rule = (
            self.env["tier.definition"].with_context(**action["context"]).create(vals)  # pyright: ignore[reportArgumentType]
        )
        self.assertEqual(rule.get_external_id()[rule.id].split(".")[0], two.name)

    def test_an_unknown_model_is_refused(self):
        self.make_package()
        with raises(self, UserError):
            typed.model(self.env, BuilderApproval).action_open(model_name="x_no_such")

    def test_an_ungated_model_is_told_the_gate_comes_first(self):
        """A rule on a model without the mixin never fires, which looks
        exactly like approvals being switched off; the empty list says so."""
        self.make_package()
        action = typed.model(self.env, BuilderApproval).action_open(
            model_name="res.partner"
        )
        self.assertIn("not switched on", action["help"])

    def test_a_rule_created_in_context_lands_in_source(self):
        """The rule the engine's list creates from the tab's context is
        captured the moment it exists."""
        package = self.make_package()
        self.build_demo_content(package)
        action = typed.model(self.env, BuilderApproval).action_open(
            model_name="res.partner"
        )
        vals: dict[str, object] = {
            "name": "Captured eyes",
            "model_id": action["context"]["default_model_id"],
            "review_type": "individual",
            "reviewer_id": typed.ref(self.env, "base.user_admin").id,
        }
        rule = (
            self.env["tier.definition"].with_context(**action["context"]).create(vals)  # pyright: ignore[reportArgumentType]
        )
        self.assertEqual(rule.get_external_id()[rule.id].split(".")[0], package.name)
        self.assertIn("Captured eyes", "".join(package._render_files().values()))

    def test_nothing_is_captured_without_a_package_in_context(self):
        """The engine's own form under Settings must be unaffected."""
        package = self.make_package()
        self.build_demo_content(package)
        vals: dict[str, object] = {
            "name": "Loose eyes",
            "model_id": typed.model(self.env, IrModel)._get("res.partner").id,
            "review_type": "individual",
            "reviewer_id": typed.ref(self.env, "base.user_admin").id,
        }
        rule = self.env["tier.definition"].create(vals)  # pyright: ignore[reportArgumentType]
        self.assertFalse(rule.get_external_id()[rule.id])

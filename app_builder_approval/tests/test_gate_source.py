# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What the gate writes, and what it refuses to.

The gate is only as good as the transition it names. These pin the choices
that keep it from being advisory -- every way into a gated state is an
origin, creation is guarded -- and the ones that keep it reversible: the
transition can be changed and the gate taken out, and neither costs anybody
a method they wrote beside it. ``test_live_gate`` is where the same source is
loaded and asked to actually stop a write.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from typing import cast

from odoo.exceptions import UserError
from odoo.modules.module import get_manifest
from odoo.tests import tagged

from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import modelspec, pycodegen, pyparse, typed

from ..models.builder_approval import BuilderApproval


class GateCase(BuilderCase):
    """A package, and res.partner's `type` to gate: a stored selection every
    database has, with more than two values -- which is what it takes to
    tell "every other state" from "the one state named"."""

    def setUp(self):
        super().setUp()
        self.package = self.make_package()
        self.approval = typed.model(self.env, BuilderApproval)
        fields_ = self.approval.candidate_state_fields("res.partner")
        self.values = [
            v["value"]
            for v in next(f["values"] for f in fields_ if f["name"] == "type")
        ]
        self.assertGreater(len(self.values), 3, "the fixture needs spare states")

    def enable(self, model_name: str = "res.partner", **kwargs):
        kwargs.setdefault("state_field", "type")
        kwargs.setdefault("state_to", ["invoice"])
        return self.approval.enable(
            cast("int", self.package.id), model_name, apply=False, **kwargs
        )

    def entry(self, model_name: str) -> BuilderPackageModel:
        return typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", self.package.id), ("model", "=", model_name)],
            limit=1,
        )

    def source(self, model_name: str = "res.partner") -> str:
        entry = self.entry(model_name)
        self.assertTrue(entry, "%s was never written" % model_name)
        return cast("str", self.package._read_source(cast("str", entry.python_path)))

    def attrs(self, model_name: str = "res.partner") -> dict[str, object]:
        """The class attributes as Python would read them, not as text."""
        spec = pyparse.parse_model(self.source(model_name))
        return {name: ast.literal_eval(value) for name, value in spec.class_attrs}


@tagged("post_install", "-at_install")
class TestGateCoverage(GateCase):
    def test_every_other_state_is_an_origin_by_default(self):
        """Draft -> Done alone leaves Draft -> In Progress -> Done ungated.
        Naming no origin means all of them, which is what the pane's "from
        any state" has always said and the default of ["draft"] never did."""
        self.enable()
        attrs = self.attrs()
        self.assertEqual(attrs["_state_to"], ["invoice"])
        self.assertEqual(
            attrs["_state_from"], [v for v in self.values if v != "invoice"]
        )

    def test_an_origin_list_that_leaves_a_way_round_is_refused(self):
        with raises(self, UserError) as caught:
            self.enable(state_from=["contact"])
        message = str(caught.exception)
        self.assertIn("no approval at all", message)
        for value in self.values:
            if value not in ("contact", "invoice"):
                self.assertIn(value, message)
        self.assertFalse(self.entry("res.partner"), "a refusal must write nothing")

    def test_a_complete_origin_list_is_accepted_as_given(self):
        origins = [v for v in reversed(self.values) if v != "invoice"]
        self.enable(state_from=origins)
        self.assertEqual(self.attrs()["_state_from"], origins)

    def test_the_creation_guard_is_written_into_the_class(self):
        """tier.validation has no create(); a record born in a gated state
        would never meet the gate. In the package, not in this addon, so it
        still guards where the builder is not installed."""
        self.enable()
        spec = pyparse.parse_model(self.source())
        guard = next(m for m in spec.methods if m.name == "_create")
        self.assertEqual(guard.args, "data_list")
        self.assertIn("super()._create(data_list)", guard.body)
        self.assertIn("_tier_validation_check_state_on_write", guard.body)
        self.assertIn("def _create(self, data_list):", self.source())

    def test_what_is_written_is_what_apply_will_accept(self):
        """Apply compiles every file and reads each class back before it
        touches the disk. The guard is the first generated method with a
        parameter, so this is the check that it survives both."""
        self.enable()
        files = self.package._render_files()
        self.package._assert_sources_compile(files)
        self.package._assert_specs_reparse(files)
        for model_name in ("res.partner", "tier.definition"):
            source = self.source(model_name)
            self.assertEqual(
                pycodegen.render_model(pyparse.parse_model(source)), source
            )

    def test_the_guards_signature_reads_back_and_a_selfless_one_does_not(self):
        """The parser learned parameters for this one method. What it reads
        is what was written, and a function that is not a method at all is
        refused rather than quietly given a `self`."""
        self.enable()
        source = self.source()
        self.assertIn("def _create(self, data_list):", source)
        broken = source.replace(
            "def _create(self, data_list):", "def _create(data_list):"
        )
        with raises(self, pyparse.UnsupportedConstruct):
            pyparse.parse_model(broken)


@tagged("post_install", "-at_install")
class TestCancelState(GateCase):
    def test_no_cancel_state_is_written_as_one_that_cannot_match(self):
        """The engine defaults to "cancel" and tests it with `in` against the
        string, so a model with no cancelled state would drop its approvals
        on entering any state spelled "can". Always explicit, never that."""
        self.enable()
        self.assertEqual(self.attrs()["_cancel_state"], "")
        self.assertIn('_cancel_state = ""', self.source())

    def test_a_chosen_cancel_state_is_written(self):
        self.enable(cancel_state="other")
        self.assertEqual(self.attrs()["_cancel_state"], "other")
        self.assertIn("other", cast("list[str]", self.attrs()["_state_from"]))

    def test_a_cancel_state_the_field_does_not_have_is_refused(self):
        with raises(self, UserError) as caught:
            self.enable(cancel_state="cancelled")
        self.assertIn("cancelled", str(caught.exception))

    def test_a_cancel_state_cannot_be_source_of_its_own(self):
        """The value is written into a class body. One with a quote in it
        used to be interpolated bare; now it is not a value of the field, so
        it never gets that far."""
        with raises(self, UserError):
            self.enable(cancel_state='x"\n    _state_to = []\n    y = "')
        self.assertFalse(self.entry("res.partner"))

    def test_a_cancel_state_cannot_also_need_approving_into(self):
        with raises(self, UserError) as caught:
            self.enable(cancel_state="invoice")
        self.assertIn("cancelled state", str(caught.exception))

    def test_strings_are_escaped_not_interpolated(self):
        """Belt to the validation's braces: a field whose values cannot be
        read is not checked, so the writer itself must not trust them."""
        from ..models.builder_approval import GateConfigJSON

        config: GateConfigJSON = {
            "state_field": "type",
            "state_from": ['a"b'],
            "state_to": ["c\\d"],
            "cancel_state": 'e"f',
        }
        self.approval._write_gated_model(self.package, "res.partner", config)
        attrs = self.attrs()
        self.assertEqual(attrs["_state_from"], ['a"b'])
        self.assertEqual(attrs["_state_to"], ["c\\d"])
        self.assertEqual(attrs["_cancel_state"], 'e"f')
        self.package._assert_sources_compile(self.package._render_files())


@tagged("post_install", "-at_install")
class TestChangeAndDisable(GateCase):
    def test_the_transition_can_be_changed(self):
        self.enable()
        self.approval.reconfigure(
            cast("int", self.package.id),
            "res.partner",
            state_field="type",
            state_to=["delivery"],
            cancel_state="other",
            apply=False,
        )
        attrs = self.attrs()
        self.assertEqual(attrs["_state_to"], ["delivery"])
        self.assertEqual(
            attrs["_state_from"], [v for v in self.values if v != "delivery"]
        )
        self.assertEqual(attrs["_cancel_state"], "other")
        source = self.source()
        self.assertEqual(source.count("tier.validation"), 1)
        self.assertEqual(source.count("def _create("), 1)

    def test_a_change_is_checked_like_an_enable(self):
        self.enable()
        with raises(self, UserError):
            self.approval.reconfigure(
                cast("int", self.package.id),
                "res.partner",
                state_field="type",
                state_from=["contact"],
                state_to=["delivery"],
                apply=False,
            )
        self.assertEqual(self.attrs()["_state_to"], ["invoice"])

    def test_changing_a_model_that_is_not_gated_is_refused(self):
        with raises(self, UserError) as caught:
            self.approval.reconfigure(
                cast("int", self.package.id),
                "res.partner",
                state_field="type",
                state_to=["delivery"],
                apply=False,
            )
        self.assertIn("does not have approvals turned on", str(caught.exception))

    def test_disabling_takes_out_exactly_what_enabling_wrote(self):
        self.enable()
        self.approval.disable(cast("int", self.package.id), "res.partner", apply=False)
        source = self.source()
        spec = pyparse.parse_model(source)
        self.assertEqual(spec.inherit, ())
        self.assertEqual(spec.class_attrs, ())
        self.assertEqual(spec.methods, ())
        self.assertNotIn("tier.validation", source)
        self.assertIn('_inherit = "res.partner"', source)
        picker = self.source("tier.definition")
        self.assertNotIn("_get_tier_validation_model_names", picker)
        self.assertNotIn("res.partner", picker)
        files = self.package._render_files()
        self.package._assert_sources_compile(files)
        self.package._assert_specs_reparse(files)

    def test_disabling_keeps_what_the_class_had_besides(self):
        """A mixin configured by other class attributes, a method graduated
        onto the model: none of it is the gate's to remove."""
        self.enable()
        entry = self.entry("res.partner")
        spec = cast("modelspec.ModelSpec", entry._current_spec())
        self.package._seed_source_for(
            "res.partner",
            replace(
                spec,
                class_attrs=spec.class_attrs + (("_mail_post_access", '"read"'),),
                methods=spec.methods
                + (modelspec.MethodSpec(name="_builder_notify", body="return True"),),
            ),
        )
        self.approval.disable(cast("int", self.package.id), "res.partner", apply=False)
        spec = pyparse.parse_model(self.source())
        self.assertEqual(spec.class_attrs, (("_mail_post_access", '"read"'),))
        self.assertEqual([m.name for m in spec.methods], ["_builder_notify"])

    def test_disabling_a_model_that_is_not_gated_is_refused(self):
        with raises(self, UserError) as caught:
            self.approval.disable(
                cast("int", self.package.id), "res.partner", apply=False
            )
        self.assertIn("nothing here to change", str(caught.exception))

    def test_enabling_again_after_disabling_works(self):
        self.enable()
        self.approval.disable(cast("int", self.package.id), "res.partner", apply=False)
        self.enable(state_to=["delivery"])
        self.assertEqual(self.attrs()["_state_to"], ["delivery"])


@tagged("post_install", "-at_install")
class TestModelPicker(GateCase):
    def _picked(self) -> list[str]:
        spec = pyparse.parse_model(self.source("tier.definition"))
        picker = next(
            m for m in spec.methods if m.name == "_get_tier_validation_model_names"
        )
        call = next(
            node
            for node in ast.walk(ast.parse(picker.body))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "extend"
        )
        return ast.literal_eval(call.args[0])

    def test_other_methods_on_the_extension_survive(self):
        """The picker is one method on a class that may carry others. The
        rewrite used to replace the whole tuple with it."""
        entry = typed.model(self.env, BuilderPackageModel)._adopt(
            self.package, "tier.definition", extends=True
        )
        self.package._seed_source_for(
            "tier.definition",
            modelspec.ModelSpec(
                name="tier.definition",
                description="",
                class_name=pycodegen.class_name_for("tier.definition"),
                extends=True,
                methods=(
                    modelspec.MethodSpec(name="_builder_escalate", body="return 1"),
                ),
            ),
        )
        self.assertTrue(entry._current_spec())
        self.enable()
        spec = pyparse.parse_model(self.source("tier.definition"))
        self.assertEqual(
            sorted(m.name for m in spec.methods),
            ["_builder_escalate", "_get_tier_validation_model_names"],
        )
        self.approval.disable(cast("int", self.package.id), "res.partner", apply=False)
        spec = pyparse.parse_model(self.source("tier.definition"))
        self.assertEqual([m.name for m in spec.methods], ["_builder_escalate"])

    def test_every_gated_model_is_offered_and_only_those(self):
        self.enable()
        self.enable("ir.cron", state_field="interval_type", state_to=["months"])
        self.assertEqual(self._picked(), ["ir.cron", "res.partner"])
        self.approval.disable(cast("int", self.package.id), "res.partner", apply=False)
        self.assertEqual(self._picked(), ["ir.cron"])

    def test_a_tier_definition_file_the_builder_cannot_read_is_left_alone(self):
        """Freeze rather than guess: a class with code in its block the
        parser refuses is somebody's, and replacing it with a blank class
        plus the picker would delete what was not understood."""
        typed.model(self.env, BuilderPackageModel)._adopt(
            self.package, "tier.definition", extends=True
        )
        relative = self.package._seed_source_for(
            "tier.definition",
            modelspec.ModelSpec(
                name="tier.definition",
                description="",
                class_name=pycodegen.class_name_for("tier.definition"),
                extends=True,
            ),
        )
        source = cast("str", self.package._read_source(relative))
        hand_edited = source.replace(
            pycodegen.END_MARKER,
            "    def write(self, vals):\n        return super().write(vals)\n\n"
            + pycodegen.END_MARKER,
        )
        self.assertNotEqual(hand_edited, source)
        self.package._write_files({relative: hand_edited})
        with raises(self, UserError) as caught:
            self.enable()
        self.assertIn("nowhere safe", str(caught.exception))
        self.assertEqual(self.package._read_source(relative), hand_edited)
        self.assertFalse(
            self.entry("res.partner"),
            "the gate was written although its picker could not be",
        )


@tagged("post_install", "-at_install")
class TestOptIn(BuilderCase):
    def test_the_alpha_addon_does_not_install_itself(self):
        """It overrides tier.definition and writes Python into models. A
        database that merely uses OCA tier validation must not get that for
        having installed the builder core."""
        self.assertFalse(get_manifest("app_builder_approval")["auto_install"])

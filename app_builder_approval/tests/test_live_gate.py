# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The gate, live: the generated class is loaded and asked to stop a write.

Every other test of enabling reads the source it produced. That proves what
was written and nothing about whether it works -- and an approval gate that
is written correctly and enforces nothing is the failure that matters, since
it looks exactly like one that does.

The obstacle is that Apply commits and reloads the module, and
``_button_immediate_function`` raises under test mode. So the reload is done
by hand here, and only the reload: the model is the builder's own scaffold
(status field, reference sequence), the gate is written by ``enable()``
exactly as the pane calls it, and the files it wrote are executed and built
into this transaction's registry the way OCA's own tier-validation tests
load their fake models. What is asserted on is then real ``create()`` and
``write()`` calls by a user who is not the reviewer.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from odoo_test_helper import FakeModelLoader

from odoo.exceptions import ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import modelspec, scaffold, typed
from odoo.addons.base.models.ir_model import IrModel

from ..models.builder_approval import BuilderApproval
from ..models.builder_approval_surface import BuilderApproval as ApprovalSurface

MODEL = "gate.probe.job"


@tagged("post_install", "-at_install")
class TestLiveGate(BuilderCase):
    def setUp(self):
        super().setUp()
        self.loader = FakeModelLoader(self.env, self.__module__)
        self.loader.backup_registry()
        self.addCleanup(self.loader.restore_registry)

        self.package = self.make_package()
        self.approval = typed.model(self.env, BuilderApproval)

        # The model Build-an-app makes: a draft / in progress / done status
        # with a clickable statusbar, and a reference filled by a sequence in
        # `create()` -- the one other thing the builder generates there, so
        # the guard is proven to coexist with it.
        spec = scaffold.scaffold_spec(
            MODEL,
            "Gate Probe Job",
            scaffold.ScaffoldOptions.from_keys(["stage", "reference"]),
        )
        typed.model(self.env, BuilderPackageModel)._adopt(self.package, MODEL)
        self.package._seed_source_for(MODEL, spec)
        self.reload(MODEL)
        sequence: dict[str, object] = {"name": "Gate Probe", "code": MODEL}
        self.env["ir.sequence"].create(sequence)  # pyright: ignore[reportArgumentType]

        self.staff = new_test_user(
            self.env, login="gate_probe_staff", groups="base.group_user"
        )
        self.reviewer = new_test_user(
            self.env, login="gate_probe_reviewer", groups="base.group_user"
        )

    # -- the reload Apply would do ------------------------------------------

    def reload(self, *model_names: str) -> None:
        """Execute what the package has on disk and build it into the registry."""
        classes: list[Any] = []
        for model_name in model_names:
            entry = typed.model(self.env, BuilderPackageModel).search(
                [("package_id", "=", self.package.id), ("model", "=", model_name)],
                limit=1,
            )
            relative = cast("str", entry.python_path)
            source = cast("str", self.package._read_source(relative))
            spec = entry._current_spec()
            self.assertTrue(spec, "%s did not read back" % relative)
            # `MetaModel` reads the addon a class belongs to off its
            # `__module__`, as it would for a file imported from the package.
            namespace: dict[str, Any] = {
                "__name__": "odoo.addons.%s.models.%s"
                % (self.package.name, relative.rsplit("/", 1)[-1][:-3])
            }
            exec(compile(source, relative, "exec"), namespace)  # pylint: disable=exec-used
            classes.append(namespace[cast("Any", spec).class_name])
        self.loader.update_registry(tuple(classes))
        self.env.invalidate_all()

    def gate(self, **kwargs: Any) -> None:
        kwargs.setdefault("state_to", ["done"])
        self.approval.enable(cast("int", self.package.id), MODEL, apply=False, **kwargs)
        self.reload(MODEL, "tier.definition")
        access: dict[str, object] = {
            "name": "gate probe",
            "model_id": typed.model(self.env, IrModel)._get(MODEL).id,
            "group_id": typed.ref(self.env, "base.group_user").id,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        }
        self.env["ir.model.access"].create(access)  # pyright: ignore[reportArgumentType]

    def rule(self, **overrides: object):
        vals: dict[str, object] = {
            "name": "Reviewer signs off",
            "model_id": typed.model(self.env, IrModel)._get(MODEL).id,
            "review_type": "individual",
            "reviewer_id": self.reviewer.id,
        }
        vals.update(overrides)
        return self.env["tier.definition"].create(vals)  # pyright: ignore[reportArgumentType]

    def jobs(self, user=None) -> Any:
        """The gated model as somebody who is not the administrator.

        `Any`: the model exists only in this test's registry, so there is no
        class to name -- the dynamically-named-model rule, as everywhere.
        """
        return self.env[MODEL].with_user(user or self.staff)

    # -- the tests -------------------------------------------------------------

    def test_the_loaded_class_is_the_gated_one(self):
        self.gate()
        model = self.jobs()
        self.assertIn("tier.validation", model._inherit_module)
        self.assertEqual(model._state_to, ["done"])
        self.assertEqual(model._state_from, ["draft", "in_progress"])
        self.assertEqual(model._cancel_state, "")
        self.assertEqual(
            self.approval.gate_config(MODEL),
            {
                "state_field": "state",
                "state_from": ["draft", "in_progress"],
                "state_to": ["done"],
                "cancel_state": "",
            },
        )
        # The pane is told the same thing, and offered the fields a change
        # of transition would pick from.
        gate = typed.model(self.env, ApprovalSurface).catalogue(MODEL)["gate"]
        self.assertTrue(gate["on"])
        self.assertEqual(gate["current"], self.approval.gate_config(MODEL))
        self.assertIn("state", [f["name"] for f in gate["state_fields"]])

    def test_the_model_can_be_picked_in_a_rule(self):
        self.gate()
        self.assertIn(
            MODEL,
            cast("Any", self.env["tier.definition"])._get_tier_validation_model_names(),
        )
        self.assertTrue(self.rule())

    def test_with_no_rule_nothing_is_asked(self):
        """The mixin alone gates nothing: rules are what ask."""
        self.gate()
        job = self.jobs().create({"name": "Free"})
        job.write({"state": "done"})
        self.assertEqual(job.state, "done")
        self.assertTrue(self.jobs().create({"name": "Born done", "state": "done"}))

    def test_the_gated_write_is_refused(self):
        self.gate()
        self.rule()
        job = self.jobs().create({"name": "Needs sign-off"})
        self.assertEqual(job.state, "draft")
        with raises(self, ValidationError):
            job.write({"state": "done"})
        self.assertEqual(job.state, "draft")

    def test_stepping_through_another_state_does_not_get_round_it(self):
        """The bypass the default of ["draft"] left open, from the statusbar
        itself: In Progress is not a gated state, so getting there is free --
        and Done from there used to be free too."""
        self.gate()
        self.rule()
        job = self.jobs().create({"name": "Two clicks"})
        job.write({"state": "in_progress"})
        self.assertEqual(job.state, "in_progress")
        with raises(self, ValidationError):
            job.write({"state": "done"})
        self.assertEqual(job.state, "in_progress")

    def test_a_stage_added_after_enabling_is_gated_too(self):
        """Stages stay editable after the gate is on. A list of origins
        frozen at enable time left a new one out, and Draft -> Review ->
        Done was then the bypass all over again."""
        self.gate()
        self.rule()
        entry = typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", self.package.id), ("model", "=", MODEL)], limit=1
        )
        spec = cast("modelspec.ModelSpec", entry._current_spec())
        state = cast("modelspec.FieldSpec", spec.field("state"))
        review = modelspec.SelectionSpec("review", "Review")
        self.package._seed_source_for(
            MODEL,
            modelspec.with_field(
                spec,
                replace(
                    state,
                    selection=state.selection[:1] + (review,) + state.selection[1:],
                ),
            ),
        )
        self.reload(MODEL)
        self.assertIn("review", self.jobs()._state_from)
        job = self.jobs().create({"name": "Side door"})
        job.write({"state": "review"})
        self.assertEqual(job.state, "review")
        with raises(self, ValidationError):
            job.write({"state": "done"})
        self.assertEqual(job.state, "review")

    def test_duplicating_a_record_in_a_gated_state(self):
        """Duplicate goes through `create()`. A field called `state` is not
        copied unless it says so (Odoo's own default), so the builder's
        status starts the duplicate over at Draft and nothing is asked. A
        duplicate that does land in a gated state -- a status field that is
        copied, or a default that says so -- is a record born there, and is
        asked about like any other."""
        self.gate()
        job = self.jobs().create({"name": "Original", "state": "done"})
        self.rule()
        self.assertFalse(self.env[MODEL]._fields["state"].copy)
        fresh = job.copy()
        self.assertEqual(fresh.state, "draft")
        self.assertFalse(fresh.sudo().review_ids)
        with raises(self, ValidationError):
            job.copy({"state": "done"})
        copied = job.with_user(self.reviewer).copy({"state": "done"})
        self.assertEqual(copied.state, "done")
        self.assertEqual(copied.sudo().review_ids.mapped("status"), ["approved"])

    def test_module_data_is_loaded_as_shipped(self):
        """A package's own records, loaded by the superuser as it installs,
        are not asked about: a rule loaded first must not make the package
        uninstallable. A person's import also runs in install mode, but not
        as the superuser, so it still is."""
        self.gate()
        self.rule()
        loaded: Any = (
            cast("Any", self.env[MODEL])
            .sudo()
            .with_context(install_mode=True)
            .create({"name": "Shipped", "state": "done"})
        )
        self.assertEqual(loaded.state, "done")
        self.assertFalse(loaded.review_ids)
        with raises(self, ValidationError):
            self.jobs().with_context(install_mode=True).create(
                {"name": "Imported", "state": "done"}
            )

    def test_creating_past_the_gate_is_refused(self):
        """tier.validation gates write() only. The generated `_create` is
        what stops `create({"state": "done"})`."""
        self.gate()
        self.rule()
        with raises(self, ValidationError):
            self.jobs().create({"name": "Born done", "state": "done"})
        self.assertFalse(self.env[MODEL].search([("name", "=", "Born done")]))
        with raises(self, ValidationError):
            self.jobs().create(
                [{"name": "Fine"}, {"name": "Born done too", "state": "done"}]
            )

    def test_creating_before_the_gate_is_untouched(self):
        self.gate()
        self.rule()
        jobs = self.jobs().create(
            [{"name": "One"}, {"name": "Two", "state": "in_progress"}]
        )
        self.assertEqual(jobs.mapped("state"), ["draft", "in_progress"])
        self.assertFalse(jobs.review_ids)
        # The sequence's own create() override still ran beneath the guard.
        self.assertTrue(all(ref and ref != "New" for ref in jobs.mapped("reference")))

    def test_an_approved_record_goes_through(self):
        self.gate()
        self.rule()
        job = self.jobs().create({"name": "By the book"})
        job.request_validation()
        self.assertTrue(job.review_ids)
        with raises(self, ValidationError):
            job.write({"state": "done"})
        job.with_user(self.reviewer).validate_tier()
        job.invalidate_recordset()
        job.write({"state": "done"})
        self.assertEqual(job.state, "done")

    def test_a_reviewer_creating_past_the_gate_approves_in_passing(self):
        """The same thing the engine does on a write: whoever may approve is
        not made to ask themselves, and the review is still recorded."""
        self.gate()
        self.rule()
        job = self.jobs(self.reviewer).create({"name": "Signed", "state": "done"})
        self.assertEqual(job.state, "done")
        self.assertEqual(job.sudo().review_ids.mapped("status"), ["approved"])

    def test_a_rule_that_does_not_match_does_not_block_creation(self):
        self.gate()
        self.rule(definition_domain="[('name', '=', 'Big one')]")
        self.assertTrue(self.jobs().create({"name": "Small", "state": "done"}))
        with raises(self, ValidationError):
            self.jobs().create({"name": "Big one", "state": "done"})

    def test_going_back_asks_again(self):
        """Done -> Draft -> Done must not ride on the first approval."""
        self.gate()
        self.rule()
        job = self.jobs().create({"name": "Round trip"})
        job.request_validation()
        job.with_user(self.reviewer).validate_tier()
        job.invalidate_recordset()
        job.write({"state": "done"})
        job.write({"state": "draft"})
        job.invalidate_recordset()
        self.assertFalse(job.review_ids)
        with raises(self, ValidationError):
            job.write({"state": "done"})

    def test_disabling_lifts_the_gate_from_the_source(self):
        """Not reloadable in place here -- a mixin cannot be taken back out
        of a registry class by building on top of it -- so what is checked
        is that the source Apply would load no longer carries the gate."""
        self.gate()
        self.approval.disable(cast("int", self.package.id), MODEL, apply=False)
        entry = typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", self.package.id), ("model", "=", MODEL)], limit=1
        )
        spec = cast("Any", entry._current_spec())
        self.assertNotIn("tier.validation", spec.inherit)
        self.assertFalse(spec.methods)
        self.assertEqual(spec.sequence_field, "reference")
        self.assertEqual(
            spec, scaffold.scaffold_spec(MODEL, "Gate Probe Job", self._options())
        )

    def _options(self):
        return scaffold.ScaffoldOptions.from_keys(["stage", "reference"])

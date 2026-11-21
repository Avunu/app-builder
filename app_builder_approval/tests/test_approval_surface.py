# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approval rules as a record pane: the gate reported, a rule from a
template with its reviewer, its sentence, and the file it lands in."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base_tier_validation.models.tier_definition import TierDefinition

from ..models.builder_approval import BuilderApproval as BuilderApprovalBase
from ..models.builder_approval_surface import BuilderApproval

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs it at runtime. `BuilderRecordSurface` is `builder.
    # approval`'s sibling mixin (`_inherit = ["builder.record.surface",
    # "builder.approval"]`, registry-level, never a real Python base class of
    # the imported `BuilderApproval` above) -- the identical gap `typed.py`'s
    # own `security()`/`serializer()` document, cast at each real call site
    # the same way `builder_approval_surface.py` itself casts `super()` to
    # this same class.
    from odoo.addons.app_builder_base.models.builder_record_surface import (
        BuilderRecordSurface,
        RecordCheckDomainJSON,
    )


@tagged("post_install", "-at_install")
class TestApprovalSurface(BuilderCase):
    def setUp(self):
        super().setUp()
        self.Surface = typed.model(self.env, BuilderApproval)
        self.package = self.make_package()
        self.build_demo_content(self.package)

    def test_the_catalogue_reports_the_gate(self):
        """res.partner carries no mixin: the gate is off and the status
        fields it could hang on are listed; a gated model says so."""
        catalogue = self.Surface.catalogue("res.partner")
        gate = catalogue["gate"]
        self.assertFalse(gate["on"])
        self.assertIn("res.partner", gate["title"])
        self.assertEqual(gate["call"], "enable_gate")
        self.assertIsInstance(gate["state_fields"], list)
        # Nothing is enforced yet, so there is no transition to report; the
        # ways to change and remove one are named for when there is.
        self.assertIsNone(gate["current"])
        self.assertEqual(gate["update_call"], "update_gate")
        self.assertEqual(gate["disable_call"], "disable_gate")
        # The pane's hint is the one place a user is told what the gate
        # covers before they switch it on.
        self.assertIn("every way into", gate["consequence"])
        # Nobody's gate, so nobody's to change.
        self.assertEqual(gate["module"], "")
        # Turning it off is explained before it is offered: the rules stay,
        # and the one stored column the gate added is kept, renamed.
        self.assertIn("rules stay", gate["off_consequence"])
        self.assertIn("renamed column", gate["off_consequence"])
        gated = next(
            (
                name
                for name, model in self.env.registry.items()
                if "tier.validation" in getattr(model, "_inherit_module", {})
            ),
            None,
        )
        if gated:
            self.assertTrue(self.Surface.catalogue(gated)["gate"]["on"])
            # What is enforced is reported, so it can be changed.
            self.assertTrue(self.Surface.catalogue(gated)["gate"]["current"])
            # And by whom: only that module's package can change it.
            self.assertEqual(
                self.Surface.catalogue(gated)["gate"]["module"],
                self.env[gated]._inherit_module["tier.validation"],  # pyright: ignore[reportAttributeAccessIssue]
            )

    def test_a_template_makes_a_rule_with_its_reviewer_in_the_file(self):
        row = cast("BuilderRecordSurface", self.Surface).create_record(
            "res.partner",
            cast("int", self.package.id),
            {
                "name": "Manager signs",
                "reviewer_id": typed.ref(self.env, "base.user_admin").id,
            },
            template="approve_by_user",
        )
        rule = typed.model(self.env, TierDefinition).browse(row["id"])
        self.assertEqual(rule.review_type, "individual")
        self.assertEqual(rule.reviewer_id, self.env.ref("base.user_admin"))
        self.assertEqual(rule.definition_type, "domain")
        self.assertEqual(
            rule.get_external_id()[rule.id].split(".")[0], self.package.name
        )
        self.assertIn("approves", row["sentence"])
        rendered = self.package._render_files()["security/res_partner_approval.xml"]
        self.assertIn("Manager signs", rendered)
        self.assertIn("base.user_admin", rendered)

    def test_a_reviewer_only_this_database_has_is_refused(self):
        """A user with no xmlid cannot be pointed at from a file."""
        user = self.make_user("reviewer", ["base.group_user"])
        with raises(self, UserError):
            cast("BuilderRecordSurface", self.Surface).create_record(
                "res.partner",
                cast("int", self.package.id),
                {"name": "Nobody can find them", "reviewer_id": user.id},
                template="approve_by_user",
            )

    def test_describe_says_what_the_condition_matches(self):
        row = cast("BuilderRecordSurface", self.Surface).create_record(
            "res.partner",
            cast("int", self.package.id),
            {
                "name": "Companies only",
                "reviewer_group_id": typed.ref(self.env, "base.group_system").id,
                "definition_domain": "[('is_company', '=', True)]",
            },
            template="approve_by_group",
        )
        described = cast("BuilderRecordSurface", self.Surface).describe(
            row["id"], cast("int", self.package.id)
        )
        matches = cast("RecordCheckDomainJSON", described["matches"])
        self.assertTrue(matches["valid"])
        self.assertIn("count", matches)
        values = cast("dict[str, object]", described["values"])
        self.assertEqual(values["review_type"], "group")
        notes = cast("list[str]", described["notes"])
        self.assertTrue(any("approval.xml" in n for n in notes))
        with raises(self, UserError):
            cast("BuilderRecordSurface", self.Surface).write_record(
                row["id"],
                {"definition_domain": "[('nope', '=', 1)]"},
                cast("int", self.package.id),
            )

    def test_rows_are_the_models_rules_only(self):
        mine = cast("BuilderRecordSurface", self.Surface).create_record(
            "res.partner",
            cast("int", self.package.id),
            {
                "name": "Partners",
                "reviewer_id": typed.ref(self.env, "base.user_admin").id,
            },
            template="approve_by_user",
        )
        cast("BuilderRecordSurface", self.Surface).create_record(
            "res.users",
            cast("int", self.package.id),
            {
                "name": "Users",
                "reviewer_id": typed.ref(self.env, "base.user_admin").id,
            },
            template="approve_by_user",
        )
        rows = cast("BuilderRecordSurface", self.Surface).rows(
            "res.partner", cast("int", self.package.id)
        )
        self.assertEqual([r["id"] for r in rows], [mine["id"]])
        cast("BuilderRecordSurface", self.Surface).remove_record(
            mine["id"], cast("int", self.package.id), force=True
        )
        self.assertNotIn("Partners", "".join(self.package._render_files().values()))


@tagged("post_install", "-at_install")
class TestDisableOnlyDropsTheGate(BuilderCase):
    """What the pane says about turning approvals off (``off_consequence``)
    against what Apply is actually told (``_drops_only_the_gate``): the
    gate's own column is confirmed, and any other pending removal in the
    package makes the whole disable a refusal rather than a partial one."""

    MODEL = "x_builder_project"

    def setUp(self):
        super().setUp()
        self.Approval = typed.model(self.env, BuilderApprovalBase)
        self.package = self.make_package()
        self.build_demo_content(self.package)

    def _decides(self, dropped: dict[str, tuple[str, ...]]) -> bool:
        package_class = type(self.package)
        with (
            patch.object(package_class, "_render_files", return_value={}),
            patch.object(package_class, "_destructive_changes", return_value=dropped),
        ):
            return self.Approval._drops_only_the_gate(self.package, self.MODEL, {})

    def test_only_the_gates_own_column_is_confirmed(self):
        self.assertTrue(self._decides({self.MODEL: ("validation_status",)}))

    def test_another_pending_removal_refuses_the_disable(self):
        # A removal on another model of the package.
        self.assertFalse(
            self._decides({self.MODEL: ("validation_status",), "x_other": ("x_note",)})
        )
        # A removal on the gated model itself that is not the gate's.
        self.assertFalse(self._decides({self.MODEL: ("validation_status", "x_note")}))
        # Nothing dropped: nothing to confirm, so nothing is.
        self.assertFalse(self._decides({}))

    def test_apply_is_not_told_to_drop_anything_else(self):
        """The refusal itself: ``allow_destructive`` stays False, so Apply's
        own guard refuses the disable, as the dialog says it will."""
        package_class = type(self.package)
        with (
            patch.object(
                package_class,
                "_destructive_changes",
                return_value={
                    self.MODEL: ("validation_status",),
                    "x_other": ("x_note",),
                },
            ),
            patch.object(package_class, "action_apply") as apply,
        ):
            self.Approval._commit_sources(
                self.package, {}, apply=True, reason="test", ungating=self.MODEL
            )
        self.assertFalse(apply.call_args.kwargs["allow_destructive"])
        gate = typed.model(self.env, BuilderApproval).catalogue("res.partner")["gate"]
        self.assertIn(
            "is refused until that removal has been applied", gate["off_consequence"]
        )

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approval rules as a record pane: the gate reported, a rule from a
template with its reviewer, its sentence, and the file it lands in."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.base_tier_validation.models.tier_definition import TierDefinition
from odoo.addons.app_builder_base.tests.common import StudioCase, raises
from odoo.addons.app_builder_base.tools import typed

from ..models.studio_approval_surface import StudioApproval

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs it at runtime. `StudioRecordSurface` is `studio.
    # approval`'s sibling mixin (`_inherit = ["studio.record.surface",
    # "studio.approval"]`, registry-level, never a real Python base class of
    # the imported `StudioApproval` above) -- the identical gap `typed.py`'s
    # own `security()`/`serializer()` document, cast at each real call site
    # the same way `studio_approval_surface.py` itself casts `super()` to
    # this same class.
    from odoo.addons.app_builder_base.models.studio_record_surface import (
        RecordCheckDomainJSON,
        StudioRecordSurface,
    )


@tagged("post_install", "-at_install")
class TestApprovalSurface(StudioCase):
    def setUp(self):
        super().setUp()
        self.Surface = typed.model(self.env, StudioApproval)
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
            self.assertEqual(self.Surface.catalogue(gated)["gate"]["state_fields"], [])

    def test_a_template_makes_a_rule_with_its_reviewer_in_the_file(self):
        row = cast("StudioRecordSurface", self.Surface).create_record(
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
            cast("StudioRecordSurface", self.Surface).create_record(
                "res.partner",
                cast("int", self.package.id),
                {"name": "Nobody can find them", "reviewer_id": user.id},
                template="approve_by_user",
            )

    def test_describe_says_what_the_condition_matches(self):
        row = cast("StudioRecordSurface", self.Surface).create_record(
            "res.partner",
            cast("int", self.package.id),
            {
                "name": "Companies only",
                "reviewer_group_id": typed.ref(self.env, "base.group_system").id,
                "definition_domain": "[('is_company', '=', True)]",
            },
            template="approve_by_group",
        )
        described = cast("StudioRecordSurface", self.Surface).describe(
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
            cast("StudioRecordSurface", self.Surface).write_record(
                row["id"],
                {"definition_domain": "[('nope', '=', 1)]"},
                cast("int", self.package.id),
            )

    def test_rows_are_the_models_rules_only(self):
        mine = cast("StudioRecordSurface", self.Surface).create_record(
            "res.partner",
            cast("int", self.package.id),
            {
                "name": "Partners",
                "reviewer_id": typed.ref(self.env, "base.user_admin").id,
            },
            template="approve_by_user",
        )
        cast("StudioRecordSurface", self.Surface).create_record(
            "res.users",
            cast("int", self.package.id),
            {
                "name": "Users",
                "reviewer_id": typed.ref(self.env, "base.user_admin").id,
            },
            template="approve_by_user",
        )
        rows = cast("StudioRecordSurface", self.Surface).rows(
            "res.partner", cast("int", self.package.id)
        )
        self.assertEqual([r["id"] for r in rows], [mine["id"]])
        cast("StudioRecordSurface", self.Surface).remove_record(
            mine["id"], cast("int", self.package.id), force=True
        )
        self.assertNotIn("Partners", "".join(self.package._render_files().values()))

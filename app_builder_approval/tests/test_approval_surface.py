# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approval rules as a record pane: the gate reported, a rule from a
template with its reviewer, its sentence, and the file it lands in."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestApprovalSurface(StudioCase):
    def setUp(self):
        super().setUp()
        self.Surface = self.env["studio.approval"]
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
        row = self.Surface.create_record(
            "res.partner",
            self.package.id,
            {
                "name": "Manager signs",
                "reviewer_id": self.env.ref("base.user_admin").id,
            },
            template="approve_by_user",
        )
        rule = self.env["tier.definition"].browse(row["id"])
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
        with self.assertRaises(UserError):
            self.Surface.create_record(
                "res.partner",
                self.package.id,
                {"name": "Nobody can find them", "reviewer_id": user.id},
                template="approve_by_user",
            )

    def test_describe_says_what_the_condition_matches(self):
        row = self.Surface.create_record(
            "res.partner",
            self.package.id,
            {
                "name": "Companies only",
                "reviewer_group_id": self.env.ref("base.group_system").id,
                "definition_domain": "[('is_company', '=', True)]",
            },
            template="approve_by_group",
        )
        described = self.Surface.describe(row["id"], self.package.id)
        self.assertTrue(described["matches"]["valid"])
        self.assertIn("count", described["matches"])
        self.assertEqual(described["values"]["review_type"], "group")
        self.assertTrue(any("approval.xml" in n for n in described["notes"]))
        with self.assertRaises(UserError):
            self.Surface.write_record(
                row["id"], {"definition_domain": "[('nope', '=', 1)]"}, self.package.id
            )

    def test_rows_are_the_models_rules_only(self):
        mine = self.Surface.create_record(
            "res.partner",
            self.package.id,
            {"name": "Partners", "reviewer_id": self.env.ref("base.user_admin").id},
            template="approve_by_user",
        )
        self.Surface.create_record(
            "res.users",
            self.package.id,
            {"name": "Users", "reviewer_id": self.env.ref("base.user_admin").id},
            template="approve_by_user",
        )
        rows = self.Surface.rows("res.partner", self.package.id)
        self.assertEqual([r["id"] for r in rows], [mine["id"]])
        self.Surface.remove_record(mine["id"], self.package.id, force=True)
        self.assertNotIn("Partners", "".join(self.package._render_files().values()))

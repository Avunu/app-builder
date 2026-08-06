# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Record rules, which the serializer could always write and nothing could make.

A rule is the one thing here whose mistake is invisible. A wrong domain does
not raise: it quietly hides records from the people the rule applies to, and
the person who wrote it is usually an administrator it does not apply to.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestRuleBuilder(StudioCase):
    def _wizard(self, package, **overrides):
        values = {
            "package_id": package.id,
            "model_id": self.env["ir.model"]._get("res.partner").id,
            "name": "Own contacts only",
            "domain": "[['user_id', '=', 1]]",
        }
        values.update(overrides)
        return self.env["studio.rule.wizard"].create(values)

    def test_a_rule_is_created_and_written_to_source(self):
        package = self.make_package()
        self._wizard(package).action_create()
        rule = self.env["ir.rule"].search([("name", "=", "Own contacts only")], limit=1)
        self.assertTrue(rule)
        self.assertEqual(rule.studio_package_id, package)
        self.assertIn("ir.rule", "".join(package._render_files().values()))

    def test_a_condition_that_does_not_search_is_refused(self):
        """Not a style objection: a rule whose domain raises makes every read
        raise, for everyone it applies to."""
        package = self.make_package()
        wizard = self._wizard(package, domain="[['nope', '=', 1]]")
        with self.assertRaises(UserError) as caught:
            wizard.action_create()
        self.assertIn("does not search", str(caught.exception))

    def test_a_rule_that_applies_to_nothing_is_refused(self):
        package = self.make_package()
        wizard = self._wizard(
            package,
            perm_read=False,
            perm_write=False,
            perm_create=False,
            perm_unlink=False,
        )
        with self.assertRaises(UserError):
            wizard.action_create()

    def test_the_wizard_says_what_the_condition_matches(self):
        package = self.make_package()
        wizard = self._wizard(package, domain="[]")
        wizard._onchange_domain()
        self.assertIn("Matches", wizard.matches)

    def test_a_broken_condition_says_so_before_saving(self):
        package = self.make_package()
        wizard = self._wizard(package, domain="[['nope', '=', 1]]")
        wizard._onchange_domain()
        self.assertIn("does not search", wizard.matches)


@tagged("post_install", "-at_install")
class TestDomainBuilder(StudioCase):
    def test_fields_come_with_operators_that_suit_them(self):
        fields = {
            f["name"]: f for f in self.env["studio.domain"].fields_for("res.partner")
        }
        self.assertIn("name", fields)
        char_ops = {o["value"] for o in fields["name"]["operators"]}
        self.assertIn("ilike", char_ops)
        # `ilike` on a boolean is accepted by Odoo and meant by nobody.
        bool_ops = {o["value"] for o in fields["active"]["operators"]}
        self.assertNotIn("ilike", bool_ops)
        self.assertNotIn(">", bool_ops)

    def test_a_selection_brings_its_values(self):
        fields = {
            f["name"]: f for f in self.env["studio.domain"].fields_for("ir.ui.view")
        }
        self.assertTrue(fields["type"].get("values"))

    def test_a_relation_names_what_it_points_at(self):
        fields = {
            f["name"]: f for f in self.env["studio.domain"].fields_for("res.partner")
        }
        self.assertEqual(fields["parent_id"]["comodel"], "res.partner")

    def test_a_flat_domain_reads_back_as_rows(self):
        read = self.env["studio.domain"].read_domain(
            "['&', ['a', '=', 1], ['b', '=', 2]]"
        )
        self.assertTrue(read["editable"])
        self.assertEqual(read["joiner"], "all")
        self.assertEqual(len(read["rows"]), 2)

    def test_a_grouped_domain_refuses_rather_than_flattening_it(self):
        read = self.env["studio.domain"].read_domain(
            "['|', '&', ['a','=',1], ['b','=',2], ['c','=',3]]"
        )
        self.assertFalse(read["editable"])
        self.assertIn("cannot be shown as a flat list", read["reason"])

    def test_rows_become_a_domain_odoo_accepts(self):
        domain = self.env["studio.domain"].write_domain(
            [
                {"field": "name", "operator": "ilike", "value": "acme"},
                {"field": "parent_id", "operator": "set"},
            ]
        )
        checked = self.env["studio.domain"].check_domain("res.partner", domain)
        self.assertTrue(checked["valid"], checked.get("reason"))

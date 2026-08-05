# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A rule using a formula must say which module it needs."""

import ast

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestFormulaBridge(StudioCase):
    def _rule(self, package, **values):
        rule = self.env["tier.definition"].create(
            {
                "name": "Conditioned",
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "sequence": 10,
                **values,
            }
        )
        package._assign(rule)
        return rule

    def test_the_formula_fields_are_written(self):
        package = self.make_package()
        self.build_demo_content(package)
        self._rule(
            package,
            definition_type="formula",
            python_code="# only big ones\nrec.credit_limit > 1000",
        )
        emitted = "".join(package._render_files().values())
        self.assertIn("only big ones", emitted)

    def test_a_formula_rule_depends_on_the_module_that_defines_it(self):
        """`review_type="expression"` loads into a database without this module
        as an invalid selection value — silently, because nothing validates a
        selection on load. The manifest's depends is derived from xmlids, and a
        selection value is not one.
        """
        package = self.make_package()
        self.build_demo_content(package)
        self._rule(package, definition_type="formula", python_code="True")
        manifest = ast.literal_eval(package._render_files()["__manifest__.py"])
        self.assertIn("base_tier_validation_formula", manifest["depends"])

    def test_an_ordinary_rule_does_not_drag_the_module_in(self):
        package = self.make_package()
        self.build_demo_content(package)
        self._rule(package, review_type="individual")
        manifest = ast.literal_eval(package._render_files()["__manifest__.py"])
        self.assertNotIn("base_tier_validation_formula", manifest["depends"])

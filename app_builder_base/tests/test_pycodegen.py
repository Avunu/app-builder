# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Python code generation for graduate-to-code."""

import ast

from odoo.tests import tagged

from ..tools import pycodegen
from .common import StudioCase


@tagged("post_install", "-at_install")
class TestPyCodegen(StudioCase):
    def _render(self, package=None):
        package = package or self.make_package()
        model = self.build_demo_content(package)
        owned = model.field_id.filtered(lambda f: f.state == "manual")
        return model, pycodegen.render_model(model, owned)

    def test_class_name_conversion(self):
        self.assertEqual(pycodegen.class_name_for("x_studio_project"), "XStudioProject")
        self.assertEqual(pycodegen.class_name_for("x.foo.bar"), "XFooBar")

    def test_module_file_name(self):
        self.assertEqual(pycodegen.module_file_for("x.foo.bar"), "x_foo_bar.py")

    def test_generated_source_is_valid_python(self):
        _model, source = self._render()
        ast.parse(source)  # raises SyntaxError if we emitted garbage

    def test_generated_source_declares_the_model(self):
        _model, source = self._render()
        self.assertIn("class XStudioProject(models.Model):", source)
        self.assertIn('_name = "x_studio_project"', source)
        self.assertIn('_description = "Studio Demo Project"', source)

    def test_rec_name_is_pinned(self):
        """_custom gives x_name for free; a real class does not (models.py:3700)."""
        _model, source = self._render()
        self.assertIn('_rec_name = "x_name"', source)

    def test_fields_are_rendered_with_their_attributes(self):
        _model, source = self._render()
        self.assertIn('x_name = fields.Char(string="Name", required=True)', source)
        self.assertIn("x_budget = fields.Float", source)
        # Long signatures wrap, so assert the parts rather than one exact line.
        self.assertIn("x_partner_id = fields.Many2one(", source)
        self.assertIn('"res.partner"', source)
        self.assertIn('ondelete="set null"', source)

    def test_literals_use_double_quotes(self):
        """Mixed quote styles read as sloppy and churn under any formatter."""
        _model, source = self._render()
        self.assertNotIn("string='", source)
        self.assertNotIn("_name = '", source)

    def test_wrapped_arguments_use_a_standard_indent(self):
        _model, source = self._render()
        self.assertIn('\n        string="Budget Doubled",', source)
        self.assertNotIn("\n            string=", source)

    def test_redundant_copy_is_not_emitted_on_computed_fields(self):
        """copy already defaults to False for a computed field."""
        _model, source = self._render()
        doubled = source.split("x_budget_doubled = fields.Float(")[1].split(")")[0]
        self.assertNotIn("copy=", doubled)

    def test_selection_values_are_inlined_in_order(self):
        _model, source = self._render()
        self.assertIn('[("draft", "Draft"), ("done", "Done")]', source)

    def test_compute_becomes_a_real_method_with_depends(self):
        """A sandboxed string is promoted to something strictly more capable."""
        _model, source = self._render()
        self.assertIn('compute="_compute_x_budget_doubled"', source)
        self.assertIn("store=True", source)
        self.assertIn('@api.depends("x_budget")', source)
        self.assertIn("def _compute_x_budget_doubled(self):", source)
        self.assertIn("r['x_budget_doubled'] = r.x_budget * 2", source)

    def test_api_is_imported_only_when_needed(self):
        _model, source = self._render()
        self.assertIn("from odoo import api, fields, models", source)

        package = self.make_package(name="x_nocompute")
        model = self.env["ir.model"].create(
            {
                "name": "No Compute",
                "model": "x_nocompute_model",
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_name",
                            "field_description": "Name",
                            "ttype": "char",
                        },
                    )
                ],
            }
        )
        package._assign([model, model.field_id.filtered(lambda f: f.state == "manual")])
        plain = pycodegen.render_model(
            model, model.field_id.filtered(lambda f: f.state == "manual")
        )
        self.assertIn("from odoo import fields, models", plain)
        self.assertNotIn("api", plain.split("\n")[3])

    def test_magic_columns_are_not_emitted(self):
        """Odoo declares id/create_uid/... itself."""
        _model, source = self._render()
        for magic in ("create_uid", "create_date", "write_uid", "__last_update"):
            self.assertNotIn("%s = fields." % magic, source)

    def test_rendering_is_deterministic(self):
        package = self.make_package()
        model = self.build_demo_content(package)
        owned = model.field_id.filtered(lambda f: f.state == "manual")
        self.assertEqual(
            pycodegen.render_model(model, owned),
            pycodegen.render_model(model, owned),
        )

    def test_transient_model_uses_transient_base(self):
        package = self.make_package(name="x_transient_pkg")
        model = self.env["ir.model"].create(
            {
                "name": "Wizardy",
                "model": "x_wizardy",
                "transient": True,
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_name",
                            "field_description": "Name",
                            "ttype": "char",
                        },
                    )
                ],
            }
        )
        package._assign(model)
        source = pycodegen.render_model(
            model, model.field_id.filtered(lambda f: f.state == "manual")
        )
        self.assertIn("class XWizardy(models.TransientModel):", source)
        ast.parse(source)

    def test_computed_field_is_not_left_readonly(self):
        """Python defaults computed fields to readonly=True; manual ones are not."""
        _model, source = self._render()
        doubled = source.split("x_budget_doubled = fields.Float(")[1].split(")")[0]
        self.assertIn("readonly=False", doubled)

    def test_selection_argument_is_always_emitted(self):
        """fields.Selection() with no selection raises at registry build."""
        package = self.make_package(name="x_emptysel")
        model = self.env["ir.model"].create(
            {
                "name": "Empty Sel",
                "model": "x_emptysel_model",
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_stage",
                            "field_description": "Stage",
                            "ttype": "selection",
                        },
                    )
                ],
            }
        )
        package._assign(model)
        source = pycodegen.render_model(
            model, model.field_id.filtered(lambda f: f.state == "manual")
        )
        ast.parse(source)
        self.assertIn("fields.Selection([]", source)

    def test_group_expand_form_matches_the_field_type(self):
        """Selection takes the boolean; only many2one takes the helper name."""
        package = self.make_package(name="x_groupexp")
        model = self.env["ir.model"].create(
            {
                "name": "Group Expand",
                "model": "x_groupexp_model",
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_stage",
                            "field_description": "Stage",
                            "ttype": "selection",
                            "group_expand": True,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "x_partner_id",
                            "field_description": "Partner",
                            "ttype": "many2one",
                            "relation": "res.partner",
                            "group_expand": True,
                        },
                    ),
                ],
            }
        )
        package._assign(model)
        source = pycodegen.render_model(
            model, model.field_id.filtered(lambda f: f.state == "manual")
        )
        stage = source.split("x_stage = fields.Selection")[1].split("\n")[0]
        partner = source.split("x_partner_id = fields.Many2one")[1].split(")")[0]
        self.assertIn("group_expand=True", stage)
        self.assertIn('group_expand="_read_group_expand_full"', partner)

    def test_models_init_lists_every_module(self):
        init = pycodegen.render_models_init(["x.b", "x_a"])
        self.assertEqual(init, "from . import x_a\nfrom . import x_b\n")

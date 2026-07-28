# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Graduate custom models from metadata to Python source."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StudioGraduateWizard(models.TransientModel):
    _name = "studio.graduate.wizard"
    _description = "Studio: Graduate Models to Code"

    package_id = fields.Many2one("studio.package", required=True)
    model_ids = fields.Many2many(
        "ir.model",
        string="Models",
        required=True,
        domain="[('id', 'in', available_model_ids)]",
    )
    available_model_ids = fields.Many2many(
        "ir.model",
        "studio_graduate_available_rel",
        compute="_compute_available_model_ids",
    )
    preview = fields.Text(readonly=True)

    @api.depends("package_id")
    def _compute_available_model_ids(self):
        for wizard in self:
            if not wizard.package_id:
                wizard.available_model_ids = False
                continue
            names = wizard.package_id._owned_model_names() - (
                wizard.package_id._graduated_set()
            )
            wizard.available_model_ids = self.env["ir.model"].search(
                [("model", "in", list(names))]
            )

    @api.onchange("model_ids")
    def _onchange_model_ids(self):
        """Show the developer exactly what they are about to own."""
        from odoo.addons.app_builder_base.tools import pycodegen

        chunks = []
        for model in self.model_ids:
            owned = model.field_id.filtered(lambda f: f.state == "manual")
            chunks.append(
                pycodegen.render_model(pycodegen.spec_from_ir_model(model, owned))
            )
        self.preview = "\n\n".join(chunks)

    def action_graduate(self):
        self.ensure_one()
        if not self.model_ids:
            raise UserError(_("Choose at least one model."))
        return self.package_id.action_graduate(self.model_ids.mapped("model"))

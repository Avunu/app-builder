# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Bringing existing ``x_`` models under Python management.

New models are Python from the first save, so this is only ever a migration
path -- for a package built by an older version of the studio, or a model
somebody made by hand in Settings -> Technical. That second case is the one
that needs surfacing: such a model belongs to no package, so nothing in the
product mentioned it and there was no way to adopt it at all. It shows up here
alongside the rest, and choosing a package captures it on the way through.

Adoption is not a handoff and closes no door. Afterwards the model is exactly
like any other the builder owns: the marked block inside its class stays in
sync with the composer, and everything outside it is the developer's.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import pycodegen


class StudioAdoptWizard(models.TransientModel):
    _name = "studio.adopt.wizard"
    _inherit = ["studio.security.mixin"]
    _description = "Studio: Adopt Models into Code"

    package_id = fields.Many2one(
        "studio.package",
        required=True,
        default=lambda self: self._default_package(),
        help="Where the generated classes will live.",
    )
    model_ids = fields.Many2many(
        "ir.model",
        string="Models",
        required=True,
        domain="[('id', 'in', available_model_ids)]",
    )
    available_model_ids = fields.Many2many(
        "ir.model",
        "studio_adopt_available_rel",
        compute="_compute_available_model_ids",
    )
    unowned_count = fields.Integer(compute="_compute_available_model_ids")
    preview = fields.Text(readonly=True)

    @api.model
    def _default_package(self):
        """The obvious package, when there is only one to choose."""
        packages = self.env["studio.package"].search([])
        writable = packages.filtered("writable")
        return writable[:1].id if len(writable) == 1 else False

    @api.depends("package_id")
    def _compute_available_model_ids(self):
        """Every manual model that still has no class, wherever it lives.

        Deliberately not restricted to the chosen package. A model created by
        hand in Settings -> Technical belongs to no package and would never
        appear in a package-scoped list, which is exactly why nothing in the
        product used to mention it. Adoption captures it first.
        """
        adoptable = self._adoptable_models()
        for wizard in self:
            wizard.available_model_ids = adoptable
            already = (
                wizard.package_id._owned_model_names() if wizard.package_id else set()
            )
            wizard.unowned_count = len(
                [model for model in adoptable if model.model not in already]
            )

    @api.model
    def _adoptable_models(self):
        """Manual models no package already defines in Python."""
        owned = set(
            self.env["studio.package.model"]
            .search([("source", "in", ("python", "frozen"))])
            .mapped("model")
        )
        manual = self.env["ir.model"].search([("state", "=", "manual")])
        return manual.filtered(lambda m: m.model not in owned)

    @api.onchange("model_ids")
    def _onchange_model_ids(self):
        """Show the developer exactly what they are about to own."""
        chunks = []
        for model in self.model_ids:
            owned = model.field_id.filtered(lambda f: f.state == "manual")
            chunks.append(
                pycodegen.render_model(pycodegen.spec_from_ir_model(model, owned))
            )
        self.preview = "\n\n".join(chunks)

    def action_adopt(self):
        self.ensure_one()
        self._assert_studio_manager()
        if not self.model_ids:
            raise UserError(_("Choose at least one model."))
        self._capture_unowned()
        return self.package_id.action_adopt(self.model_ids.mapped("model"))

    def _capture_unowned(self):
        """Bring models the package does not yet own into it.

        ``action_adopt`` refuses a model the package does not own, and rightly
        so. But refusing is the wrong answer for a hand-made model that belongs
        to no package at all -- there is nowhere else for it to go, and the
        user has just said where they want it.
        """
        self.ensure_one()
        already = self.package_id._owned_model_names()
        missing = self.model_ids.filtered(lambda m: m.model not in already)
        for model in missing:
            self.package_id.studio_capture(
                [model, model.field_id.filtered(lambda f: f.state == "manual")]
            )
        return missing

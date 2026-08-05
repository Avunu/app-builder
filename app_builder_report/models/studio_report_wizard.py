# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Guided creation of a report, which is an action plus a template."""

from odoo import api, fields, models

from odoo.addons.app_builder_base.tools import scaffold


class StudioReportWizard(models.TransientModel):
    _name = "studio.report.wizard"
    _description = "Studio: New Report"

    package_id = fields.Many2one(
        "studio.package",
        required=True,
        default=lambda self: self.env["studio.package"]._suggested().id or False,
    )
    name = fields.Char(required=True, help="What the Print menu will say.")
    model_id = fields.Many2one("ir.model", string="Prints", required=True)
    layout = fields.Selection(
        selection=lambda self: [
            (layout.key, layout.label) for layout in scaffold.REPORT_LAYOUTS
        ],
        required=True,
        default="external",
        help="External carries the company header and footer, internal only "
        "the header, blank neither.",
    )
    paperformat_id = fields.Many2one(
        "report.paperformat",
        string="Paper format",
        help="Leave empty to use the company's.",
    )
    layout_help = fields.Char(compute="_compute_layout_help")

    @api.depends("layout")
    def _compute_layout_help(self):
        described = {layout.key: layout.help for layout in scaffold.REPORT_LAYOUTS}
        for wizard in self:
            wizard.layout_help = described.get(wizard.layout, "")

    def action_create(self):
        """Create it, then open it -- an empty report is not a finished job."""
        self.ensure_one()
        made = self.env["studio.report"].create_report(
            self.package_id.id,
            self.model_id.model,
            self.name,
            layout=self.layout,
            paperformat_id=self.paperformat_id.id or None,
        )
        return self.env["studio.report"].edit_action(made["report_id"])

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, models


class StudioWorkspace(models.AbstractModel):
    _inherit = "studio.workspace"

    @api.model
    def _inventory_group(self, model_name, record):
        if model_name == "tier.definition":
            return "approvals"
        return super()._inventory_group(model_name, record)

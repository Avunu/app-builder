# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, models


class StudioWorkspace(models.AbstractModel):
    _inherit = "studio.workspace"

    @api.model
    def _inventory_group(self, model_name, record):
        """An automation is one thing to the user, rule and actions alike."""
        if model_name == "base.automation":
            return "automations"
        if (
            model_name == "ir.actions.server"
            and record is not None
            and record.base_automation_id
        ):
            return "automations"
        return super()._inventory_group(model_name, record)

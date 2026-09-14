# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Compose opens the console, now that there is one.

A model the package defines in Python was composed as a list of fields beside
a preview. The console edits the same draft by dropping fields onto the
model's form, where they will actually be seen -- so that is where "Compose"
goes. The field list is still one click away (``action_compose_fields``): it
is the honest view of what the class *is*, and the composer's tour still
drives it.

A model with no form view has nothing to drop onto, and falls back to the
composer rather than to an error about a view that does not exist.
"""

from odoo import models


class StudioPackageModel(models.Model):
    _inherit = "studio.package.model"

    def action_compose(self):
        self.ensure_one()
        View = self.env["ir.ui.view"]
        if self.source != "python" or not View.default_view(self.model, "form"):
            return super().action_compose()
        params = {"model": self.model, "view_type": "form", "opened_from": "model"}
        return {
            "type": "ir.actions.client",
            "tag": "app_builder_console",
            "name": self.model,
            "target": "fullscreen",
            "params": params,
            # The same in the context, so the console survives a reload from
            # its own URL -- Apply rebuilds the registry, and the page has to
            # come back to the model it was editing.
            "context": dict(params),
        }

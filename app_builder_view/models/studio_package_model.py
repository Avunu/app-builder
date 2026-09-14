# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Compose opens the console.

A model the package defines in Python is edited by dropping fields onto the
view where they will actually be seen, and its class -- every field, in the
order it is written -- sits in the console's View tab. That is the one
builder: the field-list-beside-a-preview it replaced is gone, and with it
the second UI that had to keep up with the first.

The console needs a view to stand on: the form when there is one, else
whatever the model has. A model with no views at all is a scaffold that
has not happened yet, and the sentence says so.
"""

from odoo import _, models
from odoo.exceptions import UserError

# In the order the console prefers to open on: a form is where a field is
# dropped; a list or a kanban still shows the model and carries its draft.
CANVAS_TYPES = ("form", "list", "kanban")


class StudioPackageModel(models.Model):
    _inherit = "studio.package.model"

    def action_compose(self):
        self.ensure_one()
        if self.source != "python":
            return super().action_compose()
        View = self.env["ir.ui.view"]
        view_type = next(
            (t for t in CANVAS_TYPES if View.default_view(self.model, t)), None
        )
        if not view_type:
            raise UserError(
                _(
                    "%s has no view to open the console on yet. Add one from "
                    "the app builder, or write one, and come back.",
                    self.model,
                )
            )
        return {
            "type": "ir.actions.client",
            "tag": "app_builder_console",
            "name": self.model,
            "target": "fullscreen",
            # The console keeps what it needs to come back after a reload
            # -- Apply rebuilds the registry -- in its own URL.
            "params": {
                "pane": "views",
                "package_id": self.package_id.id,
                "res_model": self.model,
                "view_type": view_type,
                "opened_from": "model",
            },
        }

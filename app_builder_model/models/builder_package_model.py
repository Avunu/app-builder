# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What ``create_app`` remembers about a model it has not finished.

``create_app`` commits between making a model and making it an app, so a
failure in the second half leaves a model with no access rule, view or menu.
Recognising that model on the next attempt by its shape alone would also
match a manual model somebody adopted and never gave a view -- and "finishing"
that one would overwrite its source with a scaffold. So the first half says so
outright: it sets this flag in the same commit that makes the model, and the
second half clears it once the app is whole.
"""

from __future__ import annotations

from odoo import fields, models


class BuilderPackageModel(models.Model):
    _inherit = "builder.package.model"

    create_app_pending = fields.Boolean(
        string="App Not Finished",
        copy=False,
        readonly=True,
        help="Set when the builder created this model as an app and has not "
        "yet built its access rules, views and menu. Creating the app again "
        "under the same name finishes it.",
    )

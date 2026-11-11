# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # What the console remembers about this user: the package last opened,
    # the models opened lately, whether the getting-started list was
    # dismissed. A small JSON blob rather than a column per preference;
    # ``builder.workspace.user_prefs`` is the only reader and writer.
    builder_prefs = fields.Char(
        "Builder preferences", default="{}", groups="base.group_system"
    )

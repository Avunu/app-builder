# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package ownership for menus, actions, security and automations.

These records are all freely creatable by a builder package -- unlike ir.model /
ir.model.fields, there is no "declared in Python" variant to protect. The
mixins themselves live in the engine; this is only the list of what wears them.
"""

from odoo import models


class IrUiMenu(models.Model):
    _name = "ir.ui.menu"
    _inherit = ["ir.ui.menu", "builder.owned.mixin"]


class IrActionsActWindow(models.Model):
    _name = "ir.actions.act_window"
    _inherit = ["ir.actions.act_window", "builder.owned.mixin"]


class IrActionsServer(models.Model):
    _name = "ir.actions.server"
    _inherit = [
        "ir.actions.server",
        "builder.owned.mixin",
        "builder.captured.on.create",
    ]


class IrActionsReport(models.Model):
    _name = "ir.actions.report"
    _inherit = ["ir.actions.report", "builder.owned.mixin"]


# Captured on create like an automation: the console's Access Control and
# Filter Rules tabs open Odoo's own lists with a package in context, and a row
# made there is exactly the kind of record that works in this database and
# ships nowhere unless somebody takes ownership of it at once.
class IrModelAccess(models.Model):
    _name = "ir.model.access"
    _inherit = [
        "ir.model.access",
        "builder.owned.mixin",
        "builder.captured.on.create",
    ]


class IrRule(models.Model):
    _name = "ir.rule"
    _inherit = ["ir.rule", "builder.owned.mixin", "builder.captured.on.create"]


class BaseAutomation(models.Model):
    _name = "base.automation"
    _inherit = [
        "base.automation",
        "builder.owned.mixin",
        "builder.captured.on.create",
    ]

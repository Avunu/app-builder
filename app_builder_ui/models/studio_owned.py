# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package ownership for menus, actions, security and automations.

These records are all freely creatable by a studio package -- unlike ir.model /
ir.model.fields, there is no "declared in Python" variant to protect.
"""

from odoo import models


class IrUiMenu(models.Model):
    _name = "ir.ui.menu"
    _inherit = ["ir.ui.menu", "studio.owned.mixin"]


class IrActionsActWindow(models.Model):
    _name = "ir.actions.act_window"
    _inherit = ["ir.actions.act_window", "studio.owned.mixin"]


class IrActionsServer(models.Model):
    _name = "ir.actions.server"
    _inherit = ["ir.actions.server", "studio.owned.mixin"]


class IrActionsReport(models.Model):
    _name = "ir.actions.report"
    _inherit = ["ir.actions.report", "studio.owned.mixin"]


class IrModelAccess(models.Model):
    _name = "ir.model.access"
    _inherit = ["ir.model.access", "studio.owned.mixin"]


class IrRule(models.Model):
    _name = "ir.rule"
    _inherit = ["ir.rule", "studio.owned.mixin"]


class BaseAutomation(models.Model):
    _name = "base.automation"
    _inherit = ["base.automation", "studio.owned.mixin"]

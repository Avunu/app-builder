# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package ownership for menus, actions, security and automations.

These records are all freely creatable by a studio package -- unlike ir.model /
ir.model.fields, there is no "declared in Python" variant to protect.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class StudioCapturedOnCreate(models.AbstractModel):
    """Records that belong to the package the studio is working in.

    Same reasoning as ``ir.model.fields``: a rule created through the studio and
    left unassigned exists in this database and nowhere else, which is exactly
    the drift the project exists to prevent -- and it is invisible, because the
    rule *works*. It works here, forever, and never anywhere else.

    Only when a package is named in context, so ordinary use of Settings →
    Technical is unaffected. A warning rather than an error for the same reason
    the field mixin warns: callers that are not the studio must not be forced
    into a package they never asked for.
    """

    _name = "studio.captured.on.create"
    _description = "Studio Captured On Create"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get("studio_skip_autocapture"):
            return records
        package = (
            self.env["studio.package"]
            .browse(self.env.context.get("studio_package_id") or [])
            .exists()
        )
        if package and package.writable:
            package.studio_capture(records)
        elif self.env.context.get("studio_package_id"):
            _logger.warning(
                "%s was created for a studio package that is missing or "
                "read-only, so it will not be written to source.",
                records._name,
            )
        return records


class IrUiMenu(models.Model):
    _name = "ir.ui.menu"
    _inherit = ["ir.ui.menu", "studio.owned.mixin"]


class IrActionsActWindow(models.Model):
    _name = "ir.actions.act_window"
    _inherit = ["ir.actions.act_window", "studio.owned.mixin"]


class IrActionsServer(models.Model):
    _name = "ir.actions.server"
    _inherit = [
        "ir.actions.server",
        "studio.owned.mixin",
        "studio.captured.on.create",
    ]


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
    _inherit = [
        "base.automation",
        "studio.owned.mixin",
        "studio.captured.on.create",
    ]

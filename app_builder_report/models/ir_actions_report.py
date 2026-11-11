# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The button that gets a builder from a report to its layout.

Odoo's own report form already has a *Qweb Views* stat button, which opens the
template as a list of ``ir.ui.view`` records -- the arch in a textarea, and the
inheriting views alongside it with no indication of which is which. That is the
technical view of the thing. This is the editing one.
"""

from __future__ import annotations

from typing import cast

from odoo import models

from odoo.addons.app_builder_base.tools import typed

from .builder_report import BuilderReport, OpenConsoleActionJSON


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def action_builder_edit(self) -> OpenConsoleActionJSON:
        self.ensure_one()
        return typed.model(self.env, BuilderReport).edit_action(cast("int", self.id))

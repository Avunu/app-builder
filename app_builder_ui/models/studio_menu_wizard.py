# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Guided creation of a menu + action pair, and of an access rule."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StudioMenuWizard(models.TransientModel):
    _name = "studio.menu.wizard"
    _description = "Studio: New Menu"

    package_id = fields.Many2one("studio.package", required=True)
    name = fields.Char(required=True)
    model_id = fields.Many2one("ir.model", string="Opens model", required=True)
    parent_id = fields.Many2one(
        "ir.ui.menu",
        string="Parent menu",
        help="Leave empty to create a new top-level app menu.",
    )
    sequence = fields.Integer(default=10)
    view_mode = fields.Char(default="list,form", required=True)
    domain = fields.Char(default="[]")

    def action_create(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"].create(
            {
                "name": self.name,
                "res_model": self.model_id.model,
                "view_mode": self.view_mode,
                "domain": self.domain or "[]",
            }
        )
        menu = self.env["ir.ui.menu"].create(
            {
                "name": self.name,
                "parent_id": self.parent_id.id or False,
                "action": "ir.actions.act_window,%d" % action.id,
                "sequence": self.sequence,
            }
        )
        self.package_id.studio_capture([action, menu])
        return {"type": "ir.actions.act_window_close"}


class StudioAccessWizard(models.TransientModel):
    _name = "studio.access.wizard"
    _description = "Studio: New Access Rule"

    package_id = fields.Many2one("studio.package", required=True)
    model_id = fields.Many2one("ir.model", required=True)
    group_id = fields.Many2one(
        "res.groups",
        string="Group",
        help="Leave empty to grant access to every user, which is rarely what "
        "you want.",
    )
    perm_read = fields.Boolean(default=True)
    perm_write = fields.Boolean(default=True)
    perm_create = fields.Boolean(default=True)
    perm_unlink = fields.Boolean()

    def action_create(self):
        self.ensure_one()
        access = self.env["ir.model.access"].create(
            {
                "name": "%s %s"
                % (self.model_id.model, self.group_id.name or "all users"),
                "model_id": self.model_id.id,
                "group_id": self.group_id.id or False,
                "perm_read": self.perm_read,
                "perm_write": self.perm_write,
                "perm_create": self.perm_create,
                "perm_unlink": self.perm_unlink,
            }
        )
        self.package_id.studio_capture(access)
        return {"type": "ir.actions.act_window_close"}


class StudioAutomationWizard(models.TransientModel):
    _name = "studio.automation.wizard"
    _description = "Studio: New Automation"

    package_id = fields.Many2one("studio.package", required=True)
    name = fields.Char(required=True)
    model_id = fields.Many2one("ir.model", required=True)
    trigger = fields.Selection(
        selection=lambda self: self.env["base.automation"]._fields["trigger"].selection,
        required=True,
        default="on_create",
    )
    filter_domain = fields.Char(
        string="Only when",
        default="[]",
        help="Which records the rule should fire for. Built from conditions, "
        "or written by hand if it needs grouping.",
    )
    matches = fields.Char(readonly=True)
    code = fields.Text(
        required=True,
        default="# Available: env, model, record, records, log, UserError\n",
        help="Python evaluated in Odoo's sandbox. Stored as data on "
        "ir.actions.server, so no code file and no restart are needed.",
    )

    @api.onchange("filter_domain", "model_id")
    def _onchange_filter_domain(self):
        """Say what it will fire for, before it starts firing.

        An automation with a wrong condition is not silent like a record rule
        -- it is worse. It runs on records nobody expected, and by the time
        anybody notices it has already written to them.
        """
        for wizard in self:
            if not wizard.model_id or not wizard.filter_domain:
                wizard.matches = False
                continue
            checked = self.env["studio.domain"].check_domain(
                wizard.model_id.model, wizard.filter_domain
            )
            wizard.matches = (
                _("Would fire for %s of the records that exist now.", checked["count"])
                if checked["valid"]
                else _("This condition does not search: %s", checked["reason"])
            )

    @api.constrains("code")
    def _check_code(self):
        for wizard in self:
            if not (wizard.code or "").strip():
                raise UserError(_("The automation needs something to do."))

    def action_create(self):
        self.ensure_one()
        checked = self.env["studio.domain"].check_domain(
            self.model_id.model, self.filter_domain or "[]"
        )
        if not checked["valid"]:
            raise UserError(
                _(
                    "This condition does not search, so the automation would "
                    "raise every time it was evaluated:\n\n%s",
                    checked["reason"],
                )
            )
        server_action = self.env["ir.actions.server"].create(
            {
                "name": self.name,
                "model_id": self.model_id.id,
                "state": "code",
                "code": self.code,
            }
        )
        automation = self.env["base.automation"].create(
            {
                "name": self.name,
                "model_id": self.model_id.id,
                "trigger": self.trigger,
                "filter_domain": self.filter_domain or False,
                "action_server_ids": [(6, 0, server_action.ids)],
            }
        )
        self.package_id.studio_capture([server_action, automation])
        return {"type": "ir.actions.act_window_close"}

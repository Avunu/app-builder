# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Authoring a record rule, which until now could only be captured.

`studio.access.wizard` covers `ir.model.access` -- who may read, write, create,
delete a *model*. A record rule is the other half: *which records* of it, and it
is the half that actually enforces multi-company, ownership and confidentiality.
The serializer has always written one; nothing ever made one.

The domain is built rather than typed, through `studio.domain`, and checked
against Odoo's own parser before it is written -- a rule whose domain does not
search is a rule that raises on every read for everyone it applies to, and
writing that to source ships it to the next database too.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import domainspec


class StudioRuleWizard(models.TransientModel):
    _name = "studio.rule.wizard"
    _description = "Studio: New Record Rule"

    package_id = fields.Many2one(
        "studio.package",
        required=True,
        default=lambda self: self.env["studio.package"]._suggested().id or False,
    )
    model_id = fields.Many2one("ir.model", string="Applies to", required=True)
    name = fields.Char(required=True)
    group_ids = fields.Many2many(
        "res.groups",
        string="Groups",
        help="Leave empty for a global rule, which applies to everyone "
        "including users with no group in common — including the "
        "administrator.",
    )
    domain = fields.Char(
        string="Condition",
        default="[]",
        required=True,
        help="Which records the rule lets through. Built from conditions, or "
        "written by hand if it needs grouping.",
    )
    perm_read = fields.Boolean(string="Read", default=True)
    perm_write = fields.Boolean(string="Write", default=True)
    perm_create = fields.Boolean(string="Create", default=True)
    perm_unlink = fields.Boolean(string="Delete", default=True)
    matches = fields.Char(readonly=True, help="What the condition matches now.")

    @api.onchange("domain", "model_id")
    def _onchange_domain(self):
        """Say what the condition matches before it is saved.

        A rule is the one thing in the studio whose mistake is invisible: a
        wrong domain does not raise, it quietly hides records from the people
        it applies to, and the person who wrote it is usually an administrator
        the rule does not apply to.
        """
        for wizard in self:
            if not wizard.model_id or not wizard.domain:
                wizard.matches = False
                continue
            checked = self.env["studio.domain"].check_domain(
                wizard.model_id.model, wizard.domain
            )
            wizard.matches = (
                _("Matches %s records right now.", checked["count"])
                if checked["valid"]
                else _("This condition does not search: %s", checked["reason"])
            )

    def action_create(self):
        self.ensure_one()
        self.package_id._assert_writable()
        checked = self.env["studio.domain"].check_domain(
            self.model_id.model, self.domain
        )
        if not checked["valid"]:
            raise UserError(
                _(
                    "This condition does not search, so the rule would raise "
                    "for everyone it applies to:\n\n%s",
                    checked["reason"],
                )
            )
        if not any(
            (self.perm_read, self.perm_write, self.perm_create, self.perm_unlink)
        ):
            raise UserError(
                _("A rule that applies to no operation does nothing at all.")
            )
        rule = self.env["ir.rule"].create(
            {
                "name": self.name,
                "model_id": self.model_id.id,
                "domain_force": self.domain,
                "groups": [(6, 0, self.group_ids.ids)],
                "perm_read": self.perm_read,
                "perm_write": self.perm_write,
                "perm_create": self.perm_create,
                "perm_unlink": self.perm_unlink,
            }
        )
        self.package_id.studio_capture(rule)
        return {"type": "ir.actions.act_window_close"}

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        values.setdefault("domain", domainspec.render([]))
        return values

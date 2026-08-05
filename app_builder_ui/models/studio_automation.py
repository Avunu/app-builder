# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Automations and webhooks, reachable from the studio and written to source.

Deliberately **not** a reimplementation of ``base.automation``'s form. Odoo's
own is trigger-aware in a way that took years to get right -- which fields
appear for *Based on date field* and not for *On webhook*, that ``Update
Record`` shows a value box for a char and a record picker for a many2one -- and
a second copy of that would drift from it on the first release and be wrong in
ways nobody could see.

What the studio is actually for here is the three things Odoo's form has no
opinion about:

* **scope** -- the automations *for the model you are looking at*, rather than
  the whole database's list under Settings → Technical;
* **ownership** -- a rule created from here belongs to a package, so it lands in
  source instead of only in this database;
* **the reason to care** -- a webhook's URL and its rotate button are already on
  the form, but nobody finds the form.

So this opens Odoo's form, filtered and with a package in context. That is a
smaller thing to maintain and a better form than we would have written.
"""

from odoo import _, api, models
from odoo.exceptions import UserError


class StudioAutomation(models.AbstractModel):
    _name = "studio.automation"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Automations"

    @api.model
    def _suggested_package(self):
        return self.env["studio.package"]._suggested()

    @api.model
    def action_open(self, model_name=None, webhooks=False):
        """Odoo's automation list, scoped and with a package to record into."""
        self._assert_studio_user()
        package = self._suggested_package()
        domain = []
        context = {"studio_package_id": package.id or False}
        if model_name:
            if model_name not in self.env:
                raise UserError(_("Unknown model '%s'.", model_name))
            model = self.env["ir.model"]._get(model_name)
            domain.append(("model_id", "=", model.id))
            context["default_model_id"] = model.id
        if webhooks:
            domain.append(("trigger", "=", "on_webhook"))
            context["default_trigger"] = "on_webhook"
        return {
            "type": "ir.actions.act_window",
            "name": _("Webhooks") if webhooks else _("Automations"),
            "res_model": "base.automation",
            "view_mode": "list,form",
            "domain": domain,
            "context": context,
            "help": self._empty_state(model_name, webhooks),
        }

    @api.model
    def _empty_state(self, model_name, webhooks):
        if webhooks:
            return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
                _("Let another system drive this database"),
                _(
                    "A webhook gives you a URL. Anything that can send it a "
                    "POST can create or update records here."
                ),
            )
        return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
            _("Make something happen on its own"),
            _(
                "Pick what to watch for and what to do about it. Rules you "
                "create here are written into your studio package, so they "
                "ship with the rest of your customisation."
            ),
        )

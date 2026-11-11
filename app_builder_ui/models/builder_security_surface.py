# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Access rules and record rules, reachable from the console and written to source.

The same bargain as ``builder.automation``: Odoo's own forms for ``ir.model
.access`` and ``ir.rule`` are the right forms -- the access list is the CSV
laid out as a grid, and the rule form has the domain editor and the group
picker already -- and a second copy would only drift from them. What neither
of them has is a sense of *where you came from*: Settings → Technical lists
every row in the database, and the three that gate the model on screen are
found by knowing its technical name.

So this opens those forms, scoped to one model and with a package in context.
The scope is the part the console needs -- an "Access Control" tab that showed
the whole database would be a longer road to the same screen -- and the
package is the part the project needs: a row created from here is captured
into source the moment it exists, the way an automation is, instead of living
in this database only and working just well enough that nobody notices. The
package is the console's own when it names one -- the one its top bar shows
and its drops go into -- and the suggested one for the Builder menu, which has
no console to ask.
"""

from __future__ import annotations

from typing import TypedDict

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_base.tools.i18n import _
from odoo.addons.base.models.ir_model import IrModel


class SecuritySurfaceActionJSON(TypedDict):
    """``action_access()``/``action_rules()``'s shared return: Odoo's own
    access or rules list, scoped."""

    type: str
    name: str
    res_model: str
    view_mode: str
    views: list[tuple[bool, str]]
    domain: list[tuple[str, str, object]]
    context: dict[str, object]
    help: str


class BuilderSecuritySurface(models.AbstractModel):
    _name = "builder.security.surface"
    _inherit = ["builder.security.mixin"]
    _description = "Builder Access Control"

    @api.model
    def _scoped(
        self, model_name: str | None, package_id: int | None = None
    ) -> tuple[list[tuple[str, str, object]], dict[str, object]]:
        """The domain and context that pin a list to one model.

        ``model_id.model`` rather than the id: it reads as the model name in
        the URL and in a saved filter, and it is what both ``ir.model.access``
        and ``ir.rule`` search on. The default is the id, because that is what
        the form's picker stores.
        """
        typed.security(self)._assert_builder_user()
        package = typed.model(self.env, BuilderPackage)._chosen(package_id)
        domain: list[tuple[str, str, object]] = []
        context: dict[str, object] = {"builder_package_id": package.id or False}
        if model_name:
            if model_name not in self.env:
                raise UserError(_("Unknown model '%s'.", model_name))
            model = typed.model(self.env, IrModel)._get(model_name)
            domain.append(("model_id.model", "=", model_name))
            context["default_model_id"] = model.id
        return domain, context

    @api.model
    def action_access(
        self, model_name: str | None = None, package_id: int | None = None
    ) -> SecuritySurfaceActionJSON:
        """Odoo's access-rights list, scoped and with a package to record into."""
        domain, context = self._scoped(model_name, package_id)
        return {
            "type": "ir.actions.act_window",
            "name": _("Access Control"),
            "res_model": "ir.model.access",
            "view_mode": "list,form",
            # Spelled out because the dict is returned over plain RPC, and
            # the client derives nothing from view_mode on that path.
            "views": [(False, "list"), (False, "form")],
            "domain": domain,
            "context": context,
            "help": self._empty_state(rules=False),
        }

    @api.model
    def action_rules(
        self, model_name: str | None = None, package_id: int | None = None
    ) -> SecuritySurfaceActionJSON:
        """Odoo's record-rules list, scoped and with a package to record into."""
        domain, context = self._scoped(model_name, package_id)
        return {
            "type": "ir.actions.act_window",
            "name": _("Filter Rules"),
            "res_model": "ir.rule",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": domain,
            "context": context,
            "help": self._empty_state(rules=True),
        }

    @api.model
    def _empty_state(self, rules: bool) -> str:
        if rules:
            return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
                _("Decide which records each group sees"),
                _(
                    "A record rule is a condition on the records, per group. "
                    "Rules you create here are written into your builder "
                    "package's security files, so they ship with the rest of "
                    "your customisation."
                ),
            )
        return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
            _("Say who may read, write, create and delete"),
            _(
                "One line per group. Lines you create here are written into "
                "your builder package's access file, so they ship with the "
                "rest of your customisation."
            ),
        )

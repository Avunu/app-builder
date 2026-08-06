# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What a domain builder needs from the registry.

The pure half -- domain string to conditions and back -- is
``tools/domainspec``. This is the half that has to ask the registry: which
fields can be tested, and which operators mean anything for each of them.

Offering every operator for every type is what makes a condition builder feel
like a form nobody proof-read. ``ilike`` on a boolean and ``>`` on a many2one
are both accepted by Odoo and neither is a thing anybody means.
"""

import ast

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import domainspec

# Operators worth offering, per family of field. Order is the order they are
# shown, so the common one comes first.
TEXTUAL = ("=", "!=", "ilike", "not ilike", "set", "not set")
NUMERIC = ("=", "!=", ">", ">=", "<", "<=", "set", "not set")
EXACT = ("=", "!=", "set", "not set")
RELATIONAL = ("=", "!=", "in", "not in", "set", "not set")

OPERATORS_BY_TYPE = {
    "char": TEXTUAL,
    "text": TEXTUAL,
    "html": TEXTUAL,
    "integer": NUMERIC,
    "float": NUMERIC,
    "monetary": NUMERIC,
    "date": NUMERIC,
    "datetime": NUMERIC,
    "boolean": ("=", "!="),
    "selection": EXACT,
    "many2one": RELATIONAL,
    "many2many": RELATIONAL,
    "one2many": RELATIONAL,
}

LABELS = {
    "=": "is",
    "!=": "is not",
    ">": "is after / more than",
    ">=": "is at least",
    "<": "is before / less than",
    "<=": "is at most",
    "ilike": "contains",
    "not ilike": "does not contain",
    "in": "is one of",
    "not in": "is none of",
    "set": "is set",
    "not set": "is not set",
}


class StudioDomain(models.AbstractModel):
    _name = "studio.domain"
    _inherit = ["studio.security.mixin"]
    _description = "Studio: Condition Builder"

    @api.model
    def fields_for(self, model_name):
        """Fields a condition can test, with the operators that suit each.

        Stored fields only: a non-stored computed field cannot be searched
        unless it declares a `search` method, and offering one that raises at
        query time would be worse than leaving it out.
        """
        self._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        out = []
        for name, field in sorted(self.env[model_name]._fields.items()):
            if not field.store or field.type not in OPERATORS_BY_TYPE:
                continue
            entry = {
                "name": name,
                "string": field.string or name,
                "type": field.type,
                "operators": [
                    {"value": op, "label": LABELS[op]}
                    for op in OPERATORS_BY_TYPE[field.type]
                ],
            }
            if field.type == "selection":
                entry["values"] = [
                    {"value": value, "label": label}
                    for value, label in (
                        field.get_description(self.env).get("selection") or []
                    )
                ]
            if field.type in ("many2one", "one2many", "many2many"):
                entry["comodel"] = field.comodel_name
            out.append(entry)
        return out

    @api.model
    def read_domain(self, domain):
        """A stored domain as rows, or a refusal the caller can show.

        The refusal is the point. A nested domain has no faithful flat
        rendering, and a builder that showed one anyway would rewrite it the
        moment somebody touched an unrelated row.
        """
        self._assert_studio_user()
        parsed = domainspec.parse(domain or "[]")
        if parsed is None:
            return {
                "editable": False,
                "domain": domain,
                "reason": _(
                    "This condition groups its terms, or negates one, so it "
                    "cannot be shown as a flat list without changing what it "
                    "means. Edit it as source."
                ),
            }
        conditions, joiner = parsed
        return {
            "editable": True,
            "joiner": joiner,
            "rows": [c.as_dict() for c in conditions],
        }

    @api.model
    def write_domain(self, rows, joiner=domainspec.ALL):
        """Rows back to a domain string, validated against Odoo's own parser.

        Checked here rather than trusted: a domain that renders and does not
        *search* would be written to source and fail on somebody else's
        database, which is the failure this project is least willing to ship.
        """
        self._assert_studio_user()
        conditions = [
            domainspec.Condition(
                row.get("field"), row.get("operator", "="), row.get("value", False)
            )
            for row in rows or []
            if row.get("field")
        ]
        rendered = domainspec.render(conditions, joiner)
        return rendered

    @api.model
    def check_domain(self, model_name, domain):
        """Does this actually search? Returns the count, or the complaint."""
        self._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        # Not "is it flat" -- a source-edited domain is usually not, and is
        # usually fine. Odoo's own parser is the judge of whether it searches.
        try:
            count = self.env[model_name].search_count(ast.literal_eval(domain or "[]"))
        except Exception as err:  # noqa: BLE001 - any failure is the same answer
            return {"valid": False, "reason": str(err)}
        return {"valid": True, "count": count}

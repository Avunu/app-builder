# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What ``base_tier_validation_formula`` adds to an approval rule.

Two things, and the second is the one that bites.

**Two stored fields** — ``python_code`` and ``reviewer_expression`` — which are
user-written Python and plainly configuration. Unclassified, the completeness
guard would refuse to render any package containing a rule the moment somebody
edited one.

**Two selection values**, which is subtler. ``definition_type`` gains
``formula`` and ``domain_formula``; ``review_type`` gains ``expression``. The
base bridge emits both fields already, so a rule using one produces a file that
loads into a database without this module as an *invalid selection value* —
silently, because nothing validates a selection on load. The manifest's
``depends`` is derived from the xmlids emitted, and a selection value is not an
xmlid, so nothing was recording it.

That is design finding 4 in DESIGN.md for the third time: a package that
installs here and fails elsewhere. ``_value_depends`` is the general answer.
"""

from odoo import api, models

MODULE = "base_tier_validation_formula"


class TierDefinitionFormulaSerializer(models.AbstractModel):
    _inherit = "studio.serializer.tier.definition"

    @api.model
    def _emitted_field_names(self):
        return super()._emitted_field_names() + (
            "python_code",
            "reviewer_expression",
        )

    @api.model
    def _value_depends(self):
        depends = dict(super()._value_depends())
        depends["definition_type"] = {
            **depends.get("definition_type", {}),
            "formula": MODULE,
            "domain_formula": MODULE,
        }
        depends["review_type"] = {
            **depends.get("review_type", {}),
            "expression": MODULE,
        }
        return depends

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

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs this at runtime. Cross-addon (this addon is not
    # app_builder_base itself), so fully qualified -- same house convention
    # `tier_serializers.py`'s own imports follow.
    from odoo.addons.app_builder_base.models.studio_serializer import (
        StudioSerializer,
    )

MODULE = "base_tier_validation_formula"


class TierDefinitionFormulaSerializer(models.AbstractModel):
    _inherit = "studio.serializer.tier.definition"

    @api.model
    def _emitted_field_names(self) -> tuple[str, ...]:
        # `_inherit`-only composition (never a real Python base class), so
        # `super()` here is invisible to pyright the same way `self
        # ._assert_studio_user()` is on `studio.security.mixin` -- same gap
        # `typed.serializer_super()` targets. That helper itself does not
        # type-check at any real call site, though: pyright infers a
        # zero-arg `super()` call's own type as the synthesized concrete
        # base class (`AbstractModel` here), never as the builtin `super`
        # type `serializer_super(sup: super)` declares -- confirmed with
        # `reveal_type(super())` in isolation, not particular to this file.
        # Pre-existing in `typed.py`, out of this file's scope to fix, so
        # this uses the same direct cast `tier_serializers.py`,
        # `ir_model.py` and `base_automation_serializer.py` already use
        # instead (`serializer_super`'s own would-be body, inlined).
        return cast("StudioSerializer", super())._emitted_field_names() + (
            "python_code",
            "reviewer_expression",
        )

    @api.model
    def _value_depends(self) -> dict[str, dict[str, str]]:
        depends = dict(cast("StudioSerializer", super())._value_depends())
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

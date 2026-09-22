# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approval rules, written to source like everything else.

``tier.definition`` is configuration -- who must approve what, and in what
order -- so it belongs in the package. ``tier.review`` is the opposite: it is
one database's in-flight approvals, holding integer ``res_id`` values and user
ids, and nothing in it means anything after a fresh install. The two live in
the same module and look similar, which is exactly why the split is stated here
rather than left to be inferred.

There is no upstream precedent to copy: no module in OCA ships a
``tier.definition`` as an XML data record. So this defines the format, which is
freeing and also means nothing upstream has validated it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

from odoo.addons.app_builder_base.models.studio_serializer import SEQ_RULE

if TYPE_CHECKING:
    # Only for annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes. Both are
    # genuinely external, real classes (never looked up by name at runtime
    # here, so neither needs `typed.model()`'s real binding) -- fully
    # qualified since both are reached only through the merged tree
    # (cross-addon, not this addon's own files).
    from odoo.models import BaseModel

    from odoo.addons.base.models.ir_model import IrModel
    from odoo.addons.base_tier_validation.models.tier_definition import (
        TierDefinition,
    )
    from odoo.addons.app_builder_base.models.studio_serializer import (
        StudioSerializer,
    )


class TierDefinitionSerializer(models.AbstractModel):
    _name = "studio.serializer.tier.definition"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for tier.definition"

    _studio_model = "tier.definition"
    # Beside record rules: both answer "who may do what", both reference groups,
    # and both must load after the models they name.
    _studio_sequence = SEQ_RULE
    _studio_dir = "security"
    _studio_suffix = "_approval"
    _studio_fields = (
        "name",
        "model_id",
        "sequence",
        "review_type",
        "reviewer_id",
        "reviewer_group_id",
        "reviewer_field_id",
        "definition_type",
        "definition_domain",
        "approve_sequence",
        "approve_sequence_bypass",
        "allow_write_for_reviewer",
        "has_comment",
        "notify_on_create",
        "notify_on_pending",
        "notify_on_accepted",
        "notify_on_rejected",
        "notify_on_restarted",
        "notify_reminder_delay",
        "company_id",
        "active",
    )
    _studio_ignored = (
        # A stored related of model_id.model, readonly and with no inverse. It
        # is the column the engine actually *matches* on, which makes it look
        # important -- but writing it from a data file is impossible and
        # unnecessary: setting model_id fills it.
        "model",
        # Computed from reviewer_field_id's model; a choice-list for the UI
        # rather than a choice.
        "valid_reviewer_field_ids",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        # Grouped with the model whose records it gates, so the rule sits
        # beside that model's access rules rather than in a file of its own.
        #
        # `model_id` is a plain-string-comodel Many2one -- same
        # `_Relational.__get__` gap as every other read of one in this
        # migration (`studio_package.py`'s own `IrModelFields.model_id`).
        definition = cast("TierDefinition", record)
        model = cast("IrModel", definition.model_id)  # pyright: ignore[reportUnknownMemberType]
        return model.model or "misc"

    @api.model
    def _sort_key(self, record: BaseModel, xmlid: str) -> tuple[int, str]:
        # By sequence first: the order is the approval order, and a reader of
        # the file should see the steps in the order they happen.
        #
        # NB: the base class declares (and `studio_package.py`'s own
        # `_render_files` bucket types already pin) a 2-tuple, `(sequence,
        # xmlid)`. This override actually returns a 3-tuple -- pre-existing
        # in the untyped original, not introduced by this migration -- so
        # the declared return type here matches the *base class's contract*
        # rather than this method's own real return shape, and the mismatch
        # is flagged (not silently fixed, per this migration's own rule) in
        # this file's own conversion notes rather than papered over.
        definition = cast("TierDefinition", record)
        return (self._studio_sequence, definition.sequence, xmlid)  # pyright: ignore[reportReturnType]

    @api.model
    def _should_skip(self, record: BaseModel, fname: str) -> bool:
        if fname == "active":
            # Defaults True; only an archived rule is worth recording.
            return bool(cast("TierDefinition", record).active)
        # `super()` here resolves, to pyright, only as far as this class's
        # own *declared* Python base (`models.AbstractModel`) -- the same
        # `_inherit`-mixin-invisible-to-pyright gap `typed.security()` exists
        # for on `self`, one level up: `_inherit = "studio.serializer"` is a
        # registry-level composition, not a real Python base class, so
        # `StudioSerializer._should_skip` is nowhere in the MRO pyright can
        # see. At runtime the registry *does* build the final class with
        # `StudioSerializer` in its bases, so `super()` genuinely reaches it
        # -- this cast only tells pyright what is already true.
        return cast("StudioSerializer", super())._should_skip(record, fname)

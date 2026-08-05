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

from odoo import api, models

from odoo.addons.app_builder_base.models.studio_serializer import SEQ_RULE


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
    def _group_model(self, record):
        # Grouped with the model whose records it gates, so the rule sits
        # beside that model's access rules rather than in a file of its own.
        return record.model_id.model or "misc"

    @api.model
    def _sort_key(self, record, xmlid):
        # By sequence first: the order is the approval order, and a reader of
        # the file should see the steps in the order they happen.
        return (self._studio_sequence, record.sequence, xmlid)

    @api.model
    def _should_skip(self, record, fname):
        if fname == "active":
            # Defaults True; only an archived rule is worth recording.
            return bool(record.active)
        return super()._should_skip(record, fname)

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``base.automation``.

Lives here rather than in app_builder_base because base_automation is an optional
dependency: the engine must not require it.
"""

from odoo import api, models

from odoo.addons.app_builder_base.models.studio_serializer import SEQ_AUTOMATION


class BaseAutomationSerializer(models.AbstractModel):
    _name = "studio.serializer.base.automation"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for base.automation"

    _studio_model = "base.automation"
    _studio_sequence = SEQ_AUTOMATION
    _studio_dir = "data"
    _studio_suffix = "_automation"
    _studio_fields = (
        "name",
        "model_id",
        "active",
        "description",
        "trigger",
        "trigger_field_ids",
        "on_change_field_ids",
        "filter_pre_domain",
        "filter_domain",
        "trg_date_id",
        "trg_date_range",
        "trg_date_range_type",
        "trg_date_calendar_id",
        "trg_selection_field_id",
        "trg_field_ref",
        "action_server_ids",
        "record_getter",
        "log_webhook_calls",
    )
    _studio_ignored = (
        # A per-database secret. Committing it would both leak the URL that
        # can drive this automation and make the file differ between
        # databases; base.automation regenerates it on create.
        "webhook_uuid",
        # When the scheduled action last swept this rule. Runtime state, and
        # pinning it in source would make a reload replay or skip work
        # depending on when the file was written.
        "last_run",
    )

    @api.model
    def _group_model(self, record):
        return record.model_id.model

    @api.model
    def _should_skip(self, record, fname):
        if fname == "active":
            return bool(record.active)
        return super()._should_skip(record, fname)

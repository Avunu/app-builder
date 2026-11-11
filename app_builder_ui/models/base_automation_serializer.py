# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``base.automation``.

Lives here rather than in app_builder_base because base_automation is an optional
dependency: the engine must not require it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

from odoo.addons.app_builder_base.models.builder_serializer import SEQ_AUTOMATION

if TYPE_CHECKING:
    from odoo.models import BaseModel

    from odoo.addons.app_builder_base.models.builder_serializer import (
        BuilderSerializer,
    )


class BaseAutomationSerializer(models.AbstractModel):
    _name = "builder.serializer.base.automation"
    _inherit = "builder.serializer"
    _description = "Builder Serializer for base.automation"

    _builder_model = "base.automation"
    _builder_sequence = SEQ_AUTOMATION
    _builder_dir = "data"
    _builder_suffix = "_automation"
    _builder_fields = (
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
    _builder_ignored = (
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
    def _group_model(self, record: BaseModel) -> str | None:
        # `record` is genuinely a `base.automation` recordset at runtime, but
        # the overridden method's own declared parameter type (`BaseModel`,
        # `builder_serializer.py`) is what has to match here -- same
        # "`record[fname]`, not `record.fname`" idiom `_should_skip` below and
        # `BuilderSerializer` itself already use for a field pyright cannot
        # know a generically-typed record carries.
        return record["model_id"].model

    @api.model
    def _should_skip(self, record: BaseModel, fname: str) -> bool:
        if fname == "active":
            return bool(record["active"])
        # `BaseAutomationSerializer`'s only real base is `builder.serializer`,
        # composed in at the registry level via `_inherit` -- never a real
        # Python base class -- so `_should_skip` is invisible to pyright on
        # the plain `super()` call the same way `self._assert_builder_manager()`
        # is on `self` for the `_inherit`-mixin-invisible-to-pyright pattern
        # `typed.security()` already fixes; the identical cast, aimed at
        # `super()` instead of `self`, since there is no shared helper for
        # this call shape yet.
        return cast("BuilderSerializer", super())._should_skip(record, fname)

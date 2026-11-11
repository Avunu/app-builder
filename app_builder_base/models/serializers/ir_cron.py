# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.cron`` -- a scheduled action.

``ir.cron`` delegates to ``ir.actions.server`` (``delegate=True`` on
``ir_actions_server_id``, ``ir_cron.py:68``), which is why it carries
``builder_package_id`` without anyone adding it: the builder put that field on the
server action. The consequence was that a captured cron looked owned, its server
action serialised, and its *scheduling* -- the half that makes it a cron -- was
dropped with nothing to say so.

Nothing in the builder creates a cron today. It is written now because the hole
is cheap to close and expensive to notice: a scheduled action that silently
loses its interval on reload runs at Odoo's default, not the author's.

Emitted under ``noupdate="1"`` for the same reason as ``ir.sequence``:
``nextcall`` and ``lastcall`` are state, and re-running the data file on an
upgrade would move the schedule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

from ..builder_serializer import SEQ_CRON

if TYPE_CHECKING:
    # Only used inside annotations/cast() forward-refs (`from __future__
    # import annotations` defers all of them to strings), never at runtime --
    # same bargain `compat.py`'s own `TYPE_CHECKING`-guarded imports make.
    from typing import Any

    from odoo.models import BaseModel


class IrCronSerializer(models.AbstractModel):
    _name = "builder.serializer.ir.cron"
    _inherit = "builder.serializer"
    _description = "Builder Serializer for ir.cron"

    _builder_model = "ir.cron"
    _builder_sequence = SEQ_CRON
    _builder_dir = "data"
    _builder_suffix = "_cron"
    _builder_noupdate = True
    _builder_fields = (
        "ir_actions_server_id",
        "active",
        "interval_number",
        "interval_type",
        "nextcall",
        "priority",
        "user_id",
    )
    _builder_ignored = (
        # Delegated from ir.actions.server, which emits them itself. Emitting
        # them here would write the same values into two records and let them
        # disagree on reload.
        "cron_name",
        "name",
        "model_id",
        "state",
        "code",
        "lastcall",
        # Runtime bookkeeping: Odoo increments failure_count and stamps
        # first_failure_date when a job raises, and clears both on success.
        # They describe what happened in this database, not what the author
        # asked for.
        "failure_count",
        "first_failure_date",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        # `model_id` reaches `ir.cron` only through `ir_actions_server_id`'s
        # `delegate=True` (`ir_cron.py:70` in the merged tree) -- it is never
        # a real attribute of `ir_cron`'s own class body, so no cast to that
        # concrete class resolves it either (confirmed directly); `Any` is
        # the honest type for a value only reachable through Odoo's own
        # registry-level delegation, invisible to pyright the same way
        # `_inherit`-mixin composition is (`typed.security`'s own docstring).
        return cast("Any", record).model_id.model or "misc"

    @api.model
    def _suggest_xmlid(self, record: BaseModel) -> str | None:
        # `cron_name` is real on `ir_cron`'s own class body, but `name` is the
        # same delegated-through-`ir_actions_server_id` shape as `model_id`
        # above -- cast once, for both, rather than mixing a concrete-class
        # cast for one field and `Any` for the other on the same record.
        rec = cast("Any", record)
        slug = (rec.cron_name or rec.name or str(record.id)).lower()
        return "cron_%s" % "".join(c if c.isalnum() else "_" for c in slug).strip("_")

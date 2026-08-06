# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.cron`` -- a scheduled action.

``ir.cron`` delegates to ``ir.actions.server`` (``delegate=True`` on
``ir_actions_server_id``, ``ir_cron.py:68``), which is why it carries
``studio_package_id`` without anyone adding it: the studio put that field on the
server action. The consequence was that a captured cron looked owned, its server
action serialised, and its *scheduling* -- the half that makes it a cron -- was
dropped with nothing to say so.

Nothing in the studio creates a cron today. It is written now because the hole
is cheap to close and expensive to notice: a scheduled action that silently
loses its interval on reload runs at Odoo's default, not the author's.

Emitted under ``noupdate="1"`` for the same reason as ``ir.sequence``:
``nextcall`` and ``lastcall`` are state, and re-running the data file on an
upgrade would move the schedule.
"""

from odoo import api, models

from ..studio_serializer import SEQ_CRON


class IrCronSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.cron"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.cron"

    _studio_model = "ir.cron"
    _studio_sequence = SEQ_CRON
    _studio_dir = "data"
    _studio_suffix = "_cron"
    _studio_noupdate = True
    _studio_fields = (
        "ir_actions_server_id",
        "active",
        "interval_number",
        "interval_type",
        "nextcall",
        "priority",
        "user_id",
    )
    _studio_ignored = (
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
    def _group_model(self, record):
        return record.model_id.model or "misc"

    @api.model
    def _suggest_xmlid(self, record):
        slug = (record.cron_name or record.name or str(record.id)).lower()
        return "cron_%s" % "".join(c if c.isalnum() else "_" for c in slug).strip("_")

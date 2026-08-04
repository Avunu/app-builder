# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.sequence``.

Listed in the design's coverage from the start and never written, because
nothing generated a sequence until the scaffold did. A numbered document model
is the most ordinary thing a site manager builds, so it needs one.

Emitted under ``noupdate="1"`` deliberately: a sequence carries state --
``number_next_actual`` moves every time a record is created -- and re-running
the data file on a module upgrade would reset the counter and start handing out
references that already exist.
"""

from odoo import api, models

from ..studio_serializer import SEQ_SEQUENCE


class IrSequenceSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.sequence"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.sequence"

    _studio_model = "ir.sequence"
    _studio_sequence = SEQ_SEQUENCE
    _studio_dir = "data"
    _studio_suffix = "_data"
    _studio_noupdate = True
    _studio_fields = (
        "name",
        "code",
        "implementation",
        "prefix",
        "suffix",
        "padding",
        "number_increment",
        "use_date_range",
        "company_id",
        "active",
    )
    _studio_ignored = (
        # The counter itself, and the one place where emitting a real value
        # would be worse than dropping it. It moves every time a record is
        # created, so a package carrying it would report drifted -- and produce
        # a git diff -- on every single save a user makes. Against that, what
        # is lost is the starting number somebody chose once, which they can
        # set again; the running count is state, and state belongs in the
        # database that is running.
        "number_next",
        # Sub-sequences carry a counter each, for the same reason, and Odoo
        # creates them on demand from use_date_range -- which is emitted.
        "date_range_ids",
    )

    @api.model
    def _group_model(self, record):
        # The code is the model name for a scaffolded sequence, which keeps
        # data/<model>_data.xml next to the model it numbers.
        return record.code or "sequences"

    @api.model
    def _should_skip(self, record, fname):
        if fname == "company_id" and not record.company_id:
            # Reflection leaves this empty for a global sequence; emitting a
            # false company ref would tie the package to whichever company
            # happened to exist when it was built.
            return True
        return super()._should_skip(record, fname)

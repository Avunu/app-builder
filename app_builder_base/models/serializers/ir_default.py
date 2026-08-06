# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.default`` -- a field's default value.

The gap this closes was the same shape as the translations one and had the same
consequence: the field editor's *Default value* box writes an ``ir.default``
row, nothing emitted it, and the package reported clean. So the same action was
durable or not depending on which kind of model it landed on -- Python-defined
models carry the default in ``FieldSpec.default`` and survive, XML-defined ones
lost it.

Emitted after the field, because ``field_id`` refs it. Not under
``noupdate="1"``: unlike a sequence, a default carries no state -- it is a
setting, and a module upgrade should bring the current one.
"""

from odoo import api, models

from ..studio_serializer import SEQ_DEFAULT


class IrDefaultSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.default"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.default"

    _studio_model = "ir.default"
    _studio_sequence = SEQ_DEFAULT
    _studio_dir = "data"
    _studio_suffix = "_defaults"
    _studio_fields = (
        "field_id",
        "json_value",
        "condition",
        "user_id",
        "company_id",
    )

    @api.model
    def _group_model(self, record):
        # Beside the field it defaults, not in a file named after the package.
        return record.field_id.model_id.model or "misc"

    @api.model
    def _ownable(self, record):
        # A default scoped to one user is that user's preference, not a
        # customisation of the database -- writing it into an addon would apply
        # somebody's personal setting to everyone who installs it.
        return not record.user_id and super()._ownable(record)

    @api.model
    def _suggest_xmlid(self, record):
        return "default_%s_%s" % (
            (record.field_id.model or "").replace(".", "_"),
            record.field_id.name or record.id,
        )

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.ui.view``."""

from odoo import api, models

from ..studio_serializer import SEQ_VIEW


class IrUiViewSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.ui.view"
    _inherit = ["studio.serializer", "studio.serializer.mixin.arch"]
    _description = "Studio Serializer for ir.ui.view"

    _studio_model = "ir.ui.view"
    _studio_sequence = SEQ_VIEW
    _studio_dir = "views"
    _studio_suffix = "_views"
    # 'arch' comes last so the record reads header-then-body, and because it is
    # the only multi-line field.
    _studio_fields = (
        "name",
        "model",
        "type",
        "inherit_id",
        "mode",
        "priority",
        "key",
        "active",
        "groups_id",
        "arch",
    )

    @api.model
    def _group_model(self, record):
        # Views inheriting a core view group under the *target* model, so an
        # extension of sale.order lands in views/sale_order_views.xml rather
        # than in a file named after the studio package.
        return record.model or "misc"

    @api.model
    def _should_skip(self, record, fname):
        if fname == "arch":
            return False
        if fname == "mode":
            # 'primary' is the default and only meaningful alongside inherit_id.
            return not record.inherit_id or record.mode == "extension"
        if fname == "type":
            # Odoo infers type from the arch root tag on create; emitting it
            # would be redundant and can conflict after an arch edit.
            return True
        if fname == "key" and record.type != "qweb":
            return True
        if fname == "active":
            # 'active' defaults True; only emit when the view is archived.
            return bool(record.active)
        return super()._should_skip(record, fname)

    @api.model
    def _field_node(self, record, fname):
        if fname == "arch":
            return self._arch_node(record.arch)
        return super()._field_node(record, fname)

    @api.model
    def _sort_key(self, record, xmlid):
        # Base views must precede the views that inherit them, otherwise the
        # ref() in inherit_id resolves against a record that does not exist yet.
        return (self._studio_sequence, bool(record.inherit_id), xmlid)

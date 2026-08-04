# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.ui.view``."""

from lxml import etree

from odoo import _, api, models
from odoo.exceptions import UserError

from ...tools import xml_writer
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
        "customize_show",
        "groups_id",
        "arch",
    )
    _studio_ignored = (
        # The arch is emitted through the `arch` API field. These are its
        # storage and bookkeeping: arch_db holds the value arch computes from,
        # arch_fs the path when it came from a file, arch_prev the undo buffer,
        # arch_updated whether the DB copy has diverged from disk. Emitting any
        # of them would write the same content twice, in the wrong direction.
        "arch_db",
        "arch_fs",
        "arch_prev",
        "arch_updated",
        # The other end of inherit_id, which each inheriting view emits itself.
        "inherit_children_ids",
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
            return self._type_is_inferable(record)
        if fname == "active":
            # 'active' defaults True; only emit when the view is archived.
            return bool(record.active)
        return super()._should_skip(record, fname)

    @api.model
    def _type_is_inferable(self, record):
        """Whether ``create`` would land on this exact type without being told.

        It infers one only when the value is absent, and only from
        ``inherit_id.type`` or the arch's **root tag** -- raising *"Invalid view
        type"* outright when that tag is not a view type
        (``ir_ui_view.py:498-507``).

        For a form or a list the tag and the type agree, so the field is noise.
        For a qweb template the root is ``<t>`` or ``<data>`` and omitting the
        field does not produce a redundant record, it produces one that fails to
        load. Odoo's own data files get away with it because ``convert.py``
        injects the type for ``<template>``; this serializer emits ``<record>``
        and gets no such help.

        Note this is the one shape of mistake the completeness guard cannot
        see: ``type`` is in ``_studio_fields``, so it counts as accounted for,
        while ``_should_skip`` quietly wrote nothing.
        """
        if record.inherit_id:
            return record.type == record.inherit_id.type
        try:
            root = xml_writer.parse_arch(record.arch)
        except (etree.XMLSyntaxError, ValueError, TypeError):
            # Unparseable arch: emit the type rather than gamble on inference.
            return False
        return record.type == root.tag

    @api.model
    def _field_node(self, record, fname):
        if fname == "arch":
            node = self._arch_node(record.arch)
            self._portable_action_buttons(node)
            return node
        return super()._field_node(record, fname)

    @api.model
    def _concrete_action(self, action_id):
        """The action as its own model, not as ``ir.actions.actions``.

        ``ir.actions.actions`` is the shared table, and an xmlid is registered
        against the *concrete* model -- ``ir.model.data`` says
        ``ir.actions.server``, never ``ir.actions.actions``. Browsing the base
        model therefore finds the record and then reports it has no external ID,
        which is both wrong and hard to read as a message. ``type`` is Odoo's own
        discriminator and names the model to browse instead.
        """
        base = self.env["ir.actions.actions"].browse(action_id).exists()
        if not base:
            return base
        return self.env[base.type].browse(base.id) if base.type in self.env else base

    @api.model
    def _portable_action_buttons(self, node):
        """Turn ``<button type="action" name="42">`` into the action's xmlid.

        A raw primary key in an arch is the same mistake the emitter refuses
        everywhere else, hiding somewhere the field-level rules never look: the
        arch is one opaque string to them.

        The builder writes the xmlid in the first place, so this is for arches
        that arrived another way -- a hand-written view, or one from a database
        where ``convert.py:107`` resolved a data file's ``%(xmlid)d`` into an
        integer on the way in. Odoo's validator accepts either spelling
        (``ir_ui_view.py:3089-3096``), and only one of them still means the same
        action after a fresh install.
        """
        for button in node.iter("button"):
            if button.get("type") != "action":
                continue
            name = (button.get("name") or "").strip()
            if not name.isdigit():
                continue  # already an xmlid, which is what we want
            action = self._concrete_action(int(name))
            if not action:
                raise UserError(
                    _(
                        "A button in %(model)s runs action #%(res_id)s, which no "
                        "longer exists.",
                        model=self._studio_model,
                        res_id=name,
                    )
                )
            # Deliberately the fully-qualified xmlid rather than the shortened
            # same-module form `_ref_of` produces: an arch is read by Odoo's own
            # validator, which has no notion of "the module this file belongs
            # to" and resolves the string exactly as written.
            xmlid = self._xmlid_of(action)
            if not xmlid:
                raise UserError(
                    _(
                        "A button in %(model)s runs %(action)s, which has no "
                        "external ID and so cannot be named portably.",
                        model=self._studio_model,
                        action=action.display_name,
                    )
                )
            button.set("name", xmlid)
        return node

    @api.model
    def _sort_key(self, record, xmlid):
        # Base views must precede the views that inherit them, otherwise the
        # ref() in inherit_id resolves against a record that does not exist yet.
        return (self._studio_sequence, bool(record.inherit_id), xmlid)

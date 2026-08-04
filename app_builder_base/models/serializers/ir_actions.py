# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for the ``ir.actions.*`` family."""

from lxml import etree

from odoo import api, models

from ..studio_serializer import (
    SEQ_ACT_WINDOW,
    SEQ_ACT_WINDOW_VIEW,
    SEQ_REPORT,
    SEQ_SERVER_ACTION,
)


class IrActionsActWindowSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.actions.act_window"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.actions.act_window"

    _studio_model = "ir.actions.act_window"
    _studio_sequence = SEQ_ACT_WINDOW
    _studio_dir = "views"
    _studio_suffix = "_views"
    _studio_fields = (
        "name",
        "res_model",
        "view_mode",
        "mobile_view_mode",
        "domain",
        "context",
        "target",
        # view_id pins the action to a specific view and groups_id restricts who
        # sees it; omitting either silently dropped a real user choice.
        "view_id",
        "groups_id",
        "search_view_id",
        "res_id",
        "filter",
        "usage",
        "path",
        "binding_model_id",
        "binding_type",
        "binding_view_types",
        "limit",
        "help",
    )
    _studio_ignored = (
        # The discriminator. It is fixed by <record model="..."> on load, so
        # emitting it says nothing the record does not already say.
        "type",
        # The other end of ir.actions.act_window.view, which has a serializer
        # of its own; emitting both would define each link twice.
        "view_ids",
    )

    @api.model
    def _group_model(self, record):
        return record.res_model

    @api.model
    def _field_node(self, record, fname):
        """``res_id`` is a raw primary key, and has to leave as an xmlid.

        It is a plain Integer rather than a reference field, so nothing in the
        generic emitter knows it points at a record -- it would have gone into
        the file as a bare number that means a different record, or nothing at
        all, in the next database. The model it belongs to is right there in
        ``res_model``, which is what makes it recoverable.
        """
        if fname == "res_id" and record.res_id:
            node = etree.Element("field")
            node.set("name", fname)
            node.set(
                "eval",
                "ref(%r)"
                % self._reference_xmlid(record, fname, comodel=record.res_model),
            )
            return node
        return super()._field_node(record, fname)


class IrActionsActWindowViewSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.actions.act_window.view"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.actions.act_window.view"

    _studio_model = "ir.actions.act_window.view"
    _studio_sequence = SEQ_ACT_WINDOW_VIEW
    _studio_dir = "views"
    _studio_suffix = "_views"
    _studio_fields = ("act_window_id", "view_id", "view_mode", "sequence", "multi")

    @api.model
    def _group_model(self, record):
        return record.act_window_id.res_model

    @api.model
    def _sort_key(self, record, xmlid):
        return (self._studio_sequence, record.sequence, xmlid)


class IrActionsServerSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.actions.server"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.actions.server"

    _studio_model = "ir.actions.server"
    _studio_sequence = SEQ_SERVER_ACTION
    _studio_dir = "data"
    _studio_suffix = "_automation"
    # Grouped by the ``state`` each block configures, because that is how the
    # form reads and because the omissions that made this serializer lossy were
    # all whole blocks: an action could say state='webhook' and carry no URL.
    _studio_fields = (
        "name",
        "model_id",
        "usage",
        "state",
        "sequence",
        # Execute Code
        "code",
        # Multi Actions
        "child_ids",
        # Create / Duplicate Record
        "crud_model_id",
        "link_field_id",
        # Update Record
        "update_path",
        "update_field_id",
        "update_related_model_id",
        "update_m2m_operation",
        "update_boolean_value",
        "evaluation_type",
        "value",
        "selection_value",
        "resource_ref",
        # Send Webhook Notification
        "webhook_url",
        "webhook_field_ids",
        # presentation and bindings
        "path",
        "groups_id",
        "binding_model_id",
        "binding_type",
        "binding_view_types",
        "help",
    )
    _studio_ignored = (
        # The discriminator, fixed by <record model="..."> on load.
        "type",
        # related to model_id.model, which is emitted.
        "model_name",
        # The other end of base.automation.action_server_ids. The automation
        # owns the link and emits it; writing it from both ends would make the
        # load order significant for no reason.
        "base_automation_id",
    )

    @api.model
    def _group_model(self, record):
        return record.model_id.model


class IrActionsReportSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.actions.report"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.actions.report"

    _studio_model = "ir.actions.report"
    _studio_sequence = SEQ_REPORT
    _studio_dir = "report"
    _studio_suffix = "_reports"
    _studio_fields = (
        "name",
        "model",
        "report_type",
        "report_name",
        "report_file",
        "print_report_name",
        "paperformat_id",
        "attachment",
        "attachment_use",
        "domain",
        "multi",
        "path",
        "groups_id",
        "binding_model_id",
        "binding_type",
        "binding_view_types",
        "help",
    )
    _studio_ignored = (
        # The discriminator, fixed by <record model="..."> on load.
        "type",
    )

    @api.model
    def _group_model(self, record):
        return record.model

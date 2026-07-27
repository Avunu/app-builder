# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for the ``ir.actions.*`` family."""

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
        "domain",
        "context",
        "target",
        # view_id pins the action to a specific view and groups_id restricts who
        # sees it; omitting either silently dropped a real user choice.
        "view_id",
        "groups_id",
        "search_view_id",
        "binding_model_id",
        "binding_type",
        "binding_view_types",
        "limit",
        "help",
    )

    @api.model
    def _group_model(self, record):
        return record.res_model


class IrActionsActWindowViewSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.actions.act_window.view"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.actions.act_window.view"

    _studio_model = "ir.actions.act_window.view"
    _studio_sequence = SEQ_ACT_WINDOW_VIEW
    _studio_dir = "views"
    _studio_suffix = "_views"
    _studio_fields = ("act_window_id", "view_id", "view_mode", "sequence")

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
    _studio_fields = (
        "name",
        "model_id",
        "state",
        "sequence",
        "code",
        "child_ids",
        "crud_model_id",
        "link_field_id",
        "update_path",
        "update_field_id",
        "update_m2m_operation",
        "update_boolean_value",
        "value",
        "groups_id",
        "binding_model_id",
        "binding_type",
        "binding_view_types",
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
        "binding_model_id",
        "binding_type",
    )

    @api.model
    def _group_model(self, record):
        return record.model

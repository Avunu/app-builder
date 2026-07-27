# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.ui.menu``."""

from lxml import etree

from odoo import api, models

from ..studio_serializer import SEQ_MENU


class IrUiMenuSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.ui.menu"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.ui.menu"

    _studio_model = "ir.ui.menu"
    _studio_sequence = SEQ_MENU
    _studio_dir = "views"
    _studio_suffix = "_views"
    _studio_fields = (
        "name",
        "parent_id",
        "action",
        "sequence",
        "groups_id",
        "web_icon",
    )

    @api.model
    def _group_model(self, record):
        """Group a menu with the model its action opens.

        A menu with no action is a container (an app root or a submenu header)
        and has no model of its own, so it goes to views/menus.xml.
        """
        action = record.action
        if action and action._name == "ir.actions.act_window":
            return action.res_model
        if action and hasattr(action, "model_id") and action.model_id:
            return action.model_id.model
        return "menus"

    @api.model
    def _target_file(self, record):
        """All menus in one file.

        `_sort_key` puts parents before children, but that only orders records
        *within* a file. Grouping menus by the model their action opens scatters
        a menu tree across several files, and the manifest then loads a child
        before its parent -- an unresolvable ``parent_id`` ref on a fresh
        install. One file keeps the ordering guarantee meaningful.

        studio.package._order_data_files gives this file a rank just after the
        other views, because a menu refs an action those files define.
        """
        return "views/menus.xml"

    @api.model
    def _field_node(self, record, fname):
        if fname == "action":
            # 'action' is a reference field storing 'model,id'. Emit it as a
            # plain ref to the action's xmlid, which is what convert.py expects
            # and what a hand-written menuitem produces.
            action = record.action
            if not action:
                return None
            node = etree.Element("field")
            node.set("name", "action")
            node.set("ref", self._ref_of(action, source=self._studio_model))
            return node
        return super()._field_node(record, fname)

    @api.model
    def _sort_key(self, record, xmlid):
        # Parents before children: a child's parent_id ref must already resolve.
        depth = 0
        node = record.parent_id
        while node and depth < 32:
            depth += 1
            node = node.parent_id
        return (self._studio_sequence, depth, record.sequence, xmlid)

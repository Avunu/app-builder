# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for the ``ir.actions.*`` family."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias, cast

if TYPE_CHECKING:
    # Only used inside annotations/casts below (`from __future__ import
    # annotations` defers all of them to strings), never at runtime -- same
    # bargain every other Phase 1c file's `TYPE_CHECKING` block makes.
    from collections.abc import Callable

    from odoo.models import BaseModel

    # Core Odoo, reached only through the merged odoo-nix tree -- the
    # fully-qualified `odoo.addons....` form is correct here, not same-addon
    # (TYPING.md's "Known traps"/house conventions), the same as
    # `studio_package.py`'s own `IrModel` import and `ir_model.py`'s own
    # `IrModel`/`IrModelFields`/`IrModelSelection` imports.
    from odoo.addons.base.models.ir_actions import (
        IrActionsActWindow,
        IrActionsActWindowView,
        IrActionsServer,
    )
    from odoo.addons.base.models.ir_actions_report import IrActionsReport
    from odoo.addons.base.models.ir_model import IrModel

    # Same-addon cross-file import, so relative (house convention). Only for
    # the `self`/`super()` casts below -- see each one's own comment.
    from ..studio_serializer import StudioSerializer

# lxml ships no type stubs in this environment (a compiled extension with no
# `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an installed
# dependency here), so pyright cannot resolve `etree` as an exported member
# of `lxml` at all -- confirmed directly, `from lxml import etree` alone
# reports both `reportMissingTypeStubs` (on `lxml`) and
# `reportAttributeAccessIssue` ("etree" is unknown import symbol, on
# `etree`). Ignored narrowly on each name rather than rewriting the import
# (e.g. `import lxml.etree as etree`), which trades this gap for a different
# one: ruff's own `PLR0402` auto-fixes that form straight back to `from lxml
# import etree` (`fix = true` project-wide), silently reintroducing the
# failure. Same pattern as `studio_serializer.py`/`xml_writer.py`/
# `placement.py`/`scaffold.py`/`ir_ui_menu.py`.
from lxml import (  # pyright: ignore[reportMissingTypeStubs]
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)

from odoo import api, models

from ...tools.lxml_types import LxmlElement
from ..studio_serializer import (
    SEQ_ACT_WINDOW,
    SEQ_ACT_WINDOW_VIEW,
    SEQ_REPORT,
    SEQ_SERVER_ACTION,
)

Element: TypeAlias = LxmlElement

# `etree.Element` is the one constructor this module calls; grabbing it once,
# behind a single documented cast, keeps the "Unknown member of an unstubbed
# module" gap to two lines instead of a `# pyright: ignore` at the one call
# site. Same idiom as `studio_serializer.py`'s/`ir_ui_menu.py`'s own
# `_element` wrapper.
_element_raw = etree.Element  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_element: Callable[..., Element] = cast("Callable[..., Element]", _element_raw)


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
    def _group_model(self, record: BaseModel) -> str | None:
        # `res_model` (`ir.actions.act_window`) is a required Char, so it is
        # never really the `Literal[False]` half of the field's own
        # `str | Literal[False]` read type -- same reasoning as
        # `ir_model.py`'s own `IrModelSerializer._group_model`. `record` is
        # genuinely an `ir.actions.act_window` recordset here (this
        # serializer is only ever dispatched for that model), but the
        # overridden method's own declared parameter type is `BaseModel` --
        # house convention: cast at the read site instead of narrowing the
        # signature.
        return cast("str", cast("IrActionsActWindow", record).res_model)

    @api.model
    def _field_node(self, record: BaseModel, fname: str) -> Element | None:
        """``res_id`` is a raw primary key, and has to leave as an xmlid.

        It is a plain Integer rather than a reference field, so nothing in the
        generic emitter knows it points at a record -- it would have gone into
        the file as a bare number that means a different record, or nothing at
        all, in the next database. The model it belongs to is right there in
        ``res_model``, which is what makes it recoverable.
        """
        # Same cast-at-the-read-site reasoning as `_group_model` above.
        action = cast("IrActionsActWindow", record)
        if fname == "res_id" and action.res_id:
            node = _element("field")
            node.set("name", fname)
            # `_reference_xmlid` lives on `StudioSerializer`, composed onto
            # this class only at the Odoo registry level
            # (`_inherit = "studio.serializer"` above) -- never a real Python
            # base class, so it is invisible to pyright on `self` here. Same
            # "_inherit-mixin-invisible-to-pyright" shape `typed.security()`
            # already fixes for `studio.security.mixin`; no shared helper
            # exists for this mixin, so cast inline instead, the same as
            # `ir_ui_menu.py`'s own `cast("StudioSerializer", self)._ref_of`.
            node.set(
                "eval",
                "ref(%r)"
                % cast("StudioSerializer", self)._reference_xmlid(
                    record, fname, comodel=cast("str", action.res_model)
                ),
            )
            return node
        # Same mixin-invisibility as above, on the `super()` proxy this time
        # rather than on `self` -- `cast` only changes what pyright believes
        # the proxy's type is, not the proxy object itself, so the dispatch
        # this performs at runtime (up through the *real*, registry-composed
        # MRO, landing on `StudioSerializer._field_node`) is exactly what the
        # original, untyped call already did. Same idiom as `ir_model.py`'s
        # own `cast("StudioSerializer", super())._should_skip(...)`.
        return cast("StudioSerializer", super())._field_node(record, fname)


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
    def _group_model(self, record: BaseModel) -> str | None:
        view = cast("IrActionsActWindowView", record)
        # `act_window_id` (`ir.actions.act_window.view`) is a plain-string-
        # comodel Many2one in core (no typed-relation syntax there), so
        # pyright cannot resolve its element type from the declaration alone
        # -- the same gap `ir_model.py`'s/`ir_ui_menu.py`'s own `model_id`/
        # `parent_id` reads already hit and fix the same way. Unlike
        # `res_model`/`model` elsewhere in this file, `act_window_id` carries
        # no `required=True` in core, so it is genuinely optional here and
        # the outer cast stays `str | None` rather than being narrowed to
        # `str`.
        act_window = cast(
            "IrActionsActWindow",
            view.act_window_id,  # pyright: ignore[reportUnknownMemberType]
        )
        return cast("str | None", act_window.res_model)

    @api.model
    def _sort_key(self, record: BaseModel, xmlid: str) -> tuple[int, int, str]:
        # A wider tuple than the base's own declared `tuple[int, str]` --
        # real and intentional (several views on the same action must sort by
        # their own `sequence` too, not only by xmlid), the same shape
        # already flagged in `ir_model.py`'s own
        # `IrModelFieldsSelectionSerializer._sort_key` and `ir_ui_menu.py`'s
        # own `IrUiMenuSerializer._sort_key`. Not silently squeezed back to
        # two elements, which would either drop a real sort key or lie about
        # the type.
        return (
            self._studio_sequence,
            cast("IrActionsActWindowView", record).sequence,
            xmlid,
        )


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
    def _group_model(self, record: BaseModel) -> str | None:
        action = cast("IrActionsServer", record)
        # `model_id` (`ir.actions.server`) is a plain-string-comodel Many2one
        # -- same gap as `IrActionsActWindowViewSerializer._group_model`
        # above, but `model_id` here *is* `required=True` in core.
        model = cast(
            "IrModel",
            action.model_id,  # pyright: ignore[reportUnknownMemberType]
        )
        # `ir.model.model` is itself a required Char -- same reasoning as
        # `IrActionsActWindowSerializer._group_model` above and
        # `ir_model.py`'s own `IrModelSerializer._group_model`.
        return cast("str", model.model)


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
    def _group_model(self, record: BaseModel) -> str | None:
        # `model` (`ir.actions.report`) is a required Char -- same reasoning
        # as `IrActionsActWindowSerializer._group_model` above.
        return cast("str", cast("IrActionsReport", record).model)

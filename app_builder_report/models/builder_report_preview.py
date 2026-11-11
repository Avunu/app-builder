# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rendering a report so it can be clicked, and resolving what was clicked.

A report is a template, not a view type. The web client lays out a form or a
list from an arch; it has no renderer for qweb, so the editor's preview pane
cannot mount one. What it can show is the report's *output*, rendered to HTML
here and handed over as markup.

**How a click finds its way back to the arch.** Not through
``data-oe-xpath``: that is stamped by ``inherit_branding`` during inheritance
combination (``ir_ui_view.py:775``) and describes which view contributed a spec,
and node-level branding of rendered output is a ``website`` feature that
community's base does not have. What base does have is field branding --
``ir_qweb_fields.attributes`` (``ir_qweb_fields.py:101``) stamps
``data-oe-expression`` on every ``t-field`` when ``inherit_branding`` is on --
and for a report that is the better anchor anyway: it names the qweb expression,
which is the thing the arch also names.

**Not through ir.actions.report.** ``_render_template`` forces
``inherit_branding=False`` (``ir_actions_report.py:765``), so a report rendered
the ordinary way comes back with no branding at all whatever context it is given.
The template is rendered directly through ``ir.qweb`` instead, with the same
``docs`` the report would have passed.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypedDict, cast

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
# failure. Same pattern as `builder_serializer.py`/`xml_writer.py`/
# `placement.py`/`scaffold.py`/`ir_ui_menu.py`.
from lxml import (  # pyright: ignore[reportMissingTypeStubs]
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)
from typing_extensions import NotRequired

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_base.tools.i18n import _
from odoo.addons.app_builder_view.models.builder_view_editor import BuilderViewEditor
from odoo.addons.base.models.ir_actions_report import IrActionsReport
from odoo.addons.base.models.ir_config_parameter import IrConfigParameter
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_qweb import IrQWeb
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.base.models.res_users import Users

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from datetime import datetime

    from odoo.fields import Field
    from odoo.models import BaseModel

    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement


class PreviewHtmlJSON(TypedDict):
    """``preview_html()``'s return: the report's rendered HTML, or nothing
    to render it on yet (``res_id`` present only on the render branch)."""

    html: str
    reason: str | Literal[False]
    model: str | Literal[False]
    res_id: NotRequired[int]


class PrintableFieldJSON(TypedDict):
    """One entry of ``printable_fields()``'s ``values`` -- a plain
    ``t-field``."""

    name: str
    string: str
    type: str


class PrintableColumnJSON(TypedDict):
    """One entry of a ``PrintableListJSON``'s ``columns``."""

    name: str
    string: str


class PrintableListJSON(PrintableFieldJSON):
    """One entry of ``printable_fields()``'s ``lists`` -- a table, printing
    through its own sub-model's columns."""

    columns: list[PrintableColumnJSON]


class PrintableFieldsJSON(TypedDict):
    """``printable_fields()``'s return: what a report can print, split by
    how it prints it."""

    values: list[PrintableFieldJSON]
    lists: list[PrintableListJSON]


class _LocateExpressionFoundJSON(TypedDict):
    found: Literal[True]
    xpath: str
    expression: str
    tag: str


class _LocateExpressionNotFoundJSON(TypedDict):
    found: Literal[False]
    reason: str


#: ``locate_expression()``'s own answer shape: the locator, or why nothing
#: was found.
LocateExpressionJSON: TypeAlias = (
    _LocateExpressionFoundJSON | _LocateExpressionNotFoundJSON
)


class _BodyAnchorFoundJSON(TypedDict):
    found: Literal[True]
    xpath: str
    position: Literal["inside"]


class _BodyAnchorNotFoundJSON(TypedDict):
    found: Literal[False]
    reason: str


#: ``body_anchor()``'s own answer shape: always ``"inside"``, the one
#: position every one of its three tried expressions answers with.
BodyAnchorJSON: TypeAlias = _BodyAnchorFoundJSON | _BodyAnchorNotFoundJSON


class BuilderReportPreview(models.AbstractModel):
    _inherit = "builder.report"

    @api.model
    def _preview_record(self, model_name: str) -> BaseModel | None:
        """Something real to render, because a report of nothing shows nothing.

        The most recently created record: a report is about the shape of the
        document, and the newest record is the one the builder most likely just
        made while trying this out.
        """
        if model_name not in self.env:
            return None
        model = self.env[model_name]
        return model.search([], order="id desc", limit=1) or None

    @api.model
    def preview_html(self, view_id: int) -> PreviewHtmlJSON:
        """The report's own output, branded so its fields can be clicked."""
        typed.security(self)._assert_builder_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view or view.type != "qweb":
            raise UserError(_("That is not a report template."))
        report = typed.model(self.env, IrActionsReport).search(
            [("report_name", "=", view.key)], limit=1
        )
        model_name = report.model or view.model
        record = self._preview_record(model_name) if model_name else None
        if record is None:
            return {
                "html": "",
                "model": model_name,
                "reason": _(
                    "There is no %s to preview this on yet. Create one and the "
                    "report will draw it.",
                    typed.model(self.env, IrModel)._get(model_name).name
                    if model_name
                    else _("record"),
                ),
            }
        qweb = typed.model(self.env, IrQWeb).with_context(inherit_branding=True)
        # The same names a printed report gets (`ir.actions.report
        # ._render_template`): the internal layout stamps the time with
        # `context_timestamp`, the external one reads `res_company`.
        user = typed.model(self.env, Users).browse(self.env.uid)

        def context_timestamp(t: datetime) -> datetime:
            return fields.Datetime.context_timestamp(
                # `tz` reaches `res.users` only through its own
                # `_inherits = {'res.partner': 'partner_id'}` (delegation,
                # not `_inherit` composition) -- never a real attribute of
                # `Users`'s own class body, so no cast to that concrete
                # class resolves it either. `Any` is the honest type for a
                # value only reachable through Odoo's registry-level
                # delegation (`TYPING.md`'s own `ir.cron.model_id` note).
                self.with_context(tz=cast("Any", user).tz),
                t,
            )

        html = qweb._render(
            view.id,
            {
                "docs": record,
                "doc_ids": record.ids,
                "doc_model": model_name,
                "env": self.env,
                "time": time,
                "context_timestamp": context_timestamp,
                "user": user,
                "res_company": self.env.company,
                "web_base_url": typed.model(self.env, IrConfigParameter)
                .sudo()
                .get_param("web.base.url", default=""),  # pyright: ignore[reportArgumentType]
                # `get_param`'s own `default` parameter carries no annotation,
                # only a bare `False` default, so pyright infers `bool` and
                # rejects the real `str` default every other caller passes --
                # the same inferred-from-literal-default vendor-stub gap
                # TYPING.md's own "Known traps" documents for
                # `Selection.__init__`.
            },
        )
        return {
            "html": str(html),
            "reason": False,
            "res_id": cast("int", record.id),
            # The client needs this and cannot read it off the view: a report
            # template leaves `model` empty on purpose, or every
            # `<template inherit_id=...>` written against it is silently dropped.
            "model": model_name,
        }

    @api.model
    def printable_fields(self, model_name: str) -> PrintableFieldsJSON:
        """What a report can print, split by how it prints it.

        `values` are placed as a `t-field` span; `lists` become a table. The
        split is the same one `add_report_field` refuses on, said before the
        refusal rather than after it.
        """
        typed.security(self)._assert_builder_user()
        if model_name not in self.env:
            return {"values": [], "lists": []}
        values: list[PrintableFieldJSON] = []
        lists: list[PrintableListJSON] = []
        model_fields = cast("dict[str, Field[Any]]", self.env[model_name]._fields)
        for name, field in sorted(model_fields.items()):
            if not field.store and not field.related:
                continue
            entry: dict[str, object] = {
                "name": name,
                "string": field.string or name,
                "type": field.type,
            }
            if field.type in ("one2many", "many2many"):
                entry["columns"] = [
                    {"name": sub, "string": sf.string or sub}
                    for sub, sf in sorted(
                        # `comodel_name` is `str | None` on the base
                        # descriptor, but every field reaching this branch is
                        # one2many/many2many, which always carries a real
                        # comodel -- true by construction, the same idiom
                        # `builder_domain.py`'s own `fields_for` already casts
                        # for the identical field.
                        cast(
                            "dict[str, Field[Any]]",
                            self.env[cast("str", field.comodel_name)]._fields,
                        ).items()
                    )
                    if sf.store and sf.type not in ("one2many", "many2many", "binary")
                ]
                lists.append(cast("PrintableListJSON", entry))
            elif field.type != "binary":
                values.append(cast("PrintableFieldJSON", entry))
        return {"values": values, "lists": lists}

    @api.model
    def locate_expression(self, view_id: int, expression: str) -> LocateExpressionJSON:
        """The arch node printing ``expression``, as a locator.

        The click carries `data-oe-expression` -- `doc.x_budget` -- and the arch
        carries the same string in a `t-field`. Resolution stays server-side for
        the same reason every other locator does: the rendered document a
        reader sees is theirs, shaped by their language, their company's layout
        and what they are allowed to read.
        """
        typed.security(self)._assert_builder_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The report template no longer exists."))
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        matches = [n for n in root.iter() if n.get("t-field") == expression]
        if not matches:
            return {
                "found": False,
                "reason": _(
                    "%s is printed by something the builder cannot point at — "
                    "a sub-template, or an expression built at render time.",
                    expression,
                ),
            }
        editor = typed.model(self.env, BuilderViewEditor)
        return {
            "found": True,
            "xpath": editor._locator_for(matches[0], editor._occurrences(root)),
            "expression": expression,
            "tag": matches[0].tag,
        }

    @api.model
    def body_anchor(self, view_id: int) -> BodyAnchorJSON:
        """Where a new element goes when nothing was clicked.

        Every layout this builder scaffolds puts the document body in
        ``div.page``, and so does every core report -- it is the convention
        `l10n_*` modules anchor on. Falling back to the loop keeps a
        hand-written template addressable.
        """
        typed.security(self)._assert_builder_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The report template no longer exists."))
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        for expr in (
            "//div[hasclass('page')]",
            "//t[@t-foreach='docs']",
            "//t[@t-call='web.html_container']",
        ):
            if root.xpath(expr.replace("hasclass('page')", "contains(@class,'page')")):
                return {"found": True, "xpath": expr, "position": "inside"}
        return {
            "found": False,
            "reason": _(
                "This template has no recognisable body to add to. Edit it as "
                "source, or start from a layout the builder generated."
            ),
        }

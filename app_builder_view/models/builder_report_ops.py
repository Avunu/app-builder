# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
# pylint: disable=consider-merging-classes-inherited
"""Report-shaped edits, emitted as xpath into an inheriting view.

The report editor is the *same* editor: a report template is an ir.ui.view of
type qweb, so `apply_operation` already routes an edit to an inheriting view and
already mints locators server-side. What qweb needs that a form does not is
operations that speak its vocabulary -- `t-field` rather than `<field>`, and
`t-foreach` rather than a one2many widget.

Deliberately server-side, like every other locator in this project. A report is
the one place a rich-text editor is most tempting and least safe: what the
browser holds is rendered output, and an xpath derived from rendered output
points at whatever that user's language, company layout and access rights
happened to produce.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

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

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools.i18n import _

if TYPE_CHECKING:
    from odoo.fields import Field

    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement

    # `builder_view_editor.py`'s own module also declares a class named
    # `BuilderViewEditor` (the SAME "builder.view.editor" `_name`, merged into
    # one real model by the registry, but two separate classes as far as
    # pyright is concerned) -- aliased on import so this file's own `class
    # BuilderViewEditor` below does not collide with it. `_new_xpath` is
    # declared only on that real base, invisible on a bare `self` here
    # (TYPING.md's own `_inherit`-invisibility gap); a plain `cast()` target
    # needs no runtime binding, so this stays `TYPE_CHECKING`-only rather
    # than a real top-level import, the same fix shape as
    # `builder_report_surface.py`'s own `BuilderReport`/`BuilderReportBase`.
    from .builder_view_editor import BuilderViewEditor as BuilderViewEditorBase

# Fields that cannot be printed as a bare span: a binary is not text, and a
# relation needs a sub-expression naming which of its fields to show.
UNPRINTABLE = {
    "binary": "an image or a file needs an <img> or a widget, not a text span",
    "one2many": "a list of records is a table -- use Add table instead",
    "many2many": "a list of records is a table -- use Add table instead",
}


class BuilderViewEditor(models.AbstractModel):
    _inherit = "builder.view.editor"

    @api.model
    def _report_field_expression(
        self, model_name: str, name: str, loop_var: str = "doc"
    ) -> str:
        """``doc.partner_id.name`` for a many2one, ``doc.x`` otherwise.

        A many2one rendered bare prints the record's display name via
        `t-field`, which is right often enough that Odoo does it -- but naming
        the field explicitly is what makes the generated source say what it
        prints.
        """
        model = self.env[model_name]
        field = cast("dict[str, Field[Any]]", model._fields).get(name)
        if field is None:
            raise UserError(
                _("%(model)s has no field %(name)s.", model=model_name, name=name)
            )
        if field.type in UNPRINTABLE:
            raise UserError(
                _(
                    "%(label)s cannot be placed as text: %(why)s.",
                    label=field.string or name,
                    why=UNPRINTABLE[field.type],
                )
            )
        return "%s.%s" % (loop_var, name)

    @api.model
    def _already_prints(self, arch: str | None, expression: str) -> bool:
        """Whether ``arch`` already has a span for this expression.

        Only consulted for a view the package owns outright, where each edit is
        applied to the arch itself rather than accumulated in a spec -- so the
        spec-level dedup below cannot see what the previous click did.
        """
        if not arch:
            return False
        try:
            root = cast("LxmlElement", etree.fromstring(arch.encode()))
        except etree.XMLSyntaxError:  # pragma: no cover - _check_xml guards this
            return False
        return any(node.get("t-field") == expression for node in root.iter())

    def _op_add_report_field(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement | None:
        """A `t-field` span, optionally with a label beside it.

        Idempotent on (anchor, field) for the same reason `_op_add_field` is: a
        double-click must not print the value twice.
        """
        name = cast("str | None", operation.get("name"))
        model_name = cast("str | None", operation.get("model"))
        if not name or not model_name:
            raise UserError(_("Placing a field requires a model and a field name."))
        expression = self._report_field_expression(
            model_name, name, cast("str", operation.get("loop_var") or "doc")
        )
        position = cast("str", operation.get("position", "inside"))
        expr = cast("str", operation["xpath"])

        # On a view the package owns, each edit is merged into the arch itself
        # and the spec below starts empty every time, so it cannot see what the
        # previous click did. apply_operation hands us the arch for this.
        if self._already_prints(
            cast("str | None", operation.get("_current_arch")), expression
        ):
            return None

        node = None
        for candidate in root.findall("xpath"):
            if candidate.get("expr") == expr and candidate.get("position") == position:
                if any(
                    span.get("t-field") == expression for span in candidate.iter("span")
                ):
                    return candidate
                node = candidate
                break
        if node is None:
            node = cast("BuilderViewEditorBase", self)._new_xpath(root, expr, position)

        label = cast("str | None", operation.get("label"))
        host = node
        if label:
            # A labelled value is one unit: wrapping them means a later edit
            # moves or hides both, which is what somebody means by "the
            # customer reference line".
            host = cast("LxmlElement", etree.SubElement(node, "div", {"class": "mb-2"}))
            strong = cast("LxmlElement", etree.SubElement(host, "strong"))
            strong.text = label
            strong.tail = " "
        etree.SubElement(host, "span", {"t-field": expression})
        return node

    def _op_add_report_table(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """A `t-foreach` table over a one2many, with chosen columns.

        The second most common report edit after placing a field, and the one
        hand-editing gets wrong most often: the loop variable has to be named,
        the header and the body have to agree on column order, and the totals
        row is a different expression from the cells.
        """
        name = cast("str | None", operation.get("name"))
        model_name = cast("str | None", operation.get("model"))
        columns = cast("list[str] | None", operation.get("columns")) or []
        if not name or not model_name:
            raise UserError(_("A table needs a model and a one2many field."))
        field = cast("dict[str, Field[Any]]", self.env[model_name]._fields).get(name)
        if field is None or field.type not in ("one2many", "many2many"):
            raise UserError(
                _("%s is not a list of records, so it cannot be a table.", name)
            )
        if not columns:
            raise UserError(_("Choose at least one column for the table."))

        child = self.env[cast("str", field.comodel_name)]
        unknown = [c for c in columns if c not in child._fields]
        if unknown:
            raise UserError(
                _(
                    "%(model)s has no field %(name)s.",
                    model=field.comodel_name,
                    name=", ".join(unknown),
                )
            )

        expr = cast("str", operation["xpath"])
        position = cast("str", operation.get("position", "inside"))
        node = cast("BuilderViewEditorBase", self)._new_xpath(root, expr, position)
        loop_var = cast("str", operation.get("loop_var") or "line")

        table = cast(
            "LxmlElement", etree.SubElement(node, "table", {"class": "table table-sm"})
        )
        thead = cast("LxmlElement", etree.SubElement(table, "thead"))
        head = cast("LxmlElement", etree.SubElement(thead, "tr"))
        for column in columns:
            cell = cast("LxmlElement", etree.SubElement(head, "th"))
            cell.text = child._fields[column].string or column
        body = cast("LxmlElement", etree.SubElement(table, "tbody"))
        row = cast(
            "LxmlElement",
            etree.SubElement(
                body,
                "tr",
                {
                    "t-foreach": "%s.%s"
                    % (cast("str", operation.get("parent_var") or "doc"), name),
                    "t-as": loop_var,
                },
            ),
        )
        for column in columns:
            cell = cast("LxmlElement", etree.SubElement(row, "td"))
            etree.SubElement(cell, "span", {"t-field": "%s.%s" % (loop_var, column)})
        return node

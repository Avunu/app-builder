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

And deliberately a *sequence*, like every other edit of somebody else's view:
each operation appends one spec, evaluated on the tree the specs before it
left behind, and "is it already there?" is asked of that tree
(``_beside_anchor``), never of the spec. Removal, moving and attributes are
the view editor's own operations and need nothing report-specific.
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

from .builder_view_editor import INSERT_POSITIONS

if TYPE_CHECKING:
    from odoo.fields import Field

    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement

    # `builder_view_editor.py`'s own module also declares a class named
    # `BuilderViewEditor` (the SAME "builder.view.editor" `_name`, merged into
    # one real model by the registry, but two separate classes as far as
    # pyright is concerned) -- aliased on import so this file's own `class
    # BuilderViewEditor` below does not collide with it. `_new_xpath` and
    # `_beside_anchor` are declared only on that real base, invisible on a
    # bare `self` here (TYPING.md's own `_inherit`-invisibility gap); a plain
    # `cast()` target needs no runtime binding, so this stays
    # `TYPE_CHECKING`-only rather than a real top-level import, the same fix
    # shape as `builder_report_surface.py`'s own `BuilderReport`/
    # `BuilderReportBase`.
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
    def _report_position(self, operation: dict[str, object]) -> str:
        """Where a new value or table goes: before, after or inside.

        ``replace`` would delete the anchor along with placing the value, and
        ``attributes`` is not a place at all. `_new_xpath` accepts both for
        the raw operations, so a report add says no itself.
        """
        position = operation.get("position", "inside")
        if position not in INSERT_POSITIONS:
            raise UserError(
                _(
                    "A value or a table goes before, after or inside something, "
                    "not '%s'.",
                    position,
                )
            )
        return cast("str", position)

    @api.model
    def _standing_at(
        self, operation: dict[str, object], expr: str, position: str
    ) -> LxmlElement | None:
        """What already stands exactly where this add would put its node.

        Asked of the tree the spec is about to be applied to, on both paths
        (``_beside_anchor``). The report operations used to ask the spec --
        which remembers a value this package placed and has since removed, so
        putting it back did nothing and said it had -- and, on a template the
        package owns, the whole arch, so a value printed anywhere could not be
        printed anywhere else.
        """
        tree = cast("LxmlElement | None", operation.get("_tree"))
        if tree is None:
            return None
        return cast("BuilderViewEditorBase", self)._beside_anchor(tree, expr, position)

    @api.model
    def _printed_unit(
        self, node: LxmlElement | None, expression: str
    ) -> tuple[bool, str | None]:
        """Whether ``node`` is a value printing ``expression`` the way
        ``_op_add_report_field`` writes one, and its label if it has one.

        Either a bare ``<span t-field>``, or the labelled unit: a ``<div>``
        holding exactly a ``<strong>`` and that span.
        """
        if node is None:
            return False, None
        if node.tag == "span" and node.get("t-field") == expression:
            return True, None
        if node.tag != "div":
            return False, None
        children = [child for child in node if isinstance(child.tag, str)]
        if (
            len(children) == 2
            and children[0].tag == "strong"
            and children[1].tag == "span"
            and children[1].get("t-field") == expression
        ):
            return True, (children[0].text or "").strip() or None
        return False, None

    def _op_add_report_field(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """A `t-field` span, optionally with a label beside it.

        Idempotent on (anchor, position, value) for the same reason
        `_op_add_field` is: a double-click must not print the value twice.
        "Already there" means the same value standing exactly where this one
        would go, in the tree the spec applies to (``_standing_at``). The same
        value elsewhere is a second place to print it, and a value placed,
        removed and placed again is placed again.

        Every add is a spec of its own, appended. Folding a second value into
        an earlier block with the same locator moved it ahead of everything
        placed in between: core evaluates specs in order, and the earlier
        block runs earlier.
        """
        name = cast("str | None", operation.get("name"))
        model_name = cast("str | None", operation.get("model"))
        if not name or not model_name:
            raise UserError(_("Placing a field requires a model and a field name."))
        expression = self._report_field_expression(
            model_name, name, cast("str", operation.get("loop_var") or "doc")
        )
        position = self._report_position(operation)
        expr = cast("str", operation["xpath"])
        label = (cast("str | None", operation.get("label")) or "").strip() or None

        held, held_label = self._printed_unit(
            self._standing_at(operation, expr, position), expression
        )
        if held:
            if held_label != label:
                # A replay asking for another label is a request to change
                # it. Printing the value again would show it twice, and
                # dropping the request would claim a label that was not set.
                raise UserError(
                    _(
                        "%s is already printed there; change its label instead "
                        "of placing it again.",
                        expression,
                    )
                )
            return root

        node = cast("BuilderViewEditorBase", self)._new_xpath(root, expr, position)
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

        A replayed add -- the same list, tabled exactly where this one would
        go -- changes nothing; the same list with other columns there is
        refused rather than tabled twice. Both read off the tree, like a
        value's (``_standing_at``).
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
        position = self._report_position(operation)
        loop_var = cast("str", operation.get("loop_var") or "line")
        loop = "%s.%s" % (cast("str", operation.get("parent_var") or "doc"), name)
        cells = ["%s.%s" % (loop_var, column) for column in columns]

        standing = self._standing_at(operation, expr, position)
        rows = (
            [row for row in standing.iter("tr") if row.get("t-foreach") == loop]
            if standing is not None and standing.tag == "table"
            else []
        )
        if rows:
            printed = [
                cast("str", span.get("t-field"))
                for span in rows[0].iter("span")
                if span.get("t-field")
            ]
            if printed != cells:
                raise UserError(
                    _(
                        "%s is already tabled there; change that table's "
                        "columns instead of adding another.",
                        loop,
                    )
                )
            return root

        node = cast("BuilderViewEditorBase", self)._new_xpath(root, expr, position)
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
            etree.SubElement(body, "tr", {"t-foreach": loop, "t-as": loop_var}),
        )
        for expression in cells:
            cell = cast("LxmlElement", etree.SubElement(row, "td"))
            etree.SubElement(cell, "span", {"t-field": expression})
        return node

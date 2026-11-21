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
(``_beside_anchor``), never of the spec. Moving and attributes are the view
editor's own operations and need nothing report-specific. Removal is too,
underneath; what a report adds is knowing what goes with a value -- its
label, its column's header, its table (``_op_remove_report_element``).
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
    from collections import Counter

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
            if label is not None and held_label != label:
                # A replay asking for another label is a request to change
                # it. Printing the value again would show it twice, and
                # dropping the request would claim a label that was not set.
                # No label at all is not a request to remove one: the console
                # forgets the label once it has placed the value, so a second
                # click on Place is a replay, the same as a double-click.
                field = cast("dict[str, Field[Any]]", self.env[model_name]._fields)[
                    name
                ]
                raise UserError(
                    _(
                        "%s is already printed there; change its label instead "
                        "of placing it again.",
                        field.string or name,
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

    @api.model
    def _tabled_columns(self, node: LxmlElement | None, loop: str) -> list[str] | None:
        """The columns of ``node`` if it is a table ``_op_add_report_table``
        made over ``loop``, else None.

        Only the shape this editor writes counts: a ``<table>`` holding a
        ``<thead>`` with one header row and a ``<tbody>`` with one ``<tr
        t-foreach t-as>`` whose every cell is a single ``<span t-field>`` on
        the row's own loop variable, one header cell per body cell. Columns
        are returned without the loop variable, so a replay naming it
        differently is still the same table. A hand-written or core table over
        the same list (an order-line table, with its own spans and widgets) is
        somebody else's table, and a builder table is free to go beside it.
        """

        def elements(parent: LxmlElement) -> list[LxmlElement]:
            return [child for child in parent if isinstance(child.tag, str)]

        if node is None or node.tag != "table":
            return None
        parts = elements(node)
        if [part.tag for part in parts] != ["thead", "tbody"]:
            return None
        heads, rows = elements(parts[0]), elements(parts[1])
        if len(heads) != 1 or len(rows) != 1 or heads[0].tag != "tr":
            return None
        row = rows[0]
        loop_var = row.get("t-as")
        if row.tag != "tr" or row.get("t-foreach") != loop or not loop_var:
            return None
        cells = elements(row)
        if not cells or len(elements(heads[0])) != len(cells):
            return None
        prefix = "%s." % loop_var
        columns: list[str] = []
        for cell in cells:
            spans = elements(cell)
            if cell.tag != "td" or len(spans) != 1 or spans[0].tag != "span":
                return None
            expression = spans[0].get("t-field") or ""
            column = expression[len(prefix) :]
            if not expression.startswith(prefix) or not column or "." in column:
                return None
            columns.append(column)
        return columns

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

        printed = self._tabled_columns(
            self._standing_at(operation, expr, position), loop
        )
        if printed is not None:
            if printed != columns:
                raise UserError(
                    _(
                        "A table of %s is already there; change that table's "
                        "columns instead of adding another.",
                        field.string or name,
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

    # -- taking a value out ------------------------------------------------------

    @api.model
    def _labelled_unit(self, node: LxmlElement) -> LxmlElement | None:
        """The labelled unit ``node`` is the value of, or None.

        ``_op_add_report_field`` writes a labelled value as one ``<div>``
        holding a ``<strong>`` and the span. Taking out the span alone
        leaves the label printed beside nothing.
        """
        expression = node.get("t-field")
        parent = node.getparent()
        if node.tag != "span" or not expression or parent is None:
            return None
        held, _label = self._printed_unit(parent, expression)
        return parent if held and parent.tag == "div" else None

    @api.model
    def _builder_column(self, node: LxmlElement) -> tuple[LxmlElement, int, int] | None:
        """The table ``_op_add_report_table`` made that ``node`` is a cell
        value of, the cell's index in its row and how many cells the row
        has; None otherwise.

        Only that shape has columns the builder can take out: one header
        cell per body cell, in the same order. A hand-written table's
        columns are whatever its ``t-if``s and ``colspan``s make them.
        """
        cell = node.getparent()
        row = cell.getparent() if cell is not None else None
        body = row.getparent() if row is not None else None
        table = body.getparent() if body is not None else None
        if (
            node.tag != "span"
            or cell is None
            or cell.tag != "td"
            or row is None
            or table is None
            or self._tabled_columns(table, row.get("t-foreach") or "") is None
        ):
            return None
        cells = cast("BuilderViewEditorBase", self)._specs(row)
        index = next(i for i, each in enumerate(cells) if each is cell)
        return table, index, len(cells)

    @api.model
    def _enclosing_table(self, node: LxmlElement) -> LxmlElement | None:
        """The nearest ``<table>`` ``node`` is printed in, or None."""
        return next(
            (ancestor for ancestor in node.iterancestors() if ancestor.tag == "table"),
            None,
        )

    @api.model
    def _report_removals(self, node: LxmlElement) -> list[str]:
        """What the console may offer to take out when ``node`` -- a value
        printed by ``t-field`` -- is selected, the first being what Delete
        does.

        ``labelled`` is a value and its label, ``value`` the value alone,
        ``column`` the column of a table the builder made and ``table`` the
        whole table the value is printed in.
        """
        if self._builder_column(node) is not None:
            return ["column", "table"]
        if self._labelled_unit(node) is not None:
            return ["labelled"]
        if self._enclosing_table(node) is not None:
            return ["value", "table"]
        return ["value"]

    @api.model
    def _table_locator(
        self,
        table: LxmlElement,
        node: LxmlElement,
        occurrences: Counter[tuple[str, str, str]],
    ) -> str:
        """The table holding ``node``, located by what it prints: a table
        has no identity of its own, and its indexed path is the most
        fragile locator there is."""
        editor = cast("BuilderViewEditorBase", self)
        held = editor._unique_predicate(node, occurrences)
        if held:
            return "//table[.//%s]" % held
        return editor._locator_for(table, occurrences)

    def _op_remove_report_element(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Take a value out of a report, with what belongs to it.

        ``xpath`` locates the value the console has selected -- a
        ``t-field`` -- and ``unit`` says how much goes with it: ``value``
        (or ``labelled``) the value, and its label when it has one;
        ``column`` its column of a builder table, header and all; ``table``
        the table it is printed in. A column that is the table's last takes
        the table with it: a table of nothing is not a table.

        What the unit is, is read off the tree the spec applies to
        (``_tree``), like every other report edit, and the removal is the
        view editor's own (``_op_remove_node``): a ``replace`` per node, or
        the insertion taken back when the last spec made it -- so a value
        removed can be placed again (``_standing_at``).
        """
        editor = cast("BuilderViewEditorBase", self)
        unit = operation.get("unit") or "value"
        if unit not in ("value", "labelled", "column", "table"):
            raise UserError(
                _("A value, a column or a table can be removed, not '%s'.", unit)
            )
        tree = cast("LxmlElement | None", operation.get("_tree"))
        expr = cast("str", operation["xpath"])
        found = editor._resolve_xpath(tree, expr) if tree is not None else None
        if tree is None or not found:
            # Already gone: nothing to take out, and nothing is written.
            return root
        node = found[0]
        expression = node.get("t-field") or node.tag
        occurrences = editor._occurrences(tree)
        exprs: list[str]
        if unit in ("value", "labelled"):
            doomed = self._labelled_unit(node)
            exprs = [editor._locator_for(doomed or node, occurrences)]
            operation["_what"] = expression
        elif unit == "table":
            table = self._enclosing_table(node)
            if table is None:
                raise UserError(_("%s is not printed in a table.", expression))
            exprs = [self._table_locator(table, node, occurrences)]
            operation["_what"] = _("the table printing %s", expression)
        else:
            column = self._builder_column(node)
            if column is None:
                raise UserError(
                    _(
                        "%s is not a column of a table the builder made; "
                        "remove the whole table, or edit it as source.",
                        expression,
                    )
                )
            table, index, width = column
            located = self._table_locator(table, node, occurrences)
            if width == 1:
                exprs = [located]
                operation["_what"] = _("the table printing %s", expression)
            else:
                # The header first: its locator goes through the table,
                # which is found by the value this removal takes out.
                exprs = [
                    "%s/thead/tr/th[%d]" % (located, index + 1),
                    editor._locator_for(
                        cast("LxmlElement", node.getparent()), occurrences
                    ),
                ]
                operation["_what"] = _("the %s column", expression)
        removal: dict[str, object] = {"xpath": exprs[0], "_tree": tree}
        if len(exprs) > 1:
            removal["label_xpath"] = exprs[1]
        return self._op_remove_node(root, removal)

    def _op_remove_node(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """A labelled value's span takes its label with it.

        A raw ``remove_node`` on ``//span[@t-field=...]`` of a value
        ``_op_add_report_field`` placed with a label used to leave the
        ``<strong>`` behind, printing a label for nothing. The unit is
        removed instead -- read off the tree the spec applies to, so a span
        somebody else wrapped is left to mean what it says.
        """
        editor = cast("BuilderViewEditorBase", self)
        tree = cast("LxmlElement | None", operation.get("_tree"))
        expr = cast("str", operation["xpath"])
        found = editor._resolve_xpath(tree, expr) if tree is not None else None
        if tree is not None and found and not operation.get("label_xpath"):
            unit = self._labelled_unit(found[0])
            if unit is not None:
                operation = dict(
                    operation,
                    xpath=editor._locator_for(unit, editor._occurrences(tree)),
                )
        return cast("BuilderViewEditorBase", super())._op_remove_node(root, operation)

    @api.model
    def _describe(self, operation: dict[str, object]) -> str:
        if operation.get("type") == "remove_report_element":
            return _("removed %s", operation.get("_what") or _("a value"))
        return cast("BuilderViewEditorBase", super())._describe(operation)

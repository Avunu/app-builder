# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Putting a field into the views that show it.

A field the builder adds but never places is invisible: the column exists, the
class has it, and the form does not show it. That is the most confusing thing
the builder can produce, so placement is part of adding a field rather than a
separate chore.

This edits the arch of views the package **owns outright**. Patching our own
primary view with an ``<xpath>`` extension would produce source no developer
would have written; ``studio.view.editor`` exists for the other case, editing
views belonging to somebody else, and stays the tool for that.

Removal matters as much as insertion and is easier to forget: a ``<field>``
naming a column that no longer exists fails view validation, which fails the
reload, which rolls the whole apply back. Dropping a field therefore has to
take its view nodes with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias, cast

from .lxml_types import LxmlElement

if TYPE_CHECKING:
    # `Callable` here only ever appears inside a type annotation
    # (`_sub_element`/`_element` below); `from __future__ import
    # annotations` defers every annotation to a string, so nothing needs
    # this name at runtime.
    from collections.abc import Callable

# lxml ships no type stubs in this environment (a compiled extension with no
# `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an installed
# dependency here), so pyright cannot resolve `etree` as an exported member
# of `lxml` at all -- confirmed directly, `from lxml import etree` alone
# reports both `reportMissingTypeStubs` (on `lxml`) and
# `reportAttributeAccessIssue` ("etree" is unknown import symbol, on
# `etree`). Ignored narrowly on each name rather than rewriting the import
# (e.g. `import lxml.etree as etree`), which trades this gap for a
# different one: ruff's own `PLR0402` auto-fixes that form straight back to
# `from lxml import etree` (`fix = true` project-wide), silently
# reintroducing the failure.
from lxml import (  # pyright: ignore[reportMissingTypeStubs]
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)

# `LxmlElement` (`lxml_types.py`, shared with `xml_writer.py` and
# `app_builder_view/tools/canvas_stamp.py`) is the real, checkable type for
# every element this module touches -- an arch root, a
# ``<field>``/``<group>``/``<notebook>``/``<page>``/``<filter>`` node.
Element: TypeAlias = LxmlElement

# `etree.SubElement`/`etree.Element` are the two constructors this module
# actually calls; grabbing each once, behind a single documented cast, keeps
# the "Unknown member of an unstubbed module" gap to two lines instead of one
# `# pyright: ignore` per call site (there are a dozen). The raw attribute
# access is unavoidably Unknown twice over -- pyright cannot name the
# member's own type, so it cannot name the *variable's* type either -- hence
# two rule codes on the one line that touches `etree` directly.
_sub_element_raw = etree.SubElement  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_sub_element: Callable[..., Element] = cast("Callable[..., Element]", _sub_element_raw)
_element_raw = etree.Element  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_element: Callable[..., Element] = cast("Callable[..., Element]", _element_raw)

# Fields that carry meaning to Odoo rather than to the user; the scaffold places
# them deliberately or not at all, so automatic placement must leave them alone.
NEVER_PLACE = frozenset(
    {"active", "sequence", "name", "reference", "company_id", "currency_id"}
)

_NOTEBOOK_TYPES = frozenset({"one2many", "many2many", "html", "text"})


def wants_notebook(ttype: str) -> bool:
    """Whether this type belongs on its own page rather than in a column.

    A related list in a two-column group is unreadable at any real row count,
    and it is the layout every hand-written Odoo form avoids.
    """
    return ttype in _NOTEBOOK_TYPES


# -- insertion ------------------------------------------------------------


def place_in_form(
    root: Element,
    name: str,
    ttype: str,
    label: str | None = None,
    widget: str | None = None,
) -> bool:
    """Add a field to a form arch, in the slot its type deserves."""
    if _find_field(root, name) is not None:
        return False
    if wants_notebook(ttype):
        return _place_in_notebook(root, name, label, widget)
    return _place_in_group(root, name, widget)


def _attrs(name: str, widget: str | None) -> dict[str, str]:
    """A field node's attributes. The widget is why placement carries one.

    A preset like Priority or Image *is* a widget plus some values: without
    writing it here the field lands as a bare selection or a file input, which
    is the type it really is and not the thing the user picked.
    """
    attrs: dict[str, str] = {"name": name}
    if widget:
        attrs["widget"] = widget
    return attrs


def _place_in_group(root: Element, name: str, widget: str | None = None) -> bool:
    sheet = root.find(".//sheet")
    host = sheet if sheet is not None else root
    columns: list[Element] = host.findall("./group/group")
    if not columns:
        outer = _sub_element(host, "group")
        columns = [_sub_element(outer, "group"), _sub_element(outer, "group")]
        # A notebook must stay last, so a group created late moves above it.
        notebook = host.find("./notebook")
        if notebook is not None:
            host.remove(outer)
            host.insert(list(host).index(notebook), outer)
    # Balance the two columns rather than always appending to the first, so a
    # form built one field at a time ends up looking like a designed one.
    target = min(columns, key=lambda column: len(column.findall("field")))
    _sub_element(target, "field", _attrs(name, widget))
    return True


def _place_in_notebook(
    root: Element,
    name: str,
    label: str | None = None,
    widget: str | None = None,
) -> bool:
    sheet = root.find(".//sheet")
    host = sheet if sheet is not None else root
    notebook = host.find("./notebook")
    if notebook is None:
        notebook = _sub_element(host, "notebook")
    page = _sub_element(notebook, "page", string=label or name, name="page_%s" % name)
    _sub_element(page, "field", _attrs(name, widget))
    return True


def place_in_list(root: Element, name: str, widget: str | None = None) -> bool:
    if _find_field(root, name) is not None:
        return False
    field = _element("field", _attrs(name, widget))
    # The state badge reads as a status column and belongs at the end.
    badge = next(
        (f for f in root.findall("field") if f.get("widget") == "badge"),
        None,
    )
    if badge is not None:
        root.insert(list(root).index(badge), field)
    else:
        root.append(field)
    return True


def place_in_search(root: Element, name: str) -> bool:
    if _find_field(root, name) is not None:
        return False
    field = _element("field", name=name)
    fields = root.findall("field")
    if fields:
        root.insert(list(root).index(fields[-1]) + 1, field)
    else:
        root.insert(0, field)
    return True


def place_group_by(root: Element, name: str, label: str | None = None) -> bool:
    """Add a group-by filter to a search arch, in the group-by group."""
    filter_name = "group_by_%s" % name
    if root.find(".//filter[@name='%s']" % filter_name) is not None:
        return False
    group = root.find("./group")
    if group is None:
        group = _sub_element(root, "group", string="Group By")
    _sub_element(
        group,
        "filter",
        name=filter_name,
        string=label or name,
        context="{'group_by': '%s'}" % name,
    )
    return True


# -- removal --------------------------------------------------------------


def remove_field(root: Element, name: str) -> bool:
    """Take a field out of an arch, along with anything left empty behind it.

    A page whose only field is gone, or a group-by naming a dropped column, is
    not merely untidy -- the group-by would fail view validation on the next
    load, which is the same crash removal is trying to avoid.
    """
    changed = False
    for node in root.xpath(".//field[@name='%s']" % name):
        parent = node.getparent()
        parent.remove(node)
        changed = True
        # An emptied page is a tab that opens onto nothing.
        if parent.tag == "page" and not len(parent):
            notebook = parent.getparent()
            notebook.remove(parent)
            if not len(notebook):
                notebook.getparent().remove(notebook)
    for node in root.xpath(".//filter[@context]"):
        context = node.get("context") or ""
        if "'group_by': '%s'" % name in context or '"group_by": "%s"' % name in context:
            node.getparent().remove(node)
            changed = True
    return changed


# -- shared ---------------------------------------------------------------


def _find_field(root: Element, name: str) -> Element | None:
    """A field anywhere in this arch, including inside a subview.

    Deliberately recursive: if the name already appears at all, placing it again
    would render it twice, and a duplicated field in one form is a bug the user
    reports as "it saved my value in the wrong box".
    """
    return next(iter(root.xpath(".//field[@name='%s']" % name)), None)

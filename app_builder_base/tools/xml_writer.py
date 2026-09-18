# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Canonical, byte-stable XML emission.

Determinism is the whole point of this module. Odoo Studio's one-shot export is
unusable in review because its output ordering follows dict/insertion order and
record ids, so a semantic no-op still produces a large diff. Everything here is
ordered by a *declared* rule instead, so re-serialising an unchanged package
yields a byte-identical file and an empty ``git diff``.

Two rules do the heavy lifting:

* attributes are emitted in :data:`ATTRIBUTE_ORDER`, then alphabetically;
* only *structural* elements are re-indented. An element carrying mixed content
  (text interleaved with children, e.g. a QWeb body or an HTML snippet) is left
  byte-for-byte alone, because reflowing it would change its rendered meaning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    # Only used inside annotations (`from __future__ import annotations`
    # defers all of them to strings), never at runtime -- flake8-type-checking
    # (TC001/TC003) wants typing-only imports guarded exactly like this,
    # same as the odoo-only import in catalogue.py's own precedent.
    from collections.abc import Iterable

    from .lxml_types import LxmlElement as XmlElement

from lxml import (  # pyright: ignore[reportMissingTypeStubs] -- lxml ships no type stubs in this environment (no `lxml-stubs`; the compiled `etree`/`_elementpath` extensions carry no `.pyi`/`py.typed`). `XmlElement` (`lxml_types.py`, the module three `tools/` readers share) hand-declares the small slice of the real `_Element` API this file touches, so the rest of the file is genuinely typed rather than `Any`-contaminated from this one boundary outward.
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType] -- same gap as the `from lxml import` line above; pyright cannot resolve `etree` as a symbol at all without a stub.
)


class XmlParser(Protocol):
    """The parser instance ``parse_arch`` builds and hands to ``fromstring``."""


# Attributes a reader expects first, in the order an Odoo developer writes them.
# Anything not listed sorts alphabetically after these.
ATTRIBUTE_ORDER = (
    # <record> / <field> plumbing
    "id",
    "model",
    "name",
    "ref",
    "eval",
    "type",
    "search",
    "file",
    "forcecreate",
    "noupdate",
    # inheritance
    "expr",
    "position",
    # common view attributes
    "string",
    "widget",
    "options",
    "domain",
    "context",
    "invisible",
    "column_invisible",
    "readonly",
    "required",
    "groups",
)

INDENT = "    "

_ORDER_INDEX = {name: i for i, name in enumerate(ATTRIBUTE_ORDER)}


def _attr_sort_key(item: tuple[str, str]) -> tuple[int, str]:
    name = item[0]
    return (_ORDER_INDEX.get(name, len(ATTRIBUTE_ORDER)), name)


def canonicalize_attributes(elem: XmlElement) -> None:
    """Reorder every attribute in ``elem`` and its subtree, in place.

    lxml preserves attribute insertion order, so the only way to reorder is to
    clear and re-add.
    """
    items = sorted(elem.attrib.items(), key=_attr_sort_key)
    if items != list(elem.attrib.items()):
        elem.attrib.clear()
        for key, value in items:
            elem.set(key, value)
    for child in elem:
        if isinstance(child.tag, str):  # skip comments / PIs
            canonicalize_attributes(child)


# Only these are layout whitespace we may discard. str.strip() would also eat
# U+00A0 and friends, which are *content* -- silently deleting the &nbsp; that
# separates two inline elements in a QWeb template or an HTML field.
LAYOUT_WHITESPACE = " \t\r\n\f\v"


def _is_blank(text: str | None) -> bool:
    return not text or not text.strip(LAYOUT_WHITESPACE)


def _has_mixed_content(elem: XmlElement) -> bool:
    """True when ``elem`` interleaves text with child elements."""
    if len(elem) == 0:
        return False
    if not _is_blank(elem.text):
        return True
    return any(not _is_blank(child.tail) for child in elem)


def indent(elem: XmlElement, level: int = 0, unit: str = INDENT) -> None:
    """Re-indent structural elements, leaving mixed content untouched.

    Returning early on mixed content is what makes this safe to run over a QWeb
    template or an HTML field: reflowing those would insert significant
    whitespace into the rendered output.
    """
    if len(elem) == 0 or _has_mixed_content(elem):
        return

    child_pad = "\n" + unit * (level + 1)
    own_pad = "\n" + unit * level

    elem.text = child_pad
    last = len(elem) - 1
    for i, child in enumerate(elem):
        if isinstance(child.tag, str):
            indent(child, level + 1, unit)
        child.tail = own_pad if i == last else child_pad


def build_document(
    record_nodes: Iterable[XmlElement],
    noupdate_nodes: Iterable[XmlElement] = (),
) -> XmlElement:
    """Assemble ``<odoo>`` from already-ordered record nodes.

    ``noupdate_nodes`` land in a trailing ``<data noupdate="1">`` block; keeping
    it last (rather than interleaving) is another ordering rule that keeps
    output stable as records move in and out of the noupdate set.
    """
    root = cast("XmlElement", etree.Element("odoo"))  # pyright: ignore[reportUnknownMemberType] -- see the `lxml` import's own ignore comment above.
    for node in record_nodes:
        root.append(node)
    if noupdate_nodes:
        data = cast("XmlElement", etree.SubElement(root, "data"))  # pyright: ignore[reportUnknownMemberType] -- see the `lxml` import's own ignore comment above.
        data.set("noupdate", "1")
        for node in noupdate_nodes:
            data.append(node)
    return root


def serialize_document(root: XmlElement) -> str:
    """Render a document root to the exact bytes we write to disk."""
    canonicalize_attributes(root)
    indent(root)
    body = cast("str", etree.tostring(root, encoding="unicode", pretty_print=False))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- see the `lxml` import's own ignore comment above; `root` satisfies `etree.tostring`'s real signature even though pyright cannot see that signature to confirm it.
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def parse_arch(arch: str | bytes) -> XmlElement:
    """Parse a view arch string into an element, tolerating a leading decl."""
    parser = cast(
        "XmlParser",
        etree.XMLParser(remove_blank_text=False, resolve_entities=False),  # pyright: ignore[reportUnknownMemberType] -- see the `lxml` import's own ignore comment above.
    )
    if isinstance(arch, str):
        arch = arch.encode("utf-8")
    return cast("XmlElement", etree.fromstring(arch, parser=parser))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- see the `lxml` import's own ignore comment above; `parser` satisfies `etree.fromstring`'s real signature even though pyright cannot see that signature to confirm it.


def normalize_arch(arch: str | bytes) -> str:
    """Return a canonical string form of a view arch.

    Used both when writing files and when comparing DB state to disk state, so
    that a whitespace-only difference never registers as drift.
    """
    node = parse_arch(arch)
    canonicalize_attributes(node)
    indent(node)
    return cast("str", etree.tostring(node, encoding="unicode", pretty_print=False))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- see the `lxml` import's own ignore comment above.

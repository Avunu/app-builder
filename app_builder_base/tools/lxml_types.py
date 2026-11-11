# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A hand-traced, narrow stand-in for lxml's own ``_Element``.

lxml ships no type stubs in this environment -- a compiled extension with no
``.pyi``/``py.typed`` marker, and ``lxml-stubs``/``types-lxml`` is not an
installed dependency here (confirmed directly: ``from lxml import etree``
alone reports both ``reportMissingTypeStubs`` and
``reportAttributeAccessIssue``). Every ``tools/`` module that walks or edits
an arch needs a real, checkable type for an element, so this is the one
place that type is declared: ``xml_writer.py``, ``placement.py`` (both in
this addon) and ``app_builder_view/tools/canvas_stamp.py`` each independently
hand-rolled an almost-identical local ``Protocol`` before this module existed
-- reconciled here so the three readers check against one contract instead of
three that drift apart, and so the next reader has somewhere to import from
rather than a fourth copy to write.

Narrower than the real ``_Element``: only what an actual call site of the
three current readers calls, extended as each new reader needs. ``tag`` is
``Any`` rather than lxml's real, wider contract (``str`` for an ordinary
element, a factory callable for a comment or processing-instruction node)
for two independent reasons, both confirmed against real call sites rather
than assumed: first, every real read of it narrows with
``isinstance(x.tag, str)`` first, and a plain ``str`` would make that check
always-true as far as pyright can tell -- exactly what
``reportUnnecessaryIsInstance`` (this directory's strict settings) flags,
when it is not always true; a ``str | Callable[..., object]`` union would
keep that narrowing meaningful, but second, ``canvas_stamp.py``'s own
``stamp()`` assigns ``element.tag`` straight into ``BuilderNode["tag"]``
(declared ``str``) at a point where the value is already guaranteed to be a
real tag by an invariant ``_walk`` established earlier (every element it
lists already passed ``isinstance(child.tag, str)``) but that a plain list
of tuples cannot carry forward for pyright to see -- so a union would fail
that assignment without an extra, unnecessary-at-runtime ``cast``. ``Any``
is the one type honest enough to satisfy both real constraints at once,
matching the same reasoning ``compat.py``'s own ``_fields: dict[str,
Field[Any]]`` already documents for a value whose real type genuinely
varies by caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator, MutableMapping


class ElementTree(Protocol):
    """lxml's own ``_ElementTree`` -- only the one method
    ``LxmlElement.getroottree()`` below is for: minting an absolute,
    root-anchored path to a node that no attribute identifies uniquely
    (``builder_view_editor.py:_locator_for``'s own positional fallback, the
    same call core's own ``distribute_branding`` uses)."""

    def getpath(self, element: LxmlElement) -> str: ...


class LxmlElement(Protocol):
    """The slice of lxml's ``_Element`` these ``tools/`` modules touch."""

    tag: Any
    text: str | None
    tail: str | None
    attrib: MutableMapping[str, str]

    def get(self, key: str, default: str | None = None) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def append(self, node: LxmlElement) -> None: ...
    def insert(self, index: int, node: LxmlElement) -> None: ...
    def remove(self, node: LxmlElement) -> None: ...
    def find(self, path: str) -> LxmlElement | None: ...
    def findall(self, path: str) -> list[LxmlElement]: ...
    #: lxml's real ``xpath`` returns a mix of elements, strings and booleans
    #: depending on the expression -- ``list[Any]`` is the honest static
    #: return type of the call itself, not a vendor-gap workaround; every
    #: current caller (``placement.py``) only ever writes expressions that
    #: return elements, and narrows by use rather than by a type this
    #: Protocol has no way to express per-expression.
    def xpath(self, path: str) -> list[Any]: ...
    def getparent(self) -> LxmlElement | None: ...
    #: Real lxml also accepts `*tags` (multiple tag names/wildcards) after
    #: `tag`; narrowed here to the one-tag form every current reader
    #: actually calls (`ir_ui_view.py`'s own `node.iter("button")`) rather
    #: than the fuller variadic signature nothing yet needs.
    def iter(self, tag: str | None = None) -> Iterator[LxmlElement]: ...
    def iterancestors(self) -> Iterator[LxmlElement]: ...
    #: `builder_view_editor.py`'s own `_locator_for`, positional fallback.
    def getroottree(self) -> ElementTree: ...
    #: `builder_view_editor.py`'s own `_own_label`, walking back through
    #: unnamed siblings (a comment, a processing instruction).
    def getprevious(self) -> LxmlElement | None: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[LxmlElement]: ...

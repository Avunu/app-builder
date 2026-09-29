# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""``odoo._``, with the type it really has.

Odoo 18's ``_`` is the plain function ``odoo.tools.translate.get_text_alias``
-- ``(source: str, *args, **kwargs)`` with the varargs unannotated -- so every
file that writes ``from odoo import _`` gets one "partially unknown" import
under strict checking (TYPING.md, Known traps).

This re-exports the *same function object* under a ``Protocol`` that says so.
It must stay the identical object, never a wrapper: ``get_text_alias`` finds
the addon and the language by reading its **caller's** frame
(``_get_translation_source(1)``), so a wrapper function would put itself in
that frame and every translation would silently resolve against this module.
A cast of the original changes what a type checker believes and nothing
else, which is also why source-based extraction of ``_("...")`` terms is
unaffected -- it looks at the call, not the import.

Use it exactly like ``odoo._``::

    from ..tools.i18n import _
"""

from __future__ import annotations

from typing import Protocol, cast

from odoo import _ as _odoo  # pyright: ignore[reportUnknownVariableType]


class Gettext(Protocol):
    """What ``_`` accepts: a term, then either ``%s`` positionals or ``%(k)s``
    keywords (Odoo asserts not both)."""

    def __call__(self, source: str, *args: object, **kwargs: object) -> str: ...


_ = cast("Gettext", _odoo)

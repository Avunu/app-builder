# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The one cast every ``self.env["..."]`` in this codebase goes through.

``Environment.__getitem__`` returns the bare ``BaseModel`` whatever string it
is asked for -- there is no way for it to know which real subclass a model
name names. Every model file's own call to it would otherwise need its own
cast (or lose every method/field only the real subclass declares), which is
exactly the kind of small, repeated unsafety Phase 1c exists to remove.

``model(env, cls)`` replaces ``env["model.name"]`` with ``model(env, Cls)``:
the model name is read off the class itself (its own ``_name``), so the
string and the class it names can never drift apart at a call site, and the
cast lives here once instead of at every one of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    # Only for the annotations below; with `from __future__ import
    # annotations` nothing here needs these at runtime, and this file stays
    # importable with no Odoo on the path -- the same bargain `compat.py`'s
    # own `TYPE_CHECKING`-guarded imports make.
    from odoo import api
    from odoo.models import BaseModel

M = TypeVar("M", bound="BaseModel")


def model(env: api.Environment, cls: type[M]) -> M:
    """``env[cls._name]``, typed as ``cls`` rather than the bare ``BaseModel``.

    ``cls._name`` is declared ``str | None`` on ``BaseModel`` itself (``None``
    for an abstract mixin with no table of its own), so the cast to ``str``
    below is real, not decorative -- every concrete model class this is ever
    called with overrides it with its own literal name, but pyright only
    knows the declared type of the attribute on the bound (``BaseModel``),
    not the narrower literal a real subclass happens to assign. The return
    is cast to the type parameter ``M`` itself, by name, rather than to the
    runtime value ``cls`` -- the same thing at any one call site (`M` is
    exactly what `cls` was passed as), but the name is what a generic
    function's own return type actually is, and pyright resolves it to
    whatever `M` is bound to for that call.
    """
    return cast("M", env[cast("str", cls._name)])

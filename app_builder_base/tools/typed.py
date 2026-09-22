# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The casts Odoo's own registry-level dynamism otherwise needs at every call
site, done once here instead.

``Environment.__getitem__`` returns the bare ``BaseModel`` whatever string it
is asked for -- there is no way for it to know which real subclass a model
name names. ``_inherit`` mixin composition has the identical shape one level
up: a class using ``_inherit = ["some.mixin"]`` gets that mixin's methods at
the registry level, never as a real Python base class, so nothing in its own
MRO carries them as far as a type checker can see. Both are exactly the kind
of small, repeated unsafety Phase 1c exists to remove -- one cast per real
gap, done here, rather than once per call site across every model file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    # Only for the annotations below; with `from __future__ import
    # annotations` nothing here needs these at runtime, and this file stays
    # importable with no Odoo on the path -- the same bargain `compat.py`'s
    # own `TYPE_CHECKING`-guarded imports make. `StudioSecurityMixin` is this
    # file's one exception to "tools/ never names a specific models/ class":
    # a `TYPE_CHECKING`-only reference costs nothing at runtime and creates
    # no real import cycle (`models/` already imports `tools/` for real,
    # never the other way around), so `security()` below can name it
    # directly rather than accepting an unchecked `Any`.
    from odoo import api
    from odoo.models import BaseModel

    from ..models.studio_security import StudioSecurityMixin
    from ..models.studio_serializer import StudioSerializer

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


def ref(env: api.Environment, xml_id: str) -> BaseModel:
    """``env.ref(xml_id)``, typed as the real record it returns by default.

    ``Environment.ref`` (``odoo/api.py``) is one unannotated function whose
    return genuinely depends on ``raise_if_not_found`` (default ``True``,
    the only form this helper accepts): true, it either returns a real
    record or raises ``ValueError`` -- ``None`` is only reachable on the
    ``raise_if_not_found=False`` path this helper does not expose. pyright
    infers the union of every branch in the unannotated body regardless of
    which argument a given call actually passes, so every real call site
    sees ``BaseModel | None`` whether or not ``None`` is reachable there --
    the same "one optional parameter, no overloads, union-of-branches
    inference" shape TYPING.md's own "Known traps" section already
    documents for ``Environment.get`` (a different method, same root cause)
    and, in the test suite, ``TestCase.assertRaises`` (``common.py``'s own
    ``raises()``).
    """
    # `Environment.ref` is unannotated, so this file's own strict `tools/`
    # setting (`reportUnknownMemberType`) flags the call itself, not just
    # its return -- same shape as `compat.py`'s own `env[model]._fields`.
    return cast("BaseModel", env.ref(xml_id))  # pyright: ignore[reportUnknownMemberType]


def security(self: BaseModel) -> StudioSecurityMixin:
    """``self``, cast to the guard every studio RPC method calls first.

    ``studio_security.py``'s own docstring: "called first in every studio
    method reachable over RPC." Every real caller composes it the same way
    (``_inherit = ["studio.security.mixin"]``, registry-level, never a real
    Python base class), so ``self._assert_studio_manager()``/``self
    ._assert_studio_user()`` are invisible to pyright on every one of them --
    confirmed the moment the first real caller (``studio_package.py``, 8 call
    sites) needed the equivalent inline cast at every single one.
    """
    return cast("StudioSecurityMixin", self)


def serializer(self: BaseModel) -> StudioSerializer:
    """``self``, cast to ``studio.serializer``'s own real methods.

    Every concrete serializer composes ``studio.serializer`` only via
    ``_inherit = "studio.serializer"`` (registry-level, never a real Python
    base class), so a subclass calling one of the base's own methods on
    itself (``self._ref_of(...)``, ``self._target_file(...)``, ...) is
    invisible to pyright the same way ``self._assert_studio_manager()`` is
    on ``studio.security.mixin`` -- the same fix, aimed at a different
    mixin.
    """
    return cast("StudioSerializer", self)

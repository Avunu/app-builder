# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Opt-in runtime type checking of the pure ``tools/`` modules (TYPING.md,
Phase 1e).

Off unless ``APP_BUILDER_TYPEGUARD`` is set to something truthy, in which
case ``app_builder_base/__init__.py`` calls :func:`install` *before* it
imports anything from ``tools/`` -- typeguard rewrites a module as it is
imported, so there is no installing it afterwards. Never set in production;
``typeguard`` is a development dependency (``nix/pyproject.toml``).

What it checks, and what it deliberately does not:

* Only the ``tools/`` packages of this repo's addons. They are pure
  functions over dataclasses, dicts and strings -- the one place a runtime
  check is cheap and true. ORM code is the opposite: a recordset's static
  type (``Users``, ``BuilderPackage``) is a claim ``typed.model()`` makes with
  a ``cast``, and a runtime check of it would only ever compare the cast with
  itself.
* Not ``typed.py`` (its casts have nothing to check, and its ``TypeVar``
  bound is a ``TYPE_CHECKING``-only name) and not ``lxml_types.py``. Any
  ``Protocol`` this repo defines is passed over by :func:`_skip_protocols`:
  they are hand-written stand-ins for stubless lxml, whose real objects do
  not carry the declared attribute types.
* An annotation that cannot be resolved at run time is an *error*, not a
  silent skip: a check that quietly does not run reads exactly like a check
  that passed.

The first full run of the suite under this hook (893 tests) found one real
annotation defect (``modelspec.spec_to_json`` took only a ``ModelSpec`` but
is called with a ``FieldSpec``) and three violations, all from one test that
drives the documented "the default resolver leaves labels lazy" path on
purpose -- see ``tests/common.py:unchecked``.
"""

from __future__ import annotations

import pathlib
import typing

#: Pure typing scaffolding: nothing at run time for a checker to test.
_SKIP = {"__init__", "typed", "lxml_types", "i18n"}


def modules() -> list[str]:
    """Dotted names of every ``tools/`` module this hook instruments."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    found = []
    for tools in sorted(repo.glob("app_builder*/tools")):
        addon = tools.parent.name
        found.extend(
            f"odoo.addons.{addon}.tools.{path.stem}"
            for path in sorted(tools.glob("*.py"))
            if path.stem not in _SKIP
        )
    return found


def _skip_protocols(
    origin_type: type, args: tuple[typing.Any, ...], extras: tuple[typing.Any, ...]
) -> typing.Callable[..., None] | None:
    if getattr(
        origin_type, "_is_protocol", False
    ) and origin_type.__module__.startswith("odoo.addons.app_builder"):
        return lambda value, origin, args, memo: None
    return None


def install() -> None:
    # Optional test dependency: absent from a plain dev env.
    import typeguard  # pyright: ignore[reportMissingImports]

    typeguard.config.forward_ref_policy = typeguard.ForwardRefPolicy.ERROR
    typeguard.config.collection_check_strategy = (
        typeguard.CollectionCheckStrategy.ALL_ITEMS
    )
    # Ahead of typeguard's own lookup, which would otherwise claim every
    # Protocol first.
    typeguard.checker_lookup_functions.insert(0, _skip_protocols)
    typeguard.install_import_hook(modules())

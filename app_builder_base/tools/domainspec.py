# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Between a domain string and something a person can edit.

A domain is prefix notation -- ``['&', '&', a, b, c]`` -- which is exact, total,
and not a thing anybody builds in a form. What a builder can offer is a list of
conditions and one choice of "all of these" or "any of these", which covers the
domains people actually write and refuses the rest.

Refusing is the important half. A domain with nested groups, or a mixture of
``&`` and ``|``, or a ``!``, has no faithful rendering as a flat list -- and a
builder that showed one anyway would silently rewrite somebody's rule the first
time they touched an unrelated row. ``parse`` returns None for anything it
cannot represent, and the caller says "edit this as source" rather than
pretending.

Pure, like the rest of ``tools/``: no ``odoo.osv.expression`` and no registry, so
it is unit-testable and the round trip can be asserted directly.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict, cast

if TYPE_CHECKING:
    # `render`'s own parameter type only; with `from __future__ import
    # annotations` nothing here needs `Sequence` at runtime.
    from collections.abc import Sequence

ALL = "all"
ANY = "any"

# The joiner a domain's prefix operator means, and back.
_JOINER_OF = {"&": ALL, "|": ANY}
_OPERATOR_OF = {ALL: "&", ANY: "|"}

# Operators that take no value: `set` and `not set` are the two everybody wants
# and nobody spells the same way twice. Kept here so the UI, the renderer and
# the parser cannot disagree about which ones skip the value box.
VALUELESS = {"set", "not set"}

_VALUELESS_DOMAIN: dict[str, tuple[str, bool]] = {
    "set": ("!=", False),
    "not set": ("=", False),
}

#: One leaf of Odoo's own prefix-notation domain: ``(field, operator, value)``.
#: ``value`` is honestly ``object``, not a narrower type -- a leaf's value is
#: whatever the field and operator call for (a string, a number, a bool, a
#: list of ids, ...), and nothing here inspects it beyond passing it through
#: or comparing it by identity against the two valueless sentinels above.
DomainLeaf: TypeAlias = tuple[str, str, object]


class ConditionJSON(TypedDict):
    """What ``Condition.as_dict`` sends: the wire shape ``read_domain``
    (``builder_domain.py``) returns a list of, one per row. ``value`` stays
    ``object`` for the same reason ``DomainLeaf.value`` does -- it is
    whatever the field's own type and the chosen operator call for.
    """

    field: str
    operator: str
    value: object


@dataclass
class Condition:
    field: str
    operator: str
    value: object = False

    def as_leaf(self) -> DomainLeaf:
        if self.operator in VALUELESS:
            return (self.field, *_VALUELESS_DOMAIN[self.operator])
        return (self.field, self.operator, self.value)

    def as_dict(self) -> ConditionJSON:
        return {"field": self.field, "operator": self.operator, "value": self.value}


#: ``parse``'s success shape: the flat conditions, and which joiner binds them.
ParsedDomain: TypeAlias = tuple[list[Condition], str]


def render(conditions: Sequence[Condition], joiner: str = ALL) -> str:
    """Conditions -> a domain string Odoo will accept.

    An empty list is ``[]``, which every caller means as "no restriction" --
    not as "match nothing".
    """
    if joiner not in _OPERATOR_OF:
        raise ValueError("unknown joiner %r" % joiner)
    leaves = [c.as_leaf() for c in conditions]
    if not leaves:
        return "[]"
    prefix = [_OPERATOR_OF[joiner]] * (len(leaves) - 1)
    return repr([*prefix, *[list(leaf) for leaf in leaves]])


def parse(domain: str | None) -> ParsedDomain | None:
    """A domain string -> ``(conditions, joiner)``, or ``None``.

    None means "this is not a flat list of conditions", which is a statement
    about the domain rather than a failure: the caller shows the source instead.
    """
    if domain is None:
        return None
    text = domain.strip()
    if not text:
        return [], ALL
    try:
        # `ast.literal_eval` is typed to return `Any`: the whole point of this
        # function is to make no assumption about what a person actually wrote,
        # so everything below re-derives its shape from scratch via `isinstance`
        # rather than trusting a static type for it.
        parsed_raw: Any = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed_raw, list | tuple):
        return None
    # `isinstance` against a bare, unparameterized `(list, tuple)` narrows an
    # `Any` to `list[Unknown] | tuple[Unknown, ...]`, not `list[Any] |
    # tuple[Any, ...]` -- pyright fills an unparameterized generic's type
    # argument with `Unknown` rather than `Any` when narrowing a
    # dynamically-typed value, and that `Unknown` survives even an explicit
    # re-annotation of a new variable (confirmed empirically: only `cast`
    # clears it). Nothing below is less safe for admitting the container is
    # honestly `Any`-shaped -- every element is re-validated by hand anyway.
    parsed = cast("list[Any] | tuple[Any, ...]", parsed_raw)
    if not parsed:
        return [], ALL

    operators: list[str] = [t for t in parsed if isinstance(t, str)]
    leaves: list[list[Any] | tuple[Any, ...]] = [
        t for t in parsed if isinstance(t, list | tuple)
    ]
    if not leaves or len(leaves) + len(operators) != len(parsed):
        return None
    if any(op not in _JOINER_OF for op in operators):
        # A '!' -- or a string where a leaf should be.
        return None
    if operators and len(set(operators)) != 1:
        # A mixture is a shape, and a flat list cannot carry it.
        return None
    # Odoo's implicit joiner is AND, so no operator at all means "all of them".
    if operators and len(operators) != len(leaves) - 1:
        # Grouped: ['&', '|', a, b, c] binds differently from a flat list.
        return None

    conditions: list[Condition] = []
    for leaf in leaves:
        if len(leaf) != 3:
            return None
        field, operator, value = leaf
        if not isinstance(field, str) or not isinstance(operator, str):
            return None
        conditions.append(_condition(field, operator, value))
    joiner = _JOINER_OF[operators[0]] if operators else ALL
    return conditions, joiner


def _condition(field: str, operator: str, value: object) -> Condition:
    """Fold the two spellings of emptiness back into their names."""
    for name, (op, val) in _VALUELESS_DOMAIN.items():
        if operator == op and value is val:
            return Condition(field, name)
    return Condition(field, operator, value)

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

import ast
from dataclasses import dataclass

ALL = "all"
ANY = "any"

# The joiner a domain's prefix operator means, and back.
_JOINER_OF = {"&": ALL, "|": ANY}
_OPERATOR_OF = {ALL: "&", ANY: "|"}

# Operators that take no value: `set` and `not set` are the two everybody wants
# and nobody spells the same way twice. Kept here so the UI, the renderer and
# the parser cannot disagree about which ones skip the value box.
VALUELESS = {"set", "not set"}

_VALUELESS_DOMAIN = {
    "set": ("!=", False),
    "not set": ("=", False),
}


@dataclass
class Condition:
    field: str
    operator: str
    value: object = False

    def as_leaf(self):
        if self.operator in VALUELESS:
            return (self.field, *_VALUELESS_DOMAIN[self.operator])
        return (self.field, self.operator, self.value)

    def as_dict(self):
        return {"field": self.field, "operator": self.operator, "value": self.value}


def render(conditions, joiner=ALL):
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


def parse(domain):
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
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed, (list, tuple)):
        return None
    if not parsed:
        return [], ALL

    operators = [t for t in parsed if isinstance(t, str)]
    leaves = [t for t in parsed if isinstance(t, (list, tuple))]
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

    conditions = []
    for leaf in leaves:
        if len(leaf) != 3:
            return None
        field, operator, value = leaf
        if not isinstance(field, str) or not isinstance(operator, str):
            return None
        conditions.append(_condition(field, operator, value))
    joiner = _JOINER_OF[operators[0]] if operators else ALL
    return conditions, joiner


def _condition(field, operator, value):
    """Fold the two spellings of emptiness back into their names."""
    for name, (op, val) in _VALUELESS_DOMAIN.items():
        if operator == op and value is val:
            return Condition(field, name)
    return Condition(field, operator, value)

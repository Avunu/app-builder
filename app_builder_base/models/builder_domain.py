# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What a domain builder needs from the registry.

The pure half -- domain string to conditions and back -- is
``tools/domainspec``. This is the half that has to ask the registry: which
fields can be tested, and which operators mean anything for each of them.

Offering every operator for every type is what makes a condition builder feel
like a form nobody proof-read. ``ilike`` on a boolean and ``>`` on a many2one
are both accepted by Odoo and neither is a thing anybody means.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypedDict, cast

from odoo import api, models
from odoo.exceptions import UserError

from ..tools import domainspec, typed
from ..tools.i18n import _

if TYPE_CHECKING:
    # `write_domain`'s own parameter type only; with `from __future__ import
    # annotations` nothing here needs `Sequence` at runtime.
    from collections.abc import Sequence

    from odoo.fields import Field

# Operators worth offering, per family of field. Order is the order they are
# shown, so the common one comes first.
TEXTUAL: tuple[str, ...] = ("=", "!=", "ilike", "not ilike", "set", "not set")
NUMERIC: tuple[str, ...] = ("=", "!=", ">", ">=", "<", "<=", "set", "not set")
EXACT: tuple[str, ...] = ("=", "!=", "set", "not set")
RELATIONAL: tuple[str, ...] = ("=", "!=", "in", "not in", "set", "not set")

OPERATORS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "char": TEXTUAL,
    "text": TEXTUAL,
    "html": TEXTUAL,
    "integer": NUMERIC,
    "float": NUMERIC,
    "monetary": NUMERIC,
    "date": NUMERIC,
    "datetime": NUMERIC,
    "boolean": ("=", "!="),
    "selection": EXACT,
    "many2one": RELATIONAL,
    "many2many": RELATIONAL,
    "one2many": RELATIONAL,
}

LABELS: dict[str, str] = {
    "=": "is",
    "!=": "is not",
    ">": "is after / more than",
    ">=": "is at least",
    "<": "is before / less than",
    "<=": "is at most",
    "ilike": "contains",
    "not ilike": "does not contain",
    "in": "is one of",
    "not in": "is none of",
    "set": "is set",
    "not set": "is not set",
}


class OperatorJSON(TypedDict):
    """One operator a condition on a field can use, label included."""

    value: str
    label: str


class SelectionValueJSON(TypedDict):
    """One choice of a selection field, as ``fields_for`` reports it."""

    value: str
    label: str


class _FieldSpecRequiredJSON(TypedDict):
    name: str
    string: str
    type: str
    operators: list[OperatorJSON]


class FieldSpecJSON(_FieldSpecRequiredJSON, total=False):
    """A field a condition can test, as ``fields_for`` returns it -- one
    entry per stored field whose type offers at least one sane operator.
    ``values`` is present only for a selection field, ``comodel`` only for
    a relational one; ``OPERATORS_BY_TYPE``'s own keys make the two
    mutually exclusive by construction.
    """

    values: list[SelectionValueJSON]
    comodel: str


class _DomainNotEditableJSON(TypedDict):
    editable: Literal[False]
    domain: str | None
    reason: str


class _DomainEditableJSON(TypedDict):
    editable: Literal[True]
    joiner: str
    rows: list[domainspec.ConditionJSON]


#: ``read_domain``'s own answer shape: either a refusal (the domain groups or
#: negates its terms, so it cannot be shown flat) or the flattened rows.
ReadDomainJSON: TypeAlias = _DomainNotEditableJSON | _DomainEditableJSON


class DomainRowJSON(TypedDict, total=False):
    """One row of a condition builder's grid, as the console sends it back
    to ``write_domain``. Every key is optional: a row can be mid-edit (no
    field chosen yet, filtered out below) or use a valueless operator
    (``set``/``not set``, which the body never reads ``value`` for).
    """

    field: str
    operator: str
    value: object


class _DomainInvalidJSON(TypedDict):
    valid: Literal[False]
    reason: str


class _DomainValidJSON(TypedDict):
    valid: Literal[True]
    count: int


#: ``check_domain``'s own answer shape: whether the domain actually searches,
#: and either the complaint or the count.
CheckDomainJSON: TypeAlias = _DomainInvalidJSON | _DomainValidJSON


class BuilderDomain(models.AbstractModel):
    _name = "builder.domain"
    _inherit = ["builder.security.mixin"]
    _description = "Builder: Condition Builder"

    @api.model
    def fields_for(self, model_name: str) -> list[FieldSpecJSON]:
        """Fields a condition can test, with the operators that suit each.

        Stored fields only: a non-stored computed field cannot be searched
        unless it declares a `search` method, and offering one that raises at
        query time would be worse than leaving it out.
        """
        typed.security(self)._assert_builder_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        out: list[FieldSpecJSON] = []
        # `_fields` is OCB's own bare, unparameterized `dict[str, Field]`;
        # the cast is the same fix `builder_serializer.py`'s `fields_` makes.
        fields_ = cast("dict[str, Field[Any]]", self.env[model_name]._fields)
        for name, field in sorted(fields_.items()):
            if not field.store or field.type not in OPERATORS_BY_TYPE:
                continue
            entry: FieldSpecJSON = {
                "name": name,
                "string": field.string or name,
                "type": field.type,
                "operators": [
                    {"value": op, "label": LABELS[op]}
                    for op in OPERATORS_BY_TYPE[field.type]
                ],
            }
            if field.type == "selection":
                # `get_description` (`odoo/fields.py`) carries no annotation
                # of its own, on either its parameters or its return, so
                # pyright infers `dict[Unknown, Unknown]` for it and
                # `Unknown | None` for `.get("selection")` (confirmed with
                # `reveal_type`) -- a genuine untyped hole, not a gap this
                # migration introduces. `_description_selection`'s own
                # docstring ("return the selection list (pairs (value,
                # label))") is the real, honest shape; cast to it here
                # rather than leaving the read `Unknown`.
                entry["values"] = [
                    {"value": value, "label": label}
                    for value, label in (
                        cast(
                            "list[tuple[str, str]] | None",
                            field.get_description(self.env).get("selection"),
                        )
                        or []
                    )
                ]
            if field.type in ("many2one", "one2many", "many2many"):
                # `Field.comodel_name` is declared `str | None` on the base
                # descriptor (`None` for a non-relational field), but every
                # field reaching this branch is one of the three relational
                # types, which always carry a real comodel -- true by
                # construction, invisible to the type checker.
                entry["comodel"] = cast("str", field.comodel_name)
            out.append(entry)
        return out

    @api.model
    def read_domain(self, domain: str | None) -> ReadDomainJSON:
        """A stored domain as rows, or a refusal the caller can show.

        The refusal is the point. A nested domain has no faithful flat
        rendering, and a builder that showed one anyway would rewrite it the
        moment somebody touched an unrelated row.
        """
        typed.security(self)._assert_builder_user()
        parsed = domainspec.parse(domain or "[]")
        if parsed is None:
            return {
                "editable": False,
                "domain": domain,
                "reason": _(
                    "This condition groups its terms, or negates one, so it "
                    "cannot be shown as a flat list without changing what it "
                    "means. Edit it as source."
                ),
            }
        conditions, joiner = parsed
        return {
            "editable": True,
            "joiner": joiner,
            "rows": [c.as_dict() for c in conditions],
        }

    @api.model
    def write_domain(
        self,
        rows: Sequence[DomainRowJSON] | None,
        joiner: str = domainspec.ALL,
    ) -> str:
        """Rows back to a domain string, validated against Odoo's own parser.

        Checked here rather than trusted: a domain that renders and does not
        *search* would be written to source and fail on somebody else's
        database, which is the failure this project is least willing to ship.
        """
        typed.security(self)._assert_builder_user()
        conditions = [
            domainspec.Condition(
                # `row.get("field")` is re-evaluated here rather than reused
                # from the `if` clause below -- true by construction (that
                # clause already filtered out any row without one), but two
                # separate calls to `.get()` on the same key are two separate
                # reads as far as the type checker can see.
                cast("str", row.get("field")),
                row.get("operator", "="),
                row.get("value", False),
            )
            for row in rows or []
            if row.get("field")
        ]
        rendered = domainspec.render(conditions, joiner)
        return rendered

    @api.model
    def check_domain(self, model_name: str, domain: str | None) -> CheckDomainJSON:
        """Does this actually search? Returns the count, or the complaint."""
        typed.security(self)._assert_builder_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        # Not "is it flat" -- a source-edited domain is usually not, and is
        # usually fine. Odoo's own parser is the judge of whether it searches.
        try:
            count = self.env[model_name].search_count(ast.literal_eval(domain or "[]"))
        except Exception as err:  # noqa: BLE001 - any failure is the same answer
            return {"valid": False, "reason": str(err)}
        return {"valid": True, "count": count}

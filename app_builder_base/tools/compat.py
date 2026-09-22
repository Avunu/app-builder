# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What differs between the Odoo branches this code runs on.

Kept to one file so a port is a diff of one file, the way the console's
``compat.js`` keeps the client's seams together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Only for `groups_field`'s own annotations below; with `from __future__
    # import annotations` (above) nothing here needs these at runtime, and
    # this file stays importable with no Odoo on the path.
    from odoo import api
    from odoo.fields import Field


def groups_field(env: api.Environment, model: str = "res.users") -> str:
    """The field that holds a record's groups, by the name this server gives it.

    18 calls it ``groups_id``; 19 renamed it ``group_ids`` on ``res.users``,
    ``ir.ui.view``, ``ir.ui.menu`` and ``ir.actions.act_window``. Anything
    that spells one of them stops importing on the other branch, so nothing
    spells it: this answers instead, per model, since the rename did not
    reach every model at once.
    """
    # `_fields` is a heterogeneous dict (each field's own `Field[T]` differs
    # by column type), so there is no single, real `T` to name here -- `Any`
    # is the honest type, not a narrowing this function could do instead;
    # only membership (`name in fields`) is ever checked, never a value.
    # OCB's own `BaseModel._fields` is declared `dict[str, Field]` --
    # unparameterized, not `dict[str, Field[Any]]` -- so the expression
    # itself is `Unknown` before the annotation below ever applies; not
    # something this file can fix from its own side.
    fields: dict[str, Field[Any]] = env[model]._fields  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    for name in ("group_ids", "groups_id", "groups"):
        if name in fields:
            return name
    raise KeyError("%s has no groups field" % model)

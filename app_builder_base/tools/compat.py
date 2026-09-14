# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What differs between the Odoo branches this code runs on.

Kept to one file so a port is a diff of one file, the way the console's
``compat.js`` keeps the client's seams together.
"""


def groups_field(env, model="res.users"):
    """The field that holds a record's groups, by the name this server gives it.

    18 calls it ``groups_id``; 19 renamed it ``group_ids`` on ``res.users``,
    ``ir.ui.view``, ``ir.ui.menu`` and ``ir.actions.act_window``. Anything
    that spells one of them stops importing on the other branch, so nothing
    spells it: this answers instead, per model, since the rename did not
    reach every model at once.
    """
    fields = env[model]._fields
    for name in ("group_ids", "groups_id", "groups"):
        if name in fields:
            return name
    raise KeyError("%s has no groups field" % model)

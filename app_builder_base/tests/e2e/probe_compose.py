#!/usr/bin/env python
# pylint: disable=print-used,invalid-commit,sql-injection,odoo-addons-relative-import
"""Composing on an existing app: does an edit reach the database *and* the screen?

The staging half of the composer is covered by unit tests. The half that
matters cannot be: applying writes files, re-imports Python and rebuilds the
registry, and ``_button_immediate_function`` refuses to run at all when
``threading.current_thread().testing`` is set. So the interesting claims are
only ever provable here.

Four of them (the fourth below the list, with the second's other half):

1. **A field added in the composer ends up visible.** Before placement existed
   the column appeared, the class had it, and the form did not show it -- the
   most confusing thing the builder can produce, and entirely invisible to a
   test that only checks ``_fields``.
2. **A field removed in the composer takes its view nodes with it.** A
   ``<field>`` naming a dropped column fails view validation, which fails the
   reload, which rolls the whole apply back. This is the case that turns a
   small edit into a broken package.
3. **A related list and the link back apply together.** Two files, one reload:
   writing only the one2many would leave registry setup resolving an inverse
   that does not exist, and the setup it fails is the one that was going to
   create it.
4. **A restart finishes an apply that could not reload in place.** Under
   workers the apply writes and stops; the package is marked ``to upgrade``,
   and a registry loaded the way a freshly started process loads it -- no
   ``-u`` -- has to create the column. Without the mark it does not, and
   every read of the model fails.

And for the second: the removed column has to still be there, renamed aside
with its data, which only happens when the pre-migration is filed under a
version above the installed one.

Run:  python app_builder_base/tests/e2e/probe_compose.py -c odoo.conf -d <db>
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING, Any, cast

import odoo
from odoo import SUPERUSER_ID, api
from odoo.models import MetaModel
from odoo.modules.registry import Registry
from odoo.tools import sql

if TYPE_CHECKING:
    from odoo.fields import One2many

PKG = "x_compose_probe"
LABEL = "Compose Job"
CHILD = "Compose Line"


def check(label, ok, detail=""):
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", label, detail and " -- " + detail))
    return ok


def writable_addons_dir():
    for path in odoo.addons.__path__:
        if path.rstrip("/").endswith("custom") and os.access(path, os.W_OK):
            return path
    for path in odoo.addons.__path__:
        if os.access(path, os.W_OK):
            return path
    raise SystemExit("no writable addons directory on addons_path")


def arch_of(env, model_name, view_type):
    view = env["ir.ui.view"].search(
        [
            ("model", "=", model_name),
            ("type", "=", view_type),
            ("mode", "=", "primary"),
        ],
        limit=1,
    )
    return view.arch or ""


def build_app(env, package, label):
    # The console's flow calls the same RPC.
    built = env["builder.app"].create_app_rpc(
        package.id, {"label": label, "features": ["chatter"]}
    )
    return built["model"]


def draft_for(env, package, model_name):
    package_model = package.model_ids.filtered(lambda m: m.model == model_name)
    return env["builder.model.draft"].open_for(package_model)


def main():
    odoo.tools.config.parse_config(sys.argv[1:])
    dbname = odoo.tools.config["db_name"]
    if not dbname:
        raise SystemExit("pass -d <database>")

    root = writable_addons_dir()
    pkg_path = os.path.join(root, PKG)
    if os.path.isdir(pkg_path):
        shutil.rmtree(pkg_path)

    results = []
    try:
        # --- an app to compose on ----------------------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package_vals: dict[str, object] = {
                "name": PKG,
                "display_name_": "Compose Probe",
                "root_path": pkg_path,
                "auto_commit": "off",
            }
            package = env["builder.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
            parent = build_app(env, package, LABEL)
            child = build_app(env, package, CHILD)
            package_id = cast("int", package.id)
            cr.commit()
        print("  built %s and %s" % (parent, child))

        # --- 1. add a field, and look for it on the form ------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            draft = draft_for(env, env["builder.package"].browse(package_id), parent)
            draft.add_field(
                {
                    "name": "due_date",
                    "ttype": "date",
                    "string": "Due Date",
                    "placement": {"form": True, "list": True, "search": False},
                }
            )
            draft.action_apply()
            cr.commit()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            results.append(
                check(
                    "the added field is a real column",
                    "due_date" in env[parent]._fields,
                )
            )
            results.append(
                check(
                    "the added field is on the form",
                    'name="due_date"' in arch_of(env, parent, "form"),
                    "a field nobody can see is the worst thing this can produce",
                )
            )
            results.append(
                check(
                    "the added field is in the list",
                    'name="due_date"' in arch_of(env, parent, "list"),
                )
            )
            results.append(
                check(
                    "it was not put in the search view, because it was not asked for",
                    'name="due_date"' not in arch_of(env, parent, "search"),
                )
            )

        # --- 2. remove it, and check the views let go ---------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            # Something to lose: the removal below promises to keep it.
            dated_vals: dict[str, object] = {"name": "Dated", "due_date": "2026-01-02"}
            dated_id = env[parent].create(dated_vals).id  # pyright: ignore[reportArgumentType]
            table = env[parent]._table
            draft = draft_for(env, env["builder.package"].browse(package_id), parent)
            draft.remove_field("due_date")
            draft.action_apply(allow_destructive=True)
            cr.commit()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            results.append(
                check(
                    "the removed field is gone from the class",
                    "due_date" not in env[parent]._fields,
                )
            )
            # The pre-migration only runs under a version above the installed
            # one; filed under the installed version it is skipped, silently,
            # and the column is dropped with everything in it.
            cr.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = %s AND column_name LIKE %s",
                (table, "due_date_builder_removed_%"),
            )
            kept = [row[0] for row in cr.fetchall()]
            results.append(
                check(
                    "the removed column was renamed aside, not dropped",
                    len(kept) == 1,
                    "found %s" % (kept or "nothing"),
                )
            )
            if kept:
                cr.execute(
                    'SELECT "%s"::text FROM "%s" WHERE id = %%s' % (kept[0], table),
                    (dated_id,),
                )
                value = cr.fetchone()
                results.append(
                    check(
                        "and its data is still in it",
                        bool(value) and value[0] == "2026-01-02",
                        "got %s" % (value,),
                    )
                )
            results.append(
                check(
                    "the form no longer names it",
                    'name="due_date"' not in arch_of(env, parent, "form"),
                    "a <field> naming a dropped column fails the next reload",
                )
            )
            results.append(
                check(
                    "the list no longer names it",
                    'name="due_date"' not in arch_of(env, parent, "list"),
                )
            )

        # --- 3. a related list and its inverse, in one apply ---------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package = env["builder.package"].browse(package_id)
            draft = draft_for(env, package, parent)
            options = draft.inverse_options(child)
            results.append(
                check(
                    "the builder offers to create the link back",
                    options["can_create"],
                    "suggested %s" % options["suggested"],
                )
            )
            draft.add_field(
                {
                    "name": "line_ids",
                    "ttype": "one2many",
                    "comodel": child,
                    "inverse_name": options["suggested"],
                    "string": "Lines",
                    "create_inverse": True,
                }
            )
            results.append(
                check(
                    "both models are staged in one changeset",
                    draft.change_count == 2,
                    "count %s" % draft.change_count,
                )
            )
            inverse_name = options["suggested"]
            draft.action_apply()
            cr.commit()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            parent_fields = env[parent]._fields
            child_fields = env[child]._fields
            results.append(
                check("the related list exists", "line_ids" in parent_fields)
            )
            results.append(
                check(
                    "the link back exists on the other model",
                    inverse_name in child_fields,
                    "one reload covered two files",
                )
            )
            results.append(
                check(
                    "the related list resolves its inverse",
                    "line_ids" in parent_fields
                    and cast("One2many", parent_fields["line_ids"]).inverse_name
                    == inverse_name,
                )
            )
            form = arch_of(env, parent, "form")
            results.append(
                check(
                    "the related list got its own page",
                    "<page" in form and 'name="line_ids"' in form,
                    "a one2many in a two-column group is unreadable",
                )
            )
            results.append(
                check(
                    "and was not dropped into a column",
                    "<page" in form
                    and form.index("<page") < form.index('name="line_ids"'),
                )
            )
            # The real proof that the pair is sound: use it.
            record_vals: dict[str, object] = {"name": "Probe"}
            record = env[parent].create(record_vals)  # pyright: ignore[reportArgumentType]
            line_vals: dict[str, object] = {"name": "Line", inverse_name: record.id}
            env[child].create(line_vals)  # pyright: ignore[reportArgumentType]
            results.append(
                check(
                    "records can actually be linked through it",
                    # `parent`/`child` are runtime model names, not literal
                    # strings -- no real Python class exists to cast to, so
                    # this reads the field the same way `record[fname]` does
                    # in `builder_serializer.py` (an already-established
                    # idiom for exactly this "dynamic field name" shape).
                    len(record["line_ids"]) == 1,
                )
            )
            cr.commit()

        # --- 4. a server that cannot reload in place -----------------------
        # Under workers the apply writes, commits and stops; the restart has
        # to create the column, and a plain boot only upgrades a module that
        # is marked. So: apply as a multi-worker server would, then load the
        # registry the way a freshly started process does -- nothing
        # imported, no -u -- and look for the column.
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package = env["builder.package"].browse(package_id)
            draft = draft_for(env, package, parent)
            draft.add_field({"name": "note_later", "ttype": "char", "string": "Later"})
            odoo.tools.config["workers"] = 2
            try:
                package.invalidate_recordset(["reload_mode"])
                outcome = draft.action_apply()
            finally:
                odoo.tools.config["workers"] = 0
            cr.commit()
            module: Any = env["ir.module.module"].search([("name", "=", PKG)])
            results.append(
                check(
                    "under workers the apply stops and waits for a restart",
                    outcome["state"] == "awaiting_restart",
                    "state %s" % outcome["state"],
                )
            )
            results.append(
                check(
                    "and marks the package for upgrade",
                    module.state == "to upgrade",
                    "module state %s" % module.state,
                )
            )
            results.append(
                check(
                    "the column does not exist yet",
                    not sql.column_exists(cr, table, "note_later"),
                )
            )

        # What a restart amounts to: a process that has imported nothing.
        for name in [
            m
            for m in sys.modules
            if m == "odoo.addons.%s" % PKG or m.startswith("odoo.addons.%s." % PKG)
        ]:
            del sys.modules[name]
        MetaModel.module_to_models.pop(PKG, None)
        registry = Registry.new(dbname)  # a plain boot: no update_module
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            module: Any = env["ir.module.module"].search([("name", "=", PKG)])
            results.append(
                check(
                    "a plain restart upgrades the marked package",
                    module.state == "installed",
                    "module state %s" % module.state,
                )
            )
            results.append(
                check(
                    "and creates the column the new Python declares",
                    "note_later" in env[parent]._fields
                    and sql.column_exists(cr, table, "note_later"),
                    "new Python on an old schema fails every read of the model",
                )
            )
            results.append(
                check(
                    "the schema is whole",
                    not cast("Any", env["builder.package"])
                    .browse(package_id)
                    ._schema_behind(),
                )
            )
    finally:
        if os.path.isdir(pkg_path):
            shutil.rmtree(pkg_path)

    ok = all(results)
    print(
        "RESULT: %s"
        % (
            "edits reach the database and the screen. ACCEPTED."
            if ok
            else "FAILED -- see above"
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

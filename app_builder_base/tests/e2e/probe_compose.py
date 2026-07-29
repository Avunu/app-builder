#!/usr/bin/env python
"""Composing on an existing app: does an edit reach the database *and* the screen?

The staging half of the composer is covered by unit tests. The half that
matters cannot be: applying writes files, re-imports Python and rebuilds the
registry, and ``_button_immediate_function`` refuses to run at all when
``threading.current_thread().testing`` is set. So the interesting claims are
only ever provable here.

Three of them:

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

Run:  python app_builder_base/tests/e2e/probe_compose.py -c odoo.conf -d <db>
"""

import os
import shutil
import sys

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

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
    wizard = env["studio.model.wizard"].create(
        {"package_id": package.id, "name": label, "add_chatter": True}
    )
    wizard._onchange_name()
    return wizard.action_create()["res_model"]


def draft_for(env, package, model_name):
    package_model = package.model_ids.filtered(lambda m: m.model == model_name)
    return env["studio.model.draft"].open_for(package_model)


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
            package = env["studio.package"].create(
                {
                    "name": PKG,
                    "display_name_": "Compose Probe",
                    "root_path": pkg_path,
                    "auto_commit": "off",
                }
            )
            parent = build_app(env, package, LABEL)
            child = build_app(env, package, CHILD)
            package_id = package.id
            cr.commit()
        print("  built %s and %s" % (parent, child))

        # --- 1. add a field, and look for it on the form ------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            draft = draft_for(env, env["studio.package"].browse(package_id), parent)
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
            draft = draft_for(env, env["studio.package"].browse(package_id), parent)
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
            package = env["studio.package"].browse(package_id)
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
                    and parent_fields["line_ids"].inverse_name == inverse_name,
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
            record = env[parent].create({"name": "Probe"})
            env[child].create({"name": "Line", inverse_name: record.id})
            results.append(
                check(
                    "records can actually be linked through it",
                    len(record.line_ids) == 1,
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

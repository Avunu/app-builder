#!/usr/bin/env python
"""The acceptance test: does one gesture produce an app somebody can use?

Not a unit test, because every interesting step is one a TransactionCase
cannot reach -- installing a module, reloading Python, and then asking a
*different user* whether they can see the result.

That last part is the point. ``IrModelAccess.check`` returns True immediately
for ``env.su``, so an app with missing or wrong ACLs looks perfect to the
administrator who built it and is invisible to everybody it was built for. The
old wizard shipped exactly that bug -- it parented the generated menu under the
studio root, which is gated on the studio group -- and nothing in the product
would have told you.

Run:  python app_builder_base/tests/e2e/probe_scaffold.py -c odoo.conf -d <db>
"""

import os
import shutil
import sys

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

PKG = "x_scaffold_probe"
LABEL = "Workshop Job"


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


def staff_user(env):
    """A plain internal user: no studio group, no settings access."""
    existing = env["res.users"].search([("login", "=", "studio_probe_staff")], limit=1)
    if existing:
        return existing
    return env["res.users"].create(
        {
            "name": "Probe Staff",
            "login": "studio_probe_staff",
            "groups_id": [(6, 0, [env.ref("base.group_user").id])],
        }
    )


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
    model_name = None
    try:
        from odoo.addons.app_builder_base.tools import scaffold

        # --- build it ----------------------------------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package = env["studio.package"].create(
                {
                    "name": PKG,
                    "display_name_": "Scaffold Probe",
                    "root_path": pkg_path,
                    "auto_commit": "off",
                }
            )
            options = scaffold.ScaffoldOptions(
                chatter=True, activities=True, stage=True, user=True, reference=True
            )
            built = env["studio.app.builder"].create_app(
                package, LABEL, options=options
            )
            model_name = built["model"].model
            cr.commit()

        print("  built model: %s" % model_name)

        # --- is it real, in a fresh registry? ----------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            results.append(check("model is in the registry", model_name in env))
            model = env[model_name]
            for expected in ("name", "state", "user_id", "reference", "active"):
                results.append(
                    check("field %s exists" % expected, expected in model._fields)
                )
            results.append(
                check(
                    "chatter is on the model",
                    "message_ids" in model._fields and "activity_ids" in model._fields,
                )
            )

            views = env["ir.ui.view"].search([("model", "=", model_name)])
            kinds = set(views.mapped("type"))
            results.append(
                check(
                    "list, form and search views exist",
                    kinds >= {"list", "form", "search"},
                    "got %s" % sorted(kinds),
                )
            )

            menu = env["ir.ui.menu"].search(
                [("name", "=", LABEL), ("parent_id", "=", False)], limit=1
            )
            results.append(check("an app-level root menu was created", bool(menu)))
            results.append(
                check(
                    "the root menu is not gated behind a group",
                    bool(menu) and not menu.groups_id,
                    "groups: %s" % menu.groups_id.mapped("name") if menu else "",
                )
            )
            results.append(
                check("the root menu has an icon", bool(menu) and bool(menu.web_icon))
            )

        # --- the part that actually matters ------------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            staff = staff_user(env)
            cr.commit()

        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, staff.id, {})
            try:
                env[model_name].check_access("read")
                readable = True
                detail = ""
            except Exception as err:
                readable = False
                detail = str(err).splitlines()[0]
            results.append(
                check("a plain internal user can read the model", readable, detail)
            )

            try:
                record = env[model_name].create({"name": "First job"})
                created = bool(record)
                detail = ""
            except Exception as err:
                created = False
                detail = str(err).splitlines()[0]
            results.append(
                check("a plain internal user can create a record", created, detail)
            )

            visible = env["ir.ui.menu"].search(
                [("name", "=", LABEL), ("parent_id", "=", False)]
            )
            results.append(
                check(
                    "the app menu is visible to that user",
                    bool(visible),
                    "this is the bug the old wizard shipped",
                )
            )

            if created:
                results.append(
                    check(
                        "the reference sequence filled in",
                        bool(record.reference) and record.reference != "New",
                        "got %r" % record.reference,
                    )
                )

        # --- and is the source honest? -----------------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package = env["studio.package"].search([("name", "=", PKG)], limit=1)
            model_file = os.path.join(
                pkg_path, "models", "%s.py" % model_name.replace(".", "_")
            )
            results.append(check("the model file exists", os.path.isfile(model_file)))
            if os.path.isfile(model_file):
                source = open(model_file).read()
                results.append(
                    check("no x_ prefix in the generated class", "x_" not in source)
                )
                results.append(
                    check("chatter is a real mixin", "mail.thread" in source)
                )
            results.append(
                check(
                    "rewriting produces no diff",
                    package._render_files()[
                        "models/%s.py" % model_name.replace(".", "_")
                    ]
                    == source,
                )
            )
    finally:
        if os.path.isdir(pkg_path):
            shutil.rmtree(pkg_path)

    print()
    if all(results):
        print("RESULT: one gesture produced a working app. ACCEPTED.")
        return 0
    print("RESULT: the scaffold did not produce a usable app.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

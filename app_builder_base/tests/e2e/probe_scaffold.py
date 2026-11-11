#!/usr/bin/env python
# pylint: disable=print-used,invalid-commit,sql-injection,odoo-addons-relative-import
"""The acceptance test: does one gesture produce an app somebody can use?

Not a unit test, because every interesting step is one a TransactionCase
cannot reach -- installing a module, reloading Python, and then asking a
*different user* whether they can see the result.

That last part is the point. ``IrModelAccess.check`` returns True immediately
for ``env.su``, so an app with missing or wrong ACLs looks perfect to the
administrator who built it and is invisible to everybody it was built for. The
old wizard shipped exactly that bug -- it parented the generated menu under the
builder root, which is gated on the builder group -- and nothing in the product
would have told you.

Run:  python app_builder_base/tests/e2e/probe_scaffold.py -c odoo.conf -d <db>
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING, Any, cast

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs this at runtime, and it sidesteps the same
    # module-level `odoo.addons.<name>` resolution trap the deferred
    # imports in `main()` are working around (`base` happens to be always
    # resolvable, but a TYPE_CHECKING-only import never runs regardless).
    from odoo.addons.base.models.res_users import Groups

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
    """A plain internal user: no builder group, no settings access."""
    existing = env["res.users"].search([("login", "=", "builder_probe_staff")], limit=1)
    if existing:
        return existing
    return env["res.users"].create(
        {
            "name": "Probe Staff",
            "login": "builder_probe_staff",
            "groups_id": [(6, 0, [env.ref("base.group_user").id])],
        }
    )


def main():
    odoo.tools.config.parse_config(sys.argv[1:])
    dbname = odoo.tools.config["db_name"]
    if not dbname:
        raise SystemExit("pass -d <database>")

    # Deferred: `parse_config` (just above) is what calls
    # `initialize_sys_path`, and only that makes `odoo.addons.<name>`
    # resolvable at all -- a module-level import of any of these would run
    # first and fail (the same trap probe_reimport.py's own conversion
    # documents).
    from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
    from odoo.addons.app_builder_base.tools import typed
    from odoo.addons.app_builder_model.models.builder_app import (
        BuilderApp,
    )
    from odoo.addons.base.models.ir_actions import IrActionsActWindow
    from odoo.addons.base.models.ir_ui_menu import IrUiMenu

    root = writable_addons_dir()
    pkg_path = os.path.join(root, PKG)
    if os.path.isdir(pkg_path):
        shutil.rmtree(pkg_path)

    results = []
    model_name = None
    try:
        # --- build it ----------------------------------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package_vals: dict[str, object] = {
                "name": PKG,
                "display_name_": "Scaffold Probe",
                "root_path": pkg_path,
                "auto_commit": "off",
            }
            package = env["builder.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
            # Through the RPC the console's Build-an-app flow calls: this is
            # the path a user actually takes, and it commits and rebuilds the
            # registry, so no TransactionCase can reach it. Tags and Lines
            # are the two features that build a second model; they cannot be
            # exercised from a TransactionCase for the same reason.
            builder = typed.model(env, BuilderApp)
            # The flow starts from the defaults and adds what is ticked.
            features = builder.features()["defaults"] + [
                "chatter",
                "stage",
                "user",
                "reference",
                "tags",
                "lines",
            ]
            built = builder.create_app_rpc(
                cast("int", package.id), {"label": LABEL, "features": features}
            )
            model_name = built["model"]
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

            # The wizard ticked Pipeline stages, whose help text promises "a
            # kanban to move records across". That promise was computed and
            # read by nothing until now, so assert it rather than let a
            # superset check pass either way.
            results.append(
                check(
                    "the kanban Pipeline stages asked for was built",
                    "kanban" in kinds,
                    "got %s" % sorted(kinds),
                )
            )
            action = typed.model(env, IrActionsActWindow).search(
                [("res_model", "=", model_name)], limit=1
            )
            results.append(
                check(
                    "and the action offers it -- unoffered views are unreachable",
                    "kanban" in (action.view_mode or ""),
                    "view_mode: %s" % action.view_mode,
                )
            )

            menu = typed.model(env, IrUiMenu).search(
                [("name", "=", LABEL), ("parent_id", "=", False)], limit=1
            )
            results.append(check("an app-level root menu was created", bool(menu)))
            results.append(
                check(
                    "the root menu is not gated behind a group",
                    bool(menu) and not menu.groups_id,
                    "groups: %s" % cast("Groups", menu.groups_id).mapped("name")
                    if menu
                    else "",
                )
            )
            # A file, in the two-part form: the built `fa-class,color,bg`
            # form is core-legal but crashes web_responsive's apps menu.
            icon = "%s,static/description/icon.png" % PKG
            results.append(
                check(
                    "the root menu's icon is a file in the package",
                    bool(menu)
                    and menu.web_icon == icon
                    and os.path.isfile(
                        os.path.join(pkg_path, "static", "description", "icon.png")
                    ),
                    "web_icon: %s" % (menu.web_icon if menu else ""),
                )
            )
            # Only true if the file was on disk when the menu was created --
            # ir.ui.menu decodes web_icon on create and never again.
            results.append(
                check(
                    "and it decoded, so the tile has image data",
                    bool(menu) and bool(menu.web_icon_data),
                )
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
            except Exception as err:  # noqa: BLE001
                # A probe asks "can this user do it"; any failure is a No, and
                # narrowing the catch would report an unexpected error as a Yes.
                readable = False
                detail = str(err).splitlines()[0]
            results.append(
                check("a plain internal user can read the model", readable, detail)
            )

            record_vals: dict[str, object] = {"name": "First job"}
            # Typed `Any`: `model_name` is dynamic (rule: dynamic model
            # names stay a plain lookup, never `typed.model()`), so there is
            # no real class to cast the created record to; pre-declared here
            # (rather than left to the `try` alone) only so pyright sees it
            # as bound below -- `created` being True already guarantees the
            # `create()` call below succeeded, at runtime.
            record: Any = None
            try:
                record = env[model_name].create(record_vals)  # pyright: ignore[reportArgumentType]
                created = bool(record)
                detail = ""
            except Exception as err:  # noqa: BLE001 - see above
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
            package = typed.model(env, BuilderPackage).search(
                [("name", "=", PKG)], limit=1
            )
            model_file = os.path.join(
                pkg_path, "models", "%s.py" % model_name.replace(".", "_")
            )
            # --- the companions ------------------------------------------
            for kind, ttype in (("tag", "many2many"), ("line", "one2many")):
                companion = "%s_%s" % (model_name, kind)
                results.append(
                    check("companion %s is in the registry" % kind, companion in env)
                )
                field = "tag_ids" if kind == "tag" else "line_ids"
                results.append(
                    check(
                        "the parent points at its %s model" % kind,
                        field in model._fields
                        and model._fields[field].type == ttype
                        and model._fields[field].comodel_name == companion,
                    )
                )
                # A companion with no ACL makes the *parent's* form fail to
                # load, not merely hide the field -- which is the kind of bug
                # that looks perfect to the administrator who built it.
                readable = env["ir.model.access"].search_count(
                    [("model_id.model", "=", companion)]
                )
                results.append(
                    check("companion %s has an access rule" % kind, bool(readable))
                )
                results.append(
                    check(
                        "companion %s file exists" % kind,
                        os.path.isfile(
                            os.path.join(
                                pkg_path,
                                "models",
                                "%s.py" % companion.replace(".", "_"),
                            )
                        ),
                    )
                )

            results.append(check("the model file exists", os.path.isfile(model_file)))
            if os.path.isfile(model_file):
                with open(model_file) as handle:
                    source = handle.read()
                results.append(
                    check("no x_ prefix in the generated class", "x_" not in source)
                )
                results.append(
                    check("chatter is a real mixin", "mail.thread" in source)
                )
            results.append(
                check(
                    "rewriting produces no diff",
                    # Pre-existing: `source` is unset whenever the model
                    # file check above failed, and this comparison runs
                    # unconditionally -- a real NameError risk in that case,
                    # not introduced or fixed here (out of scope for a
                    # typing-only pass).
                    package._render_files()[
                        "models/%s.py" % model_name.replace(".", "_")
                    ]
                    == source,  # pyright: ignore[reportPossiblyUnboundVariable]
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

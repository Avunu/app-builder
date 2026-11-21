#!/usr/bin/env python
# pylint: disable=print-used,invalid-commit,sql-injection,odoo-addons-relative-import
"""Does turning approvals on actually stop anything?

Not a unit test, for the reason every probe in ``app_builder_base/tests/e2e``
is not: the gate goes live through Apply, which commits and reloads a module,
and ``_button_immediate_function`` raises under test mode. The unit suite
loads the generated class into a test registry by hand
(``tests/test_live_gate.py``); this goes the whole way, through the calls the
console's Approvals pane makes, in a real process:

    build an app  ->  enable_gate  ->  a rule  ->  a plain user is refused
                  ->  update_gate  ->  the gate moved
                  ->  disable_gate ->  the gate is gone, the rule is not

and asks each question as a **plain internal user**, because an approval gate
looks perfect to the administrator who is also the reviewer.

Needs ``app_builder_model`` (to build the app) and ``app_builder_approval``
installed in the database. The package is written under the first writable
addons directory and removed afterwards; where that directory is a git
checkout the builder stages what it writes, so expect ``x_approval_probe``
entries in the index to unstage (``git reset -- x_approval_probe``).

Run:  python app_builder_approval/tests/e2e/probe_approval.py -c odoo.conf -d <db>
      (with APP_BUILDER_ENABLE_WRITE=1, as run_probes.sh sets it: no --dev here)
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any, cast

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

PKG = "x_approval_probe"
LABEL = "Approval Probe Job"


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


def user(env, login):
    """A plain internal user: no builder group, no settings access."""
    existing = env["res.users"].search([("login", "=", login)], limit=1)
    if existing:
        return existing
    return env["res.users"].create(
        {
            "name": login,
            "login": login,
            "groups_id": [(6, 0, [env.ref("base.group_user").id])],
        }
    )


def refused(action):
    """Whether ``action`` was stopped by the engine, and what it said."""
    from odoo.exceptions import ValidationError

    try:
        action()
    except ValidationError as err:
        return True, str(err).splitlines()[0]
    return False, "it went through"


def main():
    odoo.tools.config.parse_config(sys.argv[1:])
    dbname = odoo.tools.config["db_name"]
    if not dbname:
        raise SystemExit("pass -d <database>")

    # Deferred: `parse_config` is what makes `odoo.addons.<name>` resolvable
    # at all (the trap probe_reimport.py documents).
    from odoo.addons.app_builder_base.tools import typed
    from odoo.addons.app_builder_model.models.builder_app import BuilderApp

    root = writable_addons_dir()
    pkg_path = os.path.join(root, PKG)
    if os.path.isdir(pkg_path):
        shutil.rmtree(pkg_path)

    results = []
    try:
        # --- an app, as Build-an-app makes it ------------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package_vals: dict[str, object] = {
                "name": PKG,
                "display_name_": "Approval Probe",
                "root_path": pkg_path,
                "auto_commit": "off",
            }
            package = env["builder.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
            builder = typed.model(env, BuilderApp)
            built = builder.create_app_rpc(
                cast("int", package.id),
                {
                    "label": LABEL,
                    "features": builder.features()["defaults"] + ["stage", "reference"],
                },
            )
            model_name = built["model"]
            package_id = cast("int", package.id)
            cr.commit()
        print("  built model: %s" % model_name)
        model_file = os.path.join(
            pkg_path, "models", "%s.py" % model_name.replace(".", "_")
        )

        # --- the gate, through the pane's own call ---------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            # Exactly what the pane sends: False for "from any state".
            cast("Any", env["builder.approval"]).enable_gate(
                package_id, model_name, "state", False, ["done"], False
            )
            cr.commit()

        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            model = cast("Any", env[model_name])
            results.append(
                check(
                    "the mixin is live after Apply",
                    "tier.validation" in model._inherit_module,
                )
            )
            results.append(
                check(
                    "every other state is an origin",
                    model._state_from == ["draft", "in_progress"]
                    and model._state_to == ["done"],
                    "from %r to %r" % (model._state_from, model._state_to),
                )
            )
            results.append(
                check(
                    "no cancel state is one that cannot match",
                    model._cancel_state == "",
                    repr(model._cancel_state),
                )
            )
            results.append(
                check(
                    "the model can be picked in a rule",
                    model_name
                    in cast(
                        "Any", env["tier.definition"]
                    )._get_tier_validation_model_names(),
                )
            )
            with open(model_file) as handle:
                source = handle.read()
            results.append(
                check(
                    "the creation guard is in the package's own source",
                    "def _create(self, data_list):" in source,
                )
            )
            results.append(
                check(
                    "rewriting produces no diff",
                    cast("Any", env["builder.package"])
                    .browse(package_id)
                    ._render_files()["models/%s.py" % model_name.replace(".", "_")]
                    == source,
                )
            )
            staff = user(env, "approval_probe_staff")
            reviewer = user(env, "approval_probe_reviewer")
            rule_vals: dict[str, object] = {
                "name": "Reviewer signs off",
                "model_id": cast("Any", env["ir.model"])._get(model_name).id,
                "review_type": "individual",
                "reviewer_id": reviewer.id,
            }
            # Created the way Settings would, with no package in context: a
            # reviewer who exists only in this database cannot be written to
            # source, and the serializer rightly says so.
            rule = env["tier.definition"].create(rule_vals)  # pyright: ignore[reportArgumentType]
            rule_id = cast("int", rule.id)
            staff_id, reviewer_id = staff.id, reviewer.id
            cr.commit()

        # --- the part that actually matters ----------------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, staff_id, {})
            jobs = cast("Any", env[model_name])
            job = jobs.create({"name": "Needs sign-off"})
            results.append(
                check(
                    "a plain user can still create a draft",
                    job.state == "draft"
                    and bool(job.reference)
                    and job.reference != "New",
                    "state %r, reference %r" % (job.state, job.reference),
                )
            )
            ok, detail = refused(lambda: job.write({"state": "done"}))
            results.append(check("draft -> done is refused", ok, detail))
            cr.rollback()

            job = jobs.create({"name": "Two clicks"})
            job.write({"state": "in_progress"})
            ok, detail = refused(lambda: job.write({"state": "done"}))
            results.append(
                check("draft -> in progress -> done is refused too", ok, detail)
            )
            cr.rollback()

            ok, detail = refused(
                lambda: jobs.create({"name": "Born done", "state": "done"})
            )
            results.append(
                check("creating a record already done is refused", ok, detail)
            )
            cr.rollback()

            job = jobs.create({"name": "By the book"})
            job.request_validation()
            job.with_user(reviewer_id).validate_tier()
            job.invalidate_recordset()
            job.write({"state": "done"})
            results.append(
                check("an approved record goes through", job.state == "done")
            )
            cr.rollback()

        # --- changing the transition -----------------------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cast("Any", env["builder.approval"]).update_gate(
                package_id, model_name, "state", False, ["in_progress", "done"], False
            )
            cr.commit()

        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, staff_id, {})
            jobs = cast("Any", env[model_name])
            results.append(
                check(
                    "the changed transition is the live one",
                    jobs._state_from == ["draft"]
                    and jobs._state_to == ["in_progress", "done"],
                    "from %r to %r" % (jobs._state_from, jobs._state_to),
                )
            )
            job = jobs.create({"name": "Moved gate"})
            ok, detail = refused(lambda: job.write({"state": "in_progress"}))
            results.append(check("and it is what is refused now", ok, detail))
            cr.rollback()

        # --- and taking it out again -----------------------------------------
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cast("Any", env["builder.approval"]).disable_gate(package_id, model_name)
            cr.commit()

        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, staff_id, {})
            jobs = cast("Any", env[model_name])
            results.append(
                check(
                    "the mixin is gone after disabling",
                    "tier.validation" not in jobs._inherit_module,
                )
            )
            job = jobs.create({"name": "Free again"})
            job.write({"state": "done"})
            results.append(check("nothing is asked any more", job.state == "done"))
            results.append(
                check(
                    "the model is no longer offered in the rule picker",
                    model_name
                    not in cast("Any", env["tier.definition"])
                    .sudo()
                    ._get_tier_validation_model_names(),
                )
            )
            results.append(
                check(
                    "the rule itself was left alone",
                    bool(env["tier.definition"].sudo().browse(rule_id).exists()),
                )
            )
            with open(model_file) as handle:
                source = handle.read()
            results.append(
                check(
                    "the source carries no trace of the gate",
                    "tier.validation" not in source
                    and "_state_" not in source
                    and "def _create(" not in source,
                )
            )
            cr.rollback()
    finally:
        if os.path.isdir(pkg_path):
            shutil.rmtree(pkg_path)

    print()
    if all(results):
        print("RESULT: the gate holds, moves and comes out. ACCEPTED.")
        return 0
    print("RESULT: the approval gate did not behave as written.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Does an in-process re-import actually yield a clean registry?

This is the load-bearing assumption behind the studio's "Apply" step: that a
generated Python model file can be rewritten and re-imported inside a live
process, without a server restart. It cannot be a TransactionCase --
``_button_immediate_function`` (ir_module.py) raises outright when
``threading.current_thread().testing`` is set -- so it lives here, as a script
that drives real registries.

Two core facts make the naive approach silently wrong, which is why the probe
exists at all:

* ``load_openerp_module`` (odoo/modules/module.py) early-returns when
  ``odoo.addons.<name>`` is already in ``sys.modules``. So a plain
  ``button_immediate_upgrade`` re-runs the *data* files against the *old*
  Python classes and reports success.
* ``MetaModel.module_to_models`` (odoo/models.py) is append-only. Re-importing
  without clearing it registers every class a second time.

Run:  python app_builder_base/tests/e2e/probe_reimport.py -c odoo.conf -d <db>
Exit: 0 if the in-process path is sound, 1 if the studio must fall back to a
      process restart.
"""

import os
import shutil
import sys

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

PKG = "x_reimport_probe"
MODEL = "x.reimport.probe"

MANIFEST = """\
{
    "name": "Reimport Probe",
    "version": "18.0.1.0.0",
    "license": "AGPL-3",
    "depends": ["base"],
    "data": [],
}
"""

MODEL_SRC = """\
from odoo import fields, models


class ReimportProbe(models.Model):
    \"\"\"Reimport Probe.\"\"\"

    _name = "x.reimport.probe"
    _description = "Reimport Probe"

%s
"""


def model_source(field_names):
    body = "\n".join(
        '    %s = fields.Char(string="%s")' % (n, n.title()) for n in field_names
    )
    return MODEL_SRC % body


def write_package(root, field_names):
    pkg = os.path.join(root, PKG)
    os.makedirs(os.path.join(pkg, "models"), exist_ok=True)
    with open(os.path.join(pkg, "__manifest__.py"), "w") as fh:
        fh.write(MANIFEST)
    with open(os.path.join(pkg, "__init__.py"), "w") as fh:
        fh.write("from . import models\n")
    with open(os.path.join(pkg, "models", "__init__.py"), "w") as fh:
        fh.write("from . import probe\n")
    with open(os.path.join(pkg, "models", "probe.py"), "w") as fh:
        fh.write(model_source(field_names))
    return pkg


def reimport_module(name):
    """The mechanism under test: purge Python so the module is imported again."""
    prefix = "odoo.addons.%s" % name
    for mod in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
        del sys.modules[mod]
    odoo.models.MetaModel.module_to_models.pop(name, None)
    odoo.modules.module._get_manifest_cached.cache_clear()
    import importlib

    importlib.invalidate_caches()


def writable_addons_dir():
    for path in odoo.addons.__path__:
        if path.rstrip("/").endswith("custom") and os.access(path, os.W_OK):
            return path
    for path in odoo.addons.__path__:
        if os.access(path, os.W_OK):
            return path
    raise SystemExit("no writable addons directory on addons_path")


def columns(cr, table):
    cr.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    return {r[0] for r in cr.fetchall()}


def check(label, ok, detail=""):
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", label, detail and " -- " + detail))
    return ok


def main():
    odoo.tools.config.parse_config(sys.argv[1:])
    dbname = odoo.tools.config["db_name"]
    if not dbname:
        raise SystemExit("pass -d <database>")

    root = writable_addons_dir()
    print("addons dir: %s" % root)
    pkg_path = os.path.join(root, PKG)
    if os.path.isdir(pkg_path):
        shutil.rmtree(pkg_path)

    results = []
    try:
        # --- 1. install the package with one field -----------------------
        write_package(root, ["x_alpha"])
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["ir.module.module"].update_list()
            module = env["ir.module.module"].search([("name", "=", PKG)], limit=1)
            if not module:
                raise SystemExit("update_list did not see %s" % PKG)
            module.button_immediate_install()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            results.append(check("install: model in registry", MODEL in env))
            results.append(
                check("install: x_alpha present", "x_alpha" in env[MODEL]._fields)
            )

        # --- 2. rewrite the file, adding a field -------------------------
        write_package(root, ["x_alpha", "x_beta"])

        # --- 3. the control: an upgrade WITHOUT purging sys.modules ------
        # Documents the trap rather than asserting a requirement.
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["ir.module.module"].search(
                [("name", "=", PKG)], limit=1
            ).button_immediate_upgrade()
        naive = Registry(dbname)
        with naive.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            saw_beta_naively = "x_beta" in env[MODEL]._fields
        print(
            "  NOTE upgrade without purging sys.modules saw x_beta: %s"
            % saw_beta_naively
        )

        # --- 4. the mechanism under test ---------------------------------
        # Order is the whole trick. Purging sys.modules alone gets the new
        # class into the registry but leaves the table untouched, because
        # Registry.new only runs init_models for modules marked 'to upgrade'.
        # So: purge first so the import is fresh, *then* upgrade so the schema
        # actually follows. Doing it the other way round -- which is what the
        # naive control above does -- silently succeeds against stale classes.
        reimport_module(PKG)
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["ir.module.module"].search(
                [("name", "=", PKG)], limit=1
            ).button_immediate_upgrade()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            fields_now = env[MODEL]._fields
            results.append(
                check("reimport: x_alpha still present", "x_alpha" in fields_now)
            )
            results.append(
                check("reimport: x_beta now present", "x_beta" in fields_now)
            )

            cols = columns(cr, MODEL.replace(".", "_"))
            results.append(check("reimport: x_beta column created", "x_beta" in cols))

            klasses = [
                c
                for c in odoo.models.MetaModel.module_to_models.get(PKG, [])
                if getattr(c, "_name", None) == MODEL
            ]
            results.append(
                check(
                    "reimport: class registered exactly once",
                    len(klasses) == 1,
                    "found %d" % len(klasses),
                )
            )

            mro_hits = [
                c
                for c in type(env[MODEL]).__mro__
                if getattr(c, "_name", None) == MODEL
            ]
            results.append(
                check(
                    "reimport: no duplicate class in the MRO",
                    len(mro_hits) <= 2,
                    "mro carries %d" % len(mro_hits),
                )
            )

        # --- 5. what does REMOVING a field do to its column? -------------
        # Not an assertion about desired behaviour -- a measurement of the
        # hazard. If dropping a field from the generated .py takes the column
        # (and its data) with it, then every destructive spec diff has to emit
        # a pre-migration that renames the column aside first.
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env[MODEL].create({"x_alpha": "keep me", "x_beta": "DATA AT RISK"})
            cr.commit()

        write_package(root, ["x_alpha"])
        reimport_module(PKG)
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["ir.module.module"].search(
                [("name", "=", PKG)], limit=1
            ).button_immediate_upgrade()

        with Registry(dbname).cursor() as cr:
            survived = "x_beta" in columns(cr, MODEL.replace(".", "_"))
            if survived:
                cr.execute(
                    "SELECT x_beta FROM %s WHERE x_beta IS NOT NULL"
                    % MODEL.replace(".", "_")
                )
                rows = cr.fetchall()
            else:
                rows = []
        print(
            "  NOTE removing a field from the .py left its column: %s%s"
            % (survived, " (data intact)" if rows else "")
        )
        print(
            "       -> %s"
            % (
                "column survives; no pre-migration needed for removal"
                if survived
                else "COLUMN AND DATA DROPPED: destructive diffs need a pre-migration"
            )
        )
    finally:
        if os.path.isdir(pkg_path):
            shutil.rmtree(pkg_path)

    print()
    if all(results):
        print(
            "RESULT: in-process re-import is SOUND -- 'inproc' reload mode is viable."
        )
        return 0
    print("RESULT: in-process re-import is NOT sound -- fall back to 'restart' mode.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

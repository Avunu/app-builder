#!/usr/bin/env python
"""I2 -- does the database agree with the source we wrote?

For a Python-backed model the old round-trip invariant is false by
construction: the database is produced by class loading, not by the files being
compared. What replaces it is a prediction. ``expected_reflection`` reimplements
what ``_reflect_model_params`` / ``_reflect_field_params`` will write, and this
probe asserts the registry matches it after a real install in a fresh process.

Two subtleties that will bite if unstated, both encoded below:

* Only the keys reflection *maintains* may be compared. It UPSERTs those to the
  class's value on every ``init_models``; everything else -- compute, depends,
  domain, group_expand, tracking -- keeps whatever the row happened to hold.
* ``upsert_en`` writes only the ``en_US`` slot of a translated column, so the
  comparison has to run at ``lang=None`` or a translated database fails for a
  reason that has nothing to do with the code.

Run:  python app_builder_base/tests/e2e/probe_reflection.py -c odoo.conf -d <db>
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import TYPE_CHECKING, cast

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, and this block does
    # not need `initialize_sys_path` the way the REAL imports inside
    # `main()` do (see there for why those are deferred).
    #
    # `field_id` (an ir.model.fields One2many) reads as a messy union
    # pyright cannot iterate over -- cast at the two read sites below, the
    # same idiom every relational-field read uses (TYPING.md).
    from odoo.addons.base.models.ir_model import IrModelFields

PKG = "x_reflect_probe"
MODEL = "x.reflect.probe"

# Exactly the keys _reflect_field_params maintains. Anything outside this set
# is not a function of the class and must not be asserted.
REFLECTED_FIELD_KEYS = (
    "name",
    "field_description",
    "help",
    "ttype",
    "state",
    "relation",
    "store",
    "copied",
    "on_delete",
    "related",
    "readonly",
    "required",
    "selectable",
    "size",
    "translate",
    "relation_field",
    "currency_field",
)

MANIFEST = """\
{
    "name": "Reflection Probe",
    "version": "18.0.1.0.0",
    "license": "AGPL-3",
    "depends": ["base"],
    "data": [],
}
"""


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


def expected_reflection(spec):
    """What reflection will write, predicted from the spec alone."""
    from odoo.addons.app_builder_base.tools import modelspec

    expected = {}
    for spec_field in spec.fields:
        row = {
            "name": spec_field.name,
            "field_description": spec_field.string or spec_field.name,
            "help": spec_field.help or False,
            "ttype": spec_field.ttype,
            "state": "base",
            "relation": spec_field.comodel or False,
            "store": spec_field.is_stored,
            "readonly": bool(spec_field.readonly),
            "required": bool(spec_field.required),
            "related": spec_field.related or False,
            "relation_field": spec_field.inverse_name or False,
            "currency_field": spec_field.currency_field or False,
            "size": spec_field.size or 0,
            "translate": bool(spec_field.translate),
            "selectable": True,
        }
        if spec_field.ttype in modelspec.RELATIONAL:
            row["on_delete"] = spec_field.ondelete or (
                "set null" if spec_field.ttype == "many2one" else False
            )
        expected[spec_field.name] = row
    return expected


def actual_reflection(env, spec):
    # Deferred the same way `expected_reflection`'s own `modelspec` import
    # just above is: `initialize_sys_path` (called from `parse_config`,
    # inside `main()`) is what makes `odoo.addons.<name>` resolvable at
    # all, and this is a module-level function `main()` calls only after
    # that -- a top-level import here would run first and fail.
    from odoo.addons.base.models.ir_model import IrModel
    from odoo.addons.app_builder_base.tools import typed

    model = typed.model(env, IrModel).search([("model", "=", spec.name)], limit=1)
    rows = {}
    wanted = {f.name for f in spec.fields}
    for record in cast("IrModelFields", model.field_id):
        if record.name not in wanted:
            continue
        rows[record.name] = {
            key: record[key] for key in REFLECTED_FIELD_KEYS if key in record._fields
        }
    return model, rows


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
        from odoo.addons.base.models.ir_module import Module
        from odoo.addons.app_builder_base.tools import pycodegen, typed
        from odoo.addons.app_builder_base.tools.modelspec import (
            FieldSpec,
            ModelSpec,
            SelectionSpec,
        )

        spec = ModelSpec(
            name=MODEL,
            description="Reflection Probe",
            class_name="ReflectProbe",
            fields=(
                FieldSpec(name="name", ttype="char", string="Name", required=True),
                FieldSpec(name="note", ttype="text", string="Note", help="Some help"),
                FieldSpec(name="amount", ttype="float", string="Amount"),
                FieldSpec(name="flag", ttype="boolean", string="Flag"),
                FieldSpec(
                    name="partner_id",
                    ttype="many2one",
                    string="Partner",
                    comodel="res.partner",
                    ondelete="set null",
                ),
                FieldSpec(
                    name="state",
                    ttype="selection",
                    string="State",
                    selection=(
                        SelectionSpec("draft", "Draft", 10),
                        SelectionSpec("done", "Done", 20),
                    ),
                ),
            ),
        )

        os.makedirs(os.path.join(pkg_path, "models"), exist_ok=True)
        with open(os.path.join(pkg_path, "__manifest__.py"), "w") as fh:
            fh.write(MANIFEST)
        with open(os.path.join(pkg_path, "__init__.py"), "w") as fh:
            fh.write("from . import models\n")
        with open(os.path.join(pkg_path, "models", "__init__.py"), "w") as fh:
            fh.write("from . import probe\n")
        with open(os.path.join(pkg_path, "models", "probe.py"), "w") as fh:
            fh.write(pycodegen.render_model(spec))

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            typed.model(env, Module).update_list()
            module = typed.model(env, Module).search([("name", "=", PKG)], limit=1)
            if not module:
                raise SystemExit("update_list did not see %s" % PKG)
            module.button_immediate_install()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            # lang=None: upsert_en writes only the en_US slot of a translated
            # column, so any other language compares against a value reflection
            # never maintained.
            env = api.Environment(cr, SUPERUSER_ID, {"lang": None})
            results.append(check("model is in the registry", MODEL in env))

            model, actual = actual_reflection(env, spec)
            expected = expected_reflection(spec)

            results.append(
                check(
                    "ir_model.info == the class docstring",
                    model.info == spec.description,
                    "got %r" % model.info,
                )
            )

            missing = sorted(set(expected) - set(actual))
            results.append(
                check("every field reflected", not missing, "missing %s" % missing)
            )

            for name in sorted(set(expected) & set(actual)):
                diffs = {
                    key: (expected[name][key], actual[name].get(key))
                    for key in expected[name]
                    if key in actual[name] and expected[name][key] != actual[name][key]
                }
                results.append(
                    check(
                        "field %s reflects as predicted" % name,
                        not diffs,
                        "; ".join(
                            "%s expected %r got %r" % (k, v[0], v[1])
                            for k, v in diffs.items()
                        ),
                    )
                )

            base_states = {
                f.name: f.state
                for f in cast("IrModelFields", model.field_id)
                if f.name in expected
            }
            results.append(
                check(
                    "every field is state='base'",
                    set(base_states.values()) == {"base"},
                    "%s" % {k: v for k, v in base_states.items() if v != "base"},
                )
            )
    finally:
        if os.path.isdir(pkg_path):
            shutil.rmtree(pkg_path)

    print()
    if all(results):
        print("RESULT: the database agrees with the source (I2 holds).")
        return 0
    print("RESULT: reflection does NOT match the spec.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

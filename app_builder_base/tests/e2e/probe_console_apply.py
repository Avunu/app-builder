#!/usr/bin/env python
"""A field dropped on the console lands where it was dropped, after the reload.

The unit tests cover both halves of the gesture on a manual model, where no
reload is needed: the drop stages the field and anchors it, and placement
puts an existing column at the anchor. What they cannot cover is the step
in between -- ``action_apply`` writes the class, re-imports it and rebuilds
the registry, and ``_button_immediate_function`` refuses to run under a
test thread -- so the claim that the anchor survives a real Apply is only
provable here.

Three things are measured:

1. **The drop stages, and the canvas shows the ghost in place.** No
   ``ir.model.fields`` row, no column; a ``<widget name="app_builder_pending">``
   right after the field it was dropped after.
2. **Apply puts the real field exactly there.** In the view's arch and in
   the file on disk, immediately after the neighbour -- not wherever the
   balanced placement would have put it.
3. **Placement can be run again.** Under a ``restart`` reload the request
   dies between the reload and this step and the console runs it again; a
   second run finds the field already in the arch and does nothing.

Run:  python app_builder_base/tests/e2e/probe_console_apply.py -c odoo.conf -d <db>
"""

import os
import shutil
import sys

from lxml import etree

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry

PKG = "x_console_probe"
LABEL = "Console Job"
NEIGHBOUR = "user_id"
FIELD = "due_date"


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


def form_view(env, model_name):
    View = env["ir.ui.view"]
    return View.browse(View.default_view(model_name, "form"))


def next_after(arch, name):
    """The name of the node right after ``name`` in ``arch``, or ``None``."""
    node = arch.find(".//field[@name='%s']" % name)
    if node is None:
        return None
    following = node.getnext()
    return following.get("name") if following is not None else None


def form_arch_on_disk(pkg_path, model_name):
    """The form arch as the package wrote it, parsed out of its view file.

    ``.studio/backup`` holds the files as they were *before* the apply and
    is skipped, or the check would read the old form and call it drift.
    """
    for folder, dirs, names in os.walk(pkg_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if not name.endswith(".xml"):
                continue
            tree = etree.parse(os.path.join(folder, name))
            for record in tree.iter("record"):
                if record.get("model") != "ir.ui.view":
                    continue
                model = record.find("field[@name='model']")
                if model is None or model.text != model_name:
                    continue
                form = record.find("field[@name='arch']/form")
                if form is not None:
                    return form
    return None


def main():
    odoo.tools.config.parse_config(sys.argv[1:])
    dbname = odoo.tools.config["db_name"]
    if not dbname:
        raise SystemExit("pass -d <database>")
    # Only importable once the config has set the addons path.
    from odoo.addons.app_builder_base.tools import modelspec

    root = writable_addons_dir()
    pkg_path = os.path.join(root, PKG)
    if os.path.isdir(pkg_path):
        shutil.rmtree(pkg_path)

    results = []
    try:
        # --- an app to drop onto --------------------------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            package = env["studio.package"].create(
                {
                    "name": PKG,
                    "display_name_": "Console Probe",
                    "root_path": pkg_path,
                    "auto_commit": "off",
                }
            )
            # The console's Build-an-app flow calls the same RPC.
            built = env["studio.app.builder"].create_app_rpc(
                package.id, {"label": LABEL, "features": ["chatter", "user"]}
            )
            model_name = built["model"]
            package_id = package.id
            cr.commit()
        print("  built %s" % model_name)

        # --- 1. drop a new field after a real one ---------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            editor = env["studio.view.editor"]
            view = form_view(env, model_name)
            canvas = editor.canvas(view.id)
            token = next(
                t for t, n in canvas["nodes"].items() if n["name"] == NEIGHBOUR
            )
            result = editor.drop_at(
                view.id,
                package_id,
                {"token": token, "position": "after"},
                {
                    "kind": "new_field",
                    "values": {"ttype": "date", "field_description": "Due Date"},
                },
                expected_arch_version=canvas["arch_version"],
            )
            results.append(
                check(
                    "the drop is staged, not created",
                    result["staged"] is not None
                    and result["created"] is None
                    and result["staged"]["name"] == FIELD,
                )
            )
            results.append(
                check(
                    "no column exists yet",
                    FIELD not in env[model_name]._fields
                    and not env["ir.model.fields"].search_count(
                        [("model", "=", model_name), ("name", "=", FIELD)]
                    ),
                )
            )
            ghost_arch = etree.fromstring(result["canvas"]["arch"].encode())
            neighbour = ghost_arch.find(".//field[@name='%s']" % NEIGHBOUR)
            ghost = neighbour.getnext() if neighbour is not None else None
            results.append(
                check(
                    "the canvas shows a ghost right after the neighbour",
                    ghost is not None
                    and ghost.tag == "widget"
                    and ghost.get("name") == "app_builder_pending",
                )
            )
            results.append(
                check(
                    "the ghost is selected and listed as pending",
                    result["select"] == "p_%s" % FIELD
                    and any(
                        p["name"] == FIELD and p["placed"]
                        for p in result["canvas"]["pending"]
                    ),
                )
            )
            view.invalidate_recordset()
            results.append(
                check(
                    "the real arch has no ghost",
                    "app_builder_pending" not in view.get_combined_arch(),
                )
            )
            draft_id = result["staged"]["draft_id"]
            view_id = view.id
            cr.commit()

        # --- 2. apply: write, reload, place -----------------------------------
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            draft = env["studio.model.draft"].browse(draft_id)
            results.append(
                check(
                    "the draft survived the round trip with its anchor",
                    draft.exists() and FIELD in draft._anchors(),
                )
            )
            draft.action_apply()
            cr.commit()

        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            results.append(
                check("the field is a real column", FIELD in env[model_name]._fields)
            )
            view = env["ir.ui.view"].browse(view_id)
            arch = etree.fromstring(view.arch.encode())
            results.append(
                check(
                    "it sits exactly after the neighbour in the form arch",
                    next_after(arch, NEIGHBOUR) == FIELD,
                    "after %s comes %r" % (NEIGHBOUR, next_after(arch, NEIGHBOUR)),
                )
            )
            on_disk = form_arch_on_disk(pkg_path, model_name)
            results.append(
                check(
                    "and in the file on disk",
                    on_disk is not None and next_after(on_disk, NEIGHBOUR) == FIELD,
                    "a view edited live and not written is drift; on disk after "
                    "%s comes %r"
                    % (
                        NEIGHBOUR,
                        next_after(on_disk, NEIGHBOUR) if on_disk is not None else None,
                    ),
                )
            )
            results.append(
                check(
                    "the anchor is forgotten once the field is placed",
                    FIELD not in env["studio.model.draft"].browse(draft_id)._anchors(),
                )
            )
            history = env["studio.view.edit"].stack_for(view_id)
            results.append(
                check(
                    "the placement is in the view's history",
                    any("added %s" % FIELD in e["summary"] for e in history["undo"]),
                )
            )

            # --- 3. restart mode: placement runs again --------------------------
            draft = env["studio.model.draft"].browse(draft_id)
            spec = draft._spec()
            diff = modelspec.diff_specs(modelspec.without_field(spec, FIELD), spec)
            again = draft._place_in_views(spec, diff)
            view.invalidate_recordset()
            results.append(
                check(
                    "running placement again changes nothing",
                    not again and view.arch.count('name="%s"' % FIELD) == 1,
                )
            )
            cr.rollback()
    finally:
        if os.path.isdir(pkg_path):
            shutil.rmtree(pkg_path)

    ok = all(results)
    print(
        "RESULT: %s"
        % (
            "a dropped field lands where it was dropped, after the reload. ACCEPTED."
            if ok
            else "FAILED -- see above"
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

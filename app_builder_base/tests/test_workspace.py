# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The workspace: what the console's home and Changes pane read and do.

A package is listed with its health, created with every reason it could
fail to load checked first, and inventoried by what it owns -- and the
answers are dicts a screen can show, not recordsets.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, cast

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.base.models.ir_model import IrModel, IrModelFields
from odoo.addons.app_builder_base.models.studio_package_apply import StudioPackageApply
from odoo.addons.app_builder_base.models.studio_workspace import StudioWorkspace
from odoo.addons.app_builder_base.tools import typed

# `studio_package_apply` (the module, for `PROCESS_BOOT_ID`) stays a plain
# relative import -- only the class itself needs the fully-qualified form
# above, to share its `StudioPackage` parameter's identity with
# `common.py`'s own fully-qualified `make_package()` (TYPING.md's "Known
# traps": the same file is reachable under two pyright module identities,
# and a class from one is not assignable where the other is expected).
from ..models import studio_package_apply
from ..tools import gitrepo
from .common import StudioCase, raises

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs this at runtime.
    from odoo.sql_db import Cursor


def _git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


@tagged("post_install", "-at_install")
class TestWorkspace(StudioCase):
    def setUp(self):
        super().setUp()
        self.workspace = typed.model(self.env, StudioWorkspace)

    def _git_package(self, name="x_ws_git"):
        package = self.make_package(name=name)
        _git(package.root_path, "init", "-q")
        _git(package.root_path, "config", "user.email", "studio@example.com")
        _git(package.root_path, "config", "user.name", "Studio")
        package.invalidate_recordset(["is_git", "git_branch"])
        return package

    # -- packages ---------------------------------------------------------------

    def test_a_package_is_listed_with_its_health(self):
        package = self.make_package(name="x_ws_plain")
        listed = [p for p in self.workspace.packages() if p["id"] == package.id]
        self.assertEqual(len(listed), 1)
        entry = listed[0]
        self.assertTrue(entry["writable"])
        self.assertEqual(entry["module_state"], "installed")
        self.assertEqual(entry["reload_mode"], "inproc")
        self.assertNotIn("read_only", entry["health"])
        self.assertNotIn("not_installed", entry["health"])
        self.assertIn("no_git", entry["health"], "a plain directory is not a repo")
        self.assertEqual(
            entry["models"], {"python": 0, "frozen": 0, "extends": 0, "xml": 0}
        )
        self.assertIsNone(entry["applies"]["last"])

    def test_a_read_only_package_says_so(self):
        package = self.make_package(name="x_ws_ro", root_path=self.unwritable_path())
        entry = self.workspace.package(cast("int", package.id))
        self.assertFalse(entry["writable"])
        self.assertIn("read_only", entry["health"])

    def test_an_uninstalled_package_says_so(self):
        package = self.make_package(name="x_ws_noinst", installed=False)
        entry = self.workspace.package(cast("int", package.id))
        self.assertEqual(entry["module_state"], "unknown")
        self.assertIn("not_installed", entry["health"])

    def test_listing_reaps_an_abandoned_apply(self):
        package = self.make_package(name="x_ws_reap")
        Apply = typed.model(self.env, StudioPackageApply)
        apply = Apply._snapshot(package, {"__manifest__.py": "{}"}, stamp="1")
        apply.write({"boot_id": "gone"})
        cast("Cursor", self.env.cr).execute(
            "UPDATE studio_package_apply SET create_date = now() - interval '1 hour'"
            " WHERE id = %s",
            (apply.id,),
        )
        apply.invalidate_recordset()
        entry = self.workspace.package(cast("int", package.id))
        self.assertEqual(apply.state, "failed")
        self.assertIn("failed_apply", entry["health"])
        self.assertEqual(entry["applies"]["failed"], 1)
        last = entry["applies"]["last"]
        # `last` is `ApplyJSON | None`; `assertIn("failed_apply", ...)` above
        # already proves one exists here, but pyright cannot see that.
        assert last is not None
        self.assertEqual(last["id"], apply.id)
        self.assertTrue(last["can_rollback"])

    def test_git_state_is_counted(self):
        package = self._git_package()
        package.action_write_files()
        entry = self.workspace.package(cast("int", package.id))
        self.assertTrue(entry["git"]["is_git"])
        self.assertIn("uncommitted", entry["health"])
        self.assertGreater(entry["git"]["untracked"] + entry["git"]["dirty"], 0)

    # -- addons dirs and creation -----------------------------------------------------

    def test_addons_dirs_mark_core_and_never_offer_it(self):
        dirs = self.workspace.addons_dirs()
        self.assertTrue(dirs)
        kinds = {d["kind"] for d in dirs}
        self.assertIn("core", kinds)
        for entry in dirs:
            if entry["kind"] == "core":
                self.assertFalse(entry["writable"], entry["path"])

    def test_create_package_refuses_what_would_not_load(self):
        for values, needle in (
            ({"name": "Bad Name"}, "not a valid module name"),
            ({"name": "studio_customization"}, "reserved"),
            ({"name": "base"}, "already the name of a module"),
        ):
            with self.subTest(values=values), raises(self, UserError) as caught:
                self.workspace.create_package(values)
            self.assertIn(needle, str(caught.exception))
        # A directory off the addons path.
        with raises(self, UserError) as caught:
            self.workspace.create_package(
                {"name": "x_ws_elsewhere", "root_dir": tempfile.mkdtemp()}
            )
        self.assertIn("not on the addons path", str(caught.exception))

    def test_create_package_writes_a_module_that_odoo_can_see(self):
        writable = [
            d
            for d in self.workspace.addons_dirs()
            if d["writable"] and d["kind"] != "core"
        ]
        if not writable:
            self.skipTest("no writable addons directory on this server")
        root_dir = writable[0]["path"]
        name = "x_ws_created"
        target = os.path.join(root_dir, name)
        self.addCleanup(lambda: __import__("shutil").rmtree(target, ignore_errors=True))
        entry = self.workspace.create_package(
            {
                "name": name,
                "title": "Created here",
                "root_dir": root_dir,
                "git_init": True,
            }
        )
        self.assertEqual(entry["root_path"], target)
        self.assertTrue(os.path.isfile(os.path.join(target, "__manifest__.py")))
        self.assertTrue(entry["git"]["is_git"])
        self.assertIn("base", entry["depends"])
        # A second one with the same name is refused, and a non-empty dir too.
        with raises(self, UserError):
            self.workspace.create_package({"name": name, "root_dir": root_dir})
        self.env["studio.package"].browse(entry["id"]).unlink()
        with raises(self, UserError) as caught:
            self.workspace.create_package({"name": name, "root_dir": root_dir})
        self.assertIn("not empty", str(caught.exception))

    # -- inventory ------------------------------------------------------------------

    def test_inventory_groups_what_the_package_owns(self):
        package = self.make_package(name="x_ws_inv")
        self.build_demo_content(package)
        package.action_write_files()
        inventory = self.workspace.inventory(cast("int", package.id))
        models = {m["model"]: m for m in inventory["models"]}
        self.assertIn("x_studio_project", models)
        self.assertEqual(models["x_studio_project"]["source"], "xml")
        self.assertTrue(models["x_studio_project"]["in_registry"])
        self.assertIn("form", models["x_studio_project"]["views"])
        self.assertTrue(inventory["views"])
        self.assertTrue(inventory["actions"])
        self.assertEqual(inventory["menus"][0]["file"], "views/menus.xml")
        self.assertTrue(inventory["access"])
        for entry in inventory["views"]:
            self.assertEqual(entry["subject"], "x_studio_project")
        self.assertEqual(
            models["x_studio_project"]["counts"]["views"], len(inventory["views"])
        )

    def test_the_picker_separates_defined_from_extended(self):
        package = self.make_package(name="x_ws_pick")
        self.build_demo_content(package)
        # A manual field on a core model: the package extends res.partner.
        field_vals: dict[str, object] = {
            # `@tools.ormcache`-decorated methods read as `() -> Any` under
            # pyright (TYPING.md's "Known traps": a real stub gap in the
            # `decorator` package, not this codebase's to fix).
            "model_id": typed.model(self.env, IrModel)._get_id("res.partner"),  # pyright: ignore[reportCallIssue]
            "name": "x_ws_pick_extra",
            "ttype": "char",
            "field_description": "Pick extra",
            "studio_package_id": package.id,
        }
        typed.model(self.env, IrModelFields).create(field_vals)  # pyright: ignore[reportArgumentType]
        picker = self.workspace.models_for_picker(cast("int", package.id))
        self.assertIn("x_studio_project", [m["model"] for m in picker["defined"]])
        self.assertIn("res.partner", [m["model"] for m in picker["extended"]])
        self.workspace.remember_model("res.partner")
        self.assertEqual(
            self.workspace.models_for_picker(cast("int", package.id))["recent"][0][
                "model"
            ],
            "res.partner",
        )

    # -- changes ---------------------------------------------------------------------

    def test_changes_reports_drift_and_git(self):
        package = self._git_package(name="x_ws_changes")
        self.build_demo_content(package)
        package.action_write_files()
        self.assertTrue(
            self.workspace.commit(cast("int", package.id), "first")["committed"]
        )
        path = os.path.join(cast("str", package.root_path), "views/menus.xml")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("<!-- by hand -->\n")
        changes = self.workspace.changes(cast("int", package.id))
        self.assertEqual([d["path"] for d in changes["drift"]], ["views/menus.xml"])
        self.assertEqual(changes["drift"][0]["status"], "edited")
        self.assertEqual(
            [s["path"] for s in changes["git"]["status"]], ["views/menus.xml"]
        )
        self.assertEqual(changes["git"]["log"][0]["subject"], "first")
        diff = self.workspace.git_diff(cast("int", package.id), "views/menus.xml")[
            "diff"
        ]
        self.assertIn("by hand", diff)
        drift = self.workspace.drift_diff(cast("int", package.id), "views/menus.xml")[
            "diff"
        ]
        self.assertIn("by hand", drift)

    def test_git_status_is_package_relative_in_a_larger_repository(self):
        top = tempfile.mkdtemp(prefix="studio-test-repo-")
        _git(top, "init", "-q")
        root = os.path.join(top, "custom", "x_ws_nested")
        os.makedirs(root)
        package = self.make_package(name="x_ws_nested", root_path=root)
        package.action_write_files()
        with open(os.path.join(top, "elsewhere.txt"), "w") as handle:
            handle.write("not ours")
        status = self.workspace.changes(cast("int", package.id))["git"]["status"]
        paths = [s["path"] for s in status]
        self.assertIn("__manifest__.py", paths)
        self.assertNotIn("elsewhere.txt", paths)
        self.assertFalse(any(p.startswith("custom/") for p in paths))

    def test_commit_needs_a_message_and_a_repository(self):
        plain = self.make_package(name="x_ws_nogit")
        self.assertFalse(self.workspace.commit(cast("int", plain.id), "m")["committed"])
        package = self._git_package(name="x_ws_msg")
        with raises(self, UserError):
            self.workspace.commit(cast("int", package.id), "   ")

    def test_git_init_makes_a_repository(self):
        package = self.make_package(name="x_ws_init")
        self.assertFalse(package.is_git)
        self.assertTrue(self.workspace.git_init(cast("int", package.id))["is_git"])
        self.assertTrue(gitrepo.is_repo(cast("str", package.root_path)))

    # -- the user ---------------------------------------------------------------------

    def test_preferences_are_per_user_and_whitelisted(self):
        self.workspace.set_user_pref("last_package_id", 42)
        self.assertEqual(self.workspace.user_prefs()["last_package_id"], 42)
        with raises(self, UserError):
            self.workspace.set_user_pref("anything", 1)
        other = self.make_user("ws_other", ["app_builder_base.group_studio_user"])
        self.assertIsNone(
            self.workspace.with_user(other).user_prefs()["last_package_id"]
        )

    def test_the_checklist_reads_what_exists(self):
        self.assertFalse(any(self.workspace.checklist().values()))
        package = self._git_package(name="x_ws_check")
        self.build_demo_content(package)
        package.action_write_files()
        checklist = self.workspace.checklist(cast("int", package.id))
        self.assertTrue(checklist["package"])
        self.assertFalse(checklist["app"], "a data-records model is not an app yet")
        self.assertTrue(checklist["field"], "manual fields are owned")
        self.assertFalse(checklist["automation"])
        self.assertFalse(checklist["commit"])
        self.workspace.commit(cast("int", package.id), "done")
        self.assertTrue(self.workspace.checklist(cast("int", package.id))["commit"])

    # -- guards ---------------------------------------------------------------------

    def test_reads_need_a_builder_and_writes_a_manager(self):
        package = self.make_package(name="x_ws_guard")
        builder = self.make_user("ws_builder", ["app_builder_base.group_studio_user"])
        nobody = self.make_user("ws_nobody", ["base.group_user"])
        as_builder = self.workspace.with_user(builder)
        self.assertTrue(as_builder.packages())
        with raises(self, AccessError):
            self.workspace.with_user(nobody).packages()
        for call in (
            lambda: as_builder.commit(cast("int", package.id), "m"),
            lambda: as_builder.write_files(cast("int", package.id)),
            lambda: as_builder.create_package({"name": "x_ws_nope"}),
            lambda: as_builder.git_init(cast("int", package.id)),
            lambda: as_builder.delete_records(cast("int", package.id)),
        ):
            with raises(self, AccessError):
                call()

    def test_the_boot_id_is_stamped_on_a_snapshot(self):
        package = self.make_package(name="x_ws_boot")
        apply = typed.model(self.env, StudioPackageApply)._snapshot(
            package, {"__manifest__.py": "{}"}, stamp="2"
        )
        self.assertEqual(apply.boot_id, studio_package_apply.PROCESS_BOOT_ID)

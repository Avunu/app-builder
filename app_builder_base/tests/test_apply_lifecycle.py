# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""An apply that writes without loading, and a snapshot that is honest.

Two things the console's Changes pane stands on. A server that runs
workers cannot reload a package in place, so an apply there writes the
files, commits them and stops as ``awaiting_restart`` -- the restart the
user is told about is what makes the change live, and there is nothing
to restore because nothing was loaded. And a draft's rewritten source
goes through the apply as an overlay rather than being written ahead of
it, so the snapshot records the bytes the file *had* and a rollback puts
those back rather than the change itself.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import config

from odoo.addons.app_builder_base.models.builder_model_draft import BuilderModelDraft
from odoo.addons.app_builder_base.models.builder_package_apply import (
    BuilderPackageApply,
)
from odoo.addons.app_builder_base.models.builder_workspace import BuilderWorkspace
from odoo.addons.app_builder_base.tools import typed

from .common import BuilderCase, raises

if TYPE_CHECKING:
    # Only for the cast() calls below; with `from __future__ import
    # annotations` nothing here needs this at runtime. `BuilderPackageApply`
    # (above) is a real, top-level import -- every use of it is a runtime
    # `typed.model()` call -- but its sibling `BuilderPackageApplyFile` never
    # appears outside a `cast("BuilderPackageApplyFile", ...)` string, so it
    # stays TYPE_CHECKING-only, the same split `builder_package_model.py`'s
    # own comment on this file's `BuilderPackage` documents.
    from ..models.builder_package_apply import (
        BuilderPackageApplyFile,
    )


@tagged("post_install", "-at_install")
class TestApplyLifecycle(BuilderCase):
    def _python_package(self, name="x_life_pkg"):
        package = self.make_package(name=name)
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        return package

    def _source(self, package):
        with open(
            os.path.join(package.root_path, "models/x_builder_project.py"),
            encoding="utf-8",
        ) as handle:
            return handle.read()

    @contextlib.contextmanager
    def _no_reload(self, package):
        """An apply with its two forbidden steps stubbed: the reload, which
        cannot run in test mode, and the commit before it, which the test
        cursor refuses. Everything before and after them is real."""
        with (
            patch.object(
                type(package), "_reload_now", autospec=True, return_value=None
            ) as reload,
            patch.object(self.env.cr, "commit", return_value=None),
        ):
            yield reload

    def test_a_write_only_apply_stops_before_the_reload(self):
        package = self._python_package()
        before = self._source(package)
        with self._no_reload(package) as reload:
            apply = package.action_apply(reason="write only", reload=False)
        reload.assert_not_called()
        self.assertEqual(apply.state, "awaiting_restart")
        self.assertEqual(package.state, "synced")
        self.assertTrue(package.restart_required)
        self.assertEqual(
            self._source(package), before, "nothing changed, nothing to write"
        )

    def test_the_overlay_goes_through_the_snapshot(self):
        package = self._python_package(name="x_life_overlay")
        before = self._source(package)
        after = before.replace('string="Is Active"', 'string="Is Active?"')
        self.assertNotEqual(before, after)
        with self._no_reload(package):
            apply = package.action_apply(
                reason="overlay",
                reload=False,
                overlay={"models/x_builder_project.py": after},
            )
        self.assertEqual(self._source(package), after, "the overlay is what lands")
        entry = cast("BuilderPackageApplyFile", apply.file_ids).filtered(
            lambda f: f.path == "models/x_builder_project.py"
        )
        self.assertEqual(
            entry.content_before,
            before,
            "the snapshot must hold the bytes the file had, not the change",
        )
        backup = os.path.join(
            cast("str", apply.backup_path), "models/x_builder_project.py"
        )
        with open(backup, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_rollback_from_awaiting_restart_puts_the_old_bytes_back(self):
        package = self._python_package(name="x_life_rollback")
        before = self._source(package)
        after = before.replace('string="Budget"', 'string="Budget!"')
        self.assertNotEqual(before, after)
        with self._no_reload(package) as reload:
            apply = package.action_apply(
                reason="change",
                reload=False,
                overlay={"models/x_builder_project.py": after},
            )
            self.assertEqual(self._source(package), after)
            diff = typed.model(self.env, BuilderWorkspace).apply_diff(
                cast("int", apply.id), "models/x_builder_project.py"
            )
            self.assertIn("Budget!", diff["diff"], "before against the disk now")
            result = apply.action_rollback()
        reload.assert_called_once()
        self.assertEqual(result, {"rolled_back": True, "restart_required": False})
        self.assertEqual(apply.state, "rolled_back")
        self.assertEqual(self._source(package), before)
        self.assertFalse(package.restart_required)

    def test_a_rollback_with_nothing_recorded_is_refused(self):
        package = self._python_package(name="x_life_empty")
        vals: dict[str, object] = {
            "package_id": package.id,
            "state": "failed",
            "reason": "x",
        }
        apply = typed.model(self.env, BuilderPackageApply).create(vals)  # pyright: ignore[reportArgumentType]
        with raises(self, UserError):
            apply.action_rollback()

    def test_under_workers_every_apply_awaits_a_restart(self):
        package = self._python_package(name="x_life_workers")
        with patch.dict(config.options, {"workers": 4, "dev_mode": []}):
            package.invalidate_recordset(["reload_mode"])
            self.assertEqual(package.reload_mode, "manual")
            with self._no_reload(package) as reload:
                apply = package.action_apply(reason="under workers")
            reload.assert_not_called()
            self.assertEqual(apply.state, "awaiting_restart")
            # A rollback there restores and says the restart is still owed.
            with self._no_reload(package) as reload:
                result = apply.action_rollback()
            reload.assert_not_called()
            self.assertTrue(result["restart_required"])
            self.assertEqual(apply.state, "rolled_back")

    def test_a_draft_apply_under_workers_writes_and_stays_dirty(self):
        package = self._python_package(name="x_life_draft")
        Draft = typed.model(self.env, BuilderModelDraft)
        draft = Draft.browse(Draft.open_for_model("x_builder_project")["id"])
        draft.add_field({"name": "x_life_extra", "ttype": "char", "string": "Extra"})
        self.assertTrue(draft.dirty)
        with patch.dict(config.options, {"workers": 4, "dev_mode": []}):
            package.invalidate_recordset(["reload_mode"])
            with self._no_reload(package):
                result = draft.action_apply()
        self.assertEqual(result["state"], "awaiting_restart")
        self.assertTrue(result["restart_required"])
        self.assertFalse(result["applied"])
        self.assertIn(
            "x_life_extra", self._source(package), "written before the restart"
        )
        self.assertTrue(draft.dirty, "not live yet, so still pending")
        self.assertTrue(package.restart_required)

    def test_a_draft_apply_in_process_reports_applied(self):
        package = self._python_package(name="x_life_inproc")
        Draft = typed.model(self.env, BuilderModelDraft)
        draft = Draft.browse(Draft.open_for_model("x_builder_project")["id"])
        draft.add_field({"name": "x_life_more", "ttype": "char", "string": "More"})
        before = self._source(package)
        with (
            self._no_reload(package) as reload,
            patch.object(
                type(draft), "_place_in_views", autospec=True, return_value=True
            ),
        ):
            result = draft.action_apply()
        reload.assert_called_once()
        self.assertTrue(result["applied"])
        self.assertTrue(result["placed"])
        self.assertFalse(result["restart_required"])
        self.assertIn("x_life_more", self._source(package))
        self.assertFalse(draft.dirty, "the baseline moved with the file")
        apply = typed.model(self.env, BuilderPackageApply).browse(result["apply_id"])
        self.assertEqual(apply.state, "applied")
        entry = cast("BuilderPackageApplyFile", apply.file_ids).filtered(
            lambda f: f.path == "models/x_builder_project.py"
        )
        self.assertEqual(entry.content_before, before)

    def test_reload_from_disk_is_refused_under_workers(self):
        package = self._python_package(name="x_life_reload")
        with patch.dict(config.options, {"workers": 2, "dev_mode": []}):
            package.invalidate_recordset(["reload_mode"])
            with raises(self, UserError):
                package.action_reload()
            self.assertEqual(
                typed.model(self.env, BuilderWorkspace).reload(cast("int", package.id)),
                {"restart_required": True, "reloaded": False},
            )

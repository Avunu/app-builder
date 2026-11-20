# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What an apply promises about data, files and concurrency.

Each of these was a finding of the production-readiness audit: a promise
the apply made in a docstring or an error message and did not keep in
code. The pre-migration that never ran, the second writer nothing stopped,
the restart that loaded new Python onto an old schema.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import tempfile
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import psycopg2

from odoo import sql_db
from odoo.exceptions import UserError, ValidationError
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tools import config, file_path, mute_logger, sql
from odoo.tools.parse_version import parse_version

from odoo.addons.app_builder_base.models import builder_package
from odoo.addons.app_builder_base.models.builder_package_apply import (
    BuilderPackageApply,
)
from odoo.addons.app_builder_base.tools import atomicfile, migrationgen, typed
from odoo.addons.base.models.ir_config_parameter import IrConfigParameter
from odoo.addons.base.models.ir_model import IrModel, IrModelFields
from odoo.addons.base.models.ir_ui_view import View

from .common import BuilderCase, raises

if TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.sql_db import Cursor

OWNER = ".builder/owner"
IGNORE = ".builder/.gitignore"
BACKUPS = ".builder/backup"


@tagged("post_install", "-at_install")
class TestApplyIntegrity(BuilderCase):
    def _python_package(self, name="x_integ_pkg", **overrides):
        package = self.make_package(name=name, **overrides)
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        return package

    def _cr(self) -> Cursor:
        # `Environment.cr` is declared `BaseCursor` (TYPING.md, "Known traps").
        return cast("Cursor", self.env.cr)

    def _path(self, package, relative="models/x_builder_project.py"):
        return os.path.join(package.root_path, relative)

    def _read(self, package, relative="models/x_builder_project.py"):
        with open(self._path(package, relative), encoding="utf-8") as handle:
            return handle.read()

    def _put(self, package, relative, content):
        with open(self._path(package, relative), "w", encoding="utf-8") as handle:
            handle.write(content)

    def _drop_a_field(self, package, name="x_active_flag"):
        source = self._read(package)
        self.assertIn(name, source, "fixture must have the field to remove")
        kept = "\n".join(
            line
            for line in source.splitlines()
            if not line.strip().startswith("%s = fields." % name)
        )
        self._put(package, "models/x_builder_project.py", kept + "\n")

    @contextlib.contextmanager
    def _no_reload(self, package):
        """The reload cannot run in test mode, and the test cursor refuses
        the commit before it; everything around them is real."""
        with (
            patch.object(
                type(package), "_reload_now", autospec=True, return_value=None
            ) as reload,
            patch.object(self.env.cr, "commit", return_value=None),
        ):
            yield reload

    def _run_migration(self, source, installed_version):
        namespace: dict[str, object] = {}
        exec(compile(source, "pre-builder.py", "exec"), namespace)  # noqa: S102
        cast("Callable[[object, str], None]", namespace["migrate"])(
            self.env.cr, installed_version
        )

    def _age(self, apply, column="write_date"):
        self.env.flush_all()
        self._cr().execute(
            "UPDATE builder_package_apply SET %s = '2000-01-01' WHERE id = %%s"
            % column,
            (apply.id,),
        )
        apply.invalidate_recordset()

    # -- the pre-migration actually runs ----------------------------------

    def test_a_destructive_apply_moves_to_a_version_its_migration_runs_under(self):
        """Odoo runs ``migrations/<v>/pre-*`` only when ``installed < v <=
        manifest``. Filed under the installed version it never ran, and the
        column it existed to save was dropped."""
        package = self._python_package()
        module = self.register_module(cast("str", package.name))
        module.latest_version = "18.0.1.0.0"
        self.assertEqual(package.version, "18.0.1.0.0")
        row: dict[str, object] = {"x_name": "Kept", "x_active_flag": True}
        record = self.env["x_builder_project"].create(row)  # pyright: ignore[reportArgumentType]
        self.env.flush_all()
        self._drop_a_field(package)

        with self._no_reload(package):
            package.action_apply(reason="drop", allow_destructive=True, reload=False)

        self.assertEqual(package.version, "18.0.1.0.1")
        manifest = ast.literal_eval(self._read(package, "__manifest__.py"))
        self.assertEqual(manifest["version"], "18.0.1.0.1")
        scripts = os.listdir(self._path(package, "migrations/18.0.1.0.1"))
        self.assertEqual(len(scripts), 1)
        self.assertTrue(scripts[0].startswith("pre-builder-"))
        # Core's own comparison (odoo/modules/migration.py): installed < v
        # <= manifest.
        self.assertLess(parse_version("18.0.1.0.0"), parse_version("18.0.1.0.1"))
        self.assertLessEqual(
            parse_version("18.0.1.0.1"), parse_version(manifest["version"])
        )

        # And the script does what the apply said it would: the data is
        # still there, under a name a human can find.
        self._run_migration(
            self._read(package, "migrations/18.0.1.0.1/" + scripts[0]), "18.0.1.0.0"
        )
        columns = sql.table_columns(self.env.cr, "x_builder_project")
        kept = [c for c in columns if c.startswith("x_active_flag_builder_removed_")]
        self.assertEqual(len(kept), 1, sorted(columns))
        self.assertNotIn("x_active_flag", columns)
        self._cr().execute(
            'SELECT "%s" FROM x_builder_project WHERE id = %%s' % kept[0],
            (record.id,),
        )
        self.assertEqual(self._cr().fetchone(), (True,))

    def test_a_later_write_keeps_the_migration_the_restart_has_yet_to_run(self):
        """Only the destructive apply renders the script. Waiting for a
        restart, any ordinary write renders the package without it -- and a
        prune that took that for "deleted" left the bumped manifest to
        upgrade with no pre-migration: the column was dropped after all."""
        package = self._python_package(name="x_integ_keep")
        module = self.register_module(cast("str", package.name))
        module.latest_version = "18.0.1.0.0"
        self._drop_a_field(package)
        with self._no_reload(package):
            apply = package.action_apply(
                reason="drop", allow_destructive=True, reload=False
            )
        self.assertEqual(apply.state, "awaiting_restart")
        directory = self._path(package, "migrations/18.0.1.0.1")
        scripts = os.listdir(directory)
        self.assertEqual(len(scripts), 1)
        source = self._read(package, "migrations/18.0.1.0.1/" + scripts[0])

        package.action_write_files()  # what one more builder edit does
        package.action_write_files()  # and again, the file no longer tracked

        self.assertEqual(os.listdir(directory), scripts)
        self.assertEqual(
            self._read(package, "migrations/18.0.1.0.1/" + scripts[0]), source
        )
        manifest = ast.literal_eval(self._read(package, "__manifest__.py"))
        self.assertEqual(manifest["version"], "18.0.1.0.1")

    def test_the_new_version_clears_whatever_is_installed(self):
        package = self._python_package(name="x_integ_ver")
        module = self.register_module(cast("str", package.name))
        # Somebody raised the version by hand; the package row never heard.
        module.latest_version = "18.0.3.2.0"
        self.assertEqual(package._bump_version_for_migration(), "18.0.3.2.1")
        self.assertEqual(package.version, "18.0.3.2.1")

    def test_bump_version(self):
        self.assertEqual(migrationgen.bump_version("18.0.1.0.0"), "18.0.1.0.1")
        self.assertEqual(migrationgen.bump_version("1.0"), "1.1")
        self.assertEqual(migrationgen.bump_version("18.0.1.0.9"), "18.0.1.0.10")

    def test_one_migration_covers_every_model(self):
        """One script per apply. A script per model, all under the same
        path, left only the last model's renames."""
        package = self._python_package(name="x_integ_multi")
        rendered = package._render_pre_migration(
            {"res.partner": ("x_gone_a",), "res.users": ("x_gone_b",)},
            "20260101000000",
        )
        assert rendered is not None
        ast.parse(rendered)
        self.assertIn('ALTER TABLE "res_partner" RENAME COLUMN "x_gone_a"', rendered)
        self.assertIn('ALTER TABLE "res_users" RENAME COLUMN "x_gone_b"', rendered)
        self.assertIn("table_schema = current_schema()", rendered)

    def test_a_manual_many2many_keeps_its_links(self):
        """A many2many has no column: what goes with a manual one is its
        relation table, so that is what has to be renamed aside."""
        # Not adopted: the field has to be a manual one on a model the test
        # registry really has.
        package = self.make_package(name="x_integ_m2m")
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel).search(
            [("model", "=", "x_builder_project")]
        )
        relation = "x_integ_project_partner_rel"
        vals: dict[str, object] = {
            "name": "x_tag_ids",
            "field_description": "Tags",
            "ttype": "many2many",
            "relation": "res.partner",
            "model_id": model.id,
            "relation_table": relation,
            "column1": "project_id",
            "column2": "partner_id",
        }
        typed.model(self.env, IrModelFields).create(vals)  # pyright: ignore[reportArgumentType]
        self.assertEqual(sql.existing_tables(self.env.cr, [relation]), [relation])
        rendered = package._render_pre_migration(
            {"x_builder_project": ("x_budget", "x_tag_ids")}, "20260101000000"
        )
        assert rendered is not None
        self.assertIn('RENAME COLUMN "x_budget"', rendered)
        self.assertNotIn('RENAME COLUMN "x_tag_ids"', rendered)
        self._run_migration(rendered, "18.0.1.0.0")
        aside = relation + "_builder_removed_20260101000000"
        self.assertEqual(sql.existing_tables(self.env.cr, [relation, aside]), [aside])

    # -- files ------------------------------------------------------------

    def test_a_file_is_replaced_not_truncated(self):
        directory = tempfile.mkdtemp(prefix="builder-test-atomic-")
        target = os.path.join(directory, "sub", "a.py")
        atomicfile.write_text(target, "one\n")
        os.chmod(target, 0o640)
        inode = os.stat(target).st_ino
        atomicfile.write_text(target, "two\n")
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "two\n")
        self.assertNotEqual(os.stat(target).st_ino, inode, "renamed over")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o640)
        self.assertEqual(os.listdir(os.path.dirname(target)), ["a.py"])

    def test_a_rolled_back_transaction_puts_the_files_back(self):
        package = self._python_package(name="x_integ_undo")
        self.env.cr.postrollback.clear()  # as the commit of that request would
        relative = "views/x_builder_project_views.xml"
        before = self._read(package, relative)
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project")], limit=1
        )
        view.name = "%s (renamed)" % view.name
        package.action_write_files()
        self.assertNotEqual(self._read(package, relative), before)

        self.env.cr.postrollback.run()  # what Cursor.rollback() does

        self.assertEqual(self._read(package, relative), before)

    def test_several_writes_in_one_transaction_roll_back_to_the_first(self):
        """Odoo runs rollback hooks oldest first. One hook per write put
        the first write's "before" back and then the second's -- the
        intermediate bytes -- and recreated files the first had created."""
        package = self._python_package(name="x_integ_twice")
        self.env.cr.postrollback.clear()  # as the commit of that request would
        relative = "views/x_builder_project_views.xml"
        before = self._read(package, relative)
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project")], limit=1
        )
        name = view.name

        view.name = "%s (one)" % name
        package.action_write_files()
        package._write_files({"data/x_new.xml": "<odoo/>\n"})
        middle = self._read(package, relative)
        view.name = "%s (two)" % name
        package.action_write_files()
        package._write_files({"data/x_new.xml": "<odoo><!-- two --></odoo>\n"})
        self.assertNotIn(self._read(package, relative), (before, middle))

        self.env.cr.postrollback.run()  # what Cursor.rollback() does

        self.assertEqual(self._read(package, relative), before)
        self.assertFalse(os.path.exists(self._path(package, "data/x_new.xml")))

    def test_an_adoption_that_rolls_back_takes_its_python_with_it(self):
        package = self.make_package(name="x_integ_adopt_undo")
        self.build_demo_content(package)
        package.action_write_files()
        self.env.cr.postrollback.clear()  # as the commit of that request would
        self.assertFalse(os.path.exists(self._path(package)))

        package._write_adopted_source(["x_builder_project"])
        self.assertTrue(os.path.exists(self._path(package)))

        self.env.cr.postrollback.run()

        self.assertFalse(os.path.exists(self._path(package)))

    def test_an_apply_that_rolls_back_leaves_no_journal(self):
        """The journal is for a process that died. One whose transaction
        merely rolled back has restored its files already; a journal left
        behind is later read as a crash, and its "rollback" overwrites
        whatever has been applied since."""
        package = self._python_package(name="x_integ_nojournal")
        self.env.cr.postrollback.clear()  # as the commit of that request would
        Apply = typed.model(self.env, BuilderPackageApply)
        before = self._read(package)
        after = before.replace('string="Budget"', 'string="Budget!"')
        self.assertNotEqual(after, before)
        with (
            self._no_reload(package),
            patch.object(
                type(package), "_sync_file_records", side_effect=UserError("no")
            ),
            raises(self, UserError),
        ):
            package.action_apply(
                reason="fails",
                overlay={"models/x_builder_project.py": after},
            )
        builder_dir = self._path(package, ".builder")
        self.assertTrue(
            [n for n in os.listdir(builder_dir) if n.endswith(".json")],
            "the journal was there while the apply was in flight",
        )

        self.env.cr.postrollback.run()  # what Cursor.rollback() does

        self.assertEqual(self._read(package), before)
        self.assertFalse([n for n in os.listdir(builder_dir) if n.endswith(".json")])
        backups = os.path.join(builder_dir, "backup")
        self.assertFalse(os.path.isdir(backups) and os.listdir(backups))
        self.assertFalse(Apply._recover_journals(package))

    def test_the_builder_directory_keeps_itself_out_of_the_repository(self):
        package = self._python_package(name="x_integ_ignore")
        with self._no_reload(package):
            apply = package.action_apply(reason="x", reload=False)
        self.assertEqual(self._read(package, IGNORE), "*\n")
        self.assertEqual(self._read(package, OWNER).strip(), self._cr().dbname)
        self.assertFalse(
            [
                name
                for name in os.listdir(self._path(package, ".builder"))
                if name.endswith(".json")
            ],
            "the journal goes once the apply row is committed",
        )
        self.assertTrue(apply._backup_dir())

    # -- one apply at a time ------------------------------------------------

    def test_a_package_being_applied_refuses_a_second_writer(self):
        package = self._python_package(name="x_integ_lock")
        key = (self._cr().dbname, cast("int", package.id))
        builder_package._APPLYING[key] = -1  # some other thread
        self.addCleanup(builder_package._APPLYING.pop, key, None)
        with raises(self, UserError):
            package.action_apply(reason="second")
        with raises(self, UserError):
            package.action_write_files()
        builder_package._APPLYING.pop(key)
        with self._no_reload(package):
            package.action_apply(reason="alone")
        self.assertNotIn(key, builder_package._APPLYING, "released afterwards")

    def test_a_running_cron_stops_the_apply_before_anything_is_written(self):
        package = self._python_package(name="x_integ_cron")
        before = self._read(package)
        after = before.replace('string="Budget"', 'string="Budget!"')
        with (
            self._no_reload(package) as reload,
            patch.object(type(package), "_try_cron_lock", return_value=False),
            patch.object(builder_package, "CRON_LOCK_ATTEMPTS", 3),
            patch.object(builder_package.time, "sleep") as sleep,
            raises(self, UserError),
        ):
            package.action_apply(
                reason="cron", overlay={"models/x_builder_project.py": after}
            )
        reload.assert_not_called()
        self.assertEqual(sleep.call_count, 2, "retried, then gave up")
        self.assertEqual(self._read(package), before)
        self.assertFalse(package.apply_ids)

    def test_after_the_commit_each_attempt_at_the_cron_lock_is_a_new_snapshot(self):
        package = self._python_package(name="x_integ_fresh")
        stale = psycopg2.errors.SerializationFailure()
        with (
            patch.object(
                type(package), "_try_cron_lock", side_effect=[stale, False, True]
            ),
            patch.object(self.env.cr, "rollback") as rollback,
            patch.object(builder_package.time, "sleep") as sleep,
        ):
            package._acquire_cron_lock(fresh=True)
        self.assertEqual(rollback.call_count, 2, "a new snapshot per attempt")
        self.assertEqual(sleep.call_count, 1, "waits for a lock, not a snapshot")

    def test_no_cron_lock_after_the_commit_restores_without_reloading(self):
        package = self._python_package(name="x_integ_latecron")
        before = self._read(package)
        after = before.replace('string="Budget"', 'string="Budget!"')
        self.assertNotEqual(after, before)
        with (
            self._no_reload(package) as reload,
            patch.object(
                type(package),
                "_acquire_cron_lock",
                side_effect=[None, UserError("a cron runs")],
            ),
            raises(self, UserError),
        ):
            package.action_apply(
                reason="late cron",
                overlay={"models/x_builder_project.py": after},
            )
        reload.assert_not_called()
        self.assertEqual(self._read(package), before)

    # -- a restart that creates the schema ----------------------------------

    def test_under_workers_the_restart_is_made_to_upgrade(self):
        """A plain boot imports new Python and upgrades nothing -- unless
        the module is marked, which any registry load then honours."""
        package = self._python_package(name="x_integ_workers")
        module = self.register_module(cast("str", package.name))
        with patch.dict(config.options, {"workers": 4, "dev_mode": []}):
            package.invalidate_recordset(["reload_mode"])
            with self._no_reload(package) as reload:
                apply = package.action_apply(reason="under workers")
            reload.assert_not_called()
        self.assertEqual(apply.state, "awaiting_restart")
        self.assertEqual(module.state, "to upgrade")
        self.assertIn("marked for upgrade", apply.restart_hint or "")
        # Core's cron runner skips a database with a module in `to upgrade`.
        self.assertIn("scheduled actions", apply.restart_hint or "")

    def test_under_workers_a_first_install_happens_in_place(self):
        package = self._python_package(name="x_integ_first")
        self.register_module(cast("str", package.name)).state = "uninstalled"
        with patch.dict(config.options, {"workers": 4, "dev_mode": []}):
            package.invalidate_recordset(["reload_mode"])
            self.assertEqual(package.reload_mode, "manual")
            self.assertTrue(package._can_install_in_place())
            with self._no_reload(package) as reload:
                apply = package.action_apply(reason="first install")
            reload.assert_called_once()
        self.assertEqual(apply.state, "applied")

    def test_a_restart_without_the_upgrade_is_noticed(self):
        package = self._python_package(name="x_integ_settle")
        module = self.register_module(cast("str", package.name))
        Apply = typed.model(self.env, BuilderPackageApply)
        vals: dict[str, object] = {
            "package_id": package.id,
            "state": "awaiting_restart",
            "reason": "x",
        }
        apply = Apply.create(vals)  # pyright: ignore[reportArgumentType]
        # Core resets the mark once crons have waited five hours; a stale
        # worker's registry rebuild consumes it. The row still says an
        # upgrade is owed, so the mark is put back before the restart.
        self.assertEqual(module.state, "installed")
        Apply._reap_abandoned(package)
        self.assertEqual(apply.state, "awaiting_restart", "no restart yet")
        self.assertEqual(module.state, "to upgrade", "the lost mark is back")
        self.assertIn("scheduled actions", apply.restart_hint or "")

        # Lost again, and this time the restart happens without it.
        module.state = "installed"
        self._age(apply)
        with patch.object(
            type(package), "_schema_behind", return_value=["x_builder_project.x_new"]
        ):
            Apply._reap_abandoned(package)
        self.assertEqual(apply.state, "awaiting_restart")
        self.assertIn("-u x_integ_settle", apply.restart_hint or "")
        self.assertEqual(module.state, "to upgrade", "marked again")

        module.state = "installed"
        self._age(apply)
        self.assertEqual(package._schema_behind(), [], "the fixture's schema is whole")
        Apply._reap_abandoned(package)
        self.assertEqual(apply.state, "applied")
        self.assertFalse(package.restart_required)

    # -- several databases in one process -----------------------------------

    def test_another_database_using_the_package_forbids_a_reload_in_place(self):
        package = self._python_package(name="x_integ_multidb")
        registries = cast("Any", Registry.registries)
        registries.d["x_integ_other_db"] = SimpleNamespace(_init_modules={package.name})
        self.addCleanup(registries.d.pop, "x_integ_other_db", None)
        package.invalidate_recordset(["reload_mode"])
        self.assertEqual(package.reload_mode, "manual")
        with raises(self, UserError) as caught:
            package._reload_now()
        self.assertIn("x_integ_other_db", str(caught.exception))
        with self._no_reload(package) as reload:
            apply = package.action_apply(reason="two databases")
        reload.assert_not_called()
        self.assertEqual(apply.state, "awaiting_restart")

    def test_a_directory_another_loaded_database_writes_is_refused(self):
        package = self._python_package(name="x_integ_owner")
        registries = cast("Any", Registry.registries)
        registries.d["x_integ_other_db"] = SimpleNamespace(_init_modules=set())
        self.addCleanup(registries.d.pop, "x_integ_other_db", None)
        self._put(package, OWNER, "x_integ_other_db\n")
        with raises(self, UserError) as caught:
            package.action_write_files()
        self.assertIn("x_integ_other_db", str(caught.exception))
        # A database this server is not serving: the directory changes hands.
        self._put(package, OWNER, "x_integ_gone_db\n")
        package.action_write_files()
        self.assertEqual(self._read(package, OWNER).strip(), self._cr().dbname)

    # -- crash recovery -------------------------------------------------------

    def test_an_apply_that_died_before_its_commit_is_recovered(self):
        """The apply row commits after the files are written. A process
        killed in between left a half-written package and no row at all."""
        package = self._python_package(name="x_integ_journal")
        Apply = typed.model(self.env, BuilderPackageApply)
        before = self._read(package)
        files = {
            "models/x_builder_project.py": before + "# half\n",
            "models/x_new_thing.py": "# new\n",
        }
        lost = Apply._snapshot(package, files, reason="crash", stamp="20260101000000")
        journal = self._path(package, ".builder/apply-20260101000000.json")
        self.assertTrue(os.path.isfile(journal))
        package._write_files(files)
        lost.unlink()  # what the dead process's transaction amounts to

        self.assertFalse(Apply._recover_journals(package), "this process, in flight")
        with open(journal, encoding="utf-8") as handle:
            data = json.load(handle)
        data["boot_id"] = "another-process"
        with open(journal, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertFalse(Apply._recover_journals(package), "too young to be abandoned")
        os.utime(journal, (0, 0))

        Apply._reap_abandoned(package)

        recovered = Apply.search([("package_id", "=", package.id)])
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered.state, "failed")
        self.assertIn("stopped", recovered.error or "")
        self.assertFalse(os.path.exists(journal))
        with self._no_reload(package):
            recovered.action_rollback()
        self.assertEqual(self._read(package), before)
        self.assertFalse(os.path.exists(self._path(package, "models/x_new_thing.py")))
        Apply._reap_abandoned(package)
        self.assertEqual(len(Apply.search([("package_id", "=", package.id)])), 1)

    # -- retention ------------------------------------------------------------

    def test_old_applies_and_their_backups_are_vacuumed(self):
        package = self._python_package(name="x_integ_gc")
        Apply = typed.model(self.env, BuilderPackageApply)
        root = cast("str", package.root_path)
        records = Apply.browse()
        for index, state in enumerate(("applied", "failed", "rolled_back", "pending")):
            backup = os.path.join(root, BACKUPS, "2026010100000%d" % index)
            os.makedirs(backup)
            vals: dict[str, object] = {
                "package_id": package.id,
                "state": state,
                "backup_path": backup,
            }
            records |= Apply.create(vals)  # pyright: ignore[reportArgumentType]
        orphan = os.path.join(root, BACKUPS, "19990101000000")
        os.makedirs(orphan)
        os.utime(orphan, (0, 0))
        self.env.flush_all()
        for offset, record in enumerate(records):
            self._cr().execute(
                "UPDATE builder_package_apply"
                " SET create_date = now() - interval '90 days'"
                " + %s * interval '1 hour' WHERE id = %s",
                (offset, record.id),
            )
        records.invalidate_recordset()
        params = typed.model(self.env, IrConfigParameter).sudo()
        params.set_param("app_builder_base.apply_keep", "1")
        params.set_param("app_builder_base.apply_keep_days", "30")

        Apply._gc_old_applies()

        self.assertEqual(
            sorted(records.exists().mapped("state")),
            ["pending", "rolled_back"],
            "the newest finished apply and the one in flight stay",
        )
        self.assertEqual(
            sorted(os.listdir(os.path.join(root, BACKUPS))),
            ["20260101000002", "20260101000003"],
        )

    def test_a_backup_path_outside_the_package_is_never_removed(self):
        package = self._python_package(name="x_integ_backup")
        elsewhere = tempfile.mkdtemp(prefix="builder-test-elsewhere-")
        vals: dict[str, object] = {
            "package_id": package.id,
            "state": "applied",
            "backup_path": elsewhere,
        }
        apply = typed.model(self.env, BuilderPackageApply).create(vals)  # pyright: ignore[reportArgumentType]
        with mute_logger("odoo.addons.app_builder_base.models.builder_package_apply"):
            self.assertIsNone(apply._backup_dir())
            apply.action_discard_backup()
        self.assertTrue(os.path.isdir(elsewhere))

    # -- where a package may live -----------------------------------------------

    def test_root_path_is_constrained_whoever_writes_it(self):
        import odoo.addons

        package = self.make_package(name="x_integ_root")
        core = os.path.dirname(os.path.dirname(os.path.realpath(odoo.__file__)))
        addons_dir = os.path.realpath(odoo.addons.__path__[0])
        for bad in (
            "relative/x_integ_root",
            "/tmp/../tmp/x_integ_root",
            os.path.join(core, "odoo", "addons", "x_integ_root"),
            addons_dir,
            os.path.dirname(addons_dir),
        ):
            with raises(self, ValidationError), self.env.cr.savepoint():
                package.write({"root_path": bad})

    def test_outside_tests_a_package_lives_on_the_addons_path(self):
        import odoo.addons

        core = os.path.dirname(os.path.dirname(os.path.realpath(odoo.__file__)))
        outside_core = [
            real
            for real in (os.path.realpath(p) for p in odoo.addons.__path__)
            if not real.startswith(core + os.sep)
        ]
        package = self.make_package(name="x_integ_strict")
        with patch.object(builder_package, "_strict_root_path", return_value=True):
            with raises(self, ValidationError), self.env.cr.savepoint():
                package.write({"root_path": tempfile.mkdtemp(prefix="builder-test-")})
            if not outside_core:
                self.skipTest("no addons directory outside core in this environment")
            with raises(self, ValidationError), self.env.cr.savepoint():
                package.write(
                    {"root_path": os.path.join(outside_core[0], "other_name")}
                )
            package.write(
                {"root_path": os.path.join(outside_core[0], "x_integ_strict")}
            )

    # -- licence ----------------------------------------------------------------

    def test_a_generated_package_is_not_agpl_by_default(self):
        package = self.make_package(name="x_integ_license")
        self.assertEqual(package.license, "LGPL-3")
        self.build_demo_content(package)
        package.action_write_files()
        manifest = ast.literal_eval(self._read(package, "__manifest__.py"))
        self.assertEqual(manifest["license"], "LGPL-3")
        package.license = "OPL-1"
        package.action_write_files()
        manifest = ast.literal_eval(self._read(package, "__manifest__.py"))
        self.assertEqual(manifest["license"], "OPL-1")
        with raises(self, ValueError):
            package.license = "Whatever-1.0"

    # -- the builder's own lifecycle ----------------------------------------------

    def test_the_first_supported_schema_says_what_it_does_not_carry_over(self):
        """The convention for the builder's own upgrades, exercised: a
        script under ``migrations/<version>/`` that Odoo can load and run."""
        path = file_path("app_builder_base/migrations/18.0.2.0.0/pre-migration.py")
        namespace: dict[str, Any] = {"__name__": "pre_migration"}
        with open(path, encoding="utf-8") as handle:
            exec(compile(handle.read(), path, "exec"), namespace)  # noqa: S102
        namespace["migrate"](self.env.cr, None)  # a fresh install: nothing to say
        self.assertEqual(namespace["legacy_tables"](self.env.cr), [])
        self._cr().execute("CREATE TABLE studio_package (id integer)")
        self.assertEqual(namespace["legacy_tables"](self.env.cr), ["studio_package"])
        with self.assertLogs("pre_migration", level="WARNING") as logs:
            namespace["migrate"](self.env.cr, "18.0.1.6.0")
        self.assertIn("first supported schema", logs.output[0])

    def test_uninstalling_names_the_packages_it_orphans(self):
        from odoo.addons import app_builder_base

        installed = self.make_package(name="x_integ_uninst_a")
        self.build_demo_content(installed)
        loose = self.make_package(name="x_integ_uninst_b", installed=False)
        view_vals: dict[str, object] = {
            "name": "x_integ.loose",
            "model": "res.partner",
            "type": "form",
            "arch": "<form><field name='name'/></form>",
        }
        loose.builder_capture(typed.model(self.env, View).create(view_vals))  # pyright: ignore[reportArgumentType]
        with self.assertLogs("odoo.addons.app_builder_base", level="WARNING") as logs:
            app_builder_base.uninstall_hook(self.env)
        text = "\n".join(logs.output)
        self.assertIn("x_integ_uninst_b", text)
        self.assertNotIn("x_integ_uninst_a", text)
        self.assertEqual(loose._warn_orphans_on_uninstall(), ["x_integ_uninst_b"])


@tagged("post_install", "-at_install")
class TestCronLockSnapshot(BuilderCase):
    """Alone in its class on purpose: it ends with this transaction's
    snapshot older than a committed ``ir_cron`` row, and a test class
    shares one transaction between its tests."""

    def test_a_cron_that_has_finished_is_not_taken_for_one_that_runs(self):
        """Two real transactions. A cursor is REPEATABLE READ: once the
        scheduled action has committed its row, locking it from an older
        snapshot fails for good -- with a serialization failure, which is
        not "somebody holds the lock"."""
        package = self.make_package(name="x_integ_snapshot")
        # `Environment.cr` is declared `BaseCursor` (TYPING.md, "Known traps").
        cr = cast("Cursor", self.env.cr)
        cr.execute("SELECT id FROM ir_cron ORDER BY id LIMIT 1")
        (cron_id,) = cast("tuple[int]", cr.fetchone())
        other = sql_db.db_connect(cast("str", cr.dbname)).cursor()
        self.addCleanup(other.close)
        other.execute(
            "SELECT id FROM ir_cron WHERE id = %s FOR UPDATE NOWAIT", (cron_id,)
        )

        self.assertFalse(package._try_cron_lock(), "a cron is running: wait")

        # The cron finishes the way core's runner does: its own row, then
        # commit. (The value does not change; the row version does.)
        other.execute(
            "UPDATE ir_cron SET priority = priority WHERE id = %s", (cron_id,)
        )
        other.commit()

        with raises(self, psycopg2.errors.SerializationFailure):
            package._try_cron_lock()
        # Before the write there is a transaction to keep: Odoo retries the
        # request on this error, so it is passed on, not waited out.
        with (
            patch.object(builder_package.time, "sleep") as sleep,
            raises(self, psycopg2.errors.SerializationFailure),
        ):
            package._acquire_cron_lock()
        sleep.assert_not_called()

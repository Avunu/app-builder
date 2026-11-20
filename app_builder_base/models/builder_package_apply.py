# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One record per attempt to write a package to disk and reload it.

Module operations commit. ``_button_immediate_function`` commits before
rebuilding the registry and again after, so a failure halfway through is not
rolled back by the ORM -- and if the new Python does not import, the *next*
request re-imports the same broken file, which makes the whole database
unbootable for every user, not just the one who pressed the button.

So an apply is a small state machine with its bytes kept twice: in this record,
and under ``.builder/backup/<timestamp>/`` on disk. The on-disk copy is the one
that matters when the process dies mid-reload and nothing can run a rollback --
recovery is then ``git checkout`` or copying the backup back, from a shell.

The record itself is not durable until the apply's own commit, which comes
*after* the files are written. For that window there is a journal beside the
backup (``.builder/apply-<timestamp>.json``): written before the first file,
removed after the commit. One found later with no record to match is an apply
the process died in the middle of, and it is turned back into a record --
with a rollback on offer -- the next time the workspace is read.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config as tools_config

from odoo.addons.base.models.ir_config_parameter import IrConfigParameter
from odoo.addons.base.models.ir_module import Module as IrModuleModule

from ..tools import atomicfile, typed
from ..tools.i18n import _
from .builder_package import BUILDER_DIR, BuilderPackage, _mute_dev_watcher

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs this at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.sql_db import Cursor

_logger = logging.getLogger(__name__)

BACKUP_DIR = ".builder/backup"
JOURNAL_PREFIX = "apply-"
JOURNAL_SUFFIX = ".json"

# One per process, minted at import. An apply records the id of the process
# that started it; a 'pending' row from any other process is one whose step
# 7 never ran, because the process is gone. Under a prefork server every
# worker has an id of its own, which is why age is checked as well: a row a
# sibling worker created a moment ago is not abandoned, it is in progress.
PROCESS_BOOT_ID = uuid.uuid4().hex
PROCESS_BOOT_TIME = fields.Datetime.now()
ABANDONED_AFTER = timedelta(minutes=2)

# Applies that are over: nothing will read their snapshot again except a
# human looking at history, or a late rollback.
FINISHED_STATES = ("applied", "rolled_back", "failed")
# Retention, overridable per database (`ir.config_parameter`). An apply is
# removed only when it is BOTH beyond the newest `keep` of its package AND
# older than `days`: a busy afternoon does not eat last week's rollback, and
# a quiet package keeps its short history for ever.
KEEP_PARAM = "app_builder_base.apply_keep"
DAYS_PARAM = "app_builder_base.apply_keep_days"
DEFAULT_KEEP = 20
DEFAULT_DAYS = 30


def _server_started_at() -> datetime:
    """When the *server* this process belongs to started.

    Under a prefork server a worker is recycled now and then, and a fresh
    worker is not a restarted server: its siblings still hold the Python
    they imported before. The master's start time is the one that says
    "every process here is newer than this". Anywhere else it is this
    process's own.
    """
    if tools_config["workers"]:
        try:
            import psutil

            started = psutil.Process(os.getppid()).create_time()
            return datetime.fromtimestamp(started, timezone.utc).replace(tzinfo=None)
        except Exception:  # pragma: no cover - psutil is an Odoo dependency
            _logger.debug("Could not read the server start time", exc_info=True)
    return PROCESS_BOOT_TIME


class BuilderPackageApply(models.Model):
    _name = "builder.package.apply"
    _description = "Builder Package Apply"
    _order = "create_date desc, id desc"

    # No typed-relation declaration here -- traced and confirmed not to
    # work under this real OCB/pyright combination (TYPING.md's own "Known
    # traps"); every real read below goes through `cast("BuilderPackage",
    # self.package_id)` instead.
    package_id: fields.Many2one[Any] = fields.Many2one(
        "builder.package", required=True, ondelete="cascade", index=True
    )
    reason = fields.Char()
    state = fields.Selection(
        [  # pyright: ignore[reportArgumentType] -- `Selection.__init__`'s own
            # `selection` parameter carries no annotation of its own, only a
            # `SENTINEL` default; a real, traced vendor-stub gap, not fixable
            # from this side (TYPING.md's own "Known traps").
            ("pending", "Pending"),
            ("applied", "Applied"),
            # Written to disk and committed, not reloaded: the server runs
            # workers and cannot reload in place, so the change is live
            # once the server has been restarted -- nothing to restore.
            ("awaiting_restart", "Awaiting restart"),
            ("failed", "Failed"),
            ("rolled_back", "Rolled back"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    error = fields.Text(readonly=True)
    restart_hint = fields.Text(
        readonly=True,
        help="What the restart an apply is waiting for has to be: a plain "
        "one, or one with -u.",
    )
    backup_path = fields.Char(readonly=True)
    boot_id = fields.Char(readonly=True, help="The process that started the apply.")
    # Same "no typed-relation declaration" rule as `package_id` above.
    file_ids: fields.One2many[Any] = fields.One2many(
        "builder.package.apply.file", "apply_id"
    )

    # -- snapshot ---------------------------------------------------------

    @api.model
    def _snapshot(
        self,
        package: BuilderPackage,
        files: dict[str, str],
        reason: str = "",
        stamp: str | None = None,
    ) -> BuilderPackageApply:
        """Record the bytes currently on disk for everything we are about to
        write, before writing any of it."""
        root = package.root_path or ""
        stamp = stamp or "latest"
        backup = os.path.join(root, BACKUP_DIR, stamp)
        record = self.create(
            {  # pyright: ignore[reportArgumentType] -- `@api.model_create_multi`
                # (`odoo/api.py`) is a bare passthrough decorator that does not
                # widen `create()`'s own declared `list[ValuesType]`-only
                # signature to also cover the single-dict form it genuinely
                # accepts at runtime (TYPING.md's own "Known traps").
                "package_id": package.id,
                "reason": reason,
                "state": "pending",
                "backup_path": backup,
                "boot_id": PROCESS_BOOT_ID,
            }
        )
        # Before the first backup file: `git add .` must never see them.
        package._ignore_builder_dir()
        rows: list[dict[str, Any]] = []
        existed: dict[str, bool] = {}
        for relative in sorted(files):
            before = package._read_source(relative)
            existed[relative] = before is not None
            rows.append(
                {
                    "apply_id": record.id,
                    "path": relative,
                    "content_before": before,
                    "existed": before is not None,
                }
            )
            if before is not None:
                atomicfile.write_text(os.path.join(backup, relative), before)
        if rows:
            # `BuilderPackageApplyFile` is defined later in this same module,
            # but by the time `_snapshot` actually runs the class already
            # exists in the module's own namespace -- a real, runtime-bound
            # `cls` for `typed.model()`, not a `TYPE_CHECKING`-only forward
            # reference (TYPING.md's own file-specific notes for this file).
            typed.model(self.env, BuilderPackageApplyFile).create(rows)
        # Last, and before any package file is touched: from here until the
        # apply's commit, this is the only durable trace that an apply began.
        atomicfile.write_text(
            self._journal_path(root, stamp),
            json.dumps(
                {
                    "stamp": stamp,
                    "db": cast("str", cast("Cursor", self.env.cr).dbname),
                    "reason": reason,
                    "boot_id": PROCESS_BOOT_ID,
                    "files": existed,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return record

    @api.model
    def _journal_path(self, root: str, stamp: str) -> str:
        return os.path.join(
            root, BUILDER_DIR, "%s%s%s" % (JOURNAL_PREFIX, stamp, JOURNAL_SUFFIX)
        )

    def _clear_journal(self) -> None:
        """The record is committed; the journal that stood in for it goes."""
        for record in self:
            root = cast("BuilderPackage", record.package_id).root_path
            if not root or not record.backup_path:
                continue
            stamp = os.path.basename(record.backup_path)
            with contextlib.suppress(OSError):
                os.remove(self._journal_path(root, stamp))

    def _backup_dir(self) -> str | None:
        """The on-disk backup, if it is where a backup can only be.

        ``backup_path`` is a stored value and ``readonly`` is a view
        attribute, not a guarantee: a ``write`` can point it anywhere, and
        what is done with it is ``rmtree``. Only a path inside the
        package's own ``.builder/backup`` is ever believed.
        """
        self.ensure_one()
        root = cast("BuilderPackage", self.package_id).root_path
        if not root or not self.backup_path:
            return None
        base = os.path.realpath(os.path.join(root, BACKUP_DIR))
        real = os.path.realpath(self.backup_path)
        if not real.startswith(base + os.sep):
            _logger.warning(
                "Ignoring backup path %s of apply %s: not inside %s",
                self.backup_path,
                self.id,
                base,
            )
            return None
        return real

    def _restore(self) -> bool:
        """Put the previous bytes back. Best effort, and loud about failures.

        Runs when the registry rebuild raised, i.e. at the point where the new
        source is known bad. Any file that did not exist before is removed
        rather than left as a half-written module.
        """
        self.ensure_one()
        root = cast("BuilderPackage", self.package_id).root_path or ""
        # Old bytes going back onto disk are .py files too; the dev watcher
        # must not restart on them any more than on the write being undone.
        _mute_dev_watcher(root)
        for entry in cast("BuilderPackageApplyFile", self.file_ids):
            full = os.path.join(root, cast("str", entry.path))
            try:
                if entry.existed:
                    atomicfile.write_text(full, entry.content_before or "")
                elif os.path.isfile(full):
                    os.remove(full)
            except OSError as err:
                _logger.error("Could not restore %s: %s", full, err)
        return True

    def action_rollback(self) -> dict[str, bool]:
        """Undo an apply from the UI, then reload back to what was there.

        An apply that was written but never loaded (``awaiting_restart``,
        or one a dead process left ``pending``) is restored the same way;
        under a server that cannot reload in place the files go back and
        the restart the user was already owed is the one that makes it
        count, so nothing is reloaded here and the answer says so.
        """
        self.ensure_one()
        # `package_id` read once and reused -- side-effect-free (a Many2one
        # field read), the same "read once into a local, reuse it" idiom
        # `builder_package.py`'s own `_refresh_disk_checksum`/`_write_files`
        # already use for a field read repeated within one method.
        package = cast("BuilderPackage", self.package_id)
        # `_assert_builder_manager` lives on `builder.security.mixin`
        # (`_inherit`, not a Python base class -- Odoo's registry merges it
        # in at runtime, invisibly to pyright); `typed.security()` is the
        # shared fix (TYPING.md's own "Known traps").
        typed.security(package)._assert_builder_manager()
        package._assert_writable()
        if not self.file_ids:
            raise UserError(_("There is nothing recorded to put back."))
        # A rollback is an apply run backwards, and excludes one the same way.
        with package._applying():
            package._lock_for_write()
            restart_required = package.reload_mode == "manual"
            if not restart_required:
                package._acquire_cron_lock()
            self._restore()
            # `Environment.cr` is declared `BaseCursor`, which has no
            # `.commit()` of its own -- only the real `Cursor` subclass every
            # live request actually gets (TYPING.md's own "Known traps").
            cast("Cursor", self.env.cr).commit()  # the reload rebuilds from disk
            if not restart_required:
                package._acquire_cron_lock()
                package._reload_now()
            else:
                # The files went back; the restart still has to load them,
                # and to bring the schema back in line with them.
                self.restart_hint = package._mark_for_restart()
            self.write({"state": "rolled_back"})
            package.action_check_drift()
        return {"rolled_back": True, "restart_required": restart_required}

    def action_discard_backup(self) -> bool:
        if self:
            typed.security(
                cast("BuilderPackage", self[0].package_id)
            )._assert_builder_manager()
        for record in self:
            backup = record._backup_dir()
            if backup and os.path.isdir(backup):
                shutil.rmtree(backup, ignore_errors=True)
            record.backup_path = False
        return True

    # -- crash recovery ---------------------------------------------------

    @api.model
    def _reap_abandoned(self, packages: BuilderPackage) -> BuilderPackageApply:
        """Mark applies that were pending when the process died.

        Step 7 of the apply sequence cannot run if the process is gone -- a
        --dev=reload restart, an OOM kill. Those rows stay 'pending' forever
        and are the signal that a rollback was never completed.

        A row is abandoned when it was started by another process *and* is
        older than ``ABANDONED_AFTER``. The first clause keeps a slow apply
        in this process alive; the second covers a prefork server, where a
        sibling worker's legitimately pending apply lives for milliseconds
        and a stale one for ever. Called from the workspace, where the state
        is read, and never from ``_register_hook``: that runs again inside
        the apply's own reload and would reap the apply in flight.

        Two more things are settled on the same occasion, because this is
        where apply state is read: an apply the process died *inside the
        write of*, which left a journal and no row (``_recover_journals``),
        and applies that were waiting for a restart that has since happened
        (``_settle_awaiting_restart``).
        """
        self._recover_journals(packages)
        self._settle_awaiting_restart(packages)
        cutoff = fields.Datetime.now() - ABANDONED_AFTER
        stale = self.search(
            [
                ("package_id", "in", packages.ids),
                ("state", "=", "pending"),
                ("boot_id", "!=", PROCESS_BOOT_ID),
                ("create_date", "<", cutoff),
            ]
        )
        if not stale:
            return stale
        for record in stale:
            record.write(
                {
                    "state": "failed",
                    "error": _(
                        'The server stopped while "%s" was being applied. '
                        "The files on disk may be half-written; roll back to "
                        "restore what was there before.",
                        record.reason or _("this change"),
                    ),
                }
            )
        stale._clear_journal()
        return stale

    @api.model
    def _recover_journals(self, packages: BuilderPackage) -> BuilderPackageApply:
        """Turn an apply that died before its commit back into a record.

        The apply row and its file rows are created in the same transaction
        as the write, and that transaction commits only after the last file
        is on disk. A process killed in between leaves a half-written
        package and, in the database, nothing at all: no pending row to
        reap, no rollback to offer. The journal ``_snapshot`` wrote first
        survives, and so does the backup beside it; from the two, the row
        is rebuilt as a failed apply that can be rolled back like any other.
        """
        recovered = self.browse()
        dbname = cast("str", cast("Cursor", self.env.cr).dbname)
        for package in packages:
            root = package.root_path
            if not root:
                continue
            directory = os.path.join(root, BUILDER_DIR)
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                continue
            for name in names:
                if not (
                    name.startswith(JOURNAL_PREFIX) and name.endswith(JOURNAL_SUFFIX)
                ):
                    continue
                path = os.path.join(directory, name)
                try:
                    with open(path, encoding="utf-8") as handle:
                        loaded: Any = json.load(handle)
                    age = time.time() - os.path.getmtime(path)
                except (OSError, ValueError):
                    continue
                if not isinstance(loaded, dict):
                    continue
                journal = cast("dict[str, Any]", loaded)
                if journal.get("db") != dbname:
                    continue  # another database's apply; not ours to judge
                if (
                    journal.get("boot_id") == PROCESS_BOOT_ID
                    or age < ABANDONED_AFTER.total_seconds()
                ):
                    continue  # in flight
                stamp = str(journal.get("stamp") or "")
                if not stamp or os.sep in stamp or stamp.startswith("."):
                    continue
                backup = os.path.join(root, BACKUP_DIR, stamp)
                known = self.search(
                    [("package_id", "=", package.id), ("backup_path", "=", backup)],
                    limit=1,
                )
                if not known:
                    recovered |= self._record_from_journal(package, journal, backup)
                with contextlib.suppress(OSError):
                    os.remove(path)
        return recovered

    @api.model
    def _record_from_journal(
        self, package: BuilderPackage, journal: dict[str, Any], backup: str
    ) -> BuilderPackageApply:
        reason = str(journal.get("reason") or "")
        record = self.create(
            {  # pyright: ignore[reportArgumentType] -- see `_snapshot`.
                "package_id": package.id,
                "reason": reason,
                "state": "failed",
                "backup_path": backup,
                "boot_id": str(journal.get("boot_id") or ""),
                "error": _(
                    'The server stopped while "%s" was being written, before '
                    "the change was recorded. The files on disk may be "
                    "half-written; roll back to restore what was there "
                    "before.",
                    reason or _("this change"),
                ),
            }
        )
        rows: list[dict[str, Any]] = []
        files = cast("dict[str, Any]", journal.get("files") or {})
        for relative, existed in sorted(files.items()):
            if os.path.isabs(relative):
                continue
            if ".." in relative.split("/"):
                continue
            before: str | None = None
            if existed:
                try:
                    with open(
                        os.path.join(backup, relative), encoding="utf-8"
                    ) as handle:
                        before = handle.read()
                except (OSError, UnicodeDecodeError):
                    # No bytes to put back: restoring this one would write an
                    # empty file over whatever is there. Leave it out.
                    continue
            rows.append(
                {
                    "apply_id": record.id,
                    "path": relative,
                    "content_before": before,
                    "existed": bool(existed),
                }
            )
        if rows:
            typed.model(self.env, BuilderPackageApplyFile).create(rows)
        _logger.warning(
            "Recovered an interrupted apply of %s from its journal (%s)",
            package.name,
            backup,
        )
        return record

    @api.model
    def _settle_awaiting_restart(self, packages: BuilderPackage) -> None:
        """Close applies whose restart has happened -- or say it did not work.

        The restart is expected to have upgraded the package, because the
        apply marked it ``to upgrade`` (``BuilderPackage._mark_for_restart``).
        That mark can be lost before the restart: a worker that rebuilds its
        registry in the meantime "upgrades" the module against the Python it
        still has in memory and resets the state. So the schema is looked
        at rather than assumed. Complete, and the apply is applied. Behind,
        and the package is marked again and the hint says what to do --
        which is still better than a model that fails on every read with
        nothing on screen to explain it.
        """
        waiting = self.search(
            [
                ("package_id", "in", packages.ids),
                ("state", "=", "awaiting_restart"),
                ("write_date", "<", _server_started_at()),
            ]
        )
        if not waiting:
            return
        Module = typed.model(self.env, IrModuleModule).sudo()
        for package in cast("BuilderPackage", waiting.mapped("package_id")):
            rows = waiting.filtered(lambda r, p=package: r.package_id == p)
            module = Module.search([("name", "=", package.name)], limit=1)
            if module.state != "installed":
                # Not installed: nothing was loaded, the restart changed
                # nothing, and installing is still the user's next step.
                continue
            behind = package._schema_behind()
            if not behind:
                rows.write({"state": "applied", "restart_hint": False})
                continue
            _logger.warning(
                "%s was restarted onto new source without its upgrade; "
                "missing: %s. Marking it for upgrade again.",
                package.name,
                ", ".join(behind),
            )
            package._mark_for_restart()
            rows.write(
                {
                    "restart_hint": _(
                        "The server was restarted, but %(name)s was not "
                        "upgraded with it and the database is missing "
                        "%(missing)s. Restart again with -u %(name)s.",
                        name=package.name,
                        missing=", ".join(behind),
                    )
                }
            )

    # -- retention ----------------------------------------------------------

    @api.model
    def _retention(self) -> tuple[int, int]:
        Params = typed.model(self.env, IrConfigParameter).sudo()

        def read(key: str, default: int) -> int:
            value = cast("str | bool", Params.get_param(key))
            try:
                return max(0, int(value or default))
            except (TypeError, ValueError):
                return default

        return read(KEEP_PARAM, DEFAULT_KEEP), read(DAYS_PARAM, DEFAULT_DAYS)

    @api.autovacuum
    def _gc_old_applies(self) -> None:
        """Drop apply history nobody will roll back to any more.

        Every apply keeps the full previous content of every file it
        rendered, twice -- in ``builder.package.apply.file`` and under
        ``.builder/backup/<stamp>/`` -- and nothing else ever removed
        either. See ``KEEP_PARAM`` for the rule. Applies still in flight
        (``pending``, ``awaiting_restart``) are never touched, and neither
        is a backup directory with no row unless it is older than the
        retention period: that may be all that is left of a crashed apply.
        """
        keep, days = self._retention()
        cutoff = fields.Datetime.now() - timedelta(days=days)
        packages = typed.model(self.env, BuilderPackage).sudo().search([])
        for package in packages:
            finished = self.sudo().search(
                [
                    ("package_id", "=", package.id),
                    ("state", "in", FINISHED_STATES),
                ]
            )
            doomed = finished[keep:].filtered(lambda r: r.create_date < cutoff)
            if doomed:
                if package.writable:
                    doomed.action_discard_backup()
                doomed.unlink()
            if package.writable:
                self.sudo()._gc_orphan_backups(package, cutoff)

    @api.model
    def _gc_orphan_backups(self, package: BuilderPackage, cutoff: datetime) -> None:
        root = package.root_path
        if not root:
            return
        base = os.path.realpath(os.path.join(root, BACKUP_DIR))
        try:
            names = os.listdir(base)
        except OSError:
            return
        referenced = {
            backup
            for backup in (
                record._backup_dir()
                for record in self.search([("package_id", "=", package.id)])
            )
            if backup
        }
        limit = cutoff.replace(tzinfo=timezone.utc).timestamp()
        for name in names:
            full = os.path.join(base, name)
            if full in referenced or os.path.islink(full) or not os.path.isdir(full):
                continue
            try:
                if os.path.getmtime(full) >= limit:
                    continue
            except OSError:
                continue
            if os.path.exists(self._journal_path(root, name)):
                continue
            shutil.rmtree(full, ignore_errors=True)


class BuilderPackageApplyFile(models.Model):
    _name = "builder.package.apply.file"
    _description = "Builder Package Apply File"
    _order = "path"

    apply_id: fields.Many2one[Any] = fields.Many2one(
        "builder.package.apply", required=True, ondelete="cascade", index=True
    )
    path = fields.Char(required=True)
    content_before = fields.Text()
    existed = fields.Boolean(default=False)

    def action_view_before(self) -> bool:
        self.ensure_one()
        if not self.existed:
            raise UserError(_("%s did not exist before this change.", self.path))
        return True

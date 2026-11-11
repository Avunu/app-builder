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
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..tools import typed
from ..tools.i18n import _
from .builder_package import BuilderPackage, _mute_dev_watcher

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs this at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.sql_db import Cursor

_logger = logging.getLogger(__name__)

BACKUP_DIR = ".builder/backup"

# One per process, minted at import. An apply records the id of the process
# that started it; a 'pending' row from any other process is one whose step
# 7 never ran, because the process is gone. Under a prefork server every
# worker has an id of its own, which is why age is checked as well: a row a
# sibling worker created a moment ago is not abandoned, it is in progress.
PROCESS_BOOT_ID = uuid.uuid4().hex
ABANDONED_AFTER = timedelta(minutes=2)


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
        backup = os.path.join(package.root_path or "", BACKUP_DIR, stamp or "latest")
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
        rows: list[dict[str, Any]] = []
        for relative in sorted(files):
            before = package._read_source(relative)
            rows.append(
                {
                    "apply_id": record.id,
                    "path": relative,
                    "content_before": before,
                    "existed": before is not None,
                }
            )
            if before is not None:
                target = os.path.join(backup, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(before)
        if rows:
            # `BuilderPackageApplyFile` is defined later in this same module,
            # but by the time `_snapshot` actually runs the class already
            # exists in the module's own namespace -- a real, runtime-bound
            # `cls` for `typed.model()`, not a `TYPE_CHECKING`-only forward
            # reference (TYPING.md's own file-specific notes for this file).
            typed.model(self.env, BuilderPackageApplyFile).create(rows)
        return record

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
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    with open(full, "w", encoding="utf-8") as handle:
                        handle.write(entry.content_before or "")
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
        self._restore()
        # `Environment.cr` is declared `BaseCursor`, which has no `.commit()`
        # of its own -- only the real `Cursor` subclass every live request
        # actually gets (TYPING.md's own "Known traps").
        cast("Cursor", self.env.cr).commit()  # the reload below rebuilds from disk
        restart_required = package.reload_mode == "manual"
        if not restart_required:
            package._reload_now()
        self.write({"state": "rolled_back"})
        package.action_check_drift()
        return {"rolled_back": True, "restart_required": restart_required}

    def action_discard_backup(self) -> bool:
        for record in self:
            if record.backup_path and os.path.isdir(record.backup_path):
                shutil.rmtree(record.backup_path, ignore_errors=True)
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
        """
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
        return stale


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

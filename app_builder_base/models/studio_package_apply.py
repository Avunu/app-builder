# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One record per attempt to write a package to disk and reload it.

Module operations commit. ``_button_immediate_function`` commits before
rebuilding the registry and again after, so a failure halfway through is not
rolled back by the ORM -- and if the new Python does not import, the *next*
request re-imports the same broken file, which makes the whole database
unbootable for every user, not just the one who pressed the button.

So an apply is a small state machine with its bytes kept twice: in this record,
and under ``.studio/backup/<timestamp>/`` on disk. The on-disk copy is the one
that matters when the process dies mid-reload and nothing can run a rollback --
recovery is then ``git checkout`` or copying the backup back, from a shell.
"""

import logging
import os
import shutil

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BACKUP_DIR = ".studio/backup"


class StudioPackageApply(models.Model):
    _name = "studio.package.apply"
    _description = "Studio Package Apply"
    _order = "create_date desc, id desc"

    package_id = fields.Many2one(
        "studio.package", required=True, ondelete="cascade", index=True
    )
    reason = fields.Char()
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("applied", "Applied"),
            ("failed", "Failed"),
            ("rolled_back", "Rolled back"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    error = fields.Text(readonly=True)
    backup_path = fields.Char(readonly=True)
    file_ids = fields.One2many("studio.package.apply.file", "apply_id")

    # -- snapshot ---------------------------------------------------------

    @api.model
    def _snapshot(self, package, files, reason="", stamp=None):
        """Record the bytes currently on disk for everything we are about to
        write, before writing any of it."""
        backup = os.path.join(package.root_path or "", BACKUP_DIR, stamp or "latest")
        record = self.create(
            {
                "package_id": package.id,
                "reason": reason,
                "state": "pending",
                "backup_path": backup,
            }
        )
        rows = []
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
            self.env["studio.package.apply.file"].create(rows)
        return record

    def _restore(self):
        """Put the previous bytes back. Best effort, and loud about failures.

        Runs when the registry rebuild raised, i.e. at the point where the new
        source is known bad. Any file that did not exist before is removed
        rather than left as a half-written module.
        """
        self.ensure_one()
        root = self.package_id.root_path or ""
        for entry in self.file_ids:
            full = os.path.join(root, entry.path)
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

    def action_rollback(self):
        """Undo an apply from the UI, then reload back to what was there."""
        self.ensure_one()
        self.package_id._assert_studio_manager()
        self.package_id._assert_writable()
        self._restore()
        self.env.cr.commit()  # the reload below rebuilds from disk
        self.package_id._reload_now()
        self.write({"state": "rolled_back"})
        self.package_id.action_check_drift()
        return True

    def action_discard_backup(self):
        for record in self:
            if record.backup_path and os.path.isdir(record.backup_path):
                shutil.rmtree(record.backup_path, ignore_errors=True)
            record.backup_path = False
        return True

    # -- crash recovery ---------------------------------------------------

    @api.model
    def _reap_abandoned(self, package):
        """Mark applies that were pending when the process died.

        Step 7 of the apply sequence cannot run if the process is gone -- a
        --dev=reload restart, an OOM kill. Those rows stay 'pending' forever
        and are the signal that a rollback was never completed.
        """
        boot = self.env["ir.config_parameter"].sudo().get_param("app_builder.boot_id")
        stale = self.search(
            [("package_id", "=", package.id), ("state", "=", "pending")]
        )
        if not stale:
            return stale
        stale.write(
            {
                "state": "failed",
                "error": _(
                    "The server stopped while this change was being applied "
                    "(boot %s). The files on disk may be half-written; roll "
                    "back to restore what was there before.",
                    boot or "unknown",
                ),
            }
        )
        return stale


class StudioPackageApplyFile(models.Model):
    _name = "studio.package.apply.file"
    _description = "Studio Package Apply File"
    _order = "path"

    apply_id = fields.Many2one(
        "studio.package.apply", required=True, ondelete="cascade", index=True
    )
    path = fields.Char(required=True)
    content_before = fields.Text()
    existed = fields.Boolean(default=False)

    def action_view_before(self):
        self.ensure_one()
        if not self.existed:
            raise UserError(_("%s did not exist before this change.", self.path))
        return True

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The dev server's autoreload must not restart on the studio's own writes.

``--dev=reload`` restarts the process on any .py change under an addons
path and gives in-flight requests one second before it closes the database
connections. An apply writes .py files and reloads them in process in the
same request, so that restart killed the apply half way -- a closed cursor
inside ``update_list`` -- and the rollback after it the same way. These
pin the fix: under ``--dev=reload`` the studio reloads in process, and the
watcher looks away from a package for a few seconds around a write.
"""

import os
import shutil
import tempfile
from unittest.mock import patch

from odoo.service import server as odoo_server
from odoo.tests import tagged
from odoo.tools import config

from ..models import studio_package as package_module
from .common import StudioCase


@tagged("post_install", "-at_install")
class TestDevWatcher(StudioCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_watch_pkg")

    def _handle(self, path):
        """What the watcher does with an event for ``path``: True when it
        would have restarted the server."""
        restarted = []
        with patch.object(odoo_server, "restart", lambda: restarted.append(path)):
            odoo_server.FSWatcherBase().handle_file(path)
        return bool(restarted)

    def test_dev_reload_reloads_in_process(self):
        """The mode that let the dev server restart do the reload is gone:
        it could not work, so it is no longer offered."""
        with patch.dict(config.options, {"workers": 0, "dev_mode": ["reload"]}):
            self.package.invalidate_recordset(["reload_mode"])
            self.assertEqual(self.package.reload_mode, "inproc")
        with patch.dict(config.options, {"workers": 2, "dev_mode": ["reload"]}):
            self.package.invalidate_recordset(["reload_mode"])
            self.assertEqual(self.package.reload_mode, "manual")

    def test_a_studio_write_does_not_restart_the_dev_server(self):
        """The watcher's event for a file the studio just wrote is dropped,
        and a developer's own file elsewhere still restarts the server."""
        with patch.dict(config.options, {"dev_mode": ["reload"]}):
            self.package._write_files({"models/watched.py": "x = 1\n"})
            written = os.path.join(self.package.root_path, "models", "watched.py")
            self.assertFalse(self._handle(written), "the studio's write: no restart")
            elsewhere = tempfile.mkdtemp(prefix="studio-watch-")
            self.addCleanup(shutil.rmtree, elsewhere, True)
            other = os.path.join(elsewhere, "theirs.py")
            with open(other, "w", encoding="utf-8") as handle:
                handle.write("y = 2\n")
            self.assertTrue(self._handle(other), "someone else's file still is")

    def test_the_mute_is_a_window_not_a_switch(self):
        """A few seconds after the write the same path restarts the server
        again: an edit the developer makes there later is theirs."""
        with patch.dict(config.options, {"dev_mode": ["reload"]}):
            self.package._write_files({"models/later.py": "z = 3\n"})
            later = os.path.join(self.package.root_path, "models", "later.py")
            root = os.path.realpath(self.package.root_path)
            self.assertIn(root, package_module._WATCHER_MUTED_UNTIL)
            package_module._WATCHER_MUTED_UNTIL[root] = 0.0
            self.assertTrue(self._handle(later))
            self.assertNotIn(root, package_module._WATCHER_MUTED_UNTIL)

    def test_without_dev_reload_nothing_is_touched(self):
        """No watcher runs, so nothing is muted and nothing is wrapped for
        the sake of it."""
        package_module._WATCHER_MUTED_UNTIL.clear()
        with patch.dict(config.options, {"dev_mode": []}):
            self.package._write_files({"models/plain.py": "p = 0\n"})
        self.assertEqual(package_module._WATCHER_MUTED_UNTIL, {})

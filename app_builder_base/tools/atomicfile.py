# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Write a file so that a reader sees the old bytes or the new, never half.

The builder writes ``.py`` and ``.xml`` into a directory on ``addons_path``.
``open(path, "w")`` truncates first and writes after, so a process killed in
between leaves an empty or half-written module file -- and a truncated
``__init__.py`` is one Odoo imports on the next boot. Writing a sibling
temporary file and renaming it over the target is atomic on POSIX: the name
points at the complete old file until it points at the complete new one.

No ``odoo`` import, so it is testable without a database.
"""

from __future__ import annotations

import contextlib
import os
import tempfile

# Not ``.py``: the dev-mode file watcher restarts the server on any ``.py``
# event under an addons path, and this file exists for a few milliseconds.
TMP_SUFFIX = ".builder-tmp"


def write_text(path: str, content: str) -> None:
    """Atomically replace ``path`` with ``content`` (UTF-8)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=directory, prefix=".%s." % os.path.basename(path), suffix=TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates 0600; a generated file should look like any other
        # file in the tree, or like the one it replaces.
        try:
            mode = os.stat(path).st_mode & 0o7777
        except OSError:
            mode = 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise

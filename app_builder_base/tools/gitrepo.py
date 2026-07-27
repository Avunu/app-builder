# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Thin git wrapper.

Producing reviewable commits is what makes "move between builder and codebase"
concrete rather than aspirational, so this stays deliberately small: status,
diff, add, commit. Precedent: ``odoo-module-migrator._commit_changes``.

Every helper degrades to a benign value when git is missing or the path is not
a repository -- the studio must remain usable outside version control.
"""

import logging
import os
import subprocess

_logger = logging.getLogger(__name__)

TIMEOUT = 30


def _run(args, cwd):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as err:
        _logger.warning("git %s failed in %s: %s", " ".join(args), cwd, err)
        return None
    if result.returncode != 0:
        _logger.debug("git %s: %s", " ".join(args), result.stderr.strip())
        return None
    return result.stdout


def is_repo(path):
    if not path or not os.path.isdir(path):
        return False
    return _run(["rev-parse", "--is-inside-work-tree"], path) is not None


def current_branch(path):
    out = _run(["rev-parse", "--abbrev-ref", "HEAD"], path)
    return (out or "").strip() or False


def status(path, paths=None):
    """Porcelain status limited to ``paths``, as a list of ``(code, path)``."""
    out = _run(["status", "--porcelain", "--", *(paths or ["."])], path)
    if out is None:
        return []
    entries = []
    for line in out.splitlines():
        if len(line) > 3:
            entries.append((line[:2].strip(), line[3:]))
    return entries


def diff(path, paths=None):
    """Combined staged + unstaged diff, which is what a reviewer wants to see."""
    unstaged = _run(["diff", "--", *(paths or ["."])], path) or ""
    staged = _run(["diff", "--cached", "--", *(paths or ["."])], path) or ""
    return (staged + unstaged).strip()


def add(path, paths):
    return _run(["add", "--", *paths], path) is not None


def commit(path, message, paths=None):
    """Stage ``paths`` and commit. Returns the new sha, or False.

    Nothing-to-commit is a success with no sha, not a failure -- the builder
    calls this after every operation and most operations are no-ops for git.
    """
    if paths and not add(path, paths):
        return False
    if not status(path, paths):
        return False
    if _run(["commit", "-m", message, "--", *(paths or ["."])], path) is None:
        return False
    return (_run(["rev-parse", "HEAD"], path) or "").strip() or False

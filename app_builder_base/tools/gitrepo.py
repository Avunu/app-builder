# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Thin git wrapper.

Producing reviewable commits is what makes "move between builder and codebase"
concrete rather than aspirational, so this stays deliberately small: status,
diff, add, commit. Precedent: ``odoo-module-migrator._commit_changes``.

Every helper degrades to a benign value when git is missing or the path is not
a repository -- the builder must remain usable outside version control.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Literal, TypedDict

_logger = logging.getLogger(__name__)

TIMEOUT = 30


class LogEntryJSON(TypedDict):
    """One commit as ``log`` sends it.

    Not a dataclass's own ``to_json`` (``log`` builds this dict directly,
    there is no ``LogEntry`` class), but a wire type all the same:
    ``builder_workspace.changes()`` serves this list straight through as
    ``git.log`` in that RPC's own payload, with no further reshaping.
    """

    sha: str
    short: str
    author: str
    date: str
    subject: str


def _run(args: list[str], cwd: str) -> str | None:
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


def is_repo(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    return _run(["rev-parse", "--is-inside-work-tree"], path) is not None


def toplevel(path: str) -> str | Literal[False]:
    """The repository root ``path`` sits in, or ``False``.

    Porcelain paths are relative to this, not to ``path``: a package that is
    one directory of a larger repository gets ``custom/x_pkg/models/a.py``
    back from ``status``, and has to strip its own prefix to read it.
    """
    out = _run(["rev-parse", "--show-toplevel"], path)
    return (out or "").strip() or False


def init(path: str) -> bool:
    """Make ``path`` a repository. True when it is one afterwards."""
    if not path or not os.path.isdir(path):
        return False
    if is_repo(path):
        return True
    return _run(["init", "-q"], path) is not None


def log(
    path: str, limit: int = 20, paths: list[str] | None = None
) -> list[LogEntryJSON]:
    """The last ``limit`` commits touching ``paths``, newest first."""
    out = _run(
        [
            "log",
            "-n",
            str(limit),
            "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s",
            "--",
            *(paths or ["."]),
        ],
        path,
    )
    entries: list[LogEntryJSON] = []
    for line in (out or "").splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            sha, short, author, date, subject = parts
            entries.append(
                {
                    "sha": sha,
                    "short": short,
                    "author": author,
                    "date": date,
                    "subject": subject,
                }
            )
    return entries


def current_branch(path: str) -> str | Literal[False]:
    out = _run(["rev-parse", "--abbrev-ref", "HEAD"], path)
    return (out or "").strip() or False


def status(path: str, paths: list[str] | None = None) -> list[tuple[str, str]]:
    """Porcelain status limited to ``paths``, as a list of ``(code, path)``."""
    out = _run(
        ["status", "--porcelain", "--untracked-files=all", "--", *(paths or ["."])],
        path,
    )
    if out is None:
        return []
    entries: list[tuple[str, str]] = []
    for line in out.splitlines():
        if len(line) > 3:
            entries.append((line[:2].strip(), line[3:]))
    return entries


def diff(path: str, paths: list[str] | None = None) -> str:
    """Combined staged + unstaged diff, which is what a reviewer wants to see."""
    unstaged = _run(["diff", "--", *(paths or ["."])], path) or ""
    staged = _run(["diff", "--cached", "--", *(paths or ["."])], path) or ""
    return (staged + unstaged).strip()


def add(path: str, paths: list[str]) -> bool:
    return _run(["add", "--", *paths], path) is not None


def commit(
    path: str, message: str, paths: list[str] | None = None
) -> str | Literal[False]:
    """Stage ``paths`` and commit. Returns the new sha, or False.

    Nothing-to-commit is a success with no sha, not a failure -- the builder
    calls this after every operation and most operations are no-ops for git.
    """
    if not add(path, paths or ["."]):
        return False
    if not status(path, paths):
        return False
    if _run(["commit", "-m", message, "--", *(paths or ["."])], path) is None:
        return False
    return (_run(["rev-parse", "HEAD"], path) or "").strip() or False

#!/usr/bin/env python3
# pylint: disable=print-used
"""Check that this tree is installable, and pack it for a release.

The compiled ``.js`` is not committed, and the manifests name it, so a tree is
only installable once ``npm run build`` (or the Nix build) has run. Odoo does
not complain about an asset that is not there: the addons install and the
console never appears. This says so instead.

    python3 scripts/dist.py check [--root DIR]
        every ``.ts`` has its ``.js`` beside it, no ``.js`` is left without
        its ``.ts``, every asset a manifest names exists, and every glob of a
        manifest matches a file. Exit 1 with one line per problem.

    python3 scripts/dist.py zip OUT.zip
        ``check``, then write the addons to OUT.zip: the files git tracks plus
        the compiled ``.js``. Unpacked into an addons path it needs no build.

It needs nothing but Python's standard library and, for ``zip``, git.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
#: Where an addon's build writes: all the ``.js`` under these is compiled.
BUILT_DIRS = ("static/src", "static/tests")
GLOB_CHARS = frozenset("*?[")


def addons(root: Path) -> list[str]:
    """The addons of the tree: the directories with a manifest."""
    return sorted(p.parent.name for p in root.glob("*/__manifest__.py"))


def manifest(root: Path, addon: str) -> dict[str, object]:
    return ast.literal_eval((root / addon / "__manifest__.py").read_text("utf-8"))


def asset_paths(data: dict[str, object]) -> Iterator[tuple[str, str]]:
    """``(bundle, path)`` for every file path the manifest's assets name.

    An entry is a path or a directive tuple -- ``("include", bundle)``,
    ``("remove", path)``, ``("prepend", path)``, ``("after" | "before" |
    "replace", target, path)`` -- of which only the paths to add matter here.
    """
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        return
    for bundle, entries in assets.items():
        for entry in entries:
            if isinstance(entry, str):
                yield bundle, entry
            elif entry and entry[0] in ("prepend", "after", "before", "replace"):
                yield bundle, entry[-1]


def sources(root: Path, addon: str) -> Iterator[Path]:
    """The addon's ``.ts`` sources, declarations aside."""
    for sub in BUILT_DIRS:
        for path in sorted((root / addon / sub).rglob("*.ts")):
            if not path.name.endswith(".d.ts") and "node_modules" not in path.parts:
                yield path


def compiled(root: Path, addon: str) -> Iterator[Path]:
    """The addon's compiled ``.js``."""
    for sub in BUILT_DIRS:
        for path in sorted((root / addon / sub).rglob("*.js")):
            if "node_modules" not in path.parts:
                yield path


def check(root: Path) -> list[str]:
    """The problems that make the tree at ``root`` not installable."""
    names = addons(root)
    problems = []
    if not names:
        return [f"{root}: no addon here"]
    for addon in names:
        for ts in sources(root, addon):
            if not ts.with_suffix(".js").is_file():
                problems.append(
                    f"{ts.relative_to(root)}: not compiled (no .js beside it)"
                )
        for js in compiled(root, addon):
            if not js.with_suffix(".ts").is_file():
                problems.append(
                    f"{js.relative_to(root)}: stale (its .ts is gone); "
                    "`npm run build` removes it"
                )
        for bundle, entry in asset_paths(manifest(root, addon)):
            # Another repository's file (web/static/...) is not ours to find.
            if entry.lstrip("/").split("/", 1)[0] not in names:
                continue
            rel = entry.lstrip("/")
            if GLOB_CHARS.intersection(rel):
                if not any(p.is_file() for p in root.glob(rel)):
                    problems.append(
                        f"{addon}: {bundle} names {entry}, which matches no file"
                    )
            elif not (root / rel).is_file():
                problems.append(
                    f"{addon}: {bundle} names {entry}, which does not exist"
                )
    return problems


def tracked(root: Path, names: list[str]) -> list[str]:
    """The files of the addons that git tracks."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *names],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [name for name in out.split("\0") if name]


def write_zip(root: Path, target: Path) -> int:
    """Pack the addons: what git tracks plus the compiled ``.js``."""
    names = addons(root)
    files = set(tracked(root, names))
    for addon in names:
        files.update(str(js.relative_to(root)) for js in compiled(root, addon))
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            # A tracked file that is deleted in the working tree is not packed.
            if (root / name).is_file():
                archive.write(root / name, name)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="is this tree installable?")
    p_check.add_argument("--root", type=Path, default=REPO_ROOT)
    p_zip = sub.add_parser("zip", help="check, then pack the addons")
    p_zip.add_argument("target", type=Path)
    args = parser.parse_args(argv)

    root = (args.root if args.command == "check" else REPO_ROOT).resolve()
    problems = check(root)
    if problems:
        for problem in problems:
            print(f"dist: {problem}", file=sys.stderr)
        print(
            f"dist: {len(problems)} problem(s): this tree is not installable. "
            "Run `npm run build` first.",
            file=sys.stderr,
        )
        return 1
    names = addons(root)
    built = sum(1 for addon in names for _ in compiled(root, addon))
    print(f"dist: {len(names)} addons, {built} compiled modules, every asset found")
    if args.command == "zip":
        count = write_zip(root, args.target)
        print(f"dist: wrote {count} files to {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

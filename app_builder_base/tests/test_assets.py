# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Every shipped .js survives Odoo's own module transpiler.

TYPING.md moves the console to TypeScript, emitted to a committed .js by
esbuild (`scripts/build_ts.mjs`) rather than tsc, because tsc will not emit
in place next to JS sources still in the same program. The one thing that
purchases is worth re-checking on every run: a bare `export {}` from a
type-only module (the trap a `.d.ts`-shaped file falls into) does not match
`js_transpiler.EXPORT_OBJECT_RE`, which requires at least one name inside
the braces, and would ship straight through `wrap_with_odoo_define` as a
syntax error in every browser that loads it. Odoo's own transpiler is the
ground truth for "does this load", so this test asks it directly rather
than re-implementing its regexes.
"""

import ast
import pathlib
import re

from odoo.tests import BaseCase, tagged
from odoo.tools.js_transpiler import transpile_javascript

# A transpiled module's body should never still contain a native
# import/export statement -- every one of js_transpiler's conversion steps
# rewrites or strips them. Matched at the start of a line (after stripping
# indentation) so a string or comment that merely mentions "export" is not
# a false positive.
_LEFTOVER_MODULE_SYNTAX = re.compile(r"^\s*(import|export)\b")

# app_builder_base/tests/test_assets.py -> app_builder_base/ -> the workspace
# checkout of this repo, whose siblings are the other app_builder* addons.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _shipped_js_files():
    for addon_dir in sorted(_REPO_ROOT.glob("app_builder*")):
        static = addon_dir / "static"
        if not static.is_dir():
            continue
        yield from sorted(static.rglob("*.js"))


# A runtime import of another addon of this repo, in esbuild's output: a
# static `import ... from "@addon/..."` / `export ... from "@addon/..."`
# (possibly spanning lines), a bare `import "@addon/..."`, or a dynamic
# `import("@addon/...")`. `import type` never reaches the emitted .js, which
# is exactly why a type-only import from an addon not depended on is fine.
_RUNTIME_IMPORT = re.compile(
    r"""\b(?:import|export)\b[^;'"]*?\bfrom\s*["'](@app_builder_\w+)/"""
    r"""|\bimport\s*\(?\s*["'](@app_builder_\w+)/""",
    re.DOTALL,
)


def _studio_depends():
    """Each addon of this repo -> every addon of this repo it depends on,
    transitively."""
    direct = {}
    for addon_dir in _REPO_ROOT.glob("app_builder*"):
        manifest = addon_dir / "__manifest__.py"
        if manifest.is_file():
            data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
            direct[addon_dir.name] = set(data.get("depends", []))
    closure = {}
    for addon in direct:
        seen, todo = set(), [addon]
        while todo:
            for dep in direct.get(todo.pop(), ()):
                if dep not in seen:
                    seen.add(dep)
                    todo.append(dep)
        closure[addon] = seen
    return closure


def undeclared_runtime_imports():
    """`(file, imported addon)` for every shipped .js that imports, at
    runtime, an addon of this repo its own addon does not depend on."""
    closure = _studio_depends()
    found = []
    for path in _shipped_js_files():
        addon = path.relative_to(_REPO_ROOT).parts[0]
        content = path.read_text(encoding="utf-8")
        for match in _RUNTIME_IMPORT.finditer(content):
            target = (match.group(1) or match.group(2))[1:]
            if target != addon and target not in closure.get(addon, set()):
                found.append((path.relative_to(_REPO_ROOT).as_posix(), target))
    return found


@tagged("post_install", "-at_install")
class TestTranspiledAssets(BaseCase):
    def test_every_shipped_js_file_transpiles_cleanly(self):
        files = list(_shipped_js_files())
        self.assertTrue(files, "expected at least one shipped .js file to check")
        for path in files:
            relative = path.relative_to(_REPO_ROOT)
            url = f"/{relative.as_posix()}"
            content = path.read_text(encoding="utf-8")
            transpiled = transpile_javascript(url, content)
            leftover = [
                line
                for line in transpiled.splitlines()
                if _LEFTOVER_MODULE_SYNTAX.match(line)
            ]
            self.assertFalse(
                leftover,
                f"{path.relative_to(_REPO_ROOT)} still has native "
                f"import/export syntax after transpilation: {leftover!r}. "
                "A .ts source that emits no runtime value (a types-only "
                "module) produces exactly this from esbuild -- see "
                "TYPING.md, Known traps.",
            )

    def test_no_runtime_import_from_an_addon_not_depended_on(self):
        """A shipped .js may only import, at runtime, addons of this repo
        its own addon depends on. An import of one it does not is missing
        from the bundle whenever that addon is not installed, and the
        importing module silently never starts -- the TypeScript migration
        once routed `app_builder_ui`'s Automations menu item through
        `@app_builder_view/console/odoo` this way. Types are free to cross:
        `import type` never reaches the emitted .js."""
        self.assertEqual(
            undeclared_runtime_imports(),
            [],
            "each (file, addon) above imports that addon at runtime without "
            "its own manifest depending on it -- take only the type "
            "(`import type`) and call Odoo's own function, as "
            "app_builder_ui/static/src/automations_menu_item.ts does",
        )

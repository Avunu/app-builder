# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What the builder addons' manifests say about their assets.

Two decisions live in those ``assets`` keys and nowhere else, and neither
fails loudly when it is undone:

* **Every file is named.** The compiled ``.js`` is not under version control,
  so a glob (``static/src/console/**/*``) also loads the ``.js`` that a renamed
  or deleted ``.ts`` left on disk -- an old module, registering what it used to
  register. A named list cannot do that, and its own failure -- a new file
  nobody listed -- is what the first test here turns into a red build.

* **The console is fetched on demand.** ``web.assets_backend`` is downloaded by
  every internal user; the console is for the builder group. So the backend
  bundle holds the ways in (the systray item, the cog items) and
  ``console_loader.js``, and everything else is in
  ``app_builder_view.assets_console``. A backend file that imported a console
  module at runtime would break the web client for everyone the moment the
  import ran, since that module is not on the page; the last test reads the
  imports and refuses that.

These read files and manifests only: no database, no browser.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tests import BaseCase, tagged

# The addons that ship something under ``static/``.
ADDONS = (
    "app_builder_view",
    "app_builder_model",
    "app_builder_ui",
    "app_builder_report",
    "app_builder_approval",
)

BACKEND = "web.assets_backend"
CONSOLE = "app_builder_view.assets_console"

# What a source file is served as.
SERVED_AS = {".ts": ".js", ".xml": ".xml", ".scss": ".scss"}

# ``import ... from "x"`` and ``import "x"``, with whether it is ``import
# type`` (erased from the emitted ``.js``, so not an import at runtime).
RE_IMPORT = re.compile(
    r"""^import\s+(?P<type>type\s+)?(?:[^;'"]*?\sfrom\s+)?["'](?P<path>[^"']+)["']""",
    re.MULTILINE,
)


def _manifest(addon_dir: Path) -> dict:
    return ast.literal_eval((addon_dir / "__manifest__.py").read_text())


def _own_entries(assets: dict, addon: str) -> dict[str, list[str]]:
    """Each bundle's entries that name a file of ``addon`` itself."""
    own = {}
    for bundle, entries in assets.items():
        own[bundle] = [
            entry
            for entry in entries
            if isinstance(entry, str) and entry.startswith(addon + "/")
        ]
    return own


@tagged("post_install", "-at_install")
class TestAssets(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addons = {}
        for name in ADDONS:
            path = get_module_path(name, display_warning=False)
            if path:
                cls.addons[name] = Path(path)

    def _sources(self, addon: str, sub: str) -> set[str]:
        """What the sources under ``static/<sub>`` are served as."""
        root = self.addons[addon]
        served = set()
        for path in (root / "static" / sub).rglob("*"):
            if path.is_file() and path.suffix in SERVED_AS:
                relative = path.relative_to(root.parent).with_suffix(
                    SERVED_AS[path.suffix]
                )
                served.add(relative.as_posix())
        return served

    def _has_typescript(self, addon: str) -> bool:
        return any((self.addons[addon] / "static").rglob("*.ts"))

    def test_every_file_is_named_once_and_nothing_else(self):
        """Each source under ``static/src`` and ``static/tests`` is in exactly
        one bundle, by name; no entry is a glob; no entry names a file with
        no source."""
        for addon in self.addons:
            if not self._has_typescript(addon):
                # A deployed tree that ships only the compiled output has
                # nothing to compare the manifest against.
                continue
            own = _own_entries(_manifest(self.addons[addon]).get("assets", {}), addon)
            listed = [entry for entries in own.values() for entry in entries]
            with self.subTest(addon=addon):
                self.assertFalse(
                    [entry for entry in listed if "*" in entry or "?" in entry],
                    "a glob also loads the compiled .js a deleted .ts left behind",
                )
                self.assertEqual(
                    sorted(listed),
                    sorted(set(listed)),
                    "a file is listed twice",
                )
                sources = self._sources(addon, "src") | self._sources(addon, "tests")
                self.assertEqual(
                    sorted(sources - set(listed)),
                    [],
                    "these files exist and no bundle loads them",
                )
                self.assertEqual(
                    sorted(set(listed) - sources),
                    [],
                    "these are listed and have no source",
                )

    def test_the_console_is_not_in_the_backend_bundle(self):
        """The console's entry and its panes are in the bundle fetched on
        demand; the loader that fetches it is in the backend's."""
        assets = _manifest(self.addons["app_builder_view"])["assets"]
        prefix = "app_builder_view/static/src/console/"
        self.assertIn(prefix + "console_loader.js", assets[BACKEND])
        self.assertIn(prefix + "console.js", assets[CONSOLE])
        self.assertNotIn(prefix + "console.js", assets[BACKEND])
        # What a dark web client fetches instead: the same files.
        self.assertEqual(assets[CONSOLE + "_dark"], [("include", CONSOLE)])
        # The hoot runner fetches nothing on demand.
        self.assertIn(("include", CONSOLE), assets["web.assets_unit_tests_setup"])
        for addon, path in self.addons.items():
            backend = _manifest(path).get("assets", {}).get(BACKEND, [])
            with self.subTest(addon=addon):
                self.assertFalse(
                    [e for e in backend if isinstance(e, str) and "console_items" in e],
                    "a pane registration belongs in %s" % CONSOLE,
                )

    def test_backend_files_import_nothing_fetched_on_demand(self):
        """A file every internal user loads imports, at runtime, only what
        every internal user has."""
        backend = set()
        for path in self.addons.values():
            backend.update(
                entry
                for entry in _manifest(path).get("assets", {}).get(BACKEND, [])
                if isinstance(entry, str)
            )
        checked = 0
        for served in sorted(backend):
            if not served.endswith(".js"):
                continue
            addon, _, rest = served.partition("/")
            source = (self.addons[addon] / rest).with_suffix(".ts")
            if not source.is_file():
                continue
            for match in RE_IMPORT.finditer(source.read_text()):
                if match.group("type"):
                    continue
                target = match.group("path")
                if target.startswith("."):
                    resolved = (source.parent / target).resolve()
                    module = resolved.relative_to(
                        self.addons[addon].resolve().parent
                    ).as_posix()
                elif target.startswith("@app_builder"):
                    name, _, tail = target[1:].partition("/")
                    module = "%s/static/src/%s" % (name, tail)
                else:
                    continue
                checked += 1
                self.assertIn(
                    module + ".js",
                    backend,
                    "%s imports %s, which is only in a bundle fetched on demand"
                    % (served, target),
                )
        if any(self._has_typescript(addon) for addon in self.addons):
            self.assertGreater(checked, 0, "no import was read: the pattern is stale")

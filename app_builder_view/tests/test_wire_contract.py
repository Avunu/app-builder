# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The wire contract, both ends compared.

What the server sends the console is typed twice: as ``TypedDict``s here and
as interfaces in ``static/src/console/wire.ts``. Nothing generates one from the
other, and ``orm.call<T>`` asserts a shape without checking it; so a key renamed
on one side passes pyright and tsc alike and fails in the browser. This test is
the check in between: for every interface of ``wire.ts`` that mirrors a
``TypedDict``, the two have the same keys.

Keys only. The types beside them are still matched by eye -- a ``str`` that
became an ``int`` is not caught here -- but a key added, dropped or renamed on
one side is, and that is the drift that actually happens.

``MIRRORS`` is written out rather than worked out from the comments in
``wire.ts``, so that what is pinned does not depend on how a comment is
phrased. ``UNPINNED`` says why each remaining interface is not compared. Every
interface has to be in one or the other: a new one is a decision, not an
omission.

It reads files only: no database, no browser.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tests import BaseCase, tagged

WIRE = "static/src/console/wire.ts"

# interface in wire.ts -> (addon, file, TypedDict)
MIRRORS = {
    "RowJSON": ("app_builder_base", "tools/catalogue.py", "RowJSON"),
    "SectionJSON": ("app_builder_base", "tools/catalogue.py", "SectionJSON"),
    "WidgetJSON": ("app_builder_base", "tools/catalogue.py", "WidgetJSON"),
    "OptionGroupJSON": ("app_builder_base", "tools/catalogue.py", "OptionGroupJSON"),
    "CatalogueJSON": ("app_builder_base", "tools/catalogue.py", "CatalogueJSON"),
    "PlacementJSON": ("app_builder_base", "tools/modelspec.py", "PlacementJSON"),
    "AvailableFieldTypeJSON": (
        "app_builder_base",
        "tools/modelspec.py",
        "FieldTypeJSON",
    ),
    "PendingChangeJSON": (
        "app_builder_base",
        "models/builder_model_draft.py",
        "PendingChangeJSON",
    ),
    "DraftPackageJSON": (
        "app_builder_base",
        "models/builder_model_draft.py",
        "DraftPackageJSON",
    ),
    "DraftPayload": (
        "app_builder_base",
        "models/builder_model_draft.py",
        "DraftPayloadJSON",
    ),
    "InverseOptions": (
        "app_builder_base",
        "models/builder_model_draft.py",
        "InverseOptionsJSON",
    ),
    "ApplyEntryJSON": ("app_builder_base", "models/builder_workspace.py", "ApplyJSON"),
    "PackageEntryJSON": (
        "app_builder_base",
        "models/builder_workspace.py",
        "PackageJSON",
    ),
    "UserPrefsJSON": (
        "app_builder_base",
        "models/builder_workspace.py",
        "UserPrefsJSON",
    ),
    "RecordTemplateJSON": (
        "app_builder_base",
        "models/builder_record_surface.py",
        "RecordTemplateJSON",
    ),
    "RecordCatalogueJSON": (
        "app_builder_base",
        "models/builder_record_surface.py",
        "RecordCatalogueJSON",
    ),
    "RecordBadgeJSON": (
        "app_builder_base",
        "models/builder_record_surface.py",
        "RecordBadgeJSON",
    ),
    "RecordRowJSON": (
        "app_builder_base",
        "models/builder_record_surface.py",
        "RecordRowJSON",
    ),
    "RecordActionJSON": (
        "app_builder_base",
        "models/builder_record_surface.py",
        "RecordActionJSON",
    ),
    "StateValueJSON": (
        "app_builder_approval",
        "models/builder_approval.py",
        "StateValueJSON",
    ),
    "StateFieldJSON": (
        "app_builder_approval",
        "models/builder_approval.py",
        "StateFieldJSON",
    ),
    "GateConfigJSON": (
        "app_builder_approval",
        "models/builder_approval.py",
        "GateConfigJSON",
    ),
    "EnableApprovalJSON": (
        "app_builder_approval",
        "models/builder_approval.py",
        "EnableApprovalJSON",
    ),
    "ApprovalGateJSON": (
        "app_builder_approval",
        "models/builder_approval_surface.py",
        "ApprovalGateJSON",
    ),
    "OperationResult": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "OperationResultJSON",
    ),
    "ViewOfEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "ViewOfEntryJSON",
    ),
    "EditingContext": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "EditingContextJSON",
    ),
    "SearchFilterEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "SearchFilterEntryJSON",
    ),
    "EditingContextFieldEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "EditingContextFieldEntryJSON",
    ),
    "PreviewInfo": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "PreviewInfoJSON",
    ),
    "SelectableGroupEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "SelectableGroupEntryJSON",
    ),
    "AddableFieldEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "AddableFieldEntryJSON",
    ),
    "PlaceableFieldEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "PlaceableFieldEntryJSON",
    ),
    "AddableViewTypeEntry": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "AddableViewTypeEntryJSON",
    ),
    "SearchElements": (
        "app_builder_view",
        "models/builder_view_editor.py",
        "SearchElementsJSON",
    ),
}

# Addons a mirror lives in that this one does not depend on: a pane reads
# their keys only when the addon is installed beside it, so a tree shipped
# without one has nothing of it to drift from.
NOT_DEPENDED_ON = {"app_builder_approval"}

# Keys an interface carries that its ``TypedDict`` does not, and why.
TS_ONLY = {
    # What one surface's ``_row`` adds on top of the shared row: the menu
    # tree's depth and parent, a report's template. Optional in wire.ts.
    "RecordRowJSON": {"depth", "parent_id", "view_id"},
}

# Interfaces compared with nothing, and why.
UNPINNED = {
    "SelectionSpecJSON": "a dataclass sent through asdict(), not a TypedDict",
    "FieldSpecJSON": "a dataclass sent through asdict(), not a TypedDict",
    "DraftFieldJSON": "FieldSpecJSON plus the keys load() adds to that dict",
    "RecordChildrenJSON": "each surface's _describe_extra builds it as a plain dict",
    "RecordDescription": "describe() answers dict[str, object], widened per surface",
    "NewFieldPlan": "one interface here for a union of two TypedDicts there",
}

RE_INTERFACE = re.compile(
    r"^export interface (?P<name>\w+)(?: extends (?P<base>\w+))? \{\n(?P<body>.*?)^\}",
    re.DOTALL | re.MULTILINE,
)
# A member of the interface itself: two spaces in, as prettier leaves it. The
# members of an object type nested inside one sit deeper and are not read.
RE_KEY = re.compile(r"^  (?P<key>\w+)\??:", re.MULTILINE)


def _typeddict_keys(path: Path, name: str) -> set[str] | None:
    """The keys of ``TypedDict`` ``name`` in ``path``, its bases' included."""
    classes = {
        node.name: node
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef)
    }

    def keys(cls: str) -> set[str] | None:
        node = classes.get(cls)
        if node is None:
            return None
        found: set[str] = set()
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in classes:
                found |= keys(base.id) or set()
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name
            ):
                found.add(statement.target.id)
        return found

    return keys(name)


@tagged("post_install", "-at_install")
class TestWireContract(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = get_module_path("app_builder_view")
        if not root:
            raise RuntimeError("app_builder_view is not on the addons path")
        cls.wire = Path(root) / WIRE

    def _interfaces(self) -> dict[str, set[str]]:
        """Every interface of ``wire.ts`` and its keys, a base's included."""
        if not self.wire.is_file():
            self.skipTest("this tree ships the compiled .js without its .ts")
        declared = {}
        for match in RE_INTERFACE.finditer(self.wire.read_text()):
            declared[match.group("name")] = (
                {key.group("key") for key in RE_KEY.finditer(match.group("body"))},
                match.group("base"),
            )
        resolved = {}
        for name, (keys, base) in declared.items():
            keys = set(keys)
            while base in declared:
                keys |= declared[base][0]
                base = declared[base][1]
            resolved[name] = keys
        return resolved

    def test_every_interface_is_accounted_for(self):
        interfaces = self._interfaces()
        self.assertGreater(len(interfaces), 20, "wire.ts was not read: stale pattern")
        self.assertEqual(
            sorted(set(interfaces) - set(MIRRORS) - set(UNPINNED)),
            [],
            "new in wire.ts: pin each to its TypedDict in MIRRORS, or say in "
            "UNPINNED why it has none",
        )
        self.assertEqual(
            sorted((set(MIRRORS) | set(UNPINNED)) - set(interfaces)),
            [],
            "listed here and gone from wire.ts",
        )

    def test_mirrored_shapes_have_the_same_keys(self):
        interfaces = self._interfaces()
        for name, (addon, relative, cls) in MIRRORS.items():
            with self.subTest(interface=name, typeddict=cls):
                root = get_module_path(addon, display_warning=False)
                if not root and addon in NOT_DEPENDED_ON:
                    self.skipTest("%s is not on the addons path" % addon)
                if not root:
                    self.fail("%s is not on the addons path" % addon)
                python = _typeddict_keys(Path(root) / relative, cls)
                if python is None:
                    self.fail("%s is gone from %s" % (cls, relative))
                typescript = interfaces[name] - TS_ONLY.get(name, set())
                self.assertEqual(
                    sorted(typescript - python),
                    [],
                    "in wire.ts:%s and not in %s:%s" % (name, relative, cls),
                )
                self.assertEqual(
                    sorted(python - typescript),
                    [],
                    "in %s:%s and not in wire.ts:%s" % (relative, cls, name),
                )

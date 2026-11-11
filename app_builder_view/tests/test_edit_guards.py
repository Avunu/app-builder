# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What every edit is checked against before it touches anything.

Three guards that make live editing safe to build a drag-and-drop console on:
a version the client edits against, so a gesture minted on a stale tree is
refused rather than applied to a different one; a gate on the disk write, so a
gesture made of several operations puts one file on disk at the end and none
when it fails; and a name on every container the builder creates, so the thing
just added can be pointed at again without counting its siblings.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.exceptions import BuilderStaleView
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.base.models.res_lang import Lang

from ..models.builder_view_edit import BuilderViewEdit
from ..models.builder_view_editor import BuilderViewEditor

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime, the same bargain every other
    # converted file's own `TYPE_CHECKING` block makes.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )

    from ..models.builder_view_editor import _LocateTargetFoundJSON

FORM_ARCH = """
<form string="Guard Demo">
    <sheet>
        <group name="main">
            <field name="x_name"/>
        </group>
    </sheet>
</form>
"""


def _snapshot(root):
    """Every file under ``root`` with its content, for before/after diffs."""
    files = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as handle:
                files[os.path.relpath(path, root)] = handle.read()
    return files


@tagged("post_install", "-at_install")
class TestEditGuards(BuilderCase):
    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.history = typed.model(self.env, BuilderViewEdit)
        self.package = self.make_package(name="x_guard_pkg")
        model_vals: dict[str, object] = {
            "name": "Guard Demo",
            "model": "x_guard_demo",
            "field_id": [
                Command.create(
                    {"name": "x_name", "ttype": "char", "field_description": "Name"}
                ),
                Command.create(
                    {"name": "x_note", "ttype": "char", "field_description": "Note"}
                ),
            ],
        }
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "builder.guard.test",
            "model": "x_guard_demo",
            "type": "form",
            "arch": FORM_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]
        # Owned by somebody else, so every edit here is a patch -- the path
        # that has a view to create as well as one to write.
        self.make_package(name="x_guard_owner").builder_capture(self.view)

    def _combined(self):
        return etree.fromstring(
            typed.model(self.env, View)
            .browse(cast("int", self.view.id))
            .get_combined_arch()
            .encode()
        )

    # -- the version a client edits against ----------------------------------

    def test_the_version_changes_when_the_view_does(self):
        before = self.editor.arch_version(cast("int", self.view.id))
        self.assertEqual(
            before, self.editor.arch_version(cast("int", self.view.id)), "stable"
        )
        self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "main"},
            "x_note",
        )
        self.assertNotEqual(before, self.editor.arch_version(cast("int", self.view.id)))

    def test_the_version_is_the_same_for_every_user(self):
        """Taken from the combined arch, not the per-user projection: two
        people looking at one view must agree on what version it is -- and
        ``arch_db`` is translated, so a colleague working in French reads a
        different combined arch and must still get the same version."""
        typed.model(self.env, Lang)._activate_lang("fr_FR")
        self.view.update_field_translations(
            "arch_db", {"fr_FR": {"Guard Demo": "Démo de garde"}}
        )
        outsider = self.make_user(
            "guard_other_builder", ["base.group_system"], lang="fr_FR"
        )
        as_outsider = self.editor.with_user(outsider).with_context(lang="fr_FR")
        self.assertIn(
            "Démo de garde",
            self.view.with_user(outsider)
            .with_context(lang="fr_FR")
            .get_combined_arch(),
            "sanity: the arch really does differ by language",
        )
        self.assertEqual(
            self.editor.arch_version(cast("int", self.view.id)),
            as_outsider.arch_version(cast("int", self.view.id)),
        )
        result = as_outsider.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "main"},
            "x_note",
        )
        self.assertEqual(
            result["arch_version"],
            self.editor.arch_version(cast("int", self.view.id)),
            "the version an edit hands back is language-neutral too",
        )

    def test_a_stale_version_is_refused_before_anything_is_written(self):
        before = self.view.arch
        disk_before = _snapshot(self.package.root_path)
        # Not `assertRaises`: Odoo's wraps the block in a savepoint that is
        # rolled back on the exception, so every "nothing was written" check
        # after it would pass whatever the editor had done. The disk is
        # checked as well, since no savepoint ever covered that.
        try:
            self.editor.add_field_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {"kind": "group", "name": "main"},
                "x_note",
                expected_arch_version="something-older",
            )
        except BuilderStaleView:  # pylint: disable=except-pass
            pass
        else:
            self.fail("a stale version has to be refused")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, before)
        self.assertEqual(self.history.history_for(cast("int", self.view.id)), [])
        self.assertFalse(
            self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)]),
            "no extension may be created for an edit that was refused",
        )
        self.assertEqual(_snapshot(self.package.root_path), disk_before)

    def test_the_stale_refusal_is_a_user_error_the_client_can_tell_apart(self):
        """The client matches the class name; it has to be a UserError so the
        RPC layer serialises it with a message and no traceback."""
        self.assertTrue(issubclass(BuilderStaleView, UserError))
        self.assertIn("try again", str(BuilderStaleView()))

    def test_the_current_version_goes_through(self):
        version = self.editor.arch_version(cast("int", self.view.id))
        result = self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "main"},
            "x_note",
            expected_arch_version=version,
        )
        self.assertEqual(
            result["arch_version"],
            self.editor.arch_version(cast("int", self.view.id)),
            "the answer carries the version the next edit is checked against",
        )

    def test_no_claim_is_not_checked(self):
        """An older client, or a script, makes no claim and is not refused."""
        self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "main"},
            "x_note",
        )
        self.assertIn("x_note", self.view.get_combined_arch())

    # -- disk after database ----------------------------------------------

    def test_with_the_gate_closed_nothing_reaches_the_disk(self):
        """A gesture made of several operations wants one write, at the end:
        a file for the first step and a failure in the second would leave
        source on disk for a change the transaction rolled back. That covers
        the extension view itself, which is captured on the way -- not even
        its empty <data/> may land."""
        before = _snapshot(self.package.root_path)
        found = cast(
            "_LocateTargetFoundJSON",
            self.editor.locate_target(
                cast("int", self.view.id), {"kind": "group", "name": "main"}
            ),
        )
        self.editor.apply_operation(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {
                "type": "add_field",
                "name": "x_note",
                "xpath": found["xpath"],
                "position": "inside",
            },
            write_files=False,
        )
        patch = self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)])
        self.assertEqual(
            cast("BuilderOwnedMixin", patch).builder_package_id,
            self.package,
            "captured",
        )
        self.assertIn("x_note", self.view.get_combined_arch(), "the edit is live")
        self.assertEqual(
            len(self.history.history_for(cast("int", self.view.id))), 1, "recorded"
        )
        self.assertEqual(_snapshot(self.package.root_path), before, "disk untouched")
        self.assertEqual(self.package.state, "dirty", "and it says a write is owed")

        self.package.action_write_files()

        after = _snapshot(self.package.root_path)
        self.assertNotEqual(after, before)
        self.assertTrue(any("x_note" in content for content in after.values()))
        self.assertEqual(self.package.state, "synced")

    def test_the_gate_is_honoured_by_the_descriptor_entry_point_too(self):
        before = _snapshot(self.package.root_path)
        self.editor.apply_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "main"},
            {"type": "add_field", "name": "x_note"},
            write_files=False,
        )
        self.assertIn("x_note", self.view.get_combined_arch())
        self.assertEqual(_snapshot(self.package.root_path), before)

    def test_by_default_the_file_keeps_up_with_the_edit(self):
        before = _snapshot(self.package.root_path)
        self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "group", "name": "main"},
            "x_note",
        )
        self.assertNotEqual(_snapshot(self.package.root_path), before)

    # -- containers that can be pointed at again ---------------------------

    def test_a_new_group_gets_a_name_it_can_be_found_by(self):
        self.editor.add_container_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "sheet"},
            "group",
        )
        groups = [g.get("name") for g in self._combined().iter("group")]
        added = [n for n in groups if n and n.startswith("builder_group_")]
        self.assertEqual(len(added), 1, groups)
        found = cast(
            "_LocateTargetFoundJSON",
            self.editor.locate_target(
                cast("int", self.view.id), {"kind": "group", "name": added[0]}
            ),
        )
        self.assertEqual(
            found["xpath"],
            "//group[@name='%s']" % added[0],
            "named, so the locator is not a position that shifts",
        )

    def test_a_new_tab_and_its_notebook_get_names(self):
        self.editor.add_container_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "sheet"},
            "page",
            "Notes",
        )
        root = self._combined()
        notebook = root.find(".//notebook")
        page = notebook.find("page")
        self.assertTrue(notebook.get("name", "").startswith("builder_notebook_"))
        self.assertTrue(page.get("name", "").startswith("builder_page_"))
        self.assertEqual(page.get("string"), "Notes")

    def test_a_name_the_caller_gives_is_kept(self):
        self.editor.apply_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "sheet"},
            {"type": "add_group", "name": "mine", "string": "Mine"},
        )
        self.assertIsNotNone(self._combined().find(".//group[@name='mine']"))

    def test_two_containers_never_share_a_name(self):
        for _i in range(2):
            self.editor.add_container_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {"kind": "sheet"},
                "group",
            )
        names = [
            g.get("name")
            for g in self._combined().iter("group")
            if (g.get("name") or "").startswith("builder_group_")
        ]
        self.assertEqual(len(names), 2)
        self.assertEqual(len(set(names)), 2)

    def test_the_written_arch_carries_the_name(self):
        """The name is what makes the group addressable in the *source*, where
        the next session's locator will be minted."""
        self.editor.add_container_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "sheet"},
            "group",
            "Extra",
        )
        emitted = "".join(self.package._render_files().values())
        self.assertIn('name="builder_group_', emitted)

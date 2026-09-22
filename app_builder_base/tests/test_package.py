# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package lifecycle: writing, drift detection, guard rails."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import StudioCase, raises

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs this at runtime.
    from ..models.studio_package import StudioPackageFile


@tagged("post_install", "-at_install")
class TestPackage(StudioCase):
    def test_reserved_name_is_rejected(self):
        """graph.py hardcodes studio_customization out of the module graph."""
        with raises(self, ValidationError):
            self.make_package(name="studio_customization")

    def test_invalid_module_name_is_rejected(self):
        with raises(self, ValidationError):
            self.make_package(name="not a module")

    def test_write_creates_files_on_disk(self):
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()

        root = cast("str", package.root_path)
        for relative in (
            "__manifest__.py",
            "__init__.py",
            "models/x_studio_project.xml",
            "views/x_studio_project_views.xml",
            "security/ir.model.access.csv",
        ):
            self.assertTrue(
                os.path.isfile(os.path.join(root, relative)),
                "expected %s to be written" % relative,
            )
        self.assertEqual(package.state, "synced")
        self.assertTrue(package.file_ids)

    def test_write_is_idempotent(self):
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()
        target = os.path.join(
            cast("str", package.root_path), "models/x_studio_project.xml"
        )
        before = os.stat(target).st_mtime_ns

        package.action_write_files()
        after = os.stat(target).st_mtime_ns
        self.assertEqual(
            before,
            after,
            "an unchanged file must not be rewritten, or the FS watcher fires "
            "a pointless reload on every save",
        )

    def test_drift_is_detected(self):
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()
        package.action_check_drift()
        self.assertEqual(package.state, "synced")

        target = os.path.join(
            cast("str", package.root_path), "models/x_studio_project.xml"
        )
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("<!-- hand edit -->\n")

        package.action_check_drift()
        self.assertEqual(package.state, "drifted")
        drifted = (
            cast("StudioPackageFile", package.file_ids)
            .filtered("drifted")
            .mapped("path")
        )
        self.assertEqual(drifted, ["models/x_studio_project.xml"])

    def test_missing_directory_is_detected(self):
        import shutil

        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()
        shutil.rmtree(cast("str", package.root_path))
        package.action_check_drift()
        self.assertEqual(package.state, "missing")

    def test_readonly_package_refuses_to_write(self):
        """Production deployments are read-only by design, not by accident."""
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()
        package.root_path = self.unwritable_path()
        package.invalidate_recordset(["writable"])
        self.assertFalse(package.writable)
        with raises(self, UserError):
            package.action_write_files()

    def test_stale_generated_file_is_pruned(self):
        package = self.make_package()
        model = self.build_demo_content(package)
        package.action_write_files()

        view = self.env["ir.ui.view"].search([("model", "=", "x_studio_project")])
        action = self.env["ir.actions.act_window"].search(
            [("res_model", "=", "x_studio_project")]
        )
        menu = self.env["ir.ui.menu"].search([("name", "=", "Studio Demo Projects")])
        menu.unlink()
        action.unlink()
        view.unlink()
        package.action_write_files()

        self.assertFalse(
            os.path.isfile(
                os.path.join(
                    cast("str", package.root_path), "views/x_studio_project_views.xml"
                )
            ),
            "a generated file with no remaining records should be removed",
        )
        self.assertTrue(model.exists())

    def test_hand_edited_file_is_not_pruned(self):
        """We only delete files we generated and nobody has touched."""
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()

        target = os.path.join(
            cast("str", package.root_path), "views/x_studio_project_views.xml"
        )
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("<!-- mine -->\n")

        menu = self.env["ir.ui.menu"].search([("name", "=", "Studio Demo Projects")])
        action = self.env["ir.actions.act_window"].search(
            [("res_model", "=", "x_studio_project")]
        )
        view = self.env["ir.ui.view"].search([("model", "=", "x_studio_project")])
        menu.unlink()
        action.unlink()
        view.unlink()
        package.action_write_files()

        self.assertTrue(
            os.path.isfile(target), "a hand-edited file must never be deleted silently"
        )

    def test_app_icon_is_seeded_as_a_file(self):
        """The icon is a real PNG in the package and web_icon points at it in
        the two-part form every consumer understands -- a built
        ``fa-class,color,background`` icon crashes web_responsive's apps menu."""
        package = self.make_package()
        web_icon = package._seed_app_icon()
        self.assertEqual(web_icon, "%s,static/description/icon.png" % package.name)
        target = os.path.join(
            cast("str", package.root_path), "static/description/icon.png"
        )
        self.assertTrue(os.path.isfile(target))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")

    def test_a_replaced_app_icon_survives_writes_and_prunes(self):
        """A seed, not a render: the designer's PNG is never regenerated, and
        it is not tracked, so the pruning pass has no reason to look at it."""
        package = self.make_package()
        package._seed_app_icon()
        target = os.path.join(
            cast("str", package.root_path), "static/description/icon.png"
        )
        with open(target, "wb") as handle:
            handle.write(b"theirs")

        package._seed_app_icon()
        self.build_demo_content(package)
        package.action_write_files()
        # Same teardown as test_stale_generated_file_is_pruned: the next write
        # runs the prune pass over everything tracked.
        self.env["ir.ui.menu"].search([("name", "=", "Studio Demo Projects")]).unlink()
        self.env["ir.actions.act_window"].search(
            [("res_model", "=", "x_studio_project")]
        ).unlink()
        self.env["ir.ui.view"].search([("model", "=", "x_studio_project")]).unlink()
        package.action_write_files()

        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"theirs")

    def test_assign_allocates_stable_xmlids(self):
        package = self.make_package()
        vals: dict[str, object] = {
            "name": "Thing",
            "model": "x_studio_thing",
            "field_id": [],
        }
        model = self.env["ir.model"].create(vals)  # pyright: ignore[reportArgumentType]
        first = package._assign(model)
        second = package._assign(model)
        self.assertEqual(first, second, "assigning twice must not mint a new xmlid")
        self.assertEqual(first, ["%s.model_x_studio_thing" % package.name])

    def test_assign_deduplicates_colliding_names(self):
        package = self.make_package()
        vals: dict[str, object] = {
            "name": "same name",
            "model": "res.partner",
            "arch": "<form/>",
        }
        a = self.env["ir.ui.view"].create(vals)  # pyright: ignore[reportArgumentType]
        vals = {"name": "same name", "model": "res.partner", "arch": "<form/>"}
        b = self.env["ir.ui.view"].create(vals)  # pyright: ignore[reportArgumentType]
        first = package._assign(a)[0]
        second = package._assign(b)[0]
        self.assertNotEqual(first, second)

    def test_record_count_tracks_ownership(self):
        package = self.make_package()
        self.assertEqual(package.record_count, 0)
        self.build_demo_content(package)
        package.invalidate_recordset(["record_count"])
        self.assertGreater(package.record_count, 5)

    def test_ownership_is_searchable(self):
        """A domain on studio_package_id has to actually filter.

        Regression, and a quiet one. A non-stored field with no search method
        does not make the domain fail -- the ORM logs an error and *drops the
        leaf* (`expression.py:1179-1187`). So `[("studio_package_id", "=", id)]`
        degraded from "records this package owns" to "every record", and
        `studio.model.draft._owned_views` is built on exactly that domain: field
        placement would have edited a primary view belonging to another module
        in place, which is the one thing this project exists not to do.
        """
        package = self.make_package()
        self.build_demo_content(package)
        vals: dict[str, object] = {
            "name": "not ours",
            "model": "x_studio_project",
            "arch": "<form><sheet><field name='x_name'/></sheet></form>",
        }
        foreign = self.env["ir.ui.view"].create(vals)  # pyright: ignore[reportArgumentType]

        ours = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("studio_package_id", "=", package.id)]
        )
        self.assertTrue(ours, "the package's own views must be found")
        self.assertNotIn(
            foreign,
            ours,
            "an unowned view must not answer to a package's domain",
        )

        unowned = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("studio_package_id", "=", False)]
        )
        self.assertIn(foreign, unowned)
        self.assertFalse(ours & unowned, "owned and unowned must not overlap")

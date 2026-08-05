# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package lifecycle: writing, drift detection, guard rails."""

import os

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import StudioCase


@tagged("post_install", "-at_install")
class TestPackage(StudioCase):
    def test_reserved_name_is_rejected(self):
        """graph.py hardcodes studio_customization out of the module graph."""
        with self.assertRaises(ValidationError):
            self.make_package(name="studio_customization")

    def test_invalid_module_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_package(name="not a module")

    def test_write_creates_files_on_disk(self):
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()

        root = package.root_path
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
        target = os.path.join(package.root_path, "models/x_studio_project.xml")
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

        target = os.path.join(package.root_path, "models/x_studio_project.xml")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("<!-- hand edit -->\n")

        package.action_check_drift()
        self.assertEqual(package.state, "drifted")
        drifted = package.file_ids.filtered("drifted").mapped("path")
        self.assertEqual(drifted, ["models/x_studio_project.xml"])

    def test_missing_directory_is_detected(self):
        import shutil

        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()
        shutil.rmtree(package.root_path)
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
        with self.assertRaises(UserError):
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
                os.path.join(package.root_path, "views/x_studio_project_views.xml")
            ),
            "a generated file with no remaining records should be removed",
        )
        self.assertTrue(model.exists())

    def test_hand_edited_file_is_not_pruned(self):
        """We only delete files we generated and nobody has touched."""
        package = self.make_package()
        self.build_demo_content(package)
        package.action_write_files()

        target = os.path.join(package.root_path, "views/x_studio_project_views.xml")
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

    def test_assign_allocates_stable_xmlids(self):
        package = self.make_package()
        model = self.env["ir.model"].create(
            {"name": "Thing", "model": "x_studio_thing", "field_id": []}
        )
        first = package._assign(model)
        second = package._assign(model)
        self.assertEqual(first, second, "assigning twice must not mint a new xmlid")
        self.assertEqual(first, ["%s.model_x_studio_thing" % package.name])

    def test_assign_deduplicates_colliding_names(self):
        package = self.make_package()
        a = self.env["ir.ui.view"].create(
            {"name": "same name", "model": "res.partner", "arch": "<form/>"}
        )
        b = self.env["ir.ui.view"].create(
            {"name": "same name", "model": "res.partner", "arch": "<form/>"}
        )
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
        foreign = self.env["ir.ui.view"].create(
            {
                "name": "not ours",
                "model": "x_studio_project",
                "arch": "<form><sheet><field name='x_name'/></sheet></form>",
            }
        )

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

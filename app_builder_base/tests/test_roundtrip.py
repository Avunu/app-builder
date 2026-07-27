# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The invariant the whole architecture rests on.

Writing the database and the file in the same transaction is only legitimate if
loading the file reproduces the database exactly. If that holds, the DB write is
an optimisation; if it does not, we have two competing sources of truth and the
"files are truth" claim is a lie. So this is the test that decides whether the
design works.
"""

from odoo.tests import tagged

from .common import StudioCase


@tagged("post_install", "-at_install")
class TestRoundTrip(StudioCase):
    def test_render_is_deterministic(self):
        """Rendering twice from unchanged state produces identical bytes."""
        package = self.make_package()
        self.build_demo_content(package)
        first = package._render_files()
        second = package._render_files()
        self.assertEqual(first, second)

    def test_roundtrip_through_odoo_importer(self):
        """serialize -> wipe -> load -> serialize is a fixed point.

        Record ids all change across the wipe/reload, so byte-identical output
        also proves nothing leaks raw ids into the generated files.
        """
        package = self.make_package()
        self.build_demo_content(package)
        before = package._render_files()

        self.assertIn("models/x_studio_project.xml", before)
        self.assertIn("views/x_studio_project_views.xml", before)
        self.assertIn("security/ir.model.access.csv", before)

        original_ids = {
            entry.name: entry.res_id
            for entry in self.env["ir.model.data"].search(
                [("module", "=", package.name)]
            )
        }

        self.wipe_package_records(package)
        self.assertFalse(
            self.env["ir.model.data"].search([("module", "=", package.name)])
        )

        self.load_rendered(package, before)
        after = package._render_files()

        reloaded_ids = {
            entry.name: entry.res_id
            for entry in self.env["ir.model.data"].search(
                [("module", "=", package.name)]
            )
        }
        self.assertEqual(
            set(original_ids), set(reloaded_ids), "xmlid set must survive a reload"
        )

        for path in sorted(set(before) | set(after)):
            self.assertEqual(
                before.get(path),
                after.get(path),
                "round-trip changed %s" % path,
            )

    def test_reloaded_model_is_functional(self):
        """A model rebuilt from files is a real, usable ORM model."""
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        self.wipe_package_records(package)
        self.load_rendered(package, rendered)

        self.assertIn("x_studio_project", self.env)
        record = self.env["x_studio_project"].create(
            {"x_name": "Rebuilt", "x_budget": 21.0}
        )
        self.assertEqual(record.x_name, "Rebuilt")
        # The stored compute survived serialization as data, not code.
        self.assertEqual(record.x_budget_doubled, 42.0)
        # Selection values came back in order.
        field = self.env["ir.model.fields"]._get("x_studio_project", "x_stage")
        self.assertEqual(
            [s.value for s in field.selection_ids.sorted("sequence")],
            ["draft", "done"],
        )

    def test_no_raw_ids_in_output(self):
        """Relations must always be emitted as refs, never integer ids."""
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        menus = rendered["views/menus.xml"]
        self.assertIn('ref="', menus)
        models_xml = rendered["models/x_studio_project.xml"]
        self.assertIn('ref="model_x_studio_project"', models_xml)

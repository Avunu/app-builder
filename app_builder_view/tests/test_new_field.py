# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creating a field from inside the view editor.

Two answers, and which one applies is the substance. A manual field on a core
model is live the moment it is written, so create-and-place is one gesture. A
field on a model the package defines in Python is a class attribute and needs
the model re-imported, so the honest answer is the composer -- and saying so
before the form is filled in rather than after.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestNewFieldFromTheEditor(StudioCase):
    def _core_form(self):
        return self.env["ir.ui.view"].browse(
            self.env["ir.ui.view"].default_view("res.partner", "form")
        )

    def test_a_core_model_can_take_a_field_here(self):
        view = self._core_form()
        plan = self.env["studio.view.editor"].new_field_plan(view.id)
        self.assertTrue(plan["can_create"])
        self.assertEqual(plan["prefix"], "x_")

    def test_creating_one_places_it_in_the_same_gesture(self):
        package = self.make_package()
        view = self._core_form()
        self.env["studio.view.editor"].create_field_at(
            view.id,
            package.id,
            {"kind": "root"},
            {"field_description": "Delivery date", "ttype": "date"},
        )
        self.assertIn("x_delivery_date", self.env["res.partner"]._fields)
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", view.id), ("studio_package_id", "=", package.id)]
        )
        self.assertTrue(patch, "a core view must be patched, not rewritten")
        self.assertIn("x_delivery_date", patch.arch)

    def test_the_field_is_written_to_source(self):
        package = self.make_package()
        view = self._core_form()
        self.env["studio.view.editor"].create_field_at(
            view.id,
            package.id,
            {"kind": "root"},
            {"field_description": "Delivery date", "ttype": "date"},
        )
        self.assertIn("x_delivery_date", "".join(package._render_files().values()))

    def test_a_link_needs_something_to_link_to(self):
        package = self.make_package()
        view = self._core_form()
        with self.assertRaises(UserError):
            self.env["studio.view.editor"].create_field_at(
                view.id,
                package.id,
                {"kind": "root"},
                {"field_description": "Owner", "ttype": "many2one"},
            )

    def test_a_type_outside_the_quick_list_is_refused(self):
        """Selection, one2many and computed fields are conversations, and the
        composer is where conversations happen."""
        package = self.make_package()
        view = self._core_form()
        with self.assertRaises(UserError) as caught:
            self.env["studio.view.editor"].create_field_at(
                view.id,
                package.id,
                {"kind": "root"},
                {"field_description": "Stage", "ttype": "selection"},
            )
        self.assertIn("quick field types", str(caught.exception))

    def test_a_python_model_hands_off_to_the_composer(self):
        package = self.make_package()
        self.build_demo_content(package)
        self.env["studio.package.model"]._adopt(
            package, "x_studio_project", source="python"
        )
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        plan = self.env["studio.view.editor"].new_field_plan(view.id)
        self.assertFalse(plan["can_create"])
        self.assertEqual(plan["handoff"], package.id)
        self.assertIn("re-imported", plan["reason"])

    def test_the_handoff_refuses_rather_than_writing_a_row(self):
        """Writing a manual row onto a Python model is the drift this exists
        to prevent, so the refusal is the point rather than a limitation."""
        package = self.make_package()
        self.build_demo_content(package)
        self.env["studio.package.model"]._adopt(
            package, "x_studio_project", source="python"
        )
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        with self.assertRaises(UserError):
            self.env["studio.view.editor"].create_field_at(
                view.id,
                package.id,
                {"kind": "root"},
                {"field_description": "Late", "ttype": "boolean"},
            )
        self.assertNotIn("x_late", self.env["x_studio_project"]._fields)

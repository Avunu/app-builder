# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Driving the view editor the way a person does.

The unit tests prove the resolver picks the right node and the operations
produce the right arch. Neither can tell you whether *clicking* works: whether
the cog entry appears on an ordinary view, whether a click on a heading selects
instead of sorting the column, and whether the preview shows the result rather
than the arch it cached before the edit. That last one is the failure that
would cost the most trust and the one no server-side test can see.
"""

import tempfile

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestViewEditorTour(HttpCase):
    def test_a_list_view_can_be_edited_by_clicking_it(self):
        # Exactly one writable package, so editing_context can suggest it
        # without the editor having to ask which one to record into.
        self.env["studio.package"].create(
            {
                "name": "x_tour_view_pkg",
                "display_name_": "Tour Views",
                "root_path": tempfile.mkdtemp(prefix="studio-tour-"),
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_view_pkg", "state": "installed"}
        )

        # A plain list of a core model: the case the editor must handle by
        # emitting an inheriting view rather than rewriting anything.
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )
        self.env.ref("base.user_admin").groups_id |= self.env.ref(
            "app_builder_base.group_studio_manager"
        )

        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_view_editor_tour",
            login="admin",
        )

        # The tour asserts what the user sees; this asserts what was written.
        # A patch that renamed the column on screen but rewrote the base view
        # would look identical in the browser and be exactly wrong.
        base = self.env.ref("base.view_partner_tree")
        self.assertNotIn(
            "Full Name", base.arch, "the core view must not have been rewritten"
        )
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch, "the edit should live in an inheriting view")
        self.assertIn("Full Name", patch.arch)

    def test_a_form_view_can_be_edited_by_clicking_it(self):
        self.env["studio.package"].create(
            {
                "name": "x_tour_form_pkg",
                "display_name_": "Tour Forms",
                "root_path": tempfile.mkdtemp(prefix="studio-tour-form-"),
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "x_tour_form_pkg", "state": "installed"}
        )
        self.env.ref("base.user_admin").groups_id |= self.env.ref(
            "app_builder_base.group_studio_manager"
        )
        partner = self.env["res.partner"].create({"name": "Tour Subject"})
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contact",
                "res_model": "res.partner",
                "view_mode": "form",
                "res_id": partner.id,
            }
        )

        self.start_tour(
            "/odoo/action-%s/%s" % (action.id, partner.id),
            "app_builder_form_editor_tour",
            login="admin",
        )

        base = self.env.ref("base.view_partner_form")
        self.assertNotIn("Renamed Tab", base.arch)
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch)
        self.assertIn("Renamed Tab", patch.arch)

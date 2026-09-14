# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Build-an-app and Adopt flows, walked to Review and cancelled.

Building reloads the server twice; adopting once. Neither fits inside a
tour, so this pins the questions and the review, and asserts nothing
was written by the walk.
"""

import os
import tempfile

from odoo import Command
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioHttpCase, join_groups


@tagged("post_install", "-at_install")
class TestBuildAppTour(StudioHttpCase):
    def test_the_flows_ask_and_review_without_writing(self):
        root = tempfile.mkdtemp(prefix="studio-tour-")
        self.env["studio.package"].create(
            {
                "name": "tour_build_pkg",
                "display_name_": "Tour Build",
                "root_path": root,
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create(
            {"name": "tour_build_pkg", "state": "installed"}
        )
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        self.env["ir.model"].create(
            {
                "name": "Tour Loose",
                "model": "x_tour_loose",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_score",
                            "ttype": "float",
                            "field_description": "Score",
                        }
                    )
                ],
            }
        )
        action = self.env.ref("app_builder_view.studio_console_action")
        self.start_tour(
            "/odoo/action-%s" % action.id, "app_builder_build_app_tour", login="admin"
        )
        self.assertFalse(
            os.path.exists(os.path.join(root, "models")),
            "walking the flows must write nothing",
        )
        self.assertFalse(
            self.env["ir.model"].search_count([("model", "like", "tour_build_pkg.%")])
        )
        loose = self.env["ir.model"]._get("x_tour_loose")
        self.assertEqual(loose.state, "manual")

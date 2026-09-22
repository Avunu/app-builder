# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Build-an-app and Adopt flows, walked to Review and cancelled.

Building reloads the server twice; adopting once. Neither fits inside a
tour, so this pins the questions and the review, and asserts nothing
was written by the walk.
"""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.tests import tagged

from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.app_builder_base.tests.common import StudioHttpCase, join_groups
from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    from odoo.addons.base.models.res_users import Users


@tagged("post_install", "-at_install")
class TestBuildAppTour(StudioHttpCase):
    def test_the_flows_ask_and_review_without_writing(self):
        root = tempfile.mkdtemp(prefix="studio-tour-")
        package_vals: dict[str, object] = {
            "name": "tour_build_pkg",
            "display_name_": "Tour Build",
            "root_path": root,
            "auto_commit": "off",
        }
        self.env["studio.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {
            "name": "tour_build_pkg",
            "state": "installed",
        }
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        join_groups(
            cast("Users", typed.ref(self.env, "base.user_admin")),
            ["app_builder_base.group_studio_manager"],
        )
        model_vals: dict[str, object] = {
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
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        action = typed.ref(self.env, "app_builder_view.studio_console_action")
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
        loose = typed.model(self.env, IrModel)._get("x_tour_loose")
        self.assertEqual(loose.state, "manual")

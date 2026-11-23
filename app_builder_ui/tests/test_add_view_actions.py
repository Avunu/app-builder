# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A view the view editor adds reaches the package's own window actions.

``app_builder_view``'s ``add_view`` offers a new view type in the window
actions that show the model, but only in those the package owns -- and a
window action has an owner (``builder_package_id``) only because this addon
puts ``builder.owned.mixin`` on it. Without this addon no action is anybody's,
so ``app_builder_view`` can only pin that nothing changes; the half where
something does is pinned here, where actions can be owned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_actions import IrActionsActWindow
from odoo.addons.base.models.ir_model import IrModel

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
    from odoo.addons.app_builder_view.models.builder_view_editor import (
        BuilderViewEditor,
    )


@tagged("post_install", "-at_install")
class TestAddViewActions(BuilderCase):
    def setUp(self):
        super().setUp()
        # add_view lives in app_builder_view, which this addon does not
        # depend on.
        installed = self.env["ir.module.module"].search_count(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not installed:
            self.skipTest("app_builder_view is not installed")
        self.editor = cast("BuilderViewEditor", self.env["builder.view.editor"])
        self.package = self.make_package(name="x_addview_ui_pkg")
        self.other = self.make_package(name="x_addview_ui_other")
        # A model of our own, with no kanban, as in app_builder_view's
        # TestAddView: res.partner already ships one, so adding it is refused.
        self.demo = "x_addview_ui_demo"
        model_vals: dict[str, object] = {
            "name": "Add View UI Demo",
            "model": self.demo,
            "field_id": [
                Command.create(
                    {"name": "x_name", "ttype": "char", "field_description": "Name"}
                ),
                Command.create(
                    {"name": "x_when", "ttype": "date", "field_description": "When"}
                ),
            ],
        }
        typed.model(self.env, IrModel).create(model_vals)  # pyright: ignore[reportArgumentType]

    def _action(self, name: str, view_mode: str, owner: BuilderPackage | None):
        vals: dict[str, object] = {
            "name": name,
            "res_model": self.demo,
            "view_mode": view_mode,
        }
        action = typed.model(self.env, IrActionsActWindow).create(vals)  # pyright: ignore[reportArgumentType]
        if owner is not None:
            owner.builder_capture(action)
        return action

    def _add_kanban(self) -> None:
        self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))

    def test_the_new_type_reaches_every_action_the_package_owns(self):
        with_form = self._action("Ours", "list,form", self.package)
        list_only = self._action("Ours, list only", "list", self.package)
        # The premise the rest stands on: this addon gives actions an owner.
        for action in (with_form, list_only):
            self.assertEqual(
                cast("BuilderOwnedMixin", action).builder_package_id, self.package
            )
        self._add_kanban()
        self.assertEqual(
            with_form.view_mode,
            "list,kanban,form",
            "after list, before form: a form is a detail view and reads last",
        )
        self.assertEqual(list_only.view_mode, "list,kanban")

    def test_another_packages_action_is_left_alone(self):
        theirs = self._action("Theirs", "list,form", self.other)
        self.assertEqual(
            cast("BuilderOwnedMixin", theirs).builder_package_id, self.other
        )
        ours = self._action("Ours", "list,form", self.package)
        self._add_kanban()
        self.assertEqual(theirs.view_mode, "list,form")
        # Not because nothing was offered anywhere.
        self.assertIn("kanban", cast("str", ours.view_mode))

    def test_an_action_nobody_owns_is_left_alone(self):
        unowned = self._action("Nobody's", "list,form", None)
        self.assertFalse(cast("BuilderOwnedMixin", unowned).builder_package_id)
        ours = self._action("Ours", "list,form", self.package)
        self._add_kanban()
        self.assertEqual(unowned.view_mode, "list,form")
        self.assertIn("kanban", cast("str", ours.view_mode))

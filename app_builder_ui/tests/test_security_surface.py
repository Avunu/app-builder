# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Access rules and record rules, scoped to a model and captured on create.

The console's Access Control and Filter Rules tabs open Odoo's own lists. The
builder's job there is the same as for automations -- scope, ownership and
findability -- and these tests pin the two halves of it: the list shows the
model on the canvas and nothing else, and a row made from it belongs to the
package before anybody has to remember to assign it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModel, IrModelAccess

from ..models.builder_security_surface import BuilderSecuritySurface

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )


@tagged("post_install", "-at_install")
class TestSecuritySurface(BuilderCase):
    def _model(self, package):
        self.build_demo_content(package)
        return typed.model(self.env, IrModel)._get("x_builder_project")

    def test_the_access_action_is_scoped_to_the_model(self):
        """The domain names the model and the context defaults the picker to
        it, so New on that list starts on the right model."""
        package = self.make_package()
        model = self._model(package)
        action = typed.model(self.env, BuilderSecuritySurface).action_access(
            model_name="x_builder_project"
        )
        self.assertEqual(action["res_model"], "ir.model.access")
        self.assertIn(("model_id.model", "=", "x_builder_project"), action["domain"])
        self.assertEqual(action["context"]["default_model_id"], model.id)
        self.assertEqual(action["context"]["builder_package_id"], package.id)

    def test_the_rules_action_is_scoped_to_the_model(self):
        package = self.make_package()
        model = self._model(package)
        action = typed.model(self.env, BuilderSecuritySurface).action_rules(
            model_name="x_builder_project"
        )
        self.assertEqual(action["res_model"], "ir.rule")
        self.assertIn(("model_id.model", "=", "x_builder_project"), action["domain"])
        self.assertEqual(action["context"]["default_model_id"], model.id)
        self.assertEqual(action["context"]["builder_package_id"], package.id)

    def test_the_domain_finds_the_rows_of_that_model_only(self):
        """A domain that looked right and searched wrong would show every
        row in the database, which is the screen the tab exists to avoid."""
        package = self.make_package()
        model = self._model(package)
        vals: dict[str, object] = {
            "name": "scoped access",
            "model_id": model.id,
            "group_id": typed.ref(self.env, "base.group_user").id,
        }
        mine = self.env["ir.model.access"].create(vals)  # pyright: ignore[reportArgumentType]
        action = typed.model(self.env, BuilderSecuritySurface).action_access(
            model_name="x_builder_project"
        )
        found = typed.model(self.env, IrModelAccess).search(action["domain"])
        self.assertIn(mine, found)
        self.assertTrue(all(row.model_id == model for row in found))

    def test_no_model_means_the_whole_list(self):
        """The Builder menu has no model in hand; the tab always does."""
        self.make_package()
        action = typed.model(self.env, BuilderSecuritySurface).action_rules()
        self.assertEqual(action["domain"], [])
        self.assertNotIn("default_model_id", action["context"])

    def test_an_unknown_model_is_refused(self):
        self.make_package()
        with raises(self, UserError):
            typed.model(self.env, BuilderSecuritySurface).action_access(
                model_name="x_no_such"
            )

    def test_a_real_choice_of_package_is_not_guessed(self):
        """Two writable packages: putting the row in one of them would be
        discovered at review time, so the context names none."""
        self.make_package(name="x_builder_one")
        self.make_package(name="x_builder_two")
        action = typed.model(self.env, BuilderSecuritySurface).action_access()
        self.assertFalse(action["context"]["builder_package_id"])

    def test_the_consoles_package_is_the_one_the_list_records_into(self):
        """Two writable packages and the console has already picked one:
        the tab passes it, the context names it, and a row made from the
        list lands in that package's CSV -- not in none, and not in the
        other one."""
        one = self.make_package(name="x_builder_one")
        two = self.make_package(name="x_builder_two")
        model = self._model(two)
        Surface = typed.model(self.env, BuilderSecuritySurface)
        # `.id` on a persisted record is `IdType | Literal[False]`
        # (`NewId` covers only an unsaved one); same "true by construction"
        # cast to `int` as `builder_view_edit.py`'s own `e.id` reads.
        action = Surface.action_access(
            model_name="x_builder_project", package_id=cast("int", two.id)
        )
        self.assertEqual(action["context"]["builder_package_id"], two.id)
        self.assertEqual(
            Surface.action_rules(package_id=cast("int", one.id))["context"][
                "builder_package_id"
            ],
            one.id,
        )
        vals: dict[str, object] = {
            "name": "console access",
            "model_id": model.id,
            "group_id": typed.ref(self.env, "base.group_user").id,
        }
        access = (
            self.env["ir.model.access"].with_context(**action["context"]).create(vals)  # pyright: ignore[reportArgumentType]
        )
        self.assertEqual(cast("BuilderOwnedMixin", access).builder_package_id, two)
        self.assertIn(
            "console access", two._render_files()["security/ir.model.access.csv"]
        )
        self.assertNotIn("console access", "".join(one._render_files().values()))

    def test_a_package_that_cannot_be_written_is_not_chosen(self):
        """A package the console names but that is read-only, or gone, is
        no place to record into; the suggestion stands in for it."""
        package = self.make_package()
        gone = self.make_package(name="x_builder_gone")
        gone_id = cast("int", gone.id)
        gone.unlink()
        action = typed.model(self.env, BuilderSecuritySurface).action_access(
            package_id=gone_id
        )
        self.assertEqual(action["context"]["builder_package_id"], package.id)

    def test_an_access_row_created_in_context_lands_in_source(self):
        """The row Odoo's list creates from the tab's context is captured the
        moment it exists -- the same bargain as an automation."""
        package = self.make_package()
        model = self._model(package)
        action = typed.model(self.env, BuilderSecuritySurface).action_access(
            model_name="x_builder_project"
        )
        vals: dict[str, object] = {
            "name": "captured access",
            "model_id": action["context"]["default_model_id"],
            "group_id": typed.ref(self.env, "base.group_user").id,
            "perm_read": True,
        }
        access = (
            typed.model(self.env, IrModelAccess)
            .with_context(**action["context"])
            .create(vals)  # pyright: ignore[reportArgumentType]
        )
        self.assertEqual(access.model_id, model)
        self.assertEqual(cast("BuilderOwnedMixin", access).builder_package_id, package)
        # The row's own name: the demo content already gives the model an
        # access row, so the model's id in the CSV would prove nothing.
        self.assertIn(
            "captured access",
            package._render_files()["security/ir.model.access.csv"],
        )

    def test_a_rule_created_in_context_lands_in_source(self):
        package = self.make_package()
        self._model(package)
        action = typed.model(self.env, BuilderSecuritySurface).action_rules(
            model_name="x_builder_project"
        )
        vals: dict[str, object] = {
            "name": "captured rule",
            "model_id": action["context"]["default_model_id"],
            "domain_force": "[('x_name', '!=', False)]",
        }
        rule = (
            self.env["ir.rule"].with_context(**action["context"]).create(vals)  # pyright: ignore[reportArgumentType]
        )
        self.assertEqual(cast("BuilderOwnedMixin", rule).builder_package_id, package)
        self.assertIn("captured rule", "".join(package._render_files().values()))

    def test_nothing_is_captured_without_a_package_in_context(self):
        """Ordinary use of Settings → Technical must be unaffected."""
        package = self.make_package()
        model = self._model(package)
        vals: dict[str, object] = {
            "name": "untouched access",
            "model_id": model.id,
            "group_id": typed.ref(self.env, "base.group_user").id,
        }
        access = self.env["ir.model.access"].create(vals)  # pyright: ignore[reportArgumentType]
        self.assertFalse(cast("BuilderOwnedMixin", access).builder_package_id)

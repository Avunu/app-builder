# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The app builder as the console calls it: ids in, dicts out.

The building itself -- install, apply, reload -- cannot run inside a
transaction test (``_button_immediate_function`` refuses test mode) and is
covered by ``probe_scaffold.py``. What is tested here is everything around
it: the features on offer, the name a label gets, the menu a new app may
go under, a feature staged on a model that exists, and adoption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.models.builder_model_draft import BuilderModelDraft
from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import scaffold, typed
from odoo.addons.base.models.ir_actions import IrActionsActWindow
from odoo.addons.base.models.ir_model import IrModelFields

from ..models.builder_app import BuilderApp

if TYPE_CHECKING:
    # Only for the cast() calls below; with `from __future__ import
    # annotations` nothing here needs these at runtime -- same bargain
    # `typed.py`'s own `TYPE_CHECKING` block makes.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.app_builder_base.models.builder_package_model import (
        BuilderPackageModel,
    )
    from odoo.addons.base.models.ir_ui_menu import IrUiMenu


@tagged("post_install", "-at_install")
class TestAppBuilderRpc(BuilderCase):
    def setUp(self):
        super().setUp()
        self.builder = typed.model(self.env, BuilderApp)
        self.package = self.make_package(name="x_rpc_pkg")

    def _python_package(self, name="x_rpc_py"):
        package = self.make_package(name=name)
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        return package

    # -- features and names -----------------------------------------------------

    def test_features_cover_the_registry_and_say_what_each_implies(self):
        payload = self.builder.features()
        keys = [f["key"] for f in payload["features"]]
        self.assertEqual(keys, [f.key for f in scaffold.FEATURES])
        by_key = {f["key"]: f for f in payload["features"]}
        self.assertIn("activities", by_key["chatter"]["implies"])
        self.assertEqual(by_key["tags"]["companion"], "tag")
        self.assertFalse(by_key["activities"]["offered"], "implied, not a tile")
        self.assertIn("chatter", payload["defaults"])

    def test_suggest_name_follows_the_package_and_reports_a_taken_name(self):
        answer = self.builder.suggest_name("Workshop Job", cast("int", self.package.id))
        self.assertEqual(answer, {"model": "rpc_pkg.workshop_job", "taken": False})
        # A manual model with the derived name counts as taken.
        vals: dict[str, object] = {"name": "Clash", "model": "x_rpc_pkg_clash"}
        self.env["ir.model"].create(vals)  # pyright: ignore[reportArgumentType]
        clash = self.make_package(name="x_rpc_pkg_clash_pkg")
        self.assertFalse(
            self.builder.suggest_name("Clash", cast("int", clash.id))["taken"]
        )
        self.assertEqual(
            self.builder.suggest_name("", cast("int", self.package.id))["model"],
            "rpc_pkg",
        )

    # -- the menu an app goes under ---------------------------------------------------

    def test_a_parent_menu_needs_an_external_id(self):
        loose_vals: dict[str, object] = {"name": "Loose root"}
        loose = self.env["ir.ui.menu"].create(loose_vals)  # pyright: ignore[reportArgumentType]
        with raises(self, UserError) as caught:
            self.builder._menu_parent({"parent_id": loose.id})
        self.assertIn("external id", str(caught.exception))
        self.assertIsNone(self.builder._menu_parent(None))
        self.assertIsNone(self.builder._menu_parent({"new_root": True}))
        parent = typed.ref(self.env, "base.menu_administration")
        self.assertEqual(self.builder._menu_parent({"parent_id": parent.id}), parent)

    def test_an_app_under_an_existing_menu_has_no_root(self):
        spec = scaffold.scaffold_spec("rpc_pkg.job", "Job", scaffold.ScaffoldOptions())
        action_vals: dict[str, object] = {"name": "Job", "res_model": "res.partner"}
        action = typed.model(self.env, IrActionsActWindow).create(action_vals)  # pyright: ignore[reportArgumentType]
        parent = cast("IrUiMenu", typed.ref(self.env, "base.menu_administration"))
        menus = self.builder._build_menu(spec, action, self.package, parent=parent)
        self.assertFalse(menus["root"])
        self.assertEqual(menus["item"].parent_id, parent)
        self.assertFalse(menus["item"].web_icon)

    def test_create_app_rpc_refuses_what_create_app_would(self):
        with raises(self, UserError):
            self.builder.create_app_rpc(cast("int", self.package.id), {"label": ""})
        with raises(self, UserError) as caught:
            self.builder.create_app_rpc(
                cast("int", self.package.id),
                {"label": "X", "features": ["nope"]},
            )
        self.assertIn("nope", str(caught.exception))
        builder = self.make_user("rpc_builder", ["app_builder_base.group_builder_user"])
        with raises(self, AccessError):
            self.builder.with_user(builder).create_app_rpc(
                cast("int", self.package.id), {"label": "X"}
            )

    # -- a feature on a model that exists --------------------------------------------

    def test_add_feature_stages_fields_and_options_on_the_draft(self):
        package = self._python_package()
        answer = self.builder.add_feature(
            cast("int", package.id), "x_builder_project", "user"
        )
        self.assertEqual(answer["added"], ["user_id"])
        self.assertEqual(answer["views"], [])
        draft = typed.model(self.env, BuilderModelDraft).browse(answer["draft_id"])
        self.assertTrue(draft.dirty)
        self.assertIsNotNone(draft._spec().field("user_id"))
        self.assertEqual(draft._features(), ["user"])

    def test_add_feature_chatter_stages_the_mixins(self):
        package = self._python_package(name="x_rpc_chat")
        answer = self.builder.add_feature(
            cast("int", package.id), "x_builder_project", "chatter"
        )
        self.assertTrue(answer["chatter"])
        self.assertIn("mail.thread", answer["options"]["inherit"])
        draft = typed.model(self.env, BuilderModelDraft).browse(answer["draft_id"])
        self.assertIn("mail.activity.mixin", draft._spec().inherit)
        # Asking twice has nothing left to add.
        with raises(self, UserError) as caught:
            self.builder.add_feature(
                cast("int", package.id), "x_builder_project", "chatter"
            )
        self.assertIn("already has everything", str(caught.exception))

    def test_add_feature_reference_stages_the_sequence(self):
        package = self._python_package(name="x_rpc_ref")
        answer = self.builder.add_feature(
            cast("int", package.id), "x_builder_project", "reference"
        )
        self.assertEqual(answer["added"], ["reference"])
        self.assertEqual(answer["options"]["sequence_field"], "reference")
        draft = typed.model(self.env, BuilderModelDraft).browse(answer["draft_id"])
        self.assertEqual(draft._spec().sequence_field, "reference")

    def test_add_feature_stage_wants_a_kanban_after_apply(self):
        package = self._python_package(name="x_rpc_stage")
        answer = self.builder.add_feature(
            cast("int", package.id), "x_builder_project", "stage"
        )
        self.assertIn("state", answer["added"])
        self.assertEqual(answer["views"], ["kanban"])

    def test_tags_and_lines_are_refused_with_the_sentence(self):
        package = self._python_package(name="x_rpc_tags")
        for key in ("tags", "lines"):
            with raises(self, UserError) as caught:
                self.builder.add_feature(
                    cast("int", package.id), "x_builder_project", key
                )
            self.assertIn("second model", str(caught.exception))

    def test_add_feature_refuses_another_packages_model(self):
        package = self._python_package(name="x_rpc_owner")
        with raises(self, UserError) as caught:
            self.builder.add_feature(
                cast("int", self.package.id), "x_builder_project", "user"
            )
        self.assertIn("switch", str(caught.exception).lower())
        self.assertIn(package.name, str(caught.exception))

    # -- adopt ------------------------------------------------------------------------

    def _manual_model(self, model_name, label="Loose"):
        vals: dict[str, object] = {
            "name": label,
            "model": model_name,
            "field_id": [
                Command.create(
                    {"name": "x_name", "ttype": "char", "field_description": "Name"}
                )
            ],
        }
        return self.env["ir.model"].create(vals)  # pyright: ignore[reportArgumentType]

    def test_adoptable_models_lists_loose_models_with_a_preview(self):
        self._manual_model("x_rpc_loose")
        listed = {m["model"]: m for m in self.builder.adoptable_models()}
        self.assertIn("x_rpc_loose", listed)
        entry = listed["x_rpc_loose"]
        self.assertEqual(entry["origin"], "manual")
        self.assertIsNone(entry["owner_package"])
        self.assertEqual(entry["field_count"], 1)
        self.assertIn("class XRpcLoose", entry["preview"])

    def test_a_model_already_in_python_is_not_adoptable(self):
        self._python_package(name="x_rpc_haspy")
        self.assertNotIn(
            "x_builder_project", [m["model"] for m in self.builder.adoptable_models()]
        )

    def test_adopt_captures_and_writes_the_class(self):
        self._manual_model("x_rpc_adopted")
        answer = self.builder.adopt(
            cast("int", self.package.id), ["x_rpc_adopted"], apply=False
        )
        self.assertEqual(answer["captured"], ["x_rpc_adopted"])
        self.assertFalse(answer["applied"])
        self.assertFalse(answer["restart_required"])
        entry = cast("BuilderPackageModel", self.package.model_ids).filtered(
            lambda m: m.model == "x_rpc_adopted"
        )
        self.assertEqual(entry.source, "python")
        source = cast("str", self.package._read_source(cast("str", entry.python_path)))
        self.assertIn("x_name", source)
        with raises(self, UserError):
            self.builder.adopt(cast("int", self.package.id), [], apply=False)

    # -- a manual field --------------------------------------------------------------

    def test_create_field_writes_a_manual_field_into_the_package(self):
        answer = self.builder.create_field(
            cast("int", self.package.id),
            "res.partner",
            {
                "name": "x_rpc_score",
                "field_description": "Score",
                "ttype": "float",
                "compute": "for r in self: r['x_rpc_score'] = 1.0",
            },
        )
        field = typed.model(self.env, IrModelFields).browse(answer["field_id"])
        self.assertEqual(field.compute, "for r in self: r['x_rpc_score'] = 1.0")
        self.assertEqual(
            cast("BuilderOwnedMixin", field.sudo()).builder_package_id, self.package
        )
        with raises(self, UserError):
            self.builder.create_field(
                cast("int", self.package.id),
                "res.partner",
                {"name": "nope", "ttype": "char"},
            )
        with raises(self, UserError):
            self.builder.create_field(
                cast("int", self.package.id),
                "res.partner",
                {"name": "x_rel", "ttype": "many2one"},
            )

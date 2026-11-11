# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The menu surface: a tree of the package's menus, an app or a submenu
made with its action, moved among its siblings, and gone with its action."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_ui_menu import IrUiMenu

from ..models.builder_menu_surface import BuilderMenu

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime -- `IrModel`/`IrUiMenu`/
    # `BuilderMenu` are real, top-level imports instead (above), since
    # `typed.model()` reads `cls._name` at *runtime*. `BuilderOwnedMixin` and
    # `BuilderRecordSurface` are mixins `ir.ui.menu`/`ir.actions.act_window`
    # and `builder.menu` itself compose only via `_inherit` (registry-level,
    # never a real Python base class), the same gap `typed.py`'s own
    # `security()`/`serializer()` document for the builder's other mixins.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.app_builder_base.models.builder_record_surface import (
        BuilderRecordSurface,
    )
    from odoo.addons.base.models.ir_actions import IrActionsActWindow


@tagged("post_install", "-at_install")
class TestMenuSurface(BuilderCase):
    def setUp(self):
        super().setUp()
        self.Surface = typed.model(self.env, BuilderMenu)
        self.package = self.make_package()
        self.build_demo_content(self.package)
        self.model = typed.model(self.env, IrModel)._get("x_builder_project")

    def _file(self):
        return self.package._render_files().get("views/menus.xml", "")

    def _titles(self):
        # `rows()`'s `model_name` is declared `str`, but its own body only
        # does `bool(model_name)` (builder_menu_surface.py) -- `False` marks
        # "no filter" on purpose, narrower than the declared type allows.
        return [
            (r["depth"], r["title"])
            for r in self.Surface.rows(
                False,  # pyright: ignore[reportArgumentType]
                cast("int", self.package.id),
            )
        ]

    def test_an_app_is_a_root_with_an_icon_and_an_action(self):
        row = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Tour App", "opens_model": self.model.id},
            template="app",
        )
        menu = cast("IrUiMenu", self.env["ir.ui.menu"].browse(row["id"]))
        self.assertFalse(menu.parent_id)
        self.assertTrue(menu.web_icon)
        self.assertEqual(
            cast("IrActionsActWindow", menu.action)._name, "ir.actions.act_window"
        )
        self.assertEqual(
            cast("IrActionsActWindow", menu.action).res_model, "x_builder_project"
        )
        self.assertEqual(
            cast("BuilderOwnedMixin", menu).builder_package_id, self.package
        )
        self.assertEqual(
            cast("BuilderOwnedMixin", menu.action).builder_package_id, self.package
        )
        self.assertIn("Tour App", self._file())
        self.assertIn(
            "Tour App",
            self.package._render_files()["views/x_builder_project_views.xml"],
        )
        self.assertIn("Opens x_builder_project", row["sentence"])

    def test_a_submenu_needs_a_parent_and_sits_under_it(self):
        app = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Tour App"},
            template="app",
        )
        with raises(self, UserError):
            self.Surface.create_record(
                False,  # pyright: ignore[reportArgumentType]
                cast("int", self.package.id),
                {"name": "Orphan", "opens_model": self.model.id},
                template="submenu",
            )
        self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Projects", "parent_id": app["id"], "opens_model": self.model.id},
            template="submenu",
        )
        rows = self.Surface.rows("x_builder_project", cast("int", self.package.id))
        by_title = {r["title"]: r for r in rows}
        self.assertEqual(by_title["Projects"]["depth"], 1)
        self.assertEqual(by_title["Projects"]["parent_id"], app["id"])
        self.assertTrue(by_title["Projects"]["highlight"])
        self.assertFalse(by_title["Tour App"]["highlight"])

    def test_a_foreign_parent_is_shown_greyed_and_not_edited(self):
        parent = cast("IrUiMenu", typed.ref(self.env, "base.menu_administration"))
        sub = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {
                "name": "Under Settings",
                "parent_id": parent.id,
                "opens_model": self.model.id,
            },
            template="submenu",
        )
        rows = {
            r["title"]: r
            for r in self.Surface.rows(
                False,  # pyright: ignore[reportArgumentType]
                cast("int", self.package.id),
            )
        }
        self.assertIn(parent.name, rows)
        # `name` is `required=True` on `ir.ui.menu`, the same true-by-
        # construction idiom `builder_menu_surface.py`'s own `_row` uses.
        self.assertFalse(rows[cast("str", parent.name)]["editable"])
        self.assertIn("base", rows[cast("str", parent.name)]["reason"])
        self.assertEqual(rows["Under Settings"]["depth"], 1)
        self.assertEqual(rows["Under Settings"]["parent_id"], parent.id)
        with raises(self, UserError):
            self.Surface.write_record(
                cast("int", parent.id), {"name": "Mine"}, cast("int", self.package.id)
            )
        self.assertIn("base.menu_administration", self._file())
        self.assertEqual(sub["owned"], True)

    def test_move_renumbers_the_owned_siblings_only(self):
        app = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Tour App"},
            template="app",
        )
        names = ["One", "Two", "Three"]
        ids = {}
        for name in names:
            ids[name] = self.Surface.create_record(
                False,  # pyright: ignore[reportArgumentType]
                cast("int", self.package.id),
                {"name": name, "parent_id": app["id"]},
                template="submenu",
            )["id"]
        Menu = typed.model(self.env, IrUiMenu)
        self.assertEqual([Menu.browse(ids[n]).sequence for n in names], [10, 20, 30])
        # A sibling from elsewhere keeps its number.
        theirs_vals: dict[str, object] = {
            "name": "Theirs",
            "parent_id": app["id"],
            "sequence": 25,
        }
        theirs = Menu.create(theirs_vals)  # pyright: ignore[reportArgumentType]
        data_vals: dict[str, object] = {
            "module": "some_module",
            "name": "theirs",
            "model": "ir.ui.menu",
            "res_id": theirs.id,
        }
        self.env["ir.model.data"].create(data_vals)  # pyright: ignore[reportArgumentType]
        order = self.Surface.move(
            ids["Three"], app["id"], ids["One"], cast("int", self.package.id)
        )
        self.assertEqual(order[0], ids["Three"])
        self.assertEqual(Menu.browse(ids["Three"]).sequence, 10)
        self.assertEqual(Menu.browse(ids["One"]).sequence, 20)
        self.assertEqual(theirs.sequence, 25)
        self.assertEqual(Menu.browse(ids["Two"]).sequence, 30)
        # The foreign sibling is shown where it sits, greyed.
        self.assertEqual(
            [t for _d, t in self._titles()],
            ["Builder Demo Projects", "Tour App", "Three", "One", "Theirs", "Two"],
        )
        # Reparenting to a descendant is refused.
        with raises(self, UserError):
            self.Surface.move(
                app["id"], ids["One"], False, cast("int", self.package.id)
            )
        # To the root, last.
        self.Surface.move(ids["Two"], False, False, cast("int", self.package.id))
        self.assertFalse(Menu.browse(ids["Two"]).parent_id)

    def test_pointing_a_menu_at_a_model_makes_an_action_and_drops_the_orphan(self):
        app = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Tour App"},
            template="app",
        )
        sub = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Projects", "parent_id": app["id"], "opens_model": self.model.id},
            template="submenu",
        )
        menu = cast("IrUiMenu", self.env["ir.ui.menu"].browse(sub["id"]))
        old_action = menu.action
        users = typed.model(self.env, IrModel)._get("res.users")
        self.Surface.write_record(
            sub["id"], {"opens_model": users.id}, cast("int", self.package.id)
        )
        self.assertEqual(cast("IrActionsActWindow", menu.action).res_model, "res.users")
        self.assertFalse(cast("IrActionsActWindow", old_action).exists())
        described = cast(
            "dict[str, Any]",
            cast("BuilderRecordSurface", self.Surface).describe(
                sub["id"], cast("int", self.package.id)
            ),
        )
        self.assertEqual(described["values"]["opens_model"]["id"], users.id)
        self.assertIn("ir.actions.act_window", described["values"]["action"])

    def test_remove_takes_the_action_along_when_nothing_else_opens_it(self):
        app = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Tour App", "opens_model": self.model.id},
            template="app",
        )
        menu = cast("IrUiMenu", self.env["ir.ui.menu"].browse(app["id"]))
        action = cast("IrActionsActWindow", menu.action)
        other_vals: dict[str, object] = {
            "name": "Also",
            "action": "ir.actions.act_window,%d" % action.id,
        }
        other = self.env["ir.ui.menu"].create(other_vals)  # pyright: ignore[reportArgumentType]
        self.Surface.remove_record(app["id"], cast("int", self.package.id), force=True)
        self.assertTrue(action.exists(), "another menu still opens it")
        other.unlink()
        sub = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Alone", "opens_model": self.model.id},
            template="app",
        )
        alone = cast(
            "IrActionsActWindow",
            cast("IrUiMenu", self.env["ir.ui.menu"].browse(sub["id"])).action,
        )
        self.Surface.remove_record(sub["id"], cast("int", self.package.id), force=True)
        self.assertFalse(alone.exists())
        self.assertNotIn("Alone", "".join(self.package._render_files().values()))

    def test_the_menus_of_the_package_round_trip(self):
        app = self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {"name": "Tour App", "opens_model": self.model.id},
            template="app",
        )
        self.Surface.create_record(
            False,  # pyright: ignore[reportArgumentType]
            cast("int", self.package.id),
            {
                "name": "Projects",
                "parent_id": app["id"],
                "opens_model": self.model.id,
                "groups": [typed.ref(self.env, "base.group_user").id],
            },
            template="submenu",
        )
        files = self.package._render_files()
        menus = typed.model(self.env, IrUiMenu).search(
            [("builder_package_id", "=", self.package.id)]
        )
        xmlids = [m.get_external_id()[m.id] for m in menus]
        actions = [cast("IrActionsActWindow", m.action) for m in menus if m.action]
        menus.unlink()
        for action in actions:
            action.unlink()
        self.load_rendered(self.package, files)
        reloaded = typed.model(self.env, IrUiMenu).browse(
            [typed.ref(self.env, x).id for x in xmlids]
        )
        by_name = {m.name: m for m in reloaded}
        self.assertEqual(by_name["Projects"].parent_id, by_name["Tour App"])
        self.assertEqual(
            cast("IrActionsActWindow", by_name["Projects"].action).res_model,
            "x_builder_project",
        )
        self.assertTrue(by_name["Tour App"].web_icon)

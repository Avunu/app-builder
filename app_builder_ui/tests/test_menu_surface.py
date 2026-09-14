# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The menu surface: a tree of the package's menus, an app or a submenu
made with its action, moved among its siblings, and gone with its action."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestMenuSurface(StudioCase):
    def setUp(self):
        super().setUp()
        self.Surface = self.env["studio.menu"]
        self.package = self.make_package()
        self.build_demo_content(self.package)
        self.model = self.env["ir.model"]._get("x_studio_project")

    def _file(self):
        return self.package._render_files().get("views/menus.xml", "")

    def _titles(self):
        return [
            (r["depth"], r["title"]) for r in self.Surface.rows(False, self.package.id)
        ]

    def test_an_app_is_a_root_with_an_icon_and_an_action(self):
        row = self.Surface.create_record(
            False,
            self.package.id,
            {"name": "Tour App", "opens_model": self.model.id},
            template="app",
        )
        menu = self.env["ir.ui.menu"].browse(row["id"])
        self.assertFalse(menu.parent_id)
        self.assertTrue(menu.web_icon)
        self.assertEqual(menu.action._name, "ir.actions.act_window")
        self.assertEqual(menu.action.res_model, "x_studio_project")
        self.assertEqual(menu.studio_package_id, self.package)
        self.assertEqual(menu.action.studio_package_id, self.package)
        self.assertIn("Tour App", self._file())
        self.assertIn(
            "Tour App", self.package._render_files()["views/x_studio_project_views.xml"]
        )
        self.assertIn("Opens x_studio_project", row["sentence"])

    def test_a_submenu_needs_a_parent_and_sits_under_it(self):
        app = self.Surface.create_record(
            False, self.package.id, {"name": "Tour App"}, template="app"
        )
        with self.assertRaises(UserError):
            self.Surface.create_record(
                False,
                self.package.id,
                {"name": "Orphan", "opens_model": self.model.id},
                template="submenu",
            )
        self.Surface.create_record(
            False,
            self.package.id,
            {"name": "Projects", "parent_id": app["id"], "opens_model": self.model.id},
            template="submenu",
        )
        rows = self.Surface.rows("x_studio_project", self.package.id)
        by_title = {r["title"]: r for r in rows}
        self.assertEqual(by_title["Projects"]["depth"], 1)
        self.assertEqual(by_title["Projects"]["parent_id"], app["id"])
        self.assertTrue(by_title["Projects"]["highlight"])
        self.assertFalse(by_title["Tour App"]["highlight"])

    def test_a_foreign_parent_is_shown_greyed_and_not_edited(self):
        parent = self.env.ref("base.menu_administration")
        sub = self.Surface.create_record(
            False,
            self.package.id,
            {
                "name": "Under Settings",
                "parent_id": parent.id,
                "opens_model": self.model.id,
            },
            template="submenu",
        )
        rows = {r["title"]: r for r in self.Surface.rows(False, self.package.id)}
        self.assertIn(parent.name, rows)
        self.assertFalse(rows[parent.name]["editable"])
        self.assertIn("base", rows[parent.name]["reason"])
        self.assertEqual(rows["Under Settings"]["depth"], 1)
        self.assertEqual(rows["Under Settings"]["parent_id"], parent.id)
        with self.assertRaises(UserError):
            self.Surface.write_record(parent.id, {"name": "Mine"}, self.package.id)
        self.assertIn("base.menu_administration", self._file())
        self.assertEqual(sub["owned"], True)

    def test_move_renumbers_the_owned_siblings_only(self):
        app = self.Surface.create_record(
            False, self.package.id, {"name": "Tour App"}, template="app"
        )
        names = ["One", "Two", "Three"]
        ids = {}
        for name in names:
            ids[name] = self.Surface.create_record(
                False,
                self.package.id,
                {"name": name, "parent_id": app["id"]},
                template="submenu",
            )["id"]
        Menu = self.env["ir.ui.menu"]
        self.assertEqual([Menu.browse(ids[n]).sequence for n in names], [10, 20, 30])
        # A sibling from elsewhere keeps its number.
        theirs = Menu.create({"name": "Theirs", "parent_id": app["id"], "sequence": 25})
        self.env["ir.model.data"].create(
            {
                "module": "some_module",
                "name": "theirs",
                "model": "ir.ui.menu",
                "res_id": theirs.id,
            }
        )
        order = self.Surface.move(ids["Three"], app["id"], ids["One"], self.package.id)
        self.assertEqual(order[0], ids["Three"])
        self.assertEqual(Menu.browse(ids["Three"]).sequence, 10)
        self.assertEqual(Menu.browse(ids["One"]).sequence, 20)
        self.assertEqual(theirs.sequence, 25)
        self.assertEqual(Menu.browse(ids["Two"]).sequence, 30)
        # The foreign sibling is shown where it sits, greyed.
        self.assertEqual(
            [t for _d, t in self._titles()],
            ["Studio Demo Projects", "Tour App", "Three", "One", "Theirs", "Two"],
        )
        # Reparenting to a descendant is refused.
        with self.assertRaises(UserError):
            self.Surface.move(app["id"], ids["One"], False, self.package.id)
        # To the root, last.
        self.Surface.move(ids["Two"], False, False, self.package.id)
        self.assertFalse(Menu.browse(ids["Two"]).parent_id)

    def test_pointing_a_menu_at_a_model_makes_an_action_and_drops_the_orphan(self):
        app = self.Surface.create_record(
            False, self.package.id, {"name": "Tour App"}, template="app"
        )
        sub = self.Surface.create_record(
            False,
            self.package.id,
            {"name": "Projects", "parent_id": app["id"], "opens_model": self.model.id},
            template="submenu",
        )
        menu = self.env["ir.ui.menu"].browse(sub["id"])
        old_action = menu.action
        users = self.env["ir.model"]._get("res.users")
        self.Surface.write_record(sub["id"], {"opens_model": users.id}, self.package.id)
        self.assertEqual(menu.action.res_model, "res.users")
        self.assertFalse(old_action.exists())
        described = self.Surface.describe(sub["id"], self.package.id)
        self.assertEqual(described["values"]["opens_model"]["id"], users.id)
        self.assertIn("ir.actions.act_window", described["values"]["action"])

    def test_remove_takes_the_action_along_when_nothing_else_opens_it(self):
        app = self.Surface.create_record(
            False,
            self.package.id,
            {"name": "Tour App", "opens_model": self.model.id},
            template="app",
        )
        menu = self.env["ir.ui.menu"].browse(app["id"])
        action = menu.action
        other = self.env["ir.ui.menu"].create(
            {"name": "Also", "action": "ir.actions.act_window,%d" % action.id}
        )
        self.Surface.remove_record(app["id"], self.package.id, force=True)
        self.assertTrue(action.exists(), "another menu still opens it")
        other.unlink()
        sub = self.Surface.create_record(
            False,
            self.package.id,
            {"name": "Alone", "opens_model": self.model.id},
            template="app",
        )
        alone = self.env["ir.ui.menu"].browse(sub["id"]).action
        self.Surface.remove_record(sub["id"], self.package.id, force=True)
        self.assertFalse(alone.exists())
        self.assertNotIn("Alone", "".join(self.package._render_files().values()))

    def test_the_menus_of_the_package_round_trip(self):
        app = self.Surface.create_record(
            False,
            self.package.id,
            {"name": "Tour App", "opens_model": self.model.id},
            template="app",
        )
        self.Surface.create_record(
            False,
            self.package.id,
            {
                "name": "Projects",
                "parent_id": app["id"],
                "opens_model": self.model.id,
                "groups": [self.env.ref("base.group_user").id],
            },
            template="submenu",
        )
        files = self.package._render_files()
        menus = self.env["ir.ui.menu"].search(
            [("studio_package_id", "=", self.package.id)]
        )
        xmlids = [m.get_external_id()[m.id] for m in menus]
        actions = [m.action for m in menus if m.action]
        menus.unlink()
        for action in actions:
            action.unlink()
        self.load_rendered(self.package, files)
        reloaded = self.env["ir.ui.menu"].browse([self.env.ref(x).id for x in xmlids])
        by_name = {m.name: m for m in reloaded}
        self.assertEqual(by_name["Projects"].parent_id, by_name["Tour App"])
        self.assertEqual(by_name["Projects"].action.res_model, "x_studio_project")
        self.assertTrue(by_name["Tour App"].web_icon)

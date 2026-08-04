# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creating a view that did not exist, and making it reachable.

A scaffolded model gets a list, a form and a search view, so "click and edit a
kanban" has nothing to click until one exists. Creating the record is the easy
half: a view no action offers is a view nobody can open, which would let the
builder report success while the user never finds what it built.
"""

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase


@tagged("post_install", "-at_install")
class TestAddView(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.package = self.make_package(name="x_addview_pkg")
        # A model of our own rather than res.partner, which already ships a
        # kanban in 18 -- so "create a kanban" would be correctly refused and
        # the test would be measuring the fixture instead of the feature.
        self.model = self.env["ir.model"].create(
            {
                "name": "Add View Demo",
                "model": "x_addview_demo",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_name",
                            "ttype": "char",
                            "field_description": "Name",
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_when",
                            "ttype": "date",
                            "field_description": "When",
                        }
                    ),
                ],
            }
        )
        self.demo = "x_addview_demo"

    def _offers(self, model_name=None):
        model_name = model_name or self.demo
        return {
            entry["type"]: entry for entry in self.editor.addable_view_types(model_name)
        }

    # -- what is on offer --------------------------------------------------

    def test_a_type_the_model_already_has_is_offered_disabled(self):
        offers = self._offers("res.partner")
        self.assertFalse(offers["form"]["enabled"])
        self.assertIn("already has", offers["form"]["reason"])

    def test_calendar_lists_the_date_fields_it_could_use(self):
        offers = self._offers()
        names = [f["name"] for f in offers["calendar"]["date_fields"]]
        self.assertIn("x_when", names)

    def test_calendar_is_refused_with_a_reason_when_no_date_exists(self):
        """Shown-but-disabled, not hidden: otherwise somebody concludes the
        builder cannot do calendars at all."""
        # No fields of our own: Odoo gives a manual model its x_name for free,
        # and adding one here collides with it.
        self.env["ir.model"].create({"name": "No Dates", "model": "x_no_dates"})
        offers = self._offers("x_no_dates")
        self.assertFalse(offers["calendar"]["enabled"])
        self.assertIn("date field", offers["calendar"]["reason"])

    # -- creating ----------------------------------------------------------

    def test_a_kanban_is_created_with_the_v18_card_template(self):
        result = self.editor.add_view(self.demo, "kanban", self.package.id)
        view = self.env["ir.ui.view"].browse(result["view_id"])
        root = etree.fromstring(view.arch.encode())
        card = root.find(".//templates/t")
        self.assertEqual(
            card.get("t-name"),
            "card",
            "kanban-box is deprecated in 18 and warns on every render",
        )

    def test_the_card_uses_real_fields_so_it_stays_editable(self):
        """A card written with t-esc renders identically and puts no field name
        in the DOM, so the builder could never select anything on it."""
        result = self.editor.add_view(self.demo, "kanban", self.package.id)
        view = self.env["ir.ui.view"].browse(result["view_id"])
        root = etree.fromstring(view.arch.encode())
        self.assertTrue(root.findall(".//templates//field"))
        self.assertNotIn("t-esc", view.arch)

    def test_a_calendar_is_created_on_the_chosen_date(self):
        result = self.editor.add_view(
            self.demo, "calendar", self.package.id, date_field="x_when"
        )
        view = self.env["ir.ui.view"].browse(result["view_id"])
        root = etree.fromstring(view.arch.encode())
        self.assertEqual(root.get("date_start"), "x_when")

    def test_a_calendar_without_a_date_is_refused_readably(self):
        """date_start is mandatory, so this has to be caught before the view is
        created rather than surfacing as a render crash later."""
        with self.assertRaises(UserError) as caught:
            self.editor.add_view(self.demo, "calendar", self.package.id)
        self.assertIn("date", str(caught.exception))

    def test_the_new_view_belongs_to_the_package(self):
        result = self.editor.add_view(self.demo, "kanban", self.package.id)
        view = self.env["ir.ui.view"].browse(result["view_id"])
        self.assertEqual(view.studio_package_id, self.package)

    def test_creating_a_type_that_exists_is_refused(self):
        self.editor.add_view(self.demo, "kanban", self.package.id)
        with self.assertRaises(UserError):
            self.editor.add_view(self.demo, "kanban", self.package.id)

    # -- reachability, which is the half that is easy to forget -------------

    def test_the_new_type_is_added_to_our_own_action(self):
        action = self.env["ir.actions.act_window"].create(
            {"name": "Ours", "res_model": self.demo, "view_mode": "list,form"}
        )
        self.package.studio_capture(action)
        self.editor.add_view(self.demo, "kanban", self.package.id)
        self.assertIn("kanban", action.view_mode)
        self.assertLess(
            action.view_mode.index("kanban"),
            action.view_mode.index("form"),
            "a form is a detail view and reads last",
        )

    def test_somebody_elses_action_is_left_alone(self):
        """The studio's whole premise is that it does not rewrite what it does
        not own."""
        foreign = self.env["ir.actions.act_window"].create(
            {"name": "Theirs", "res_model": self.demo, "view_mode": "list,form"}
        )
        self.editor.add_view(self.demo, "kanban", self.package.id)
        self.assertNotIn("kanban", foreign.view_mode)

    def test_a_plain_user_cannot_create_views(self):
        outsider = self.env["res.users"].create(
            {
                "name": "Nosy",
                "login": "addview_outsider",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            self.editor.with_user(outsider).sudo(False).add_view(
                self.demo, "kanban", self.package.id
            )


@tagged("post_install", "-at_install")
class TestAddAndRemove(StudioCase):
    """The gap that made the editor a viewer for anything it did not own.

    A field could be created on any model and then placed only into views the
    package owned outright, which excluded every core screen. The server could
    always emit the inheriting <xpath>; nothing asked it to.
    """

    def _package_and_view(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        return package, view

    def test_a_field_can_be_added_to_a_view_the_package_owns(self):
        package, view = self._package_and_view()
        self.env["studio.view.editor"].add_field_at(
            view.id, package.id, {"kind": "root"}, "x_active_flag"
        )
        arch = self.env["ir.ui.view"].browse(view.id).get_combined_arch()
        self.assertIn('name="x_active_flag"', arch)

    def test_a_field_can_be_added_to_a_core_view_as_a_patch(self):
        """The headline case: a core form is patched, never rewritten."""
        package = self.make_package()
        self.build_demo_content(package)
        core = self.env.ref("base.view_partner_form")
        before = core.arch
        self.env["studio.view.editor"].add_field_at(
            core.id, package.id, {"kind": "root"}, "ref"
        )
        self.assertEqual(
            self.env.ref("base.view_partner_form").arch,
            before,
            "a core view must never be rewritten in place",
        )
        extension = self.env["ir.ui.view"].search(
            [("inherit_id", "=", core.id), ("studio_package_id", "=", package.id)]
        )
        self.assertTrue(extension, "the edit must land in an inheriting view")
        self.assertIn('name="ref"', extension.arch)

    def test_a_field_can_be_removed_again(self):
        package, view = self._package_and_view()
        editor = self.env["studio.view.editor"]
        editor.remove_at(view.id, package.id, {"kind": "field", "name": "x_budget"})
        arch = self.env["ir.ui.view"].browse(view.id).get_combined_arch()
        self.assertNotIn('name="x_budget"', arch)

    def test_a_tab_and_a_group_can_be_added(self):
        package, view = self._package_and_view()
        editor = self.env["studio.view.editor"]
        editor.add_container_at(view.id, package.id, {"kind": "sheet"}, "group")
        editor.add_container_at(view.id, package.id, {"kind": "sheet"}, "page")
        arch = self.env["ir.ui.view"].browse(view.id).get_combined_arch()
        self.assertIn("<page", arch)

    def test_an_unnamed_singleton_container_resolves_by_its_tag(self):
        """A form has one <sheet> and it has nothing else to be named by."""
        _package, view = self._package_and_view()
        root = etree.fromstring(view.get_combined_arch().encode())
        node = self.env["studio.view.editor"]._find_descriptor(root, {"kind": "sheet"})
        self.assertIsNotNone(node)
        self.assertEqual(node.tag, "sheet")

    def test_an_ambiguous_container_is_refused_rather_than_guessed(self):
        """Two groups and no name is a question, not an answer."""
        package, view = self._package_and_view()
        self.env["studio.view.editor"].add_container_at(
            view.id, package.id, {"kind": "sheet"}, "group"
        )
        root = etree.fromstring(
            self.env["ir.ui.view"].browse(view.id).get_combined_arch().encode()
        )
        self.assertGreater(len(root.findall(".//group")), 1, "sanity: two groups now")
        node = self.env["studio.view.editor"]._find_descriptor(root, {"kind": "group"})
        self.assertIsNone(node)


@tagged("post_install", "-at_install")
class TestActionButtonPortability(StudioCase):
    def test_a_button_action_is_written_as_an_xmlid(self):
        """convert.py resolves %(xmlid)d to an integer when loading an arch, so
        the database really does hold a raw id -- and writing it straight back
        out would put one database's primary key into a file meant for another.
        """
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        action = self.env["ir.actions.server"].create(
            {
                "name": "Do the thing",
                "model_id": model.id,
                "state": "code",
                "code": "pass",
            }
        )
        package._assign(action)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        self.env["studio.view.editor"].add_button_at(
            view.id, package.id, {"kind": "sheet"}, {"action_id": action.id}
        )
        # Odoo's validator takes an integer or an xmlid in a stored arch, but
        # refuses `%(xmlid)d` -- convert.py resolves that while *loading*, and a
        # view written live has nothing to resolve it. So the xmlid goes in as
        # itself, which needs no rewriting on the way out either.
        arch = self.env["ir.ui.view"].browse(view.id).get_combined_arch()
        self.assertIn("x_studio_demo.", arch)
        self.assertNotIn('name="%d"' % action.id, arch)
        emitted = "".join(package._render_files().values())
        self.assertNotIn('name="%d"' % action.id, emitted)

    def test_a_numeric_action_button_is_rewritten_on_the_way_out(self):
        """An arch that arrived with a raw id still must not reach a file."""
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        action = self.env["ir.actions.server"].create(
            {
                "name": "Legacy",
                "model_id": model.id,
                "state": "code",
                "code": "pass",
            }
        )
        package._assign(action)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        view.arch = view.arch.replace(
            "</sheet>",
            '<button name="%d" type="action" string="Legacy"/></sheet>' % action.id,
        )
        emitted = "".join(package._render_files().values())
        self.assertNotIn('name="%d"' % action.id, emitted)
        self.assertIn("ir_actions_server_legacy", emitted)

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creating a view that did not exist, and making it reachable.

A scaffolded model gets a list, a form and a search view, so "click and edit a
kanban" has nothing to click until one exists. Creating the record is the easy
half: a view no action offers is a view nobody can open, which would let the
builder report success while the user never finds what it built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_actions import IrActionsActWindow
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_view_edit import BuilderViewEdit
from ..models.builder_view_editor import BuilderViewEditor

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.web.models.ir_ui_view import View as WebView


@tagged("post_install", "-at_install")
class TestAddView(BuilderCase):
    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.package = self.make_package(name="x_addview_pkg")
        # A model of our own rather than res.partner, which already ships a
        # kanban in 18 -- so "create a kanban" would be correctly refused and
        # the test would be measuring the fixture instead of the feature.
        model_vals: dict[str, object] = {
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
        self.model = typed.model(self.env, IrModel).create(model_vals)  # pyright: ignore[reportArgumentType]
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
        no_dates_vals: dict[str, object] = {"name": "No Dates", "model": "x_no_dates"}
        typed.model(self.env, IrModel).create(no_dates_vals)  # pyright: ignore[reportArgumentType]
        offers = self._offers("x_no_dates")
        self.assertFalse(offers["calendar"]["enabled"])
        self.assertIn("date field", offers["calendar"]["reason"])

    # -- creating ----------------------------------------------------------

    def test_a_kanban_is_created_with_the_v18_card_template(self):
        result = self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))
        view = typed.model(self.env, View).browse(result["view_id"])
        root = etree.fromstring(cast("str", view.arch).encode())
        card = root.find(".//templates/t")
        self.assertEqual(
            card.get("t-name"),
            "card",
            "kanban-box is deprecated in 18 and warns on every render",
        )

    def test_the_card_uses_real_fields_so_it_stays_editable(self):
        """A card written with t-esc renders identically and puts no field name
        in the DOM, so the builder could never select anything on it."""
        result = self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))
        view = typed.model(self.env, View).browse(result["view_id"])
        root = etree.fromstring(cast("str", view.arch).encode())
        self.assertTrue(root.findall(".//templates//field"))
        self.assertNotIn("t-esc", cast("str", view.arch))

    def test_a_calendar_is_created_on_the_chosen_date(self):
        result = self.editor.add_view(
            self.demo, "calendar", cast("int", self.package.id), date_field="x_when"
        )
        view = typed.model(self.env, View).browse(result["view_id"])
        root = etree.fromstring(cast("str", view.arch).encode())
        self.assertEqual(root.get("date_start"), "x_when")

    def test_a_calendar_without_a_date_is_refused_readably(self):
        """date_start is mandatory, so this has to be caught before the view is
        created rather than surfacing as a render crash later."""
        with raises(self, UserError) as caught:
            self.editor.add_view(self.demo, "calendar", cast("int", self.package.id))
        self.assertIn("date", str(caught.exception))

    def test_the_new_view_belongs_to_the_package(self):
        result = self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))
        view = typed.model(self.env, View).browse(result["view_id"])
        self.assertEqual(
            cast("BuilderOwnedMixin", view).builder_package_id, self.package
        )

    def test_creating_a_type_that_exists_is_refused(self):
        self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))
        with raises(self, UserError):
            self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))

    # -- reachability, which is the half that is easy to forget -------------

    def test_the_new_type_is_added_to_our_own_action(self):
        action_vals: dict[str, object] = {
            "name": "Ours",
            "res_model": self.demo,
            "view_mode": "list,form",
        }
        action = typed.model(self.env, IrActionsActWindow).create(action_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(action)
        self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))
        view_mode = cast("str", action.view_mode)
        self.assertIn("kanban", view_mode)
        self.assertLess(
            view_mode.index("kanban"),
            view_mode.index("form"),
            "a form is a detail view and reads last",
        )

    def test_somebody_elses_action_is_left_alone(self):
        """The builder's whole premise is that it does not rewrite what it does
        not own."""
        foreign_vals: dict[str, object] = {
            "name": "Theirs",
            "res_model": self.demo,
            "view_mode": "list,form",
        }
        foreign = typed.model(self.env, IrActionsActWindow).create(foreign_vals)  # pyright: ignore[reportArgumentType]
        self.editor.add_view(self.demo, "kanban", cast("int", self.package.id))
        self.assertNotIn("kanban", cast("str", foreign.view_mode))

    def test_a_plain_user_cannot_create_views(self):
        outsider_vals: dict[str, object] = {
            "name": "Nosy",
            "login": "addview_outsider",
            "groups_id": [(6, 0, [typed.ref(self.env, "base.group_user").id])],
        }
        outsider = self.env["res.users"].create(outsider_vals)  # pyright: ignore[reportArgumentType]
        with raises(self, AccessError):
            self.editor.with_user(outsider).sudo(False).add_view(
                self.demo, "kanban", cast("int", self.package.id)
            )


@tagged("post_install", "-at_install")
class TestAddAndRemove(BuilderCase):
    """The gap that made the editor a viewer for anything it did not own.

    A field could be created on any model and then placed only into views the
    package owned outright, which excluded every core screen. The server could
    always emit the inheriting <xpath>; nothing asked it to.
    """

    def _package_and_view(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )
        return package, view

    def test_a_field_can_be_added_to_a_view_the_package_owns(self):
        package, view = self._package_and_view()
        typed.model(self.env, BuilderViewEditor).add_field_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "root"},
            "x_active_flag",
        )
        arch = (
            typed.model(self.env, View).browse(cast("int", view.id)).get_combined_arch()
        )
        self.assertIn('name="x_active_flag"', arch)

    def test_a_field_can_be_added_to_a_core_view_as_a_patch(self):
        """The headline case: a core form is patched, never rewritten."""
        package = self.make_package()
        self.build_demo_content(package)
        core = cast("View", typed.ref(self.env, "base.view_partner_form"))
        before = core.arch
        typed.model(self.env, BuilderViewEditor).add_field_at(
            cast("int", core.id), cast("int", package.id), {"kind": "root"}, "ref"
        )
        self.assertEqual(
            cast("View", typed.ref(self.env, "base.view_partner_form")).arch,
            before,
            "a core view must never be rewritten in place",
        )
        extension = typed.model(self.env, View).search(
            [("inherit_id", "=", core.id), ("builder_package_id", "=", package.id)]
        )
        self.assertTrue(extension, "the edit must land in an inheriting view")
        self.assertIn('name="ref"', cast("str", extension.arch))

    def test_a_field_can_be_removed_again(self):
        package, view = self._package_and_view()
        editor = typed.model(self.env, BuilderViewEditor)
        editor.remove_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "field", "name": "x_budget"},
        )
        arch = (
            typed.model(self.env, View).browse(cast("int", view.id)).get_combined_arch()
        )
        self.assertNotIn('name="x_budget"', arch)

    def test_a_tab_and_a_group_can_be_added(self):
        package, view = self._package_and_view()
        editor = typed.model(self.env, BuilderViewEditor)
        editor.add_container_at(
            cast("int", view.id), cast("int", package.id), {"kind": "sheet"}, "group"
        )
        editor.add_container_at(
            cast("int", view.id), cast("int", package.id), {"kind": "sheet"}, "page"
        )
        arch = (
            typed.model(self.env, View).browse(cast("int", view.id)).get_combined_arch()
        )
        self.assertIn("<page", arch)

    def test_an_unnamed_singleton_container_resolves_by_its_tag(self):
        """A form has one <sheet> and it has nothing else to be named by."""
        _package, view = self._package_and_view()
        root = etree.fromstring(view.get_combined_arch().encode())
        node = typed.model(self.env, BuilderViewEditor)._find_descriptor(
            root, {"kind": "sheet"}
        )
        self.assertIsNotNone(node)
        # `assertIsNotNone` is a runtime check only; it does not narrow
        # `node` for pyright the way an `if`/`assert` would.
        assert node is not None
        self.assertEqual(node.tag, "sheet")

    def test_an_ambiguous_container_is_refused_rather_than_guessed(self):
        """Two groups and no name is a question, not an answer."""
        package, view = self._package_and_view()
        typed.model(self.env, BuilderViewEditor).add_container_at(
            cast("int", view.id), cast("int", package.id), {"kind": "sheet"}, "group"
        )
        root = etree.fromstring(
            typed.model(self.env, View)
            .browse(cast("int", view.id))
            .get_combined_arch()
            .encode()
        )
        self.assertGreater(len(root.findall(".//group")), 1, "sanity: two groups now")
        node = typed.model(self.env, BuilderViewEditor)._find_descriptor(
            root, {"kind": "group"}
        )
        self.assertIsNone(node)

    # -- where exactly, when the gesture says ------------------------------

    def _fields_in_group(self, view):
        root = etree.fromstring(
            typed.model(self.env, View).browse(view.id).get_combined_arch().encode()
        )
        return [f.get("name") for f in root.find(".//group").findall("field")]

    def test_a_named_position_wins_over_the_guess(self):
        """A click can only guess "after"; a drop knows it was before."""
        package, view = self._package_and_view()
        typed.model(self.env, BuilderViewEditor).add_field_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "field", "name": "x_budget"},
            "x_active_flag",
            position="before",
        )
        names = self._fields_in_group(view)
        self.assertLess(names.index("x_active_flag"), names.index("x_budget"))

    def test_a_field_arrives_with_its_widget_in_one_change(self):
        """A preset that comes with a widget is one thing to the user, so it
        is one history entry -- not "added" followed by "changed widget"."""
        package, view = self._package_and_view()
        editor = typed.model(self.env, BuilderViewEditor)
        editor.add_field_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "field", "name": "x_budget"},
            "x_active_flag",
            attrs={"widget": "boolean_toggle"},
        )
        arch = cast(
            "str", typed.model(self.env, View).browse(cast("int", view.id)).arch
        )
        self.assertIn('<field name="x_active_flag" widget="boolean_toggle"/>', arch)
        self.assertEqual(
            len(
                typed.model(self.env, BuilderViewEdit).history_for(cast("int", view.id))
            ),
            1,
        )

    def test_a_position_that_is_not_a_place_is_refused(self):
        package, view = self._package_and_view()
        with raises(self, UserError):
            typed.model(self.env, BuilderViewEditor).add_field_at(
                cast("int", view.id),
                cast("int", package.id),
                {"kind": "field", "name": "x_budget"},
                "x_active_flag",
                position="replace",
            )

    def test_a_tab_can_be_placed_beside_another_tab(self):
        package, view = self._package_and_view()
        editor = typed.model(self.env, BuilderViewEditor)
        editor.add_container_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "sheet"},
            "page",
            "One",
        )
        editor.add_container_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "page", "index": 0},
            "page",
            "Zero",
            position="before",
        )
        root = etree.fromstring(
            typed.model(self.env, View)
            .browse(cast("int", view.id))
            .get_combined_arch()
            .encode()
        )
        self.assertEqual(
            [p.get("string") for p in root.iter("page")],
            ["Zero", "One"],
            "before the first tab, not appended to the notebook",
        )


OWNED_FORM_WITH_A_TAB = """
<form>
    <sheet>
        <group>
            <field name="x_name"/>
            <field name="x_budget"/>
        </group>
        <notebook>
            <page string="Notes"><field name="x_stage"/></page>
        </notebook>
    </sheet>
</form>
"""


@tagged("post_install", "-at_install")
class TestOwnedViewWithForeignExtension(BuilderCase):
    """The hole between the tree a locator is minted on and the one it edits.

    A locator is minted on the *combined* arch -- other modules' extensions
    included -- but an owned view is edited by applying the spec to its
    *primary* arch, which has none of them. A named locator means the same
    node in both. A positional one does not once another module has inserted
    a sibling above the target: the same path then names a different node, or
    none, and core's apply_inheritance_specs either edits the wrong node
    silently or raises a bare ValueError.
    """

    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.package = self.make_package()
        self.build_demo_content(self.package)
        self.view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )
        self.view.arch = OWNED_FORM_WITH_A_TAB
        # Another module's extension: no package, a name of its own, and it
        # puts a tab *before* ours, so every positional path into the
        # notebook is off by one between the two trees.
        other_module_vals: dict[str, object] = {
            "name": "x_builder_project.form.other_module",
            "model": "x_builder_project",
            "inherit_id": self.view.id,
            "mode": "extension",
            "arch": """
                    <data>
                        <xpath expr="//notebook" position="inside">
                            <page string="Foreign"><field name="x_partner_id"/></page>
                        </xpath>
                        <xpath expr="//page[1]" position="before">
                            <page string="Theirs"><field name="x_active_flag"/></page>
                        </xpath>
                    </data>
                """,
        }
        self.env["ir.ui.view"].create(other_module_vals)  # pyright: ignore[reportArgumentType]
        self.before = self.view.arch

    def _refused(self, anchor, needle):
        """Ask for x_budget inside ``anchor`` and expect a refusal saying
        ``needle``, then check the primary arch was left alone.

        Not ``assertRaises``: Odoo's wraps the block in a savepoint that is
        rolled back on the exception, so "arch unchanged" would hold whatever
        the editor had written before refusing.
        """
        try:
            self.editor.add_field_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                anchor,
                "x_budget",
                position="inside",
            )
        except UserError as caught:
            self.assertIn(needle, str(caught))
        else:
            self.fail("the locator has to be refused on the owned path")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, self.before)
        self.assertEqual(
            typed.model(self.env, BuilderViewEdit).history_for(
                cast("int", self.view.id)
            ),
            [],
        )

    def test_a_positional_locator_past_the_foreign_tab_is_refused(self):
        """Our tab is page[2] in the combined arch and page[1] in ours: the
        minted path finds nothing in the primary arch, and the refusal says
        so rather than blaming a node that was never found."""
        self._refused({"kind": "page", "index": 1}, "does not locate anything")

    def test_the_foreign_tab_itself_is_refused_rather_than_editing_ours(self):
        """page[1] in the combined arch is theirs; in ours it is Notes. The
        path resolves, to the wrong node -- which is the case that would have
        edited silently."""
        self._refused({"kind": "page", "index": 0}, "another module's extension")

    def test_a_named_locator_still_edits_in_place(self):
        self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "field", "name": "x_budget"},
            "x_active_flag",
        )
        self.view.invalidate_recordset()
        self.assertIn('name="x_active_flag"', cast("str", self.view.arch))
        self.assertFalse(
            self.env["ir.ui.view"].search(
                [
                    ("inherit_id", "=", self.view.id),
                    ("builder_package_id", "=", self.package.id),
                ]
            ),
            "an owned view is edited outright, not patched",
        )

    def test_a_raw_locator_that_is_not_an_xpath_is_refused_readably(self):
        """Core's apply_inheritance_specs answers a bad expression with a
        bare lxml error on the owned path; the user gets a sentence."""
        with raises(self, UserError):
            self.editor.apply_operation(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {
                    "type": "add_field",
                    "name": "x_active_flag",
                    "xpath": "//field[@name=",
                    "position": "after",
                },
            )


OWNED_FORM_WITH_BARE_GROUPS = """
<form>
    <sheet>
        <group>
            <field name="x_name"/>
        </group>
        <group>
            <field name="x_budget"/>
        </group>
        <notebook>
            <page string="Notes"><field name="x_stage"/></page>
        </notebook>
    </sheet>
</form>
"""


OWNED_FORM_WITH_WRAPPED_PAGES = """
<form>
    <sheet>
        <notebook>
            <page string="Notes"><group><field name="x_stage"/></group></page>
            <page string="Budget"><group><field name="x_budget"/></group></page>
        </notebook>
    </sheet>
</form>
"""


@tagged("post_install", "-at_install")
class TestOwnedContainersWithoutNames(BuilderCase):
    """What tells one unnamed container from another, once a foreign
    extension has shifted every positional path by one.

    Two bare groups have no name and usually no label, so tag and label
    cannot tell them apart -- but the fields in them are named, and those
    are the fingerprint. The label is a second signal because a foreign
    ``position="attributes"`` can change it on a page that is still ours.
    """

    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.package = self.make_package()
        self.build_demo_content(self.package)
        self.view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )
        self.view.arch = OWNED_FORM_WITH_BARE_GROUPS
        other_module_vals: dict[str, object] = {
            "name": "x_builder_project.form.other_module",
            "model": "x_builder_project",
            "inherit_id": self.view.id,
            "mode": "extension",
            "arch": """
                    <data>
                        <xpath expr="//group[1]" position="before">
                            <group><field name="x_partner_id"/></group>
                        </xpath>
                        <xpath expr="//page[1]" position="attributes">
                            <attribute name="string">Their Notes</attribute>
                        </xpath>
                    </data>
                """,
        }
        self.env["ir.ui.view"].create(other_module_vals)  # pyright: ignore[reportArgumentType]
        self.before = self.view.arch

    def test_a_shifted_locator_onto_a_look_alike_sibling_is_refused(self):
        """The group holding x_name is group[2] in the combined arch and
        group[1] in ours, so the minted path lands on the group holding
        x_budget: same tag, no name, no label on either. The named children
        are what give it away."""
        try:
            self.editor.add_field_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {"kind": "group", "index": 1},
                "x_active_flag",
                position="inside",
            )
        except UserError as caught:
            self.assertIn("another module's extension", str(caught))
        else:
            self.fail("the shifted locator has to be refused")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, self.before, "the wrong group was not edited")

    def test_a_page_whose_label_a_foreign_module_overrides_is_still_ours(self):
        """The combined arch says "Their Notes" and ours says "Notes"; the
        fields under it are the same, so it is the same page, and it is
        edited in place."""
        self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "page", "index": 0},
            "x_active_flag",
            position="inside",
        )
        self.view.invalidate_recordset()
        root = etree.fromstring(cast("str", self.view.arch).encode())
        page = root.find(".//page")
        self.assertEqual(
            [f.get("name") for f in page.findall("field")], ["x_stage", "x_active_flag"]
        )
        self.assertFalse(
            self.env["ir.ui.view"].search(
                [
                    ("inherit_id", "=", self.view.id),
                    ("builder_package_id", "=", self.package.id),
                ]
            ),
            "an owned view is edited outright, not patched",
        )

    def test_pages_with_no_signal_at_all_are_refused_rather_than_guessed(self):
        """Two pages that each wrap their fields in an unnamed group have no
        named children and, once a foreign tab has been inserted above them,
        a positional path lands on the wrong one. Their labels differ -- but
        an empty fingerprint must not count as a match either, or the
        "Budget" page would be edited when "Notes" was pointed at."""
        self.view.arch = OWNED_FORM_WITH_WRAPPED_PAGES
        other_tab_vals: dict[str, object] = {
            "name": "x_builder_project.form.other_tab",
            "model": "x_builder_project",
            "inherit_id": self.view.id,
            "mode": "extension",
            "arch": """
                    <data>
                        <xpath expr="//page[1]" position="before">
                            <page string="Theirs">
                                <group><field name="x_partner_id"/></group>
                            </page>
                        </xpath>
                    </data>
                """,
        }
        self.env["ir.ui.view"].create(other_tab_vals)  # pyright: ignore[reportArgumentType]
        before = self.view.arch
        try:
            self.editor.add_field_at(
                cast("int", self.view.id),
                cast("int", self.package.id),
                {"kind": "page", "index": 1},
                "x_active_flag",
                position="inside",
            )
        except UserError as caught:
            self.assertIn("another module's extension", str(caught))
        else:
            self.fail("a page with no identifying signal has to be refused")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.arch, before, "the wrong page was not edited")

    def test_a_view_nothing_extends_is_edited_by_position_without_a_signal(self):
        """With no foreign extension the combined arch is the primary arch,
        so a positional path is exact and a page with no signal is still
        editable -- the guard only has something to check when another view
        has changed the shape."""
        self.view.arch = OWNED_FORM_WITH_WRAPPED_PAGES
        self.env["ir.ui.view"].search([("inherit_id", "=", self.view.id)]).unlink()
        self.editor.add_field_at(
            cast("int", self.view.id),
            cast("int", self.package.id),
            {"kind": "page", "index": 1},
            "x_active_flag",
            position="inside",
        )
        self.view.invalidate_recordset()
        root = etree.fromstring(cast("str", self.view.arch).encode())
        pages = root.findall(".//page")
        self.assertEqual(
            [f.get("name") for f in pages[1].iter("field")],
            ["x_budget", "x_active_flag"],
        )


@tagged("post_install", "-at_install")
class TestActionButtonPortability(BuilderCase):
    def test_a_button_action_is_written_as_an_xmlid(self):
        """convert.py resolves %(xmlid)d to an integer when loading an arch, so
        the database really does hold a raw id -- and writing it straight back
        out would put one database's primary key into a file meant for another.
        """
        package = self.make_package()
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        action_vals: dict[str, object] = {
            "name": "Do the thing",
            "model_id": model.id,
            "state": "code",
            "code": "pass",
        }
        action = self.env["ir.actions.server"].create(action_vals)  # pyright: ignore[reportArgumentType]
        package._assign(action)
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )
        typed.model(self.env, BuilderViewEditor).add_button_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "sheet"},
            {"action_id": action.id},
        )
        # Odoo's validator takes an integer or an xmlid in a stored arch, but
        # refuses `%(xmlid)d` -- convert.py resolves that while *loading*, and a
        # view written live has nothing to resolve it. So the xmlid goes in as
        # itself, which needs no rewriting on the way out either.
        arch = (
            typed.model(self.env, View).browse(cast("int", view.id)).get_combined_arch()
        )
        self.assertIn("x_builder_demo.", arch)
        self.assertNotIn('name="%d"' % action.id, arch)
        emitted = "".join(package._render_files().values())
        self.assertNotIn('name="%d"' % action.id, emitted)

    def test_a_numeric_action_button_is_rewritten_on_the_way_out(self):
        """An arch that arrived with a raw id still must not reach a file."""
        package = self.make_package()
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        action_vals: dict[str, object] = {
            "name": "Legacy",
            "model_id": model.id,
            "state": "code",
            "code": "pass",
        }
        action = self.env["ir.actions.server"].create(action_vals)  # pyright: ignore[reportArgumentType]
        package._assign(action)
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )
        view.arch = cast("str", view.arch).replace(
            "</sheet>",
            '<button name="%d" type="action" string="Legacy"/></sheet>' % action.id,
        )
        emitted = "".join(package._render_files().values())
        self.assertNotIn('name="%d"' % action.id, emitted)
        self.assertIn("ir_actions_server_legacy", emitted)


@tagged("post_install", "-at_install")
class TestViewTypeDiscovery(BuilderCase):
    """The list of view types comes from Odoo, not from us.

    `ir.ui.view.get_view_info()` is the registry every module extends when it
    contributes a view type — core seeds seven, `mail` adds activity,
    `web_timeline` adds timeline. Deriving the list means a site that installs
    one sees it as soon as somebody writes a scaffold, and a site running
    enterprise sees gantt and cohort, without the engine depending on any of it.
    """

    def _offered(self):
        package = self.make_package()
        self.build_demo_content(package)
        return {
            entry["type"]: entry
            for entry in typed.model(self.env, BuilderViewEditor).addable_view_types(
                "x_builder_project"
            )
        }

    def test_every_registered_type_is_accounted_for(self):
        offered = self._offered()
        # `get_view_info` is contributed by `web`, composed via `_inherit`
        # rather than a real Python base -- same `WebView` cast
        # `builder_view_editor.py` itself uses for the identical call.
        known = set(cast("WebView", typed.model(self.env, View)).get_view_info())
        expected = known - set(typed.model(self.env, BuilderViewEditor).NOT_ADDABLE)
        self.assertEqual(set(offered), expected)

    def test_a_type_without_a_scaffold_says_so_rather_than_vanishing(self):
        """The type is installed and Odoo can render it, so "the builder cannot
        make one yet" is the true answer and a different one from "no such
        thing"."""
        editor = typed.model(self.env, BuilderViewEditor)
        unscaffolded = (
            set(cast("WebView", typed.model(self.env, View)).get_view_info())
            - set(editor.NOT_ADDABLE)
            - set(editor.VIEW_SCAFFOLDS)
        )
        if not unscaffolded:
            self.skipTest("every installed view type has a scaffold here")
        offered = self._offered()
        entry = offered[min(unscaffolded)]
        self.assertFalse(entry["enabled"])
        self.assertIn("cannot create", entry["reason"])

    def test_pivot_and_graph_are_offered(self):
        offered = self._offered()
        for view_type in ("pivot", "graph"):
            self.assertIn(view_type, offered)
            self.assertTrue(offered[view_type]["enabled"], offered[view_type]["reason"])

    def test_a_pivot_arrives_with_something_to_show(self):
        """An empty pivot is valid and useless: it opens on one Count cell."""
        package = self.make_package()
        self.build_demo_content(package)
        typed.model(self.env, BuilderViewEditor).add_view(
            "x_builder_project", "pivot", cast("int", package.id)
        )
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "pivot")], limit=1
        )
        self.assertTrue(view)
        self.assertIn("type=", cast("str", view.arch))

    def test_a_graph_can_be_created(self):
        package = self.make_package()
        self.build_demo_content(package)
        typed.model(self.env, BuilderViewEditor).add_view(
            "x_builder_project", "graph", cast("int", package.id)
        )
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_builder_project"), ("type", "=", "graph")], limit=1
        )
        self.assertTrue(view)

    def test_activity_needs_the_activity_mixin(self):
        offered = self._offered()
        if "activity" not in offered:
            self.skipTest("mail is not installed")
        entry = offered["activity"]
        self.assertFalse(entry["enabled"])
        self.assertIn("Messaging", entry["reason"])

    def test_a_timeline_reports_what_it_needs(self):
        offered = self._offered()
        if "timeline" not in offered:
            self.skipTest("web_timeline is not installed")
        entry = offered["timeline"]
        if entry["enabled"]:
            self.assertTrue(entry["date_fields"])
            self.assertTrue(
                entry["group_fields"], "web_timeline requires default_group_by"
            )

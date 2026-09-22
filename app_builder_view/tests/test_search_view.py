# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Search views, the one type with nothing to click.

A search view has no rendering of its own -- it furnishes another view's
control panel -- so the click-to-select spine has no target. It is edited as
the three lists it really is, and previewed inside a real list so the menus
being edited are the menus on screen.

The distinction that matters here: a group-by *is* a filter. What makes it one
is a `group_by` context and living inside the `<group>`. The same node outside
that group renders in the Filters menu instead, which is why the group is
created as part of adding the first group-by rather than left to the user.
"""

from __future__ import annotations

from typing import cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.tests.common import StudioCase, raises
from odoo.addons.app_builder_base.tools import typed

from ..models.studio_view_editor import StudioViewEditor

SEARCH_ARCH = """
<search string="Demo">
    <field name="x_name"/>
    <filter name="mine" string="Mine" domain="[('x_flag', '=', True)]"/>
</search>
"""


@tagged("post_install", "-at_install")
class TestSearchView(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, StudioViewEditor)
        self.package = self.make_package(name="x_search_pkg")
        model_vals: dict[str, object] = {
            "name": "Search Demo",
            "model": "x_search_demo",
            "field_id": [
                Command.create(
                    {"name": "x_name", "ttype": "char", "field_description": "Name"}
                ),
                Command.create(
                    {
                        "name": "x_flag",
                        "ttype": "boolean",
                        "field_description": "Flag",
                    }
                ),
                Command.create(
                    {
                        "name": "x_user_id",
                        "ttype": "many2one",
                        "field_description": "Owner",
                        "relation": "res.users",
                    }
                ),
            ],
        }
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "studio.search.test",
            "model": "x_search_demo",
            "type": "search",
            "arch": SEARCH_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]
        self.package.studio_capture(self.view)

    def _arch(self):
        self.view.invalidate_recordset()
        return etree.fromstring(self.view.get_combined_arch().encode())

    # -- reading -----------------------------------------------------------

    def test_the_three_lists_are_reported_separately(self):
        elements = self.editor.search_elements(cast("int", self.view.id))
        self.assertEqual([f["name"] for f in elements["fields"]], ["x_name"])
        self.assertEqual([f["name"] for f in elements["filters"]], ["mine"])
        self.assertEqual(elements["group_bys"], [])

    # -- adding ------------------------------------------------------------

    def test_a_searchable_field_is_added(self):
        self.editor.add_search_element(
            cast("int", self.view.id),
            cast("int", self.package.id),
            "field",
            {"field": "x_user_id"},
        )
        names = [f.get("name") for f in self._arch().findall("field")]
        self.assertEqual(names, ["x_name", "x_user_id"], "additions read in order")

    def test_a_filter_is_generated_from_a_field_and_a_condition(self):
        self.editor.add_search_element(
            cast("int", self.view.id),
            cast("int", self.package.id),
            "filter",
            {"field": "x_user_id", "condition": "not_set"},
        )
        added = self._arch().find(".//filter[@name='filter_x_user_id_not_set']")
        self.assertIsNotNone(added)
        self.assertEqual(added.get("domain"), "[('x_user_id', '=', False)]")
        self.assertIn("not set", added.get("string"))

    def test_the_first_group_by_brings_its_group_with_it(self):
        """A group_by filter outside the <group> lands in the Filters menu
        instead, which is not what the user asked for."""
        self.assertIsNone(self._arch().find("group"))
        self.editor.add_search_element(
            cast("int", self.view.id),
            cast("int", self.package.id),
            "group_by",
            {"field": "x_user_id"},
        )
        group = self._arch().find("group")
        self.assertIsNotNone(group, "the group has to exist for it to group by")
        self.assertIsNotNone(group.find("filter[@name='group_by_x_user_id']"))

    def test_a_second_group_by_joins_the_existing_group(self):
        for field in ("x_user_id", "x_flag"):
            self.editor.add_search_element(
                cast("int", self.view.id),
                cast("int", self.package.id),
                "group_by",
                {"field": field},
            )
        groups = self._arch().findall("group")
        self.assertEqual(len(groups), 1, "one Group By group, not one per entry")
        self.assertEqual(len(groups[0].findall("filter")), 2)

    def test_a_group_by_is_reported_as_a_group_by_not_a_filter(self):
        self.editor.add_search_element(
            cast("int", self.view.id),
            cast("int", self.package.id),
            "group_by",
            {"field": "x_user_id"},
        )
        elements = self.editor.search_elements(cast("int", self.view.id))
        self.assertEqual(
            [g["name"] for g in elements["group_bys"]], ["group_by_x_user_id"]
        )
        self.assertNotIn("group_by_x_user_id", [f["name"] for f in elements["filters"]])

    # -- removing ----------------------------------------------------------

    def test_a_filter_is_removed(self):
        self.editor.remove_search_element(
            cast("int", self.view.id), cast("int", self.package.id), "filter", "mine"
        )
        self.assertEqual(
            self.editor.search_elements(cast("int", self.view.id))["filters"], []
        )

    def test_a_searchable_field_is_removed(self):
        self.editor.remove_search_element(
            cast("int", self.view.id), cast("int", self.package.id), "field", "x_name"
        )
        self.assertEqual(
            self.editor.search_elements(cast("int", self.view.id))["fields"], []
        )

    # -- refusals ----------------------------------------------------------

    def test_a_field_that_does_not_exist_is_refused(self):
        with raises(self, UserError):
            self.editor.add_search_element(
                cast("int", self.view.id),
                cast("int", self.package.id),
                "field",
                {"field": "x_nope"},
            )

    def test_an_unknown_condition_is_refused(self):
        with raises(self, UserError):
            self.editor.add_search_element(
                cast("int", self.view.id),
                cast("int", self.package.id),
                "filter",
                {"field": "x_flag", "condition": "whenever"},
            )

    def test_removing_something_absent_is_refused(self):
        with raises(self, UserError):
            self.editor.remove_search_element(
                cast("int", self.view.id),
                cast("int", self.package.id),
                "filter",
                "nope",
            )

    def test_a_plain_user_cannot_edit_a_search_view(self):
        outsider_vals: dict[str, object] = {
            "name": "Nosy",
            "login": "search_outsider",
            "groups_id": [(6, 0, [typed.ref(self.env, "base.group_user").id])],
        }
        outsider = self.env["res.users"].create(outsider_vals)  # pyright: ignore[reportArgumentType]
        with raises(self, AccessError):
            self.editor.with_user(outsider).sudo(False).add_search_element(
                cast("int", self.view.id),
                cast("int", self.package.id),
                "field",
                {"field": "x_user_id"},
            )

    # -- previewing --------------------------------------------------------

    def test_a_search_view_previews_inside_a_list(self):
        """It has no rendering of its own, so it is shown filling a real list's
        control panel -- the menus on screen are the ones being edited."""
        host_vals: dict[str, object] = {
            "name": "studio.search.host",
            "model": "x_search_demo",
            "type": "list",
            "arch": '<list><field name="x_name"/></list>',
        }
        self.env["ir.ui.view"].create(host_vals)  # pyright: ignore[reportArgumentType]
        preview = self.editor.editing_context(cast("int", self.view.id))["preview"]
        self.assertEqual(preview["type"], "list")
        self.assertEqual(preview["search_view_id"], self.view.id)
        self.assertTrue(preview["view_id"])

    def test_a_search_view_with_no_list_says_so(self):
        preview = self.editor.editing_context(cast("int", self.view.id))["preview"]
        # `unavailable` is `NotRequired`, but `_preview_for()`'s search
        # branch (the only one reachable here, `self.view` is always type
        # "search") always sets it -- `.get()` reads it without pyright's
        # `reportTypedDictNotRequiredAccess` (same idiom as
        # `test_model_draft.py`'s own `destructive`).
        self.assertTrue(preview.get("unavailable"))


@tagged("post_install", "-at_install")
class TestBuiltFilters(StudioCase):
    """A filter with a value, or more than one term, from the condition builder.

    The four one-click conditions stay: naming "is set" takes no thought. What
    they could not express is anything with a value in it, which is most of the
    filters people actually want.
    """

    def _search_view(self):
        View_ = typed.model(self.env, View)
        return View_.browse(cast("int", View_.default_view("res.partner", "search")))

    def _add(self, package, **values):
        return typed.model(self.env, StudioViewEditor).add_search_element(
            cast("int", self._search_view().id),
            cast("int", package.id),
            "filter",
            values,
        )

    def test_a_built_filter_carries_its_value(self):
        package = self.make_package()
        self._add(
            package,
            condition="built",
            string="Companies",
            rows=[{"field": "is_company", "operator": "=", "value": True}],
        )
        patch = typed.model(self.env, View).search(
            [
                ("inherit_id", "=", self._search_view().id),
                ("studio_package_id", "=", package.id),
            ]
        )
        self.assertIn("is_company", cast("str", patch.arch))
        self.assertIn('string="Companies"', cast("str", patch.arch))

    def test_a_built_filter_can_test_two_things(self):
        """The thing the four canned conditions could not do at all."""
        package = self.make_package()
        self._add(
            package,
            condition="built",
            string="Active companies",
            rows=[
                {"field": "is_company", "operator": "=", "value": True},
                {"field": "active", "operator": "=", "value": True},
            ],
        )
        patch = typed.model(self.env, View).search(
            [
                ("inherit_id", "=", self._search_view().id),
                ("studio_package_id", "=", package.id),
            ]
        )
        self.assertIn("&amp;", cast("str", patch.arch))

    def test_a_condition_that_does_not_search_is_refused(self):
        package = self.make_package()
        with raises(self, UserError) as caught:
            self._add(
                package,
                condition="built",
                string="Nonsense",
                rows=[{"field": "nope", "operator": "=", "value": 1}],
            )
        self.assertIn("does not search", str(caught.exception))

    def test_a_built_filter_needs_a_name(self):
        """It becomes the menu entry, so an unnamed one is unfindable."""
        package = self.make_package()
        with raises(self, UserError) as caught:
            self._add(
                package,
                condition="built",
                rows=[{"field": "is_company", "operator": "=", "value": True}],
            )
        self.assertIn("menu entry", str(caught.exception))

    def test_a_built_filter_needs_no_single_field(self):
        """Insisting on one is how "filter for two things" becomes "choose one
        field first"."""
        package = self.make_package()
        self._add(
            package,
            condition="built",
            string="Two things",
            rows=[
                {"field": "is_company", "operator": "=", "value": True},
                {"field": "active", "operator": "=", "value": True},
            ],
        )
        self.assertTrue(
            self.env["ir.ui.view"].search_count(
                [
                    ("inherit_id", "=", self._search_view().id),
                    ("studio_package_id", "=", package.id),
                ]
            )
        )

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Resolving a click to a node in the view's definition.

The browser says *what* was clicked -- "the column for user_id" -- and the
server decides *where* that is. The division is not fussiness: the arch a
client receives is a per-user projection, with nodes dropped by group rights
and whole subviews grafted in, so an xpath derived from it can be wrong for the
next person to open the same view. Everything here guards that boundary.
"""

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

LIST_ARCH = """
<list string="Partners">
    <field name="name"/>
    <field name="function"/>
    <field name="email"/>
</list>
"""

# The shape that makes a naive locator wrong: the child_ids subview repeats the
# parent's field names, for a different model.
NESTED_FORM_ARCH = """
<form string="Partner">
    <sheet>
        <group>
            <field name="name"/>
            <field name="child_ids">
                <list>
                    <field name="name"/>
                    <field name="email"/>
                </list>
            </field>
        </group>
    </sheet>
</form>
"""


@tagged("post_install", "-at_install")
class TestLocateTarget(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]

    def _view(self, arch, view_type="list", model="res.partner"):
        return self.env["ir.ui.view"].create(
            {
                "name": "studio.locate.test",
                "model": model,
                "type": view_type,
                "arch": arch,
            }
        )

    # -- resolving --------------------------------------------------------

    def test_a_column_resolves_to_its_field_node(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(
            view.id, {"kind": "column", "name": "function"}
        )
        self.assertTrue(found["found"])
        self.assertEqual(found["xpath"], "//field[@name='function']")
        self.assertEqual(found["tag"], "field")

    def test_the_root_resolves_without_a_name(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(view.id, {"kind": "root"})
        self.assertTrue(found["found"])
        self.assertEqual(found["tag"], "list")
        self.assertEqual(
            found["attrs"].get("string"),
            "Partners",
            "root attributes are what a list's settings panel edits",
        )

    def test_a_field_carries_its_type_so_options_can_be_type_aware(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(view.id, {"kind": "column", "name": "name"})
        self.assertEqual(found["field"]["type"], "char")
        self.assertEqual(found["field"]["name"], "name")

    def test_existing_attributes_come_back_so_the_panel_shows_state(self):
        view = self._view(
            '<list><field name="name" optional="hide" widget="badge"/></list>'
        )
        found = self.editor.locate_target(view.id, {"kind": "column", "name": "name"})
        self.assertEqual(found["attrs"]["optional"], "hide")
        self.assertEqual(found["attrs"]["widget"], "badge")

    # -- the boundary this exists to protect ------------------------------

    def test_a_name_repeated_in_a_subview_never_yields_a_bare_locator(self):
        """//field[@name='name'] would match the subview's column too, and
        locate_node takes the first match -- so the edit would land on the
        wrong model's list."""
        view = self._view(NESTED_FORM_ARCH, view_type="form")
        found = self.editor.locate_target(view.id, {"kind": "field", "name": "name"})
        self.assertTrue(found["found"])
        self.assertNotEqual(
            found["xpath"],
            "//field[@name='name']",
            "ambiguous name must fall back to an absolute indexed path",
        )
        self.assertTrue(found["xpath"].startswith("/form"), found["xpath"])

    def test_a_subview_node_is_not_selectable_from_the_parent(self):
        """'email' exists only inside child_ids, which is another model."""
        view = self._view(NESTED_FORM_ARCH, view_type="form")
        found = self.editor.locate_target(view.id, {"kind": "field", "name": "email"})
        self.assertFalse(
            found["found"], "selecting it here would edit res.partner's child list"
        )
        self.assertIn("not something the builder can edit", found["reason"])

    def test_an_unknown_field_is_refused_with_a_reason(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(view.id, {"kind": "column", "name": "nope"})
        self.assertFalse(found["found"])
        self.assertTrue(found["reason"])

    def test_an_unknown_kind_is_refused_rather_than_guessed(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(view.id, {"kind": "whatever", "name": "name"})
        self.assertFalse(found["found"])

    # -- opening the editor ------------------------------------------------

    def test_editing_context_reports_an_unowned_view_as_not_owned(self):
        """A core view gets patched, not rewritten. Saying so is the difference
        between understanding the output and being surprised by it."""
        view = self.env.ref("base.view_partner_form")
        context = self.editor.editing_context(view.id)
        self.assertFalse(context["owned"])
        self.assertEqual(context["view"]["model"], "res.partner")

    def test_editing_context_reports_an_owned_primary_view_as_owned(self):
        package = self.make_package(name="x_ctx_pkg")
        view = self._view(LIST_ARCH)
        package.studio_capture(view)
        context = self.editor.editing_context(view.id)
        self.assertTrue(context["owned"])
        self.assertEqual(context["suggested_package_id"], package.id)

    def test_a_plain_user_cannot_resolve_or_open(self):
        view = self._view(LIST_ARCH)
        outsider = self.env["res.users"].create(
            {
                "name": "Nosy",
                "login": "locate_outsider",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        editor = self.editor.with_user(outsider).sudo(False)
        with self.assertRaises(AccessError):
            editor.locate_target(view.id, {"kind": "root"})
        with self.assertRaises(AccessError):
            editor.editing_context(view.id)


NOTEBOOK_FORM = """
<form string="Job">
    <sheet>
        <group><field name="name"/></group>
        <notebook>
            <page string="Details"><field name="comment"/></page>
            <page string="Lines" name="page_lines"><field name="function"/></page>
        </notebook>
    </sheet>
</form>
"""


@tagged("post_install", "-at_install")
class TestPageDescriptors(StudioCase):
    """Notebook pages, which mostly have no name to be found by.

    Core forms rarely name their pages, so refusing to resolve an unnamed one
    would put nearly every existing form out of reach. Position is what the
    user actually pointed at -- the third tab is the third <page> -- and it is
    how an absolute locator would index it anyway.
    """

    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.view = self.env["ir.ui.view"].create(
            {
                "name": "studio.page.test",
                "model": "res.partner",
                "type": "form",
                "arch": NOTEBOOK_FORM,
            }
        )

    def test_a_named_page_resolves_by_name(self):
        found = self.editor.locate_target(
            self.view.id, {"kind": "page", "name": "page_lines"}
        )
        self.assertTrue(found["found"])
        self.assertEqual(found["xpath"], "//page[@name='page_lines']")
        self.assertEqual(found["attrs"]["string"], "Lines")

    def test_an_unnamed_page_resolves_by_position(self):
        found = self.editor.locate_target(self.view.id, {"kind": "page", "index": 0})
        self.assertTrue(found["found"])
        self.assertEqual(
            found["attrs"]["string"], "Details", "index 0 is the first tab"
        )

    def test_position_counts_pages_in_render_order(self):
        found = self.editor.locate_target(self.view.id, {"kind": "page", "index": 1})
        self.assertEqual(found["attrs"]["string"], "Lines")

    def test_a_position_past_the_end_is_refused(self):
        found = self.editor.locate_target(self.view.id, {"kind": "page", "index": 9})
        self.assertFalse(found["found"])

    def test_a_form_field_resolves_and_carries_its_type(self):
        found = self.editor.locate_target(
            self.view.id, {"kind": "field", "name": "comment"}
        )
        self.assertTrue(found["found"])
        self.assertEqual(found["field"]["name"], "comment")

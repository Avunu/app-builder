# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Resolving a click to a node in the view's definition.

The browser says *what* was clicked -- "the column for user_id" -- and the
server decides *where* that is. The division is not fussiness: the arch a
client receives is a per-user projection, with nodes dropped by group rights
and whole subviews grafted in, so an xpath derived from it can be wrong for the
next person to open the same view. Everything here guards that boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.tests.common import StudioCase, raises
from odoo.addons.app_builder_base.tools import typed

from ..models.studio_view_editor import StudioViewEditor

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime, the same bargain every Phase 1c
    # file's own `TYPE_CHECKING` block makes. `View`/`StudioViewEditor` are
    # real, top-level imports instead (`typed.model()` reads `cls._name` at
    # runtime) -- only `locate_target`'s own found()/not-found() union
    # branches and its nested field descriptor are cast-only and need no
    # runtime binding.
    from ..models.studio_view_editor import (
        FieldInfoJSON,
        _LocateTargetFoundJSON,
        _LocateTargetNotFoundJSON,
    )

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
        self.editor = typed.model(self.env, StudioViewEditor)

    def _view(self, arch, view_type="list", model="res.partner"):
        vals: dict[str, object] = {
            "name": "studio.locate.test",
            "model": model,
            "type": view_type,
            "arch": arch,
        }
        return self.env["ir.ui.view"].create(vals)  # pyright: ignore[reportArgumentType]

    # -- resolving --------------------------------------------------------

    def test_a_column_resolves_to_its_field_node(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(
            # `.id` reads as `IdType | Literal[False]` on a typed record;
            # `locate_target`/`editing_context`/`apply_operation` all
            # declare a plain `int`, so every view/package id argument
            # below is the same cast, for the same reason.
            cast("int", view.id),
            {"kind": "column", "name": "function"},
        )
        self.assertTrue(found["found"])
        # Narrows the found()/not-found() union after the runtime check
        # above has already proven which branch this is -- same shape as
        # `typed.py`'s own relational-field casts, aimed at a TypedDict
        # union instead of an `env[...]` lookup. Every other `found =
        # cast(...)`/`= cast(...)` reassignment below is the same idiom.
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["xpath"], "//field[@name='function']")
        self.assertEqual(found["tag"], "field")

    def test_the_root_resolves_without_a_name(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(cast("int", view.id), {"kind": "root"})
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["tag"], "list")
        self.assertEqual(
            found["attrs"].get("string"),
            "Partners",
            "root attributes are what a list's settings panel edits",
        )

    def test_a_field_carries_its_type_so_options_can_be_type_aware(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(
            cast("int", view.id), {"kind": "column", "name": "name"}
        )
        found = cast("_LocateTargetFoundJSON", found)
        # `field` is `FieldInfoJSON | None` on the found() branch -- `None`
        # only when the node is not a field at all, never true for a
        # "column" descriptor, which always resolves to one.
        field = cast("FieldInfoJSON", found["field"])
        self.assertEqual(field["type"], "char")
        self.assertEqual(field["name"], "name")

    def test_existing_attributes_come_back_so_the_panel_shows_state(self):
        view = self._view(
            '<list><field name="name" optional="hide" widget="badge"/></list>'
        )
        found = self.editor.locate_target(
            cast("int", view.id), {"kind": "column", "name": "name"}
        )
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["attrs"]["optional"], "hide")
        self.assertEqual(found["attrs"]["widget"], "badge")

    # -- the boundary this exists to protect ------------------------------

    def test_a_name_repeated_in_a_subview_never_yields_a_bare_locator(self):
        """//field[@name='name'] would match the subview's column too, and
        locate_node takes the first match -- so the edit would land on the
        wrong model's list."""
        view = self._view(NESTED_FORM_ARCH, view_type="form")
        found = self.editor.locate_target(
            cast("int", view.id), {"kind": "field", "name": "name"}
        )
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        self.assertNotEqual(
            found["xpath"],
            "//field[@name='name']",
            "ambiguous name must fall back to an absolute indexed path",
        )
        self.assertTrue(found["xpath"].startswith("/form"), found["xpath"])

    def test_a_subview_node_is_not_selectable_from_the_parent(self):
        """'email' exists only inside child_ids, which is another model."""
        view = self._view(NESTED_FORM_ARCH, view_type="form")
        found = self.editor.locate_target(
            cast("int", view.id), {"kind": "field", "name": "email"}
        )
        self.assertFalse(
            found["found"], "selecting it here would edit res.partner's child list"
        )
        found = cast("_LocateTargetNotFoundJSON", found)
        self.assertIn("not something the builder can edit", found["reason"])

    def test_an_unknown_field_is_refused_with_a_reason(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(
            cast("int", view.id), {"kind": "column", "name": "nope"}
        )
        self.assertFalse(found["found"])
        found = cast("_LocateTargetNotFoundJSON", found)
        self.assertTrue(found["reason"])

    def test_an_unknown_kind_is_refused_rather_than_guessed(self):
        view = self._view(LIST_ARCH)
        found = self.editor.locate_target(
            cast("int", view.id), {"kind": "whatever", "name": "name"}
        )
        self.assertFalse(found["found"])

    # -- opening the editor ------------------------------------------------

    def test_editing_context_reports_an_unowned_view_as_not_owned(self):
        """A core view gets patched, not rewritten. Saying so is the difference
        between understanding the output and being surprised by it."""
        view = typed.ref(self.env, "base.view_partner_form")
        context = self.editor.editing_context(cast("int", view.id))
        self.assertFalse(context["owned"])
        self.assertEqual(context["view"]["model"], "res.partner")

    def test_editing_context_reports_an_owned_primary_view_as_owned(self):
        package = self.make_package(name="x_ctx_pkg")
        view = self._view(LIST_ARCH)
        package.studio_capture(view)
        context = self.editor.editing_context(cast("int", view.id))
        self.assertTrue(context["owned"])
        self.assertEqual(context["suggested_package_id"], package.id)

    def test_a_plain_user_cannot_resolve_or_open(self):
        view = self._view(LIST_ARCH)
        vals: dict[str, object] = {
            "name": "Nosy",
            "login": "locate_outsider",
            "groups_id": [(6, 0, [typed.ref(self.env, "base.group_user").id])],
        }
        outsider = self.env["res.users"].create(vals)  # pyright: ignore[reportArgumentType]
        editor = self.editor.with_user(outsider).sudo(False)
        with raises(self, AccessError):
            editor.locate_target(cast("int", view.id), {"kind": "root"})
        with raises(self, AccessError):
            editor.editing_context(cast("int", view.id))


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
        self.editor = typed.model(self.env, StudioViewEditor)
        vals: dict[str, object] = {
            "name": "studio.page.test",
            "model": "res.partner",
            "type": "form",
            "arch": NOTEBOOK_FORM,
        }
        self.view = self.env["ir.ui.view"].create(vals)  # pyright: ignore[reportArgumentType]

    def test_a_named_page_resolves_by_name(self):
        found = self.editor.locate_target(
            cast("int", self.view.id), {"kind": "page", "name": "page_lines"}
        )
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["xpath"], "//page[@name='page_lines']")
        self.assertEqual(found["attrs"]["string"], "Lines")

    def test_an_unnamed_page_resolves_by_position(self):
        found = self.editor.locate_target(
            cast("int", self.view.id), {"kind": "page", "index": 0}
        )
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(
            found["attrs"]["string"], "Details", "index 0 is the first tab"
        )

    def test_position_counts_pages_in_render_order(self):
        found = self.editor.locate_target(
            cast("int", self.view.id), {"kind": "page", "index": 1}
        )
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["attrs"]["string"], "Lines")

    def test_a_position_past_the_end_is_refused(self):
        found = self.editor.locate_target(
            cast("int", self.view.id), {"kind": "page", "index": 9}
        )
        self.assertFalse(found["found"])

    def test_a_form_field_resolves_and_carries_its_type(self):
        found = self.editor.locate_target(
            cast("int", self.view.id), {"kind": "field", "name": "comment"}
        )
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        field = cast("FieldInfoJSON", found["field"])
        self.assertEqual(field["name"], "comment")


CALENDAR_ARCH = """
<calendar string="Schedule" date_start="x_when" color="x_user_id" mode="month">
    <field name="x_name"/>
    <field name="x_user_id" filters="1"/>
</calendar>
"""


@tagged("post_install", "-at_install")
class TestCalendarEditing(StudioCase):
    """A calendar is edited as settings, not by clicking events.

    It draws events rather than fields, so there is no per-node DOM that maps
    back to the arch. What a calendar *is* lives in its root attributes, which
    is what the panel reads and writes -- and the fields it offers for those
    attributes have to be typed correctly, because a date_start that is not a
    date throws on open rather than degrading.
    """

    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, StudioViewEditor)
        # A model that genuinely has a date and a link to colour by. res.partner
        # has neither, and a calendar naming a field that does not exist fails
        # view validation at create time.
        model_vals: dict[str, object] = {
            "name": "Calendar Demo",
            "model": "x_cal_demo",
            "field_id": [
                # x_name explicitly: Odoo only auto-creates it when the
                # model is made with no fields at all.
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
            "name": "studio.calendar.test",
            "model": "x_cal_demo",
            "type": "calendar",
            "arch": CALENDAR_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]

    def test_the_root_carries_the_settings_the_panel_edits(self):
        found = self.editor.locate_target(cast("int", self.view.id), {"kind": "root"})
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["tag"], "calendar")
        self.assertEqual(found["attrs"]["date_start"], "x_when")
        self.assertEqual(found["attrs"]["color"], "x_user_id")
        self.assertEqual(found["attrs"]["mode"], "month")

    def test_a_calendar_field_resolves_for_its_filter_option(self):
        found = self.editor.locate_target(
            cast("int", self.view.id), {"kind": "field", "name": "x_user_id"}
        )
        self.assertTrue(found["found"])
        found = cast("_LocateTargetFoundJSON", found)
        self.assertEqual(found["attrs"].get("filters"), "1")

    def test_the_context_offers_the_models_fields_for_naming(self):
        """date_start and color name a field, so the panel needs real ones to
        offer rather than a free-text box."""
        context = self.editor.editing_context(cast("int", self.view.id))
        by_name = {f["name"]: f for f in context["fields"]}
        self.assertEqual(by_name["x_when"]["type"], "date")
        self.assertEqual(by_name["x_user_id"]["type"], "many2one")

    def test_audit_timestamps_are_not_offered(self):
        context = self.editor.editing_context(cast("int", self.view.id))
        names = {f["name"] for f in context["fields"]}
        self.assertNotIn("create_date", names)
        self.assertNotIn("write_date", names)

    def test_changing_a_setting_writes_a_patch_not_a_rewrite(self):
        # The base view belongs to somebody else -- which is what makes this
        # the patch path -- and it has an external ID, because the serializer
        # rightly refuses to emit a patch naming a view it cannot reference.
        owner = self.make_package(name="x_cal_owner")
        owner.studio_capture(self.view)
        package = self.make_package(name="x_cal_pkg")
        found = self.editor.locate_target(cast("int", self.view.id), {"kind": "root"})
        found = cast("_LocateTargetFoundJSON", found)
        self.editor.apply_operation(
            cast("int", self.view.id),
            cast("int", package.id),
            {
                "type": "set_attributes",
                "xpath": found["xpath"],
                "position": "attributes",
                "attrs": {"mode": "week"},
            },
        )
        self.view.invalidate_recordset()
        self.assertIn(
            'mode="month"', cast("str", self.view.arch), "the base view is untouched"
        )
        patch = typed.model(self.env, View).search([("inherit_id", "=", self.view.id)])
        self.assertTrue(patch)
        self.assertIn("week", cast("str", patch.arch))

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Driving the console the way a person does.

The unit tests prove the resolver picks the right node and the operations
produce the right arch. Neither can tell you whether *clicking* works: whether
the cog entry appears on an ordinary view, whether a click on a heading selects
instead of sorting the column, whether the canvas shows the result rather than
the arch it rendered before the edit, and whether the real view shows it once
the console is closed. That last one is the failure that would cost the most
trust and the one no server-side test can see.
"""

import os
import tempfile

from lxml import etree

from odoo import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.app_builder_base.tests.common import join_groups


@tagged("post_install", "-at_install")
class TestConsoleTour(HttpCase):
    def _package(self, name, label):
        # Exactly one writable package, so editing_context can suggest it
        # without the console having to ask which one to record into.
        package = self.env["studio.package"].create(
            {
                "name": name,
                "display_name_": label,
                "root_path": tempfile.mkdtemp(prefix="studio-tour-"),
                "auto_commit": "off",
            }
        )
        self.env["ir.module.module"].create({"name": name, "state": "installed"})
        join_groups(
            self.env.ref("base.user_admin"), ["app_builder_base.group_studio_manager"]
        )
        return package

    def _manual_field(self, name, label):
        return self.env["ir.model.fields"].create(
            {
                "name": name,
                "field_description": label,
                "ttype": "char",
                "model_id": self.env["ir.model"]._get("res.partner").id,
            }
        )

    def _assert_nothing_leaked(self, package, views):
        """No render-time marker in what was written, on either side.

        The canvas stamps every node with a class token so the browser can
        point at it; the token must never reach an inheriting view or a file
        on disk, or the next canvas would be stamped on top of the last.
        """
        for view in views:
            self.assertNotIn("o_studio_", view.arch, view.name)
        for folder, _dirs, names in os.walk(package.root_path):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    self.assertNotIn("o_studio_", handle.read(), path)

    def test_a_list_view_can_be_edited_by_clicking_it(self):
        """A rename through Properties, undone and redone, reaches the real
        list -- as a patch on the core view, never a rewrite of it."""
        self._package("x_tour_view_pkg", "Tour Views")

        # A plain list of a core model: the case the console must handle by
        # emitting an inheriting view rather than rewriting anything.
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )

        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_console_list_tour",
            login="admin",
        )

        # The tour asserts what the user sees; this asserts what was written.
        # A patch that renamed the column on screen but rewrote the base view
        # would look identical in the browser and be exactly wrong.
        base = self.env.ref("base.view_partner_tree")
        self.assertNotIn(
            "Full Name", base.arch, "the core view must not have been rewritten"
        )
        # Renamed, undone, redone: what is on disk at the end is the rename,
        # put back byte for byte by redo.
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch, "the rename should live in an inheriting view")
        self.assertIn("Full Name", patch.arch)

    def test_a_form_view_can_be_edited_by_clicking_it(self):
        """Selecting, toggling, undoing and adding from the palette, on a
        form: the palette adds at the selection and the tab stays open."""
        self._package("x_tour_form_pkg", "Tour Forms")
        # A field the form does not show, so the palette has something to
        # add that the tour can name.
        self.env["ir.model.fields"].create(
            {
                "name": "x_tour_extra",
                "field_description": "Tour Extra",
                "ttype": "char",
                "model_id": self.env["ir.model"]._get("res.partner").id,
            }
        )
        # With a job position, so that field is rendered rather than folded
        # away as empty, and its generated label has a widget beside it.
        partner = self.env["res.partner"].create(
            {"name": "Tour Subject", "function": "Tour Tester"}
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contact",
                "res_model": "res.partner",
                "view_mode": "form",
                "res_id": partner.id,
            }
        )

        self.start_tour(
            "/odoo/action-%s/%s" % (action.id, partner.id),
            "app_builder_console_form_tour",
            login="admin",
        )

        base = self.env.ref("base.view_partner_form")
        self.assertNotIn("x_tour_extra", base.arch)
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch)
        # The group and the field the palette added are there; the required
        # toggle that was undone is not.
        self.assertIn("<group", patch.arch)
        self.assertIn('name="x_tour_extra"', patch.arch)
        self.assertNotIn('required="1"', patch.arch)

    def test_a_search_view_is_edited_as_lists(self):
        """A search view is reached from another view's console and edited
        as lists; what Undo and Redo do to it shows in those lists, and the
        host list beside them is a preview that opens nothing."""
        self._package("x_tour_search_pkg", "Tour Search")
        # A field no search view mentions, so there is something to add
        # whose name the tour can look for.
        self.env["ir.model.fields"].create(
            {
                "name": "x_tour_search",
                "field_description": "Tour Search",
                "ttype": "char",
                "model_id": self.env["ir.model"]._get("res.partner").id,
            }
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )

        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_console_search_tour",
            login="admin",
        )

        # Added, undone, redone: the search view ends up with the field.
        base = self.env.ref("base.view_res_partner_filter")
        self.assertNotIn("x_tour_search", base.arch)
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch, "the field should live in an inheriting view")
        self.assertIn('name="x_tour_search"', patch.arch)

    def test_a_form_takes_drops(self):
        """Dragging onto the form: a palette field between two fields, a
        group and two columns onto the end of the sheet, a tab onto the
        notebook, a field into the empty group, a field across tabs by
        resting on the tab -- and a drag cancelled with a key, which writes
        nothing. What is on disk afterwards is what the tour dropped, where
        it dropped it, and never a canvas token."""
        package = self._package("x_tour_drag_pkg", "Tour Drag")
        self._manual_field("x_tour_extra", "Tour Extra")
        self._manual_field("x_tour_second", "Tour Second")
        # With a job position, so that field is rendered rather than folded
        # away as empty, and can be moved.
        partner = self.env["res.partner"].create(
            {"name": "Tour Subject", "function": "Tour Tester"}
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contact",
                "res_model": "res.partner",
                "view_mode": "form",
                "res_id": partner.id,
            }
        )

        self.start_tour(
            "/odoo/action-%s/%s" % (action.id, partner.id),
            "app_builder_console_drag_tour",
            login="admin",
        )

        base = self.env.ref("base.view_partner_form")
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch, "the drops should live in an inheriting view")
        root = etree.fromstring(base.get_combined_arch().encode())
        sheet = root.find("sheet")
        # The form's own fields: the embedded contact views repeat names.
        own = "//field[@name='%s'][not(ancestor::field)]"

        # The field dragged after Job Position was then carried into the
        # Purchase group of the second tab, by resting on the tab.
        extra = root.xpath(own % "x_tour_extra")
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0].getparent().get("name"), "purchase")

        # Job Position moved into the group dropped at the end of the sheet,
        # a direct child of the sheet with a studio name.
        function = root.xpath(own % "function")
        self.assertEqual(len(function), 1)
        group = function[0].getparent()
        self.assertEqual(group.getparent(), sheet)
        self.assertTrue(group.get("name", "").startswith("studio_group_"))

        # Two columns: one outer group holding two named groups, after that.
        columns = [
            g
            for g in sheet.findall("group")
            if g.get("name", "").startswith("studio_group_")
            and len(g.findall("group")) == 2
        ]
        self.assertEqual(len(columns), 1, "Columns should be one group of two")
        for inner in columns[0].findall("group"):
            self.assertTrue(inner.get("name", "").startswith("studio_group_"))

        # The tab landed in the notebook, last.
        pages = root.xpath("//notebook/page")
        self.assertEqual(pages[-1].get("string"), "New tab")

        # The cancelled drag dropped nothing.
        self.assertFalse(root.xpath(own % "x_tour_second"))

        self._assert_nothing_leaked(package, patch)

    def test_a_list_takes_drops(self):
        """A heading dragged before another reorders the columns; a palette
        field dropped between two headings lands between them."""
        package = self._package("x_tour_list_drag_pkg", "Tour List Drag")
        self._manual_field("x_tour_extra", "Tour Extra")
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contacts",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )

        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_console_list_drag_tour",
            login="admin",
        )

        base = self.env.ref("base.view_partner_tree")
        patch = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self.assertTrue(patch)
        root = etree.fromstring(base.get_combined_arch().encode())
        names = [f.get("name") for f in root.findall("field")]
        self.assertEqual(names.count("email"), 1, "moved, not copied")
        self.assertLess(names.index("email"), names.index("display_name"))
        self.assertEqual(
            names.index("x_tour_extra"),
            names.index("display_name") + 1,
            "the palette field goes right after Name",
        )
        self._assert_nothing_leaked(package, patch)

    def test_a_new_field_is_created_where_it_is_dropped(self):
        """The Text tile on a core form: an ``x_`` row exists the moment it
        lands, placed after the field it was dropped on, and the Label row
        renames the field itself. Undo takes it off the view only."""
        package = self._package("x_tour_new_field_pkg", "Tour New Field")
        partner = self.env["res.partner"].create(
            {"name": "Tour Subject", "function": "Tour Tester"}
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Contact",
                "res_model": "res.partner",
                "view_mode": "form",
                "res_id": partner.id,
            }
        )

        self.start_tour(
            "/odoo/action-%s/%s" % (action.id, partner.id),
            "app_builder_console_new_field_tour",
            login="admin",
        )

        # The field is real, renamed through the Label row, and captured
        # into the package -- the tour saw it in the palette after the undo.
        field = self.env["ir.model.fields"]._get("res.partner", "x_new_text")
        self.assertTrue(field, "the drop should have created x_new_text")
        self.assertEqual(field.state, "manual")
        self.assertEqual(field.ttype, "char")
        self.assertEqual(field.field_description, "Delivery date")
        self.assertTrue(
            self.env["ir.model.data"].search(
                [
                    ("module", "=", package.name),
                    ("model", "=", "ir.model.fields"),
                    ("res_id", "=", field.id),
                ]
            ),
            "the field should be captured into the package",
        )
        # The Link tile opened the editor and was cancelled: no relation
        # was created, and the server was never asked.
        self.assertFalse(
            self.env["ir.model.fields"].search(
                [
                    ("model", "=", "res.partner"),
                    ("state", "=", "manual"),
                    ("ttype", "=", "many2one"),
                    ("name", "like", "x_new_%"),
                ]
            )
        )
        # Undone: the view no longer shows it, and the core view was never
        # rewritten; the placement lived in an inheriting view.
        base = self.env.ref("base.view_partner_form")
        self.assertNotIn("x_new_text", base.arch)
        root = etree.fromstring(base.get_combined_arch().encode())
        self.assertFalse(root.xpath("//field[@name='x_new_text']"))
        patches = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base.id), ("name", "like", "studio")]
        )
        self._assert_nothing_leaked(package, patches)

    def _kanban_model(self, package, records=True):
        """A manual model with a kanban whose card has a side panel and a
        body, and two records, so the board renders two cards of one
        template -- the case the kanban console exists for.

        The card is laid out as a row, the way most of the core's cards
        are (`class="flex-row"`, an `<aside>` beside a `<main>`): the
        side panel is empty, so it offers one zone to drop into, and the
        arch says nothing about which way the card flows -- that is read
        off the rendering.

        Everything is captured into the package, the way the canvas tests
        capture their fixtures: a drop is recorded as an inheriting view
        of the base, and the base has to have an xmlid for that view to
        be written to source.
        """
        model = self.env["ir.model"].create(
            {
                "name": "Tour Kanban",
                "model": "x_tour_kanban",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_name",
                            "ttype": "char",
                            "field_description": "Name",
                            "required": True,
                        }
                    ),
                    Command.create(
                        {"name": "x_note", "ttype": "char", "field_description": "Note"}
                    ),
                    Command.create(
                        {
                            "name": "x_extra",
                            "ttype": "char",
                            "field_description": "Extra",
                        }
                    ),
                ],
            }
        )
        view = self.env["ir.ui.view"].create(
            {
                "name": "x_tour_kanban.kanban",
                "model": "x_tour_kanban",
                "type": "kanban",
                "arch": """
                    <kanban>
                        <templates>
                            <t t-name="card" class="flex-row">
                                <aside/>
                                <main>
                                    <field name="x_name"/>
                                    <field name="x_note"/>
                                </main>
                            </t>
                        </templates>
                    </kanban>
                """,
            }
        )
        access = self.env["ir.model.access"].create(
            {
                "name": "x_tour_kanban all",
                "model_id": model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": False,
            }
        )
        for letter in ("A", "B") if records else ():
            self.env["x_tour_kanban"].create(
                {
                    "x_name": "Card %s" % letter,
                    "x_note": "Note %s" % letter,
                    "x_extra": "Extra %s" % letter,
                }
            )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Kanban",
                "res_model": "x_tour_kanban",
                "view_mode": "kanban",
            }
        )
        for owned in (model, model.field_id, view, action, access):
            package._assign(owned)
        package.action_write_files()
        return view, action

    def test_a_kanban_card_takes_drops(self):
        """A palette field dropped into the body of one card shows on every
        card; moved into the side panel of another card, it moves on every
        card; undone, it is back. One template, edited once per drop."""
        package = self._package("x_tour_kanban_pkg", "Tour Kanban")
        view, action = self._kanban_model(package)

        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_console_kanban_tour",
            login="admin",
        )

        # The package owns the view, so the drops are edits to its own arch.
        root = etree.fromstring(view.get_combined_arch().encode())
        card = root.find(".//t[@t-name='card']")
        self.assertIsNotNone(card)
        # Dropped at the end of the body, moved to the side panel, and the
        # move undone: one field, in the body, last.
        extra = root.xpath("//field[@name='x_extra']")
        self.assertEqual(len(extra), 1, "moved, not copied")
        self.assertEqual(extra[0].getparent().tag, "main")
        self.assertEqual(
            [f.get("name") for f in card.find("main").findall("field")],
            ["x_name", "x_note", "x_extra"],
        )
        self.assertFalse(card.find("aside").findall("field"))
        self.assertIn('name="x_extra"', view.arch)
        self._assert_nothing_leaked(package, view)

    def test_an_empty_kanban_takes_drops_on_its_sample_cards(self):
        """With no records the canvas shows sample cards, says so, and a
        drop into one still lands in the template."""
        package = self._package("x_tour_kanban_sample_pkg", "Tour Kanban Sample")
        view, action = self._kanban_model(package, records=False)
        self.assertEqual(
            self.env["studio.view.editor"].canvas(view.id)["record_count"], 0
        )

        self.start_tour(
            "/odoo/action-%s" % action.id,
            "app_builder_console_kanban_sample_tour",
            login="admin",
        )

        root = etree.fromstring(view.get_combined_arch().encode())
        self.assertEqual(
            [f.get("name") for f in root.find(".//t[@t-name='card']/main")],
            ["x_name", "x_note", "x_extra"],
        )
        self.assertNotIn("sample", view.arch, "sample mode is the canvas's alone")
        self._assert_nothing_leaked(package, view)

    def _python_owned_model(self, package):
        """A model the package defines in Python, without a reload.

        The App builder cannot run here: applying re-imports the package
        and ``_button_immediate_function`` refuses to run under test. So
        the model is built the way the draft tests build theirs -- a manual
        model with a form, assigned to the package, written to disk and
        adopted -- which makes it Python-owned in every way the console
        asks about (``python_owned``, ``open_for_model``) while the registry
        keeps the manual class it already has.
        """
        model = self.env["ir.model"].create(
            {
                "name": "Tour Staged",
                "model": "x_tour_staged",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_name",
                            "ttype": "char",
                            "field_description": "Name",
                            "required": True,
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_note",
                            "ttype": "char",
                            "field_description": "Note",
                        }
                    ),
                ],
            }
        )
        view = self.env["ir.ui.view"].create(
            {
                "name": "x_tour_staged.form",
                "model": "x_tour_staged",
                "arch": """
                    <form>
                        <sheet>
                            <group>
                                <field name="x_name"/>
                                <field name="x_note"/>
                            </group>
                        </sheet>
                    </form>
                """,
            }
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Tour Staged",
                "res_model": "x_tour_staged",
                "view_mode": "list,form",
            }
        )
        access = self.env["ir.model.access"].create(
            {
                "name": "x_tour_staged all",
                "model_id": model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": False,
            }
        )
        package._assign(model)
        package._assign(model.field_id)
        package._assign(view)
        package._assign(action)
        package._assign(access)
        package.action_write_files()
        package.action_adopt(["x_tour_staged"])
        return model, view, action

    def test_a_field_on_a_python_owned_model_is_staged(self):
        """The Decimal tile on a Python-owned form: a ghost in the flow of
        the form and "1 pending · Apply"; Discard clears it, and nothing
        was created or written."""
        package = self._package("x_tour_staged_pkg", "Tour Staged")
        _model, view, action = self._python_owned_model(package)
        record = self.env["x_tour_staged"].create({"x_name": "Staged Subject"})
        # Built from the App builder in real life; here the model is
        # adopted instead, since the builder's Apply cannot reload under
        # test -- see `_python_owned_model`.
        self.assertTrue(
            self.env["studio.view.editor"].editing_context(view.id)["python_owned"]
        )
        arch_before = view.arch

        self.start_tour(
            "/odoo/action-%s/%s" % (action.id, record.id),
            "app_builder_console_staged_field_tour",
            login="admin",
        )

        # Discarded: the draft is clean, no field exists, the view is as
        # it was, and nothing on disk mentions a decimal.
        draft = self.env["studio.model.draft"].search(
            [("package_model_id.model", "=", "x_tour_staged")]
        )
        self.assertTrue(draft, "the drop should have opened a draft")
        self.assertFalse(any(draft.mapped("dirty")))
        self.assertFalse(
            self.env["ir.model.fields"]._get("x_tour_staged", "x_new_decimal")
        )
        self.assertEqual(view.arch, arch_before)
        for folder, _dirs, names in os.walk(package.root_path):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    self.assertNotIn("new_decimal", handle.read(), path)
        self._assert_nothing_leaked(package, view)

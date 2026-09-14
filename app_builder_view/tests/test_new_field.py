# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creating a field from inside the view editor.

Two answers, and which one applies is the substance. A manual field on a core
model is live the moment it is written, so create-and-place is one gesture --
for every tile of the picker, with its preset, not just the plain types. A
field on a model the package defines in Python is a class attribute and needs
the model re-imported, so it is staged and anchored, and saying so happens
before the form is filled in rather than after.

What has to hold on the live path: each preset produces the right row and
the right widget, a refusal arrives as a sentence before the row exists,
and a view operation that fails leaves no row and no file.
"""

from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

from .test_drop_at import _snapshot


@tagged("post_install", "-at_install")
class TestNewFieldFromTheEditor(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.package = self.make_package()

    def _core_form(self, model="res.partner"):
        return self.env["ir.ui.view"].browse(
            self.env["ir.ui.view"].default_view(model, "form")
        )

    def _create(self, values, model="res.partner", anchor=None):
        view = self._core_form(model)
        return view, self.editor.create_field_at(
            view.id, self.package.id, anchor or {"kind": "root"}, values
        )

    def _patch_of(self, view):
        return self.env["ir.ui.view"].search(
            [("inherit_id", "=", view.id), ("studio_package_id", "=", self.package.id)]
        )

    def _row(self, model, name):
        # A search, not `_get`: that one is cached, and a row the transaction
        # rolled back would still be answered from the cache.
        return self.env["ir.model.fields"].search(
            [("model", "=", model), ("name", "=", name)]
        )

    def _placed(self, view, name):
        view.invalidate_recordset()
        return etree.fromstring(view.get_combined_arch().encode()).find(
            ".//field[@name='%s']" % name
        )

    # -- the plan -------------------------------------------------------------

    def test_a_core_model_can_take_a_field_here(self):
        view = self._core_form()
        plan = self.env["studio.view.editor"].new_field_plan(view.id)
        self.assertTrue(plan["can_create"])
        self.assertEqual(plan["prefix"], "x_")

    def test_creating_one_places_it_in_the_same_gesture(self):
        view, created = self._create(
            {"field_description": "Delivery date", "ttype": "date"}
        )
        self.assertEqual(
            created, {"name": "x_delivery_date", "label": "Delivery date", "live": True}
        )
        self.assertIn("x_delivery_date", self.env["res.partner"]._fields)
        patch_view = self._patch_of(view)
        self.assertTrue(patch_view, "a core view must be patched, not rewritten")
        self.assertIn("x_delivery_date", patch_view.arch)

    def test_the_field_is_written_to_source(self):
        self._create({"field_description": "Delivery date", "ttype": "date"})
        self.assertIn("x_delivery_date", "".join(self.package._render_files().values()))

    def test_the_old_quick_vocabulary_still_works(self):
        """``relation`` was the key the first panel sent for a link; it is
        still taken, so an older client keeps working."""
        self._create(
            {"field_description": "Owner", "ttype": "many2one", "relation": "res.users"}
        )
        row = self._row("res.partner", "x_owner")
        self.assertEqual(row.relation, "res.users")
        self.assertEqual(row.on_delete, "set null")

    # -- every preset, live ---------------------------------------------------

    def test_priority_is_a_selection_with_four_values_and_a_star(self):
        view, _created = self._create(
            {"field_description": "Urgency", "ttype": "priority"}
        )
        row = self._row("res.partner", "x_urgency")
        self.assertEqual(row.ttype, "selection")
        self.assertEqual(
            [(s.value, s.name) for s in row.selection_ids],
            [("0", "Normal"), ("1", "Low"), ("2", "High"), ("3", "Very High")],
        )
        self.assertEqual(self._placed(view, "x_urgency").get("widget"), "priority")
        self.assertIn(
            "Very High",
            "".join(self.package._render_files().values()),
            "the values are captured with the field, or the next database "
            "loads a selection with none",
        )

    def test_image_and_signature_are_binaries_with_a_widget(self):
        view, _created = self._create({"field_description": "Photo", "ttype": "image"})
        self.assertEqual(self._row("res.partner", "x_photo").ttype, "binary")
        self.assertEqual(self._placed(view, "x_photo").get("widget"), "image")
        view, _created = self._create({"field_description": "Signed", "ttype": "sign"})
        self.assertEqual(self._row("res.partner", "x_signed").ttype, "binary")
        self.assertEqual(self._placed(view, "x_signed").get("widget"), "signature")

    def test_a_date_range_is_a_datetime_with_a_widget(self):
        view, _created = self._create(
            {"field_description": "Window", "ttype": "daterange"}
        )
        self.assertEqual(self._row("res.partner", "x_window").ttype, "datetime")
        self.assertEqual(self._placed(view, "x_window").get("widget"), "daterange")

    def test_tags_are_a_many2many_shown_as_tags(self):
        view, _created = self._create(
            {
                "field_description": "Labels",
                "ttype": "tags",
                "comodel": "res.partner.category",
            }
        )
        row = self._row("res.partner", "x_labels")
        self.assertEqual(row.ttype, "many2many")
        self.assertEqual(row.relation, "res.partner.category")
        self.assertEqual(self._placed(view, "x_labels").get("widget"), "many2many_tags")

    def test_a_selection_arrives_with_its_values(self):
        self._create(
            {
                "field_description": "Tier",
                "ttype": "selection",
                "selection": [
                    {"value": "gold", "label": "Gold", "sequence": 10},
                    {"value": "silver", "label": "Silver", "sequence": 20},
                ],
            }
        )
        row = self._row("res.partner", "x_tier")
        self.assertEqual([s.value for s in row.selection_ids], ["gold", "silver"])
        owned = self.env["ir.model.data"].search(
            [
                ("model", "=", "ir.model.fields.selection"),
                ("res_id", "in", row.selection_ids.ids),
                ("module", "=", self.package.name),
            ]
        )
        self.assertEqual(len(owned), 2, "the rows belong to the package too")

    def test_a_related_list_needs_a_link_back_that_exists(self):
        view, _created = self._create(
            {
                "field_description": "Accounts",
                "ttype": "lines",
                "comodel": "res.partner.bank",
                "inverse_name": "partner_id",
            }
        )
        row = self._row("res.partner", "x_accounts")
        self.assertEqual(row.ttype, "one2many")
        self.assertEqual(row.relation_field, "partner_id")
        self.assertIsNone(self._placed(view, "x_accounts").get("widget"), "no widget")

    def test_an_amount_finds_the_currency_field_by_itself(self):
        """``res.company`` has ``currency_id``; core would accept the row
        with the field left blank, and the row names it anyway so the
        source says which."""
        self._create(
            {"field_description": "Budget", "ttype": "monetary"}, model="res.company"
        )
        row = self._row("res.company", "x_budget")
        self.assertEqual(row.ttype, "monetary")
        self.assertEqual(row.currency_field, "currency_id")

    def test_a_related_field_takes_the_type_of_what_it_follows(self):
        self._create(
            {
                "field_description": "Parent country",
                "ttype": "related",
                "related": "parent_id.country_id",
            }
        )
        row = self._row("res.partner", "x_parent_country")
        self.assertEqual(row.ttype, "many2one")
        self.assertEqual(row.relation, "res.country")
        self.assertEqual(row.related, "parent_id.country_id")
        self.assertFalse(
            row.store, "a stored copy of another record's value goes stale"
        )

    def test_a_label_the_model_already_uses_gets_a_suffix(self):
        """Two Text tiles dropped before either was renamed are both "New
        Text"; the second becomes ``x_new_text_2`` rather than a refusal
        for a name the user never typed."""
        _view, first = self._create({"field_description": "New Text", "ttype": "char"})
        _view, second = self._create({"field_description": "New Text", "ttype": "char"})
        self.assertEqual(first["name"], "x_new_text")
        self.assertEqual(second["name"], "x_new_text_2")
        self.assertIn("x_new_text_2", self.env["res.partner"]._fields)

    def test_a_name_the_user_typed_is_not_renamed(self):
        self._create({"field_description": "Nick", "ttype": "char"})
        with self.assertRaises(UserError) as caught:
            self._create(
                {"field_description": "Nick", "ttype": "char", "name": "x_nick"}
            )
        self.assertIn("already has a field called x_nick", str(caught.exception))

    def test_copy_is_the_spec_word_for_the_copied_column(self):
        self._create({"field_description": "Ref", "ttype": "char", "copy": False})
        self.assertFalse(self._row("res.partner", "x_ref").copied)
        self._create({"field_description": "Note", "ttype": "char", "copy": True})
        self.assertTrue(self._row("res.partner", "x_note").copied)

    # -- refusals, before the row exists --------------------------------------

    def _refused(self, values, model="res.partner"):
        with self.assertRaises(UserError) as caught:
            self._create(values, model=model)
        return str(caught.exception)

    def test_a_link_needs_something_to_link_to(self):
        message = self._refused({"field_description": "Owner", "ttype": "many2one"})
        self.assertIn("Choose the model", message)
        self.assertFalse(self._row("res.partner", "x_owner"))

    def test_a_link_to_a_model_that_does_not_exist_is_refused(self):
        message = self._refused(
            {"field_description": "Owner", "ttype": "many2one", "comodel": "no.such"}
        )
        self.assertIn("no.such", message)

    def test_a_related_list_without_a_link_back_is_refused(self):
        message = self._refused(
            {
                "field_description": "Accounts",
                "ttype": "lines",
                "comodel": "res.partner.bank",
            }
        )
        self.assertIn("links back", message)
        message = self._refused(
            {
                "field_description": "Accounts",
                "ttype": "lines",
                "comodel": "res.partner.bank",
                "inverse_name": "acc_number",
            }
        )
        self.assertIn("no link field called acc_number", message)

    def test_a_link_back_aimed_elsewhere_is_refused(self):
        """Core only checks a many2one of that name exists; one pointing at
        another model would load and show nothing."""
        message = self._refused(
            {
                "field_description": "Companies",
                "ttype": "one2many",
                "comodel": "res.users",
                "inverse_name": "company_id",
            }
        )
        self.assertIn("links to res.company", message)

    def test_an_amount_without_a_currency_field_is_refused(self):
        message = self._refused({"field_description": "Budget", "ttype": "monetary"})
        self.assertIn("currency field", message)

    def test_a_related_path_that_breaks_names_the_step(self):
        message = self._refused(
            {"field_description": "X", "ttype": "related", "related": "parent_id.nope"}
        )
        self.assertIn("nope is not a field of res.partner", message)
        message = self._refused(
            {"field_description": "X", "ttype": "related", "related": "email.name"}
        )
        self.assertIn("not a relation", message)

    def test_a_selection_without_values_is_refused(self):
        message = self._refused({"field_description": "Stage", "ttype": "selection"})
        self.assertIn("at least one value", message)

    def test_a_computed_field_is_not_created_live(self):
        message = self._refused(
            {"field_description": "Total", "ttype": "float", "compute": "x = 1"}
        )
        self.assertIn("defines in Python", message)

    def test_a_python_model_stages_rather_than_creating_live(self):
        package = self.package
        self.build_demo_content(package)
        self.env["studio.package.model"]._adopt(
            package, "x_studio_project", source="python"
        )
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        plan = self.env["studio.view.editor"].new_field_plan(view.id)
        self.assertFalse(plan["can_create"])
        self.assertEqual(plan["handoff"], package.id)
        self.assertIn("re-imported", plan["reason"])

    def test_the_handoff_refuses_rather_than_writing_a_row(self):
        """Writing a manual row onto a Python model is the drift this exists
        to prevent, so the refusal is the point rather than a limitation."""
        package = self.package
        self.build_demo_content(package)
        self.env["studio.package.model"]._adopt(
            package, "x_studio_project", source="python"
        )
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        with self.assertRaises(UserError):
            self.env["studio.view.editor"].create_field_at(
                view.id,
                package.id,
                {"kind": "root"},
                {"field_description": "Late", "ttype": "boolean"},
            )
        self.assertNotIn("x_late", self.env["x_studio_project"]._fields)

    # -- atomicity ------------------------------------------------------------

    def test_a_failed_view_operation_leaves_no_file(self):
        """Disk after database: the row is created, the view is patched,
        the package is written last. A view operation that fails finds
        nothing on disk to undo -- which is what this pins. The row goes
        with the transaction, and that is the RPC's job, not the method's:
        ``assertRaises`` rolls a savepoint back the same way, so a row
        assertion here would hold whatever the method did."""
        disk = _snapshot(self.package.root_path)
        Editor = self.env.registry["studio.view.editor"]
        with (
            patch.object(
                Editor, "_op_add_field", autospec=True, side_effect=UserError("boom")
            ),
            self.assertRaises(UserError),
        ):
            self._create({"field_description": "Delivery date", "ttype": "date"})
        self.assertEqual(_snapshot(self.package.root_path), disk)
        self.assertNotIn(
            "x_delivery_date", "".join(_snapshot(self.package.root_path).values())
        )

    def test_an_anchor_that_does_not_resolve_leaves_no_file(self):
        disk = _snapshot(self.package.root_path)
        with self.assertRaises(UserError):
            self._create(
                {"field_description": "Delivery date", "ttype": "date"},
                anchor={"kind": "field", "name": "no_such_field"},
            )
        self.assertEqual(_snapshot(self.package.root_path), disk)

    def test_the_disk_is_written_once(self):
        Package = self.env.registry["studio.package"]
        original = Package.action_write_files
        with patch.object(
            Package, "action_write_files", autospec=True, side_effect=original
        ) as spy:
            self._create({"field_description": "Urgency", "ttype": "priority"})
        self.assertEqual(spy.call_count, 1)

    # -- the drop -------------------------------------------------------------

    def test_dropping_a_new_field_lands_it_and_selects_it(self):
        view = self._core_form()
        canvas = self.editor.canvas(view.id)
        email = next(t for t, n in canvas["nodes"].items() if n["name"] == "email")
        result = self.editor.drop_at(
            view.id,
            self.package.id,
            {"token": email, "position": "after"},
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "Nick"},
            },
            expected_arch_version=canvas["arch_version"],
        )
        self.assertFalse(result["stale"])
        self.assertEqual(
            result["created"], {"name": "x_nick", "label": "Nick", "live": True}
        )
        self.assertIsNone(result["staged"])
        self.assertIsNone(result["draft"])
        selected = result["canvas"]["nodes"][result["select"]]
        self.assertEqual(selected["name"], "x_nick")
        self.assertEqual(selected["field"]["origin"], "manual")
        combined = etree.fromstring(view.get_combined_arch().encode())
        email_node = combined.find(".//field[@name='email']")
        # Right after Email -- which `mail` keeps in a row div the group
        # draws no label for, so the new field is given one of its own,
        # in the same edit.
        label = email_node.getnext()
        self.assertEqual((label.tag, label.get("for")), ("label", "x_nick"))
        self.assertEqual(label.getnext().get("name"), "x_nick")
        self.assertEqual(selected["label"]["by"], "label")
        self.assertEqual(result["history"]["undo"][0]["summary"], "added x_nick")
        self.assertEqual(len(result["history"]["undo"]), 1, "one edit, label included")

    # -- what the tiles say ---------------------------------------------------

    def test_field_types_say_what_a_drop_will_do(self):
        entries = {e["value"]: e for e in self.editor.field_types_for("res.partner")}
        self.assertTrue(entries["char"]["live"])
        self.assertFalse(entries["char"]["needs_dialog"])
        self.assertTrue(entries["priority"]["live"])
        self.assertFalse(entries["priority"]["needs_dialog"], "the values come with it")
        self.assertTrue(entries["selection"]["needs_dialog"])
        self.assertTrue(entries["many2one"]["needs_dialog"])
        self.assertTrue(
            entries["lines"]["live"], "true, and the dialog asks for the inverse"
        )
        self.assertTrue(entries["lines"]["needs_dialog"])
        self.assertTrue(entries["related"]["needs_dialog"])
        self.assertFalse(entries["monetary"]["enabled"], "res.partner has no currency")
        self.assertFalse(entries["monetary"]["live"])
        self.assertFalse(entries["properties"]["live"])

    def test_an_amount_needs_no_dialog_where_the_currency_is_obvious(self):
        entries = {e["value"]: e for e in self.editor.field_types_for("res.company")}
        self.assertTrue(entries["monetary"]["live"])
        self.assertFalse(entries["monetary"]["needs_dialog"])

    def test_nothing_is_live_on_a_python_owned_model(self):
        self.build_demo_content(self.package)
        self.env["studio.package.model"]._adopt(
            self.package, "x_studio_project", source="python"
        )
        entries = self.editor.field_types_for("x_studio_project")
        self.assertTrue(entries)
        self.assertFalse(any(e["live"] for e in entries))

    # -- editing a manual field's definition ---------------------------------

    def test_a_manual_field_definition_can_be_changed(self):
        self._create({"field_description": "Nick", "ttype": "char"})
        Package = self.env.registry["studio.package"]
        original = Package.action_write_files
        with patch.object(
            Package, "action_write_files", autospec=True, side_effect=original
        ) as spy:
            definition = self.editor.update_manual_field(
                "res.partner",
                "x_nick",
                {
                    "field_description": "Nickname",
                    "help": "What friends say",
                    "readonly": True,
                },
                self.package.id,
            )
        self.assertEqual(spy.call_count, 1)
        row = self._row("res.partner", "x_nick")
        self.assertEqual(row.field_description, "Nickname")
        self.assertEqual(row.help, "What friends say")
        self.assertTrue(row.readonly)
        self.assertEqual(definition["origin"], "manual")
        self.assertIn("field_description", definition["editable"])
        self.assertIn("translate", definition["editable"])
        self.assertEqual(definition["values"]["field_description"], "Nickname")
        self.assertIn("Nickname", "".join(self.package._render_files().values()))

    def test_selection_values_are_synchronised_by_value(self):
        """A value records already hold keeps its row; a label change is a
        write, a missing value an unlink, a new value a create."""
        self._create({"field_description": "Urgency", "ttype": "priority"})
        row = self._row("res.partner", "x_urgency")
        kept = row.selection_ids.filtered(lambda s: s.value == "2")
        definition = self.editor.update_manual_field(
            "res.partner",
            "x_urgency",
            {
                "selection": [
                    {"value": "0", "label": "Meh", "sequence": 10},
                    {"value": "2", "label": "High", "sequence": 30},
                    {"value": "9", "label": "Fire", "sequence": 90},
                ]
            },
            self.package.id,
        )
        self.assertEqual(
            [(s.value, s.name) for s in row.selection_ids],
            [("0", "Meh"), ("2", "High"), ("9", "Fire")],
        )
        self.assertTrue(kept.exists(), "the row for a kept value is the same row")
        self.assertEqual(
            [s["value"] for s in definition["values"]["selection"]], ["0", "2", "9"]
        )
        self.assertIn("Fire", "".join(self.package._render_files().values()))

    def test_a_core_field_definition_is_not_written(self):
        with self.assertRaises(UserError) as caught:
            self.editor.update_manual_field(
                "res.partner", "name", {"field_description": "Nom"}, self.package.id
            )
        self.assertIn("defined in Python", str(caught.exception))
        self.assertEqual(self._row("res.partner", "name").field_description, "Name")

    def test_a_key_the_panel_does_not_offer_is_refused(self):
        self._create({"field_description": "Nick", "ttype": "char"})
        with self.assertRaises(UserError) as caught:
            self.editor.update_manual_field(
                "res.partner", "x_nick", {"ttype": "text"}, self.package.id
            )
        self.assertIn("ttype", str(caught.exception))

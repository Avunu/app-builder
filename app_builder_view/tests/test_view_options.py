# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The option catalogue is data now, so it can be checked like data.

That is most of the point of moving it off the client. While the rows were
JavaScript objects carrying functions, "does every row name an attribute the
editor can actually write" was not a question anything could ask.
"""

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase
from odoo.addons.app_builder_base.tools import catalogue

from ..tools import view_options

# Renderers the properties panel implements. A row asking for anything else
# renders as nothing at all, which reads as a missing feature rather than a typo.
KNOWN_ROW_TYPES = {"text", "toggle", "select", "groups", "condition"}


def _owner_name(owner):
    """An option group is identified by id, a widget by its registry value."""
    return getattr(owner, "id", None) or getattr(owner, "value", "?")


@tagged("post_install", "-at_install")
class TestOptionCatalogue(StudioCase):
    def _all_rows(self):
        for group in view_options.OPTION_GROUPS:
            for row in group.rows:
                yield group, row
        for widget in catalogue.WIDGETS:
            for row in widget.rows:
                yield widget, row

    def test_every_row_has_a_renderer(self):
        for owner, row in self._all_rows():
            self.assertIn(
                row.type,
                KNOWN_ROW_TYPES,
                "%s row '%s' asks for renderer '%s'"
                % (_owner_name(owner), row.name, row.type),
            )

    def test_every_row_targets_an_attribute_or_an_option(self):
        for owner, row in self._all_rows():
            self.assertIn(
                row.target,
                (catalogue.ATTRIBUTE, catalogue.OPTION),
                "%s row '%s'" % (getattr(owner, "id", "?"), row.name),
            )

    def test_a_select_row_can_produce_choices(self):
        """Static choices or a named source -- never an empty dropdown."""
        for owner, row in self._all_rows():
            if row.type != "select":
                continue
            self.assertTrue(
                row.choices or row.source,
                "%s row '%s' is a select with nothing to select"
                % (_owner_name(owner), row.name),
            )

    def test_widget_values_are_unique(self):
        seen = [entry.value for entry in catalogue.WIDGETS]
        self.assertEqual(len(seen), len(set(seen)), "a widget is declared twice")

    def test_every_widget_declares_the_types_it_serves(self):
        for entry in catalogue.WIDGETS:
            self.assertTrue(entry.types, "%s serves no field type" % entry.value)

    def test_groups_are_scoped_to_view_types_that_exist(self):
        known = set(self.env["ir.ui.view"]._fields["type"].get_values(self.env))
        for group in view_options.OPTION_GROUPS:
            for view_type in group.view_types:
                self.assertIn(view_type, known, "group %s" % group.id)

    def test_the_caller_supplies_the_language(self):
        """Labels stay lazy until somebody who knows the language resolves them.

        `_lt` resolves by inspecting the calling frame for a language
        (`translate.py:614`), and this module has no environment in scope. The
        first version stringified inside `to_json`, so Odoo found no language,
        logged an error and failed the run. The resolver is passed in now, from
        the model layer, and defaults to leaving the value alone.
        """
        payload = view_options.groups_json("form", self.env._)
        self.assertTrue(payload)
        for group in payload:
            self.assertIsInstance(group["title"], str)
            for row in group["rows"]:
                self.assertIsInstance(row["label"], str)
                self.assertIsInstance(row["help"], str)
                for _value, label in row["choices"]:
                    self.assertIsInstance(label, str)

    def test_the_default_resolver_does_not_guess(self):
        """Left alone rather than resolved against whatever frame is handy."""
        payload = view_options.groups_json("form")
        titles = [group["title"] for group in payload]
        self.assertTrue(
            any(not isinstance(title, str) for title in titles),
            "a lazy label resolved without being asked to",
        )


@tagged("post_install", "-at_install")
class TestEditingContextCarriesTheCatalogue(StudioCase):
    def test_editing_context_sends_options_and_widgets(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        context = self.env["studio.view.editor"].editing_context(view.id)
        self.assertTrue(context["options"], "the panel would have nothing to show")
        self.assertTrue(context["catalogue"]["widgets"])
        ids = {group["id"] for group in context["options"]}
        self.assertIn("form_field", ids)
        self.assertNotIn(
            "list_root", ids, "a form must not be offered a list's settings"
        )

    def test_a_widget_row_is_present_for_fields(self):
        package = self.make_package()
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )
        context = self.env["studio.view.editor"].editing_context(view.id)
        group = next(g for g in context["options"] if g["id"] == "form_field")
        names = [row["name"] for row in group["rows"]]
        self.assertIn("widget", names)
        self.assertIn(
            "groups", names, "field-level group visibility is a documented property"
        )

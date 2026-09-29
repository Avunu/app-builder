# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The option catalogue is data now, so it can be checked like data.

That is most of the point of moving it off the client. While the rows were
JavaScript objects carrying functions, "does every row name an attribute the
editor can actually write" was not a question anything could ask.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase, unchecked
from odoo.addons.app_builder_base.tools import catalogue, typed

from ..models.studio_view_editor import StudioViewEditor
from ..tools import view_options

if TYPE_CHECKING:
    # Only used inside the `cast()` calls below (`from __future__ import
    # annotations` defers them to strings) -- `_fields["type"]` off a
    # `typed.model()`-less lookup is the base `Field`, which does not
    # declare `get_values`; only its `Selection` subclass does (`odoo
    # /fields.py`). Same shape as `studio_approval.py`'s own traced
    # `_selection_values` gap.
    from odoo.fields import Selection

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

    def test_groups_are_scoped_to_view_types_that_could_exist(self):
        """Installed here, or declared as something a module may contribute.

        A panel for an absent type is deliberate and harmless -- `groups_json`
        filters by the view's real type, so it never matches, and it is ready
        the day somebody installs the module. What must not pass is a typo, so
        the optional ones are listed rather than assumed.
        """
        known = set(
            cast("Selection", self.env["ir.ui.view"]._fields["type"]).get_values(
                self.env
            )
        )
        allowed = known | set(view_options.OPTIONAL_VIEW_TYPES)
        for group in view_options.OPTION_GROUPS:
            for view_type in group.view_types:
                self.assertIn(view_type, allowed, "group %s" % group.id)

    def test_an_uninstalled_view_type_offers_no_panel(self):
        absent = [
            t
            for t in view_options.OPTIONAL_VIEW_TYPES
            if t
            not in cast("Selection", self.env["ir.ui.view"]._fields["type"]).get_values(
                self.env
            )
        ]
        if not absent:
            self.skipTest("every optional view type is installed here")
        self.assertTrue(
            view_options.groups_for(absent[0]),
            "the panel is declared, ready for when the module is installed",
        )

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
        with unchecked():
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
        context = typed.model(self.env, StudioViewEditor).editing_context(
            cast("int", view.id)
        )
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
        context = typed.model(self.env, StudioViewEditor).editing_context(
            cast("int", view.id)
        )
        group = next(g for g in context["options"] if g["id"] == "form_field")
        names = [row["name"] for row in group["rows"]]
        self.assertIn("widget", names)
        self.assertIn(
            "groups", names, "field-level group visibility is a documented property"
        )

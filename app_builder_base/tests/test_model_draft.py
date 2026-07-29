# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The edit buffer the composer sits on.

Everything here is the contract the OWL client will call, so it is worth
pinning before the client exists rather than after: staging an edit must not
touch the registry, the tray must describe what will happen, and Apply must
refuse rather than surprise.
"""

import json
import os

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..tools import modelspec
from .common import StudioCase


@tagged("post_install", "-at_install")
class TestModelDraft(StudioCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_draft_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project"])
        self.package_model = self.package.model_ids.filtered(
            lambda m: m.model == "x_studio_project"
        )

    def _draft(self):
        return self.env["studio.model.draft"].open_for(self.package_model)

    # -- opening ----------------------------------------------------------

    def test_a_draft_starts_clean_and_matches_the_file(self):
        draft = self._draft()
        self.assertFalse(draft.dirty)
        self.assertEqual(draft.change_count, 0)
        self.assertEqual(draft.spec_json, draft.base_spec_json)
        self.assertEqual(draft._spec(), self.package_model._current_spec())

    def test_a_frozen_model_cannot_be_opened(self):
        """Better to say why than to offer an editor that cannot save."""
        path = os.path.join(self.package.root_path, self.package_model.python_path)
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        from ..tools import pycodegen

        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                source.replace(
                    pycodegen.END_MARKER,
                    '    _inherits = {"a": "b"}\n' + pycodegen.END_MARKER,
                )
            )
        self.package_model._current_spec()  # freezes it
        self.assertEqual(self.package_model.source, "frozen")

        with self.assertRaises(UserError) as caught:
            self._draft()
        self.assertIn("x_studio_project", str(caught.exception))

    # -- staging ----------------------------------------------------------

    def test_staging_an_edit_does_not_touch_the_registry(self):
        """The whole reason the buffer exists: no setup_models per keystroke."""
        draft = self._draft()
        before = set(self.env["x_studio_project"]._fields)

        draft.add_field({"name": "x_colour", "ttype": "char", "string": "Colour"})

        self.assertTrue(draft.dirty)
        self.assertEqual(
            set(self.env["x_studio_project"]._fields),
            before,
            "nothing may reach the registry until Apply",
        )
        self.assertIn("x_colour", draft._spec().field_names)

    def test_a_duplicate_field_is_refused(self):
        draft = self._draft()
        with self.assertRaises(UserError):
            draft.add_field({"name": "x_budget", "ttype": "float"})

    def test_updating_a_field_keeps_its_position(self):
        """Field order is class order, which is the order the views show."""
        draft = self._draft()
        before = draft._spec().field_names
        draft.update_field("x_budget", {"string": "Renamed"})
        self.assertEqual(draft._spec().field_names, before)
        self.assertEqual(draft._spec().field("x_budget").string, "Renamed")

    def test_updating_an_unknown_field_is_refused(self):
        draft = self._draft()
        with self.assertRaises(UserError):
            draft.update_field("x_nope", {"string": "x"})

    def test_moving_a_field_reorders_it(self):
        draft = self._draft()
        draft.move_field("x_budget", before="x_name")
        names = draft._spec().field_names
        self.assertLess(names.index("x_budget"), names.index("x_name"))

    def test_model_options_are_limited_to_what_the_builder_owns(self):
        draft = self._draft()
        draft.set_model_options({"order": "x_name"})
        self.assertEqual(draft._spec().order, "x_name")
        with self.assertRaises(UserError):
            draft.set_model_options({"name": "something.else"})

    def test_discard_returns_to_the_file(self):
        draft = self._draft()
        draft.add_field({"name": "x_temp", "ttype": "char"})
        draft.action_discard()
        self.assertFalse(draft.dirty)
        self.assertNotIn("x_temp", draft._spec().field_names)

    # -- the tray ---------------------------------------------------------

    def test_the_tray_describes_each_pending_edit(self):
        draft = self._draft()
        draft.add_field({"name": "x_colour", "ttype": "char", "string": "Colour"})
        draft.update_field("x_budget", {"string": "Spend"})
        draft.remove_field("x_active_flag")

        by_kind = {c["kind"]: c for c in draft.pending_changes()}
        self.assertEqual(by_kind["added"]["name"], "x_colour")
        self.assertIn("Text", by_kind["added"]["detail"], "types read as affordances")
        self.assertEqual(by_kind["changed"]["name"], "x_budget")
        self.assertEqual(by_kind["removed"]["name"], "x_active_flag")

    def test_the_tray_flags_a_removal_that_would_lose_data(self):
        draft = self._draft()
        draft.remove_field("x_budget")
        removed = next(c for c in draft.pending_changes() if c["kind"] == "removed")
        self.assertTrue(removed["destructive"])

    def test_preview_diff_shows_what_apply_would_write(self):
        """Apply should never be a leap of faith."""
        draft = self._draft()
        draft.add_field({"name": "x_colour", "ttype": "char", "string": "Colour"})
        diff = draft.preview_diff()
        self.assertIn("+", diff)
        self.assertIn("x_colour", diff)
        self.assertIn("x_colour", draft.preview_source())

    def test_an_unchanged_draft_previews_an_empty_diff(self):
        self.assertEqual(self._draft().preview_diff(), "")

    # -- validation -------------------------------------------------------

    def test_validate_catches_what_odoo_no_longer_will(self):
        draft = self._draft()
        draft.set_model_options({"order": "not_a_field"})
        self.assertTrue(any("_order" in e for e in draft.validate()))

    def test_apply_refuses_an_invalid_spec_before_writing(self):
        draft = self._draft()
        draft.add_field({"name": "class", "ttype": "char"})
        with self.assertRaises(UserError):
            draft.action_apply()

    def test_apply_refuses_a_destructive_change_unless_asked(self):
        draft = self._draft()
        draft.remove_field("x_budget")
        with self.assertRaises(UserError) as caught:
            draft.action_apply()
        message = str(caught.exception)
        self.assertTrue(
            "x_budget" in message or "destructive" in message.lower(),
            "the refusal has to name what would be lost: %s" % message,
        )

    # -- the picker -------------------------------------------------------

    def test_field_types_offer_affordances_not_orm_types(self):
        draft = self._draft()
        by_value = {t["value"]: t for t in draft.field_types()}
        self.assertEqual(by_value["one2many"]["label"], "Related list")
        self.assertEqual(by_value["char"]["label"], "Text")

    def test_unusable_types_are_shown_disabled_with_a_reason(self):
        """Hiding them teaches nobody anything."""
        draft = self._draft()
        for entry in draft.field_types():
            if entry["value"] in modelspec.UNSUPPORTED_TTYPES:
                self.assertFalse(entry["enabled"])
                self.assertTrue(entry["tooltip"])

    def test_monetary_is_disabled_until_the_model_has_a_currency(self):
        draft = self._draft()
        monetary = next(t for t in draft.field_types() if t["value"] == "monetary")
        self.assertFalse(monetary["enabled"])
        self.assertIn("Currency", monetary["tooltip"])

        draft.add_field(
            {"name": "x_currency_id", "ttype": "many2one", "comodel": "res.currency"}
        )
        monetary = next(t for t in draft.field_types() if t["value"] == "monetary")
        self.assertTrue(monetary["enabled"], "adding a currency field unlocks it")

    # -- access -----------------------------------------------------------

    def test_a_plain_user_cannot_stage_edits(self):
        draft = self._draft()
        outsider = self.env["res.users"].create(
            {
                "name": "Nosy",
                "login": "draft_outsider",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            draft.with_user(outsider).sudo(False).add_field(
                {"name": "x_sneaky", "ttype": "char"}
            )

    # -- serialization ----------------------------------------------------

    def test_the_buffer_round_trips_through_json(self):
        """It is stored as text, so a lossy dump would silently drop edits."""
        draft = self._draft()
        draft.add_field(
            {
                "name": "x_state",
                "ttype": "selection",
                "string": "State",
                "selection": [
                    {"value": "a", "label": "A", "sequence": 10},
                    {"value": "b", "label": "B", "sequence": 20},
                ],
            }
        )
        reloaded = modelspec.spec_from_json(json.loads(draft.spec_json))
        self.assertEqual(reloaded, draft._spec())
        self.assertEqual(len(reloaded.field("x_state").selection), 2)

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The edit buffer the composer sits on.

Everything here is the contract the OWL client will call, so it is worth
pinning before the client exists rather than after: staging an edit must not
touch the registry, the tray must describe what will happen, and Apply must
refuse rather than surprise.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.base.models.ir_model import IrModel

from ..models.studio_model_draft import StudioModelDraft
from ..tools import modelspec, typed
from ..tools import placement as placement_tool
from .common import StudioCase, raises

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime, the same bargain every other
    # converted file's own `TYPE_CHECKING` block makes. `IrModel` and
    # `StudioModelDraft` above are real, runtime imports instead -- both
    # are passed to `typed.model()`, not just named in a cast string.
    from odoo.sql_db import Cursor

    from odoo.addons.base.models.ir_model import IrModelFields

    from ..models.studio_package import StudioPackage
    from ..models.studio_package_model import StudioPackageModel
    from ..tools.modelspec import FieldSpec


@tagged("post_install", "-at_install")
class TestModelDraft(StudioCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_draft_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project"])
        self.package_model = cast(
            "StudioPackageModel", self.package.model_ids
        ).filtered(lambda m: m.model == "x_studio_project")

    def _draft(self):
        return typed.model(self.env, StudioModelDraft).open_for(self.package_model)

    # -- opening ----------------------------------------------------------

    def test_a_draft_starts_clean_and_matches_the_file(self):
        draft = self._draft()
        self.assertFalse(draft.dirty)
        self.assertEqual(draft.change_count, 0)
        self.assertEqual(draft.spec_json, draft.base_spec_json)
        self.assertEqual(draft._spec(), self.package_model._current_spec())

    def test_a_frozen_model_cannot_be_opened(self):
        """Better to say why than to offer an editor that cannot save."""
        path = os.path.join(
            cast("str", self.package.root_path),
            cast("str", self.package_model.python_path),
        )
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

        with raises(self, UserError) as caught:
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
        with raises(self, UserError):
            draft.add_field({"name": "x_budget", "ttype": "float"})

    def test_updating_a_field_keeps_its_position(self):
        """Field order is class order, which is the order the views show."""
        draft = self._draft()
        before = draft._spec().field_names
        draft.update_field("x_budget", {"string": "Renamed"})
        self.assertEqual(draft._spec().field_names, before)
        # `x_budget` is one of `build_demo_content`'s own fixed fields, so
        # `.field()` is never `None` here -- same reasoning as
        # `studio_model_draft.py`'s own `spec_field = cast("FieldSpec",
        # after.field(name))`.
        self.assertEqual(
            cast("FieldSpec", draft._spec().field("x_budget")).string, "Renamed"
        )

    def test_updating_an_unknown_field_is_refused(self):
        draft = self._draft()
        with raises(self, UserError):
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
        with raises(self, UserError):
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
        # `destructive` is `NotRequired`, but `_own_changes()` always sets it
        # on a `"removed"` entry (its own docstring) -- `.get()` reads it
        # without pyright's `reportTypedDictNotRequiredAccess`.
        self.assertTrue(removed.get("destructive"))

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
        with raises(self, UserError):
            draft.action_apply()

    def test_apply_refuses_a_destructive_change_unless_asked(self):
        draft = self._draft()
        draft.remove_field("x_budget")
        with raises(self, UserError) as caught:
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
        # `@api.model_create_multi`'s own stub gap (TYPING.md's "Known
        # traps"): the single-dict form needs the named local + ignore
        # idiom, the same as every other `.create(vals)` in this suite.
        vals: dict[str, object] = {
            "name": "Nosy",
            "login": "draft_outsider",
            "groups_id": [(6, 0, [typed.ref(self.env, "base.group_user").id])],
        }
        outsider = self.env["res.users"].create(vals)  # pyright: ignore[reportArgumentType]
        with raises(self, AccessError):
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
        reloaded = modelspec.spec_from_json(json.loads(cast("str", draft.spec_json)))
        self.assertEqual(reloaded, draft._spec())
        # Just added above, so never `None` -- same reasoning as
        # `test_updating_a_field_keeps_its_position`'s own cast.
        self.assertEqual(len(cast("FieldSpec", reloaded.field("x_state")).selection), 2)


@tagged("post_install", "-at_install")
class TestRelationships(StudioCase):
    """A related list needs a field on the other model pointing back.

    Making the user go and build that first is the gesture every studio gets
    wrong. The interesting part is not the UI but the atomicity: both classes
    have to be written before the single reload, because a one2many whose
    inverse does not exist yet fails registry setup -- and the setup it fails
    is the one that was going to create it.
    """

    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_rel_pkg")
        self.build_demo_content(self.package)
        self._make_sibling()
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project", "x_studio_task"])
        self.project = cast("StudioPackageModel", self.package.model_ids).filtered(
            lambda m: m.model == "x_studio_project"
        )
        self.task = cast("StudioPackageModel", self.package.model_ids).filtered(
            lambda m: m.model == "x_studio_task"
        )

    def _make_sibling(self):
        # `@api.model_create_multi`'s own stub gap: named local first, same
        # idiom as `common.py`'s own `build_demo_content`.
        vals: dict[str, object] = {
            "name": "Studio Demo Task",
            "model": "x_studio_task",
            "field_id": [
                Command.create(
                    {
                        "name": "x_name",
                        "ttype": "char",
                        "field_description": "Name",
                    }
                )
            ],
        }
        model = typed.model(self.env, IrModel).create(vals)  # pyright: ignore[reportArgumentType]
        self.package.studio_capture(
            [
                model,
                cast("IrModelFields", model.field_id).filtered(
                    lambda f: f.state == "manual"
                ),
            ]
        )

    def _draft(self):
        return typed.model(self.env, StudioModelDraft).open_for(self.project)

    # -- what the picker offers -------------------------------------------

    def test_a_sibling_can_have_the_link_made_for_it(self):
        options = self._draft().inverse_options("x_studio_task")
        self.assertTrue(options["can_create"])
        self.assertEqual(options["suggested"], "x_studio_project_id")
        self.assertFalse(options["reason"])

    def test_a_model_we_do_not_own_says_why_not(self):
        options = self._draft().inverse_options("res.partner")
        self.assertFalse(options["can_create"])
        self.assertIn("res.partner", options["reason"])
        self.assertIn(
            "Add a link",
            options["reason"],
            "the message has to say what to do next, not just refuse",
        )

    def test_an_existing_link_back_is_offered(self):
        """Reusing a link that already points back beats making a second one
        that means the same thing."""
        # Staged on the sibling's own draft and applied to its file, because
        # candidates are read from the definition rather than the registry --
        # an adopted model has no class imported yet.
        draft = self._draft()
        companion = draft._companion_for(self.task)
        companion.add_field(
            {
                "name": "x_owner_id",
                "ttype": "many2one",
                "comodel": "x_studio_project",
                "string": "Owner",
            }
        )
        cast("StudioPackage", self.task.package_id)._write_files(
            {
                cast("str", self.task.python_path): companion._rewritten_source(
                    companion._spec()
                )
            }
        )
        options = draft.inverse_options("x_studio_task")
        self.assertEqual(
            [candidate["name"] for candidate in options["candidates"]], ["x_owner_id"]
        )
        self.assertTrue(
            options["can_create"], "making a new one stays available as well"
        )

    # -- staging both sides -----------------------------------------------

    def test_creating_the_inverse_stages_it_on_the_other_model(self):
        draft = self._draft()
        draft.add_field(
            {
                "name": "task_ids",
                "ttype": "one2many",
                "comodel": "x_studio_task",
                "inverse_name": "x_studio_project_id",
                "string": "Tasks",
                "create_inverse": True,
            }
        )
        companion = cast("StudioModelDraft", draft.companion_ids)
        self.assertEqual(len(companion), 1)
        self.assertEqual(companion.model, "x_studio_task")
        # Just staged above as the one2many's inverse, so never `None`.
        inverse = cast("FieldSpec", companion._spec().field("x_studio_project_id"))
        self.assertEqual(inverse.ttype, "many2one")
        self.assertEqual(inverse.comodel, "x_studio_project")
        self.assertEqual(
            inverse.ondelete,
            "cascade",
            "lines outliving their parent would be orphans in every list",
        )

    def test_the_change_count_covers_both_models(self):
        draft = self._draft()
        draft.add_field(
            {
                "name": "task_ids",
                "ttype": "one2many",
                "comodel": "x_studio_task",
                "inverse_name": "x_studio_project_id",
                "string": "Tasks",
                "create_inverse": True,
            }
        )
        draft.invalidate_recordset()
        self.assertEqual(
            draft.change_count,
            2,
            "an Apply button that stayed grey would be lying about the other model",
        )

    def test_the_tray_names_the_other_model(self):
        draft = self._draft()
        draft.add_field(
            {
                "name": "task_ids",
                "ttype": "one2many",
                "comodel": "x_studio_task",
                "inverse_name": "x_studio_project_id",
                "string": "Tasks",
                "create_inverse": True,
            }
        )
        entries = draft.pending_changes()
        companion = [entry for entry in entries if entry.get("model")]
        self.assertEqual(len(companion), 1)
        # `model` is `NotRequired`, but the filter above already proved it
        # is set on this entry -- `.get()` reads it the same way
        # `pending_changes()`'s own splice (`out.append({**change, "model":
        # ...})`) sets it, without `reportTypedDictNotRequiredAccess`.
        self.assertEqual(companion[0].get("model"), "x_studio_task")
        self.assertEqual(companion[0]["name"], "x_studio_project_id")

    def test_the_diff_shows_both_files(self):
        draft = self._draft()
        draft.add_field(
            {
                "name": "task_ids",
                "ttype": "one2many",
                "comodel": "x_studio_task",
                "inverse_name": "x_studio_project_id",
                "string": "Tasks",
                "create_inverse": True,
            }
        )
        diff = draft.preview_diff()
        self.assertIn("x_studio_project (after)", diff)
        self.assertIn("x_studio_task (after)", diff)
        self.assertIn("x_studio_project_id", diff)

    def test_discarding_drops_the_companion(self):
        draft = self._draft()
        draft.add_field(
            {
                "name": "task_ids",
                "ttype": "one2many",
                "comodel": "x_studio_task",
                "inverse_name": "x_studio_project_id",
                "string": "Tasks",
                "create_inverse": True,
            }
        )
        draft.action_discard()
        self.assertFalse(draft.companion_ids)
        draft.invalidate_recordset()
        self.assertEqual(draft.change_count, 0)

    def test_reusing_a_clean_draft_sheds_its_stale_companions(self):
        """After an Apply both drafts are rebased, so the draft is clean and
        the companion is still attached -- holding the other model as it was
        then. The console reuses a clean draft by name, and an Apply on it
        would write every companion's file from that old spec, taking with
        it anything applied to the other model since. Reuse has to drop them
        the way discard does."""
        Draft = typed.model(self.env, StudioModelDraft)
        draft = Draft.browse(Draft.open_for_model("x_studio_project")["id"])
        draft.add_field(
            {
                "name": "task_ids",
                "ttype": "one2many",
                "comodel": "x_studio_task",
                "inverse_name": "x_studio_project_id",
                "string": "Tasks",
                "create_inverse": True,
            }
        )
        companion = cast("StudioModelDraft", draft.companion_ids)
        self.assertEqual(companion.model, "x_studio_task", "sanity: staged")
        # Rebased the way action_apply does at the end -- without calling it,
        # since it reloads the registry.
        for staged in draft | companion:
            staged.base_spec_json = staged.spec_json
        draft.invalidate_recordset()
        self.assertFalse(draft.dirty, "sanity: clean, companion attached")

        # The task model moves on through a draft of its own, and its file
        # with it: this is what the stale companion would have overwritten.
        other = Draft.open_for(self.task)
        other.add_field({"name": "x_colour", "ttype": "char", "string": "Colour"})
        cast("StudioPackage", self.task.package_id)._write_files(
            {cast("str", self.task.python_path): other._rewritten_source(other._spec())}
        )
        other.base_spec_json = other.spec_json

        again = Draft.open_for_model("x_studio_project")
        self.assertEqual(again["id"], draft.id, "sanity: reused")
        self.assertFalse(draft.companion_ids)
        self.assertFalse(companion.exists())
        self.assertFalse(
            [entry for entry in again["pending"] if entry.get("model")],
            "nothing about x_studio_task may still be pending",
        )
        self.assertEqual(draft.placement_json, "{}")
        self.assertTrue(
            draft._companion_for(self.task)._spec().field("x_colour"),
            "a companion made now reads the task model as it is on disk",
        )

    def test_an_inverse_on_a_model_we_do_not_own_is_refused(self):
        draft = self._draft()
        with raises(self, UserError) as caught:
            draft.add_field(
                {
                    "name": "partner_ids",
                    "ttype": "one2many",
                    "comodel": "res.partner",
                    "inverse_name": "x_studio_project_id",
                    "string": "Partners",
                    "create_inverse": True,
                }
            )
        self.assertIn("res.partner", str(caught.exception))

    def test_a_companion_error_blocks_this_apply(self):
        """The companion applies in the same transaction, so its problem is
        this Apply's problem -- finding it afterwards means finding it during
        a rollback."""
        draft = self._draft()
        companion = draft._companion_for(self.task)
        companion.add_field({"name": "id", "ttype": "char", "string": "Broken"})
        errors = draft.validate()
        self.assertTrue(errors)
        self.assertTrue(
            any(error.startswith("x_studio_task: ") for error in errors),
            "an error has to say which model it is about: %s" % errors,
        )


@tagged("post_install", "-at_install")
class TestConsoleHooks(StudioCase):
    """What the drag-and-drop console leans on the draft for.

    The console drops a field at a spot in a view before the column exists,
    and needs three promises from the buffer: that it is still there when the
    user comes back, that one model has one draft per user rather than one
    per drop, and that the remembered spot is honoured on Apply -- through a
    hook this addon only declares, since routing an insertion through the
    view editor is ``app_builder_view``'s business.
    """

    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_hook_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project"])
        self.package_model = cast(
            "StudioPackageModel", self.package.model_ids
        ).filtered(lambda m: m.model == "x_studio_project")

    def _draft(self):
        return typed.model(self.env, StudioModelDraft).open_for(self.package_model)

    def _age(self, draft, days):
        """Make a draft look idle for ``days``, the way the vacuum sees it."""
        self.env.flush_all()
        # `Environment.cr` is declared `BaseCursor`, which has no
        # `.execute()` of its own -- only the real `Cursor` subclass every
        # live request actually gets (TYPING.md's own "Known traps"), same
        # cast `studio_package.py`'s own `cr = cast("Cursor", self.env.cr)`
        # already uses.
        cast("Cursor", self.env.cr).execute(
            "UPDATE studio_model_draft SET write_date = "
            "(now() AT TIME ZONE 'UTC') - interval '%s days' WHERE id = %s",
            (days, draft.id),
        )
        draft.invalidate_recordset()

    def _added(self, draft, name):
        """A spec/diff pair claiming ``name`` was just added.

        Built from a field the registry already has, so the arch the fallback
        writes still validates without an Apply in the middle of the test.
        """
        spec = draft._spec()
        return spec, modelspec.diff_specs(modelspec.without_field(spec, name), spec)

    # -- lifetime ---------------------------------------------------------

    def test_a_draft_survives_a_working_week_of_idleness(self):
        """The server default is an hour, and the daily vacuum would take a
        draft left open over lunch -- with the pending drops in it."""
        Draft = typed.model(self.env, StudioModelDraft)
        self.assertEqual(Draft._transient_max_hours, 168)
        kept, gone = self._draft(), self._draft()
        self._age(kept, 2)
        self._age(gone, 10)
        Draft._transient_vacuum()
        self.assertTrue(kept.exists(), "two idle days are not abandonment")
        self.assertFalse(gone.exists(), "ten are")

    # -- one draft per user and model ------------------------------------

    def test_open_for_model_reuses_this_users_draft(self):
        Draft = typed.model(self.env, StudioModelDraft)
        first = Draft.open_for_model("x_studio_project")
        second = Draft.open_for_model("x_studio_project")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["model"], "x_studio_project")
        other = Draft.with_user(self.env.ref("base.user_admin"))
        self.assertNotEqual(
            other.open_for_model("x_studio_project")["id"],
            first["id"],
            "another builder's tray is their own",
        )

    def test_open_for_model_keeps_pending_edits(self):
        """Finding the draft again is the whole point: the drop staged a
        minute ago has to still be in it."""
        Draft = typed.model(self.env, StudioModelDraft)
        draft = Draft.browse(Draft.open_for_model("x_studio_project")["id"])
        draft.add_field({"name": "x_colour", "ttype": "char", "string": "Colour"})
        again = Draft.open_for_model("x_studio_project")
        self.assertEqual(again["id"], draft.id)
        self.assertIn("x_colour", [f["name"] for f in again["fields"]])

    def test_open_for_model_refreshes_a_clean_draft_from_disk(self):
        """A clean draft has nothing to lose and a baseline that may predate
        an Apply; staging on the stale one would write the old block back."""
        Draft = typed.model(self.env, StudioModelDraft)
        draft = Draft.browse(Draft.open_for_model("x_studio_project")["id"])
        stale = json.loads(cast("str", draft.base_spec_json))
        stale["description"] = "Stale"
        draft.write(
            {
                "base_spec_json": json.dumps(stale, sort_keys=True),
                "spec_json": json.dumps(stale, sort_keys=True),
            }
        )
        again = Draft.open_for_model("x_studio_project")
        self.assertEqual(again["id"], draft.id)
        self.assertNotEqual(again["spec"]["description"], "Stale")

    def test_open_for_model_refuses_a_model_no_package_defines(self):
        """The live x_ path is the right door for those, and a draft that
        could never be applied would only hide that."""
        with raises(self, UserError) as caught:
            typed.model(self.env, StudioModelDraft).open_for_model("res.partner")
        self.assertIn("res.partner", str(caught.exception))

    # -- the anchored placement hook -------------------------------------

    def test_load_reports_no_anchors_in_base(self):
        self.assertEqual(self._draft().load()["anchors"], {})

    def test_an_anchor_is_offered_to_the_hook_first(self):
        """When the hook takes it, the balanced placement stays out of it --
        the arch is the hook's to write."""
        draft = self._draft()
        form = draft._owned_views()["form"]
        anchor = {"view_id": form.id, "position": "after"}
        before = form.arch
        Draft = type(draft)
        with (
            patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}),
            patch.object(
                Draft, "_place_anchored", autospec=True, return_value=True
            ) as hook,
            patch.object(placement_tool, "place_in_form") as balanced,
        ):
            self.assertTrue(draft._place_in_views(*self._added(draft, "x_active_flag")))
        hook.assert_called_once_with(draft, form, "x_active_flag", anchor, "")
        balanced.assert_not_called()
        self.assertEqual(form.arch, before)

    def test_a_declined_anchor_falls_back_to_balanced_placement(self):
        """``False`` is not a failure: the field still lands, just not at the
        remembered spot -- which is exactly what this addon alone can do."""
        draft = self._draft()
        form = draft._owned_views()["form"]
        anchor = {"view_id": form.id, "position": "after"}
        Draft = type(draft)
        with (
            patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}),
            patch.object(
                Draft, "_place_anchored", autospec=True, return_value=False
            ) as hook,
        ):
            self.assertTrue(draft._place_in_views(*self._added(draft, "x_active_flag")))
        hook.assert_called_once_with(draft, form, "x_active_flag", anchor, "")
        self.assertIn('<field name="x_active_flag"/>', cast("str", form.arch))

    def test_an_anchor_for_another_view_is_not_offered(self):
        """Anchors are per view; the hook is only asked about its own."""
        draft = self._draft()
        form = draft._owned_views()["form"]
        anchor = {"view_id": cast("int", form.id) + 1000, "position": "after"}
        Draft = type(draft)
        with (
            patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}),
            patch.object(
                Draft, "_place_anchored", autospec=True, return_value=True
            ) as hook,
        ):
            draft._place_in_views(*self._added(draft, "x_active_flag"))
        hook.assert_not_called()
        self.assertIn('<field name="x_active_flag"/>', cast("str", form.arch))

    def test_placement_is_idempotent(self):
        """Under a restart reload the request can die mid-apply and the
        console runs placement again; a field the arch already names must
        not be rendered twice, anchored or not."""
        draft = self._draft()
        form = draft._owned_views()["form"]
        Draft = type(draft)
        draft._place_in_views(*self._added(draft, "x_active_flag"))
        anchor = {"view_id": form.id, "position": "after"}
        with (
            patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}),
            patch.object(
                Draft, "_place_anchored", autospec=True, return_value=True
            ) as hook,
        ):
            self.assertFalse(
                draft._place_in_views(*self._added(draft, "x_active_flag"))
            )
        hook.assert_not_called()
        self.assertEqual(cast("str", form.arch).count('name="x_active_flag"'), 1)

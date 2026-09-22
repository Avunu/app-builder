# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Automations as a record pane: the surface the console's cards come from.

An automation is one thing to the person and two models to Odoo. These
tests pin the seam: what the catalogue offers is what the serializer
writes, a template makes a rule that runs and lands in the file, the
steps keep their order, and the guard rails (a delay with nothing to
count from, a condition that cannot search, a rule from another module)
say no before the file is written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base_automation.models.base_automation import BaseAutomation
from odoo.addons.app_builder_base.tests.common import StudioCase, raises
from odoo.addons.app_builder_base.tools import typed

from ..models.studio_automation_surface import StudioAutomation, StudioAutomationStep

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_actions import IrActionsServer
    from odoo.addons.app_builder_base.models.studio_owned_mixin import StudioOwnedMixin
    from odoo.addons.app_builder_base.models.studio_record_surface import (
        RecordActionJSON,
        RecordRowJSON,
        StudioRecordSurface,
    )

    from ..models.studio_automation_surface import TriggerRowJSON

MODEL = "x_studio_project"


@tagged("post_install", "-at_install")
class TestAutomationSurface(StudioCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        self.Surface = typed.model(self.env, StudioAutomation)
        self.Step = typed.model(self.env, StudioAutomationStep)

    def _package(self):
        package = self.make_package()
        self.build_demo_content(package)
        return package

    def _file(self, package):
        return package._render_files().get("data/%s_automation.xml" % MODEL, "")

    # -- catalogue -----------------------------------------------------------

    def test_every_trigger_is_offered_and_grouped(self):
        """The Trigger row reads the live selection, so a trigger Odoo adds
        shows up; and each one has a group in the picker, so none is lost
        at the bottom of an ungrouped list."""
        catalogue = cast("StudioRecordSurface", self.Surface).catalogue(MODEL)
        # `_section_json` (`studio_automation_surface.py`) sends the
        # "trigger" row as a `TriggerRowJSON` (`groups`/`advanced_only`
        # besides the base `RowJSON` keys) at runtime, but `catalogue()`'s
        # own declared return only promises the base shape for every row.
        trigger = cast(
            "TriggerRowJSON",
            next(
                row
                for section in catalogue["sections"]
                for row in section["rows"]
                if row["name"] == "trigger"
            ),
        )
        live = (
            self.env["base.automation"]
            ._fields["trigger"]
            .get_description(self.env)["selection"]
        )
        self.assertEqual([c[0] for c in trigger["choices"]], [c[0] for c in live])
        self.assertEqual(set(trigger["groups"]), {c[0] for c in live})
        self.assertIn("on_stage_set", trigger["advanced_only"])

    def test_the_mail_rows_follow_the_fields(self):
        """The Send Email section is declared once and dropped when the
        database has no ``template_id`` on server actions."""
        sections = {
            s["id"]
            for s in cast("StudioRecordSurface", self.Step).catalogue(MODEL)["sections"]
        }
        has_mail = "template_id" in self.env["ir.actions.server"]._fields
        self.assertEqual("mail" in sections, has_mail)
        self.assertEqual("activity" in sections, has_mail)

    def test_webhook_templates_are_only_on_the_webhooks_pane(self):
        keys = {t["key"] for t in self.Surface.templates(MODEL)}
        self.assertIn("run_code", keys)
        self.assertIn("webhook_in", keys)
        for template in self.Surface.templates(MODEL):
            # `values` is a plain `dict[str, object]` (`RecordTemplateJSON`);
            # its `steps` entry is only ever a list of step vals at runtime.
            for step in cast(
                "list[dict[str, object]]", template["values"].get("steps", [])
            ):
                self.assertIn(
                    step["state"],
                    dict(
                        self.env["ir.actions.server"]
                        ._fields["state"]
                        .get_description(self.env)["selection"]
                    ),
                )

    # -- rows ----------------------------------------------------------------

    def test_rows_are_the_models_rules_split_by_webhook(self):
        package = self._package()
        model = typed.model(self.env, IrModel)._get(MODEL)
        other = typed.model(self.env, IrModel)._get("res.users")
        Automation = self.env["base.automation"].with_context(
            studio_package_id=package.id
        )
        # `@api.model_create_multi`'s own stub gap (TYPING.md's "Known
        # traps"): every single-dict `.create(vals)` below needs the local
        # `vals` variable so the `# pyright: ignore` lands on the call's own
        # line, not somewhere inside a multi-line dict literal.
        rule_vals: dict[str, object] = {
            "name": "Rule A",
            "model_id": model.id,
            "trigger": "on_create",
        }
        rule = Automation.create(rule_vals)  # pyright: ignore[reportArgumentType]
        hook_vals: dict[str, object] = {
            "name": "Hook A",
            "model_id": model.id,
            "trigger": "on_webhook",
        }
        hook = Automation.create(hook_vals)  # pyright: ignore[reportArgumentType]
        other_vals: dict[str, object] = {
            "name": "Other",
            "model_id": other.id,
            "trigger": "on_create",
        }
        Automation.create(other_vals)  # pyright: ignore[reportArgumentType]
        rows = cast("StudioRecordSurface", self.Surface).rows(
            MODEL, cast("int", package.id)
        )
        self.assertEqual([r["id"] for r in rows], [rule.id])
        self.assertTrue(rows[0]["owned"])
        self.assertTrue(rows[0]["editable"])
        hooks = cast("StudioRecordSurface", self.Surface).rows(
            MODEL, cast("int", package.id), webhooks=True
        )
        self.assertEqual([r["id"] for r in hooks], [hook.id])
        self.assertIn("webhook", [b["key"] for b in hooks[0]["badges"]])

    def test_the_sentence_says_the_whole_rule(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL,
            cast("int", package.id),
            {"name": "Set it", "filter_domain": "[('x_name', '!=', False)]"},
            template="set_field",
        )
        self.assertIn("only when", row["sentence"])
        self.assertIn("Update", row["sentence"])

    # -- create --------------------------------------------------------------

    def test_a_template_makes_a_live_rule_with_its_steps_in_the_file(self):
        """A template is a rule and its steps, owned by the package and
        already in ``data/<model>_automation.xml`` -- steps included."""
        package = self._package()
        row = self.Surface.create_record(
            MODEL, cast("int", package.id), {"name": "On save"}, template="run_code"
        )
        rule = typed.model(self.env, BaseAutomation).browse(row["id"])
        self.assertEqual(rule.trigger, "on_create_or_write")
        self.assertEqual(
            cast("IrActionsServer", rule.action_server_ids).mapped("state"), ["code"]
        )
        self.assertEqual(
            cast("IrActionsServer", rule.action_server_ids).usage, "base_automation"
        )
        self.assertEqual(cast("StudioOwnedMixin", rule).studio_package_id, package)
        self.assertEqual(
            cast("StudioOwnedMixin", rule.action_server_ids).studio_package_id,
            package,
        )
        rendered = self._file(package)
        self.assertIn("On save", rendered)
        self.assertIn('name="code"', rendered)
        self.assertIn("action_server_ids", rendered)

    def test_step_values_ride_along_on_create(self):
        """``steps.0.webhook_url`` from the inline New form lands on the
        template's first step, not on the rule."""
        package = self._package()
        row = self.Surface.create_record(
            MODEL,
            cast("int", package.id),
            {"name": "Tell them", "steps.0.webhook_url": "https://example.com/x"},
            template="webhook_out",
        )
        rule = typed.model(self.env, BaseAutomation).browse(row["id"])
        step = cast("IrActionsServer", rule.action_server_ids)
        self.assertEqual(step.state, "webhook")
        self.assertEqual(step.webhook_url, "https://example.com/x")
        self.assertIn("https://example.com/x", self._file(package))

    def test_a_delay_needs_a_date_to_count_from(self):
        package = self._package()
        with raises(self, UserError):
            self.Surface.create_record(
                MODEL,
                cast("int", package.id),
                {"name": "Later", "trigger": "on_time", "trg_date_range": 2},
                template="blank",
            )

    def test_a_condition_that_cannot_search_is_refused(self):
        package = self._package()
        with raises(self, UserError):
            self.Surface.create_record(
                MODEL,
                cast("int", package.id),
                {"name": "Bad", "filter_domain": "[('x_no_such', '=', 1)]"},
                template="blank",
            )

    def test_an_unknown_template_is_refused(self):
        package = self._package()
        with raises(self, UserError):
            self.Surface.create_record(
                MODEL, cast("int", package.id), {"name": "x"}, "nope"
            )

    # -- describe and write --------------------------------------------------

    def test_describe_carries_the_steps_and_the_match_count(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, cast("int", package.id), {"name": "Set it"}, template="set_field"
        )
        described = cast("StudioRecordSurface", self.Surface).describe(
            row["id"], cast("int", package.id)
        )
        # `describe()`'s own declared return is `dict[str, object]` -- every
        # real subclass override widens it with keys of its own no base
        # TypedDict enumerates (`studio_record_surface.py`'s own comment on
        # `describe`), so each further key read here is its own cast at the
        # real read site, the same way `test_report_surface.py` already
        # reads a nested `described["values"]`.
        self.assertEqual(
            cast("dict[str, object]", described["values"])["trigger"],
            "on_create_or_write",
        )
        steps = cast("dict[str, object]", described["children"])
        self.assertEqual(steps["surface"], "studio.automation.step")
        items = cast("list[dict[str, object]]", steps["items"])
        self.assertEqual(len(items), 1)
        self.assertEqual(
            cast("dict[str, object]", items[0]["values"])["state"], "object_write"
        )
        self.assertIn(["code", "Execute Code"], cast("list[list[str]]", steps["kinds"]))
        self.assertIn("count", cast("dict[str, object]", described["matches"]))
        self.assertEqual(
            cast(
                "dict[str, object]",
                cast("dict[str, object]", described["advanced"])["context"],
            )["studio_package_id"],
            package.id,
        )

    def test_a_write_reaches_the_file(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, cast("int", package.id), {"name": "Set it"}, template="set_field"
        )
        cast("StudioRecordSurface", self.Surface).write_record(
            row["id"],
            {"filter_domain": "[('x_name', '=', 'a')]"},
            cast("int", package.id),
        )
        self.assertIn("x_name", self._file(package))
        with raises(self, UserError):
            cast("StudioRecordSurface", self.Surface).write_record(
                row["id"],
                {"trigger": "on_time", "trg_date_id": False},
                cast("int", package.id),
            )

    def test_a_rule_of_another_module_is_shown_and_not_edited(self):
        """A foreign rule is a row with the honest reason, refused on write,
        and offered as a switched-off copy."""
        package = self._package()
        model = typed.model(self.env, IrModel)._get(MODEL)
        theirs_vals: dict[str, object] = {
            "name": "Theirs",
            "model_id": model.id,
            "trigger": "on_create",
        }
        theirs = typed.model(self.env, BaseAutomation).create(theirs_vals)  # pyright: ignore[reportArgumentType]
        data_vals: dict[str, object] = {
            "module": "some_module",
            "name": "theirs",
            "model": "base.automation",
            "res_id": theirs.id,
        }
        self.env["ir.model.data"].create(data_vals)  # pyright: ignore[reportArgumentType]
        row = next(
            r
            for r in cast("StudioRecordSurface", self.Surface).rows(
                MODEL, cast("int", package.id)
            )
            if r["id"] == theirs.id
        )
        self.assertFalse(row["editable"])
        self.assertIn("some_module", row["reason"])
        with raises(self, UserError):
            cast("StudioRecordSurface", self.Surface).write_record(
                cast("int", theirs.id), {"name": "Mine"}, cast("int", package.id)
            )
        copy = cast("StudioRecordSurface", self.Surface).duplicate_record(
            cast("int", theirs.id), cast("int", package.id)
        )
        copied = typed.model(self.env, BaseAutomation).browse(copy["id"])
        self.assertFalse(copied.active)
        self.assertEqual(cast("StudioOwnedMixin", copied).studio_package_id, package)
        self.assertTrue(theirs.active)

    def test_rotating_the_secret_never_touches_the_file(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, cast("int", package.id), {"name": "Hook"}, template="webhook_in"
        )
        rule = typed.model(self.env, BaseAutomation).browse(row["id"])
        before_url, before_file = rule.url, self._file(package)
        cast("StudioRecordSurface", self.Surface).run(
            row["id"], "rotate_secret", cast("int", package.id)
        )
        self.assertNotEqual(rule.url, before_url)
        self.assertEqual(self._file(package), before_file)
        self.assertNotIn(rule.webhook_uuid, before_file)

    def test_remove_takes_the_rule_and_its_steps_out_of_source(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL,
            cast("int", package.id),
            {"name": "Gone soon"},
            template="run_code",
        )
        step_ids = cast(
            "IrActionsServer",
            typed.model(self.env, BaseAutomation).browse(row["id"]).action_server_ids,
        ).ids
        cast("StudioRecordSurface", self.Surface).remove_record(
            row["id"], cast("int", package.id), force=True
        )
        self.assertFalse(self.env["ir.actions.server"].browse(step_ids).exists())
        self.assertNotIn("Gone soon", "".join(package._render_files().values()))

    # -- steps ---------------------------------------------------------------

    def test_steps_are_added_and_kept_in_order(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL,
            cast("int", package.id),
            {"name": "Two things"},
            template="run_code",
        )
        added = self.Step.add_step(
            row["id"],
            cast("int", package.id),
            {"state": "webhook", "webhook_url": "https://x"},
        )
        rule = typed.model(self.env, BaseAutomation).browse(row["id"])
        self.assertEqual(
            cast("IrActionsServer", rule.action_server_ids).mapped("state"),
            ["code", "webhook"],
        )
        steps = self.Step.rows(MODEL, cast("int", package.id), automation_id=row["id"])
        self.assertEqual(
            [s["id"] for s in steps],
            cast("IrActionsServer", rule.action_server_ids).ids,
        )
        self.Step.move_step(
            cast("RecordRowJSON", added["row"])["id"],
            cast("int", cast("IrActionsServer", rule.action_server_ids)[0].id),
            cast("int", package.id),
        )
        rule.invalidate_recordset()
        self.assertEqual(
            cast("IrActionsServer", rule.action_server_ids)
            .sorted("sequence")
            .mapped("state"),
            ["webhook", "code"],
        )
        self.assertEqual(
            cast("IrActionsServer", rule.action_server_ids)
            .sorted("sequence")
            .mapped("sequence"),
            [10, 20],
        )

    def test_a_step_of_every_kind_round_trips(self):
        """The surfaces are the first thing in the studio that writes an
        update, a webhook, an email and an activity step: each must come
        back from the file it was written to with its configuration.

        On ``res.partner``: the mail steps refuse a model without a chatter.
        """
        package = self._package()
        model = "res.partner"
        row = self.Surface.create_record(
            model, cast("int", package.id), {"name": "Kinds"}, template="blank"
        )
        self.Step.add_step(
            row["id"],
            cast("int", package.id),
            {
                "state": "object_write",
                "update_path": "ref",
                "evaluation_type": "value",
                "value": "renamed",
            },
        )
        self.Step.add_step(
            row["id"],
            cast("int", package.id),
            {"state": "webhook", "webhook_url": "https://example.com/hook"},
        )
        Server = self.env["ir.actions.server"]
        has_mail = "template_id" in Server._fields
        if has_mail:
            template_vals: dict[str, object] = {
                "name": "T",
                "model_id": typed.model(self.env, IrModel)._get(model).id,
            }
            template = self.env["mail.template"].create(template_vals)  # pyright: ignore[reportArgumentType]
            # A template only this database has cannot be pointed at from a
            # file; the step says so before anything is written.
            with raises(self, UserError):
                self.Step.add_step(
                    row["id"],
                    cast("int", package.id),
                    {"state": "mail_post", "template_id": template.id},
                )
            data_vals: dict[str, object] = {
                "module": "some_module",
                "name": "template_t",
                "model": "mail.template",
                "res_id": template.id,
            }
            self.env["ir.model.data"].create(data_vals)  # pyright: ignore[reportArgumentType]
            self.Step.add_step(
                row["id"],
                cast("int", package.id),
                {"state": "mail_post", "template_id": template.id},
            )
            self.Step.add_step(
                row["id"],
                cast("int", package.id),
                {
                    "state": "next_activity",
                    "activity_type_id": typed.ref(
                        self.env, "mail.mail_activity_data_todo"
                    ).id,
                    "activity_summary": "Look",
                    "activity_date_deadline_range": 3,
                    "activity_date_deadline_range_type": "days",
                    "activity_user_type": "specific",
                    "activity_user_id": self.env.user.id,
                },
            )
        rule = typed.model(self.env, BaseAutomation).browse(row["id"])
        states = (
            cast("IrActionsServer", rule.action_server_ids)
            .sorted("sequence")
            .mapped("state")
        )
        files = package._render_files()
        rendered = files["data/res_partner_automation.xml"]
        self.assertIn("renamed", rendered)
        self.assertIn("https://example.com/hook", rendered)
        if has_mail:
            self.assertIn("mail_post", rendered)
            self.assertIn("Look", rendered)
        rule_xmlid = rule.get_external_id()[rule.id]
        cast("IrActionsServer", rule.action_server_ids).unlink()
        rule.unlink()
        self.load_rendered(package, files)
        reloaded = cast("BaseAutomation", typed.ref(self.env, rule_xmlid))
        self.assertEqual(
            cast("IrActionsServer", reloaded.action_server_ids)
            .sorted("sequence")
            .mapped("state"),
            states,
        )
        by_state = {
            s.state: s for s in cast("IrActionsServer", reloaded.action_server_ids)
        }
        self.assertEqual(by_state["object_write"].update_path, "ref")
        self.assertEqual(by_state["object_write"].value, "renamed")
        self.assertEqual(by_state["webhook"].webhook_url, "https://example.com/hook")
        if has_mail:
            # `template_id`/`activity_summary`/`activity_user_id` are added
            # by the `mail` addon's own extension of `ir.actions.server`,
            # not by the base `IrActionsServer` this method otherwise casts
            # to -- the same `cast("Any", ...)` fix `_step_label`
            # (`studio_automation_surface.py`) already uses for the
            # identical shape.
            self.assertEqual(cast("Any", by_state["mail_post"]).template_id.name, "T")
            self.assertEqual(
                cast("Any", by_state["next_activity"]).activity_summary, "Look"
            )
            self.assertEqual(
                cast("Any", by_state["next_activity"]).activity_user_id,
                self.env.user,
            )

    def test_graduate_is_offered_on_code_steps_only(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, cast("int", package.id), {"name": "Code"}, template="set_field"
        )
        rule = typed.model(self.env, BaseAutomation).browse(row["id"])
        described = cast("StudioRecordSurface", self.Step).describe(
            cast("int", cast("IrActionsServer", rule.action_server_ids).id),
            cast("int", package.id),
        )
        self.assertNotIn(
            "graduate",
            [a["key"] for a in cast("list[RecordActionJSON]", described["actions"])],
        )
        code = self.Step.add_step(row["id"], cast("int", package.id), {"state": "code"})
        self.assertIn(
            "graduate",
            [a["key"] for a in cast("list[RecordActionJSON]", code["actions"])],
        )

    def test_reads_need_a_studio_user_and_writes_a_manager(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, cast("int", package.id), {"name": "Guarded"}, template="run_code"
        )
        builder = self.make_user("builder", ["app_builder_base.group_studio_user"])
        self.assertTrue(
            cast("StudioRecordSurface", self.Surface.with_user(builder)).rows(
                MODEL, cast("int", package.id)
            )
        )
        with raises(self, AccessError):
            cast("StudioRecordSurface", self.Surface.with_user(builder)).write_record(
                row["id"], {"name": "Renamed"}, cast("int", package.id)
            )
        nobody = self.make_user("nobody", ["base.group_user"])
        with raises(self, AccessError):
            cast("StudioRecordSurface", self.Surface.with_user(nobody)).rows(
                MODEL, cast("int", package.id)
            )

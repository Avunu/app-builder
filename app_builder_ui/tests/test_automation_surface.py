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

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

MODEL = "x_studio_project"


@tagged("post_install", "-at_install")
class TestAutomationSurface(StudioCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.env["base.automation"]._unregister_hook)
        self.Surface = self.env["studio.automation"]
        self.Step = self.env["studio.automation.step"]

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
        catalogue = self.Surface.catalogue(MODEL)
        trigger = next(
            row
            for section in catalogue["sections"]
            for row in section["rows"]
            if row["name"] == "trigger"
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
        sections = {s["id"] for s in self.Step.catalogue(MODEL)["sections"]}
        has_mail = "template_id" in self.env["ir.actions.server"]._fields
        self.assertEqual("mail" in sections, has_mail)
        self.assertEqual("activity" in sections, has_mail)

    def test_webhook_templates_are_only_on_the_webhooks_pane(self):
        keys = {t["key"] for t in self.Surface.templates(MODEL)}
        self.assertIn("run_code", keys)
        self.assertIn("webhook_in", keys)
        for template in self.Surface.templates(MODEL):
            for step in template["values"].get("steps", []):
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
        model = self.env["ir.model"]._get(MODEL)
        other = self.env["ir.model"]._get("res.users")
        Automation = self.env["base.automation"].with_context(
            studio_package_id=package.id
        )
        rule = Automation.create(
            {"name": "Rule A", "model_id": model.id, "trigger": "on_create"}
        )
        hook = Automation.create(
            {"name": "Hook A", "model_id": model.id, "trigger": "on_webhook"}
        )
        Automation.create(
            {"name": "Other", "model_id": other.id, "trigger": "on_create"}
        )
        rows = self.Surface.rows(MODEL, package.id)
        self.assertEqual([r["id"] for r in rows], [rule.id])
        self.assertTrue(rows[0]["owned"])
        self.assertTrue(rows[0]["editable"])
        hooks = self.Surface.rows(MODEL, package.id, webhooks=True)
        self.assertEqual([r["id"] for r in hooks], [hook.id])
        self.assertIn("webhook", [b["key"] for b in hooks[0]["badges"]])

    def test_the_sentence_says_the_whole_rule(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL,
            package.id,
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
            MODEL, package.id, {"name": "On save"}, template="run_code"
        )
        rule = self.env["base.automation"].browse(row["id"])
        self.assertEqual(rule.trigger, "on_create_or_write")
        self.assertEqual(rule.action_server_ids.mapped("state"), ["code"])
        self.assertEqual(rule.action_server_ids.usage, "base_automation")
        self.assertEqual(rule.studio_package_id, package)
        self.assertEqual(rule.action_server_ids.studio_package_id, package)
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
            package.id,
            {"name": "Tell them", "steps.0.webhook_url": "https://example.com/x"},
            template="webhook_out",
        )
        rule = self.env["base.automation"].browse(row["id"])
        step = rule.action_server_ids
        self.assertEqual(step.state, "webhook")
        self.assertEqual(step.webhook_url, "https://example.com/x")
        self.assertIn("https://example.com/x", self._file(package))

    def test_a_delay_needs_a_date_to_count_from(self):
        package = self._package()
        with self.assertRaises(UserError):
            self.Surface.create_record(
                MODEL,
                package.id,
                {"name": "Later", "trigger": "on_time", "trg_date_range": 2},
                template="blank",
            )

    def test_a_condition_that_cannot_search_is_refused(self):
        package = self._package()
        with self.assertRaises(UserError):
            self.Surface.create_record(
                MODEL,
                package.id,
                {"name": "Bad", "filter_domain": "[('x_no_such', '=', 1)]"},
                template="blank",
            )

    def test_an_unknown_template_is_refused(self):
        package = self._package()
        with self.assertRaises(UserError):
            self.Surface.create_record(MODEL, package.id, {"name": "x"}, "nope")

    # -- describe and write --------------------------------------------------

    def test_describe_carries_the_steps_and_the_match_count(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Set it"}, template="set_field"
        )
        described = self.Surface.describe(row["id"], package.id)
        self.assertEqual(described["values"]["trigger"], "on_create_or_write")
        steps = described["children"]
        self.assertEqual(steps["surface"], "studio.automation.step")
        self.assertEqual(len(steps["items"]), 1)
        self.assertEqual(steps["items"][0]["values"]["state"], "object_write")
        self.assertIn(["code", "Execute Code"], steps["kinds"])
        self.assertIn("count", described["matches"])
        self.assertEqual(
            described["advanced"]["context"]["studio_package_id"], package.id
        )

    def test_a_write_reaches_the_file(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Set it"}, template="set_field"
        )
        self.Surface.write_record(
            row["id"], {"filter_domain": "[('x_name', '=', 'a')]"}, package.id
        )
        self.assertIn("x_name", self._file(package))
        with self.assertRaises(UserError):
            self.Surface.write_record(
                row["id"], {"trigger": "on_time", "trg_date_id": False}, package.id
            )

    def test_a_rule_of_another_module_is_shown_and_not_edited(self):
        """A foreign rule is a row with the honest reason, refused on write,
        and offered as a switched-off copy."""
        package = self._package()
        model = self.env["ir.model"]._get(MODEL)
        theirs = self.env["base.automation"].create(
            {"name": "Theirs", "model_id": model.id, "trigger": "on_create"}
        )
        self.env["ir.model.data"].create(
            {
                "module": "some_module",
                "name": "theirs",
                "model": "base.automation",
                "res_id": theirs.id,
            }
        )
        row = next(
            r for r in self.Surface.rows(MODEL, package.id) if r["id"] == theirs.id
        )
        self.assertFalse(row["editable"])
        self.assertIn("some_module", row["reason"])
        with self.assertRaises(UserError):
            self.Surface.write_record(theirs.id, {"name": "Mine"}, package.id)
        copy = self.Surface.duplicate_record(theirs.id, package.id)
        copied = self.env["base.automation"].browse(copy["id"])
        self.assertFalse(copied.active)
        self.assertEqual(copied.studio_package_id, package)
        self.assertTrue(theirs.active)

    def test_rotating_the_secret_never_touches_the_file(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Hook"}, template="webhook_in"
        )
        rule = self.env["base.automation"].browse(row["id"])
        before_url, before_file = rule.url, self._file(package)
        self.Surface.run(row["id"], "rotate_secret", package.id)
        self.assertNotEqual(rule.url, before_url)
        self.assertEqual(self._file(package), before_file)
        self.assertNotIn(rule.webhook_uuid, before_file)

    def test_remove_takes_the_rule_and_its_steps_out_of_source(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Gone soon"}, template="run_code"
        )
        step_ids = self.env["base.automation"].browse(row["id"]).action_server_ids.ids
        self.Surface.remove_record(row["id"], package.id, force=True)
        self.assertFalse(self.env["ir.actions.server"].browse(step_ids).exists())
        self.assertNotIn("Gone soon", "".join(package._render_files().values()))

    # -- steps ---------------------------------------------------------------

    def test_steps_are_added_and_kept_in_order(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Two things"}, template="run_code"
        )
        added = self.Step.add_step(
            row["id"], package.id, {"state": "webhook", "webhook_url": "https://x"}
        )
        rule = self.env["base.automation"].browse(row["id"])
        self.assertEqual(rule.action_server_ids.mapped("state"), ["code", "webhook"])
        steps = self.Step.rows(MODEL, package.id, automation_id=row["id"])
        self.assertEqual([s["id"] for s in steps], rule.action_server_ids.ids)
        self.Step.move_step(
            added["row"]["id"], rule.action_server_ids[0].id, package.id
        )
        rule.invalidate_recordset()
        self.assertEqual(
            rule.action_server_ids.sorted("sequence").mapped("state"),
            ["webhook", "code"],
        )
        self.assertEqual(
            rule.action_server_ids.sorted("sequence").mapped("sequence"), [10, 20]
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
            model, package.id, {"name": "Kinds"}, template="blank"
        )
        self.Step.add_step(
            row["id"],
            package.id,
            {
                "state": "object_write",
                "update_path": "ref",
                "evaluation_type": "value",
                "value": "renamed",
            },
        )
        self.Step.add_step(
            row["id"],
            package.id,
            {"state": "webhook", "webhook_url": "https://example.com/hook"},
        )
        Server = self.env["ir.actions.server"]
        has_mail = "template_id" in Server._fields
        if has_mail:
            template = self.env["mail.template"].create(
                {"name": "T", "model_id": self.env["ir.model"]._get(model).id}
            )
            # A template only this database has cannot be pointed at from a
            # file; the step says so before anything is written.
            with self.assertRaises(UserError):
                self.Step.add_step(
                    row["id"],
                    package.id,
                    {"state": "mail_post", "template_id": template.id},
                )
            self.env["ir.model.data"].create(
                {
                    "module": "some_module",
                    "name": "template_t",
                    "model": "mail.template",
                    "res_id": template.id,
                }
            )
            self.Step.add_step(
                row["id"],
                package.id,
                {"state": "mail_post", "template_id": template.id},
            )
            self.Step.add_step(
                row["id"],
                package.id,
                {
                    "state": "next_activity",
                    "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                    "activity_summary": "Look",
                    "activity_date_deadline_range": 3,
                    "activity_date_deadline_range_type": "days",
                    "activity_user_type": "specific",
                    "activity_user_id": self.env.user.id,
                },
            )
        rule = self.env["base.automation"].browse(row["id"])
        states = rule.action_server_ids.sorted("sequence").mapped("state")
        files = package._render_files()
        rendered = files["data/res_partner_automation.xml"]
        self.assertIn("renamed", rendered)
        self.assertIn("https://example.com/hook", rendered)
        if has_mail:
            self.assertIn("mail_post", rendered)
            self.assertIn("Look", rendered)
        rule_xmlid = rule.get_external_id()[rule.id]
        rule.action_server_ids.unlink()
        rule.unlink()
        self.load_rendered(package, files)
        reloaded = self.env.ref(rule_xmlid)
        self.assertEqual(
            reloaded.action_server_ids.sorted("sequence").mapped("state"), states
        )
        by_state = {s.state: s for s in reloaded.action_server_ids}
        self.assertEqual(by_state["object_write"].update_path, "ref")
        self.assertEqual(by_state["object_write"].value, "renamed")
        self.assertEqual(by_state["webhook"].webhook_url, "https://example.com/hook")
        if has_mail:
            self.assertEqual(by_state["mail_post"].template_id.name, "T")
            self.assertEqual(by_state["next_activity"].activity_summary, "Look")
            self.assertEqual(by_state["next_activity"].activity_user_id, self.env.user)

    def test_graduate_is_offered_on_code_steps_only(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Code"}, template="set_field"
        )
        rule = self.env["base.automation"].browse(row["id"])
        described = self.Step.describe(rule.action_server_ids.id, package.id)
        self.assertNotIn("graduate", [a["key"] for a in described["actions"]])
        code = self.Step.add_step(row["id"], package.id, {"state": "code"})
        self.assertIn("graduate", [a["key"] for a in code["actions"]])

    def test_reads_need_a_studio_user_and_writes_a_manager(self):
        package = self._package()
        row = self.Surface.create_record(
            MODEL, package.id, {"name": "Guarded"}, template="run_code"
        )
        builder = self.make_user("builder", ["app_builder_base.group_studio_user"])
        self.assertTrue(self.Surface.with_user(builder).rows(MODEL, package.id))
        with self.assertRaises(AccessError):
            self.Surface.with_user(builder).write_record(
                row["id"], {"name": "Renamed"}, package.id
            )
        nobody = self.make_user("nobody", ["base.group_user"])
        with self.assertRaises(AccessError):
            self.Surface.with_user(nobody).rows(MODEL, package.id)

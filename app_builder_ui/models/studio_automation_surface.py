# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Automations and webhooks as a record pane, and the steps of one.

An automation is one thing to the user -- when, only if, then what --
and two models to Odoo: the ``base.automation`` rule and the ordered
``ir.actions.server`` rows it runs. The pane shows the rule as a card
whose sentence is the whole of it, and its sidebar edits the rule's rows
and, under them, the steps; ``studio.automation.step`` is the surface
for the steps, keyed by the rule rather than by the model.

What the catalogue exposes is what the serializer writes
(``base_automation_serializer.py``, ``serializers/ir_actions.py``): nothing
new reaches disk. The mail and sms rows are declared here and dropped
at ``catalogue()`` time when their fields are not on this database --
the bargain ``app_builder_mail`` makes for the serializer, so that this
addon depends on neither.
"""

import uuid

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools.catalogue import Row, Section

# The triggers whose value picker is a `Many2oneReference` the catalogue
# has no honest row for: offered, and their value set through Advanced.
ADVANCED_TRIGGERS = ("on_stage_set", "on_user_set", "on_tag_set")

WRITE_TRIGGERS = (
    "on_write",
    "on_create_or_write",
    "on_archive",
    "on_unarchive",
    "on_priority_set",
    "on_stage_set",
    "on_state_set",
    "on_tag_set",
    "on_user_set",
)
TIME_TRIGGERS = ("on_time", "on_time_created", "on_time_updated")

TRIGGER_GROUPS = {
    "on_create_or_write": "values",
    "on_create": "values",
    "on_write": "values",
    "on_unlink": "values",
    "on_archive": "values",
    "on_unarchive": "values",
    "on_state_set": "values",
    "on_priority_set": "values",
    "on_stage_set": "values",
    "on_user_set": "values",
    "on_tag_set": "values",
    "on_time": "timing",
    "on_time_created": "timing",
    "on_time_updated": "timing",
    "on_change": "custom",
    "on_message_received": "external",
    "on_message_sent": "external",
    "on_webhook": "external",
}


class StudioAutomation(models.AbstractModel):
    _name = "studio.automation"
    # The surface first: it carries the security mixin ``studio.automation``
    # already has, and Python's MRO wants the derived class before its base.
    _inherit = ["studio.record.surface", "studio.automation"]

    _surface_model = "base.automation"
    _surface_model_field = "model_id"
    _surface_sections = (
        Section(
            "rule",
            "Automation",
            (
                Row(name="name", label="Name", type="text", required=True),
                Row(
                    name="active",
                    label="Active",
                    type="toggle",
                    help="Off: nothing runs and the rule stays in source.",
                ),
            ),
        ),
        Section(
            "trigger",
            "Trigger",
            (
                Row(
                    name="trigger",
                    label="Trigger",
                    type="select",
                    selection_from="base.automation.trigger",
                    required=True,
                    allow_empty=False,
                ),
                Row(
                    name="trigger_field_ids",
                    label="Watching",
                    type="fields",
                    comodel="ir.model.fields",
                    comodel_domain="[('model_id', '=', {model_id}), "
                    "('store', '=', True)]",
                    help="Empty: any change.",
                    visible_when=(("trigger", ("on_write", "on_create_or_write")),),
                ),
                Row(
                    name="trg_selection_field_id",
                    label="When set to",
                    type="many2one",
                    comodel="ir.model.fields.selection",
                    comodel_domain="[('field_id.model_id', '=', {model_id}), "
                    "('field_id.name', 'in', ['state', 'priority'])]",
                    visible_when=(("trigger", ("on_state_set", "on_priority_set")),),
                ),
                Row(
                    name="trg_date_id",
                    label="Counting from",
                    type="many2one",
                    comodel="ir.model.fields",
                    comodel_domain="[('model_id', '=', {model_id}), "
                    "('ttype', 'in', ['date', 'datetime'])]",
                    visible_when=(("trigger", ("on_time",)),),
                ),
                Row(
                    name="trg_date_range",
                    label="Delay",
                    type="integer",
                    visible_when=(("trigger", TIME_TRIGGERS),),
                ),
                Row(
                    name="trg_date_range_type",
                    label="Delay unit",
                    type="select",
                    selection_from="base.automation.trg_date_range_type",
                    visible_when=(("trigger", TIME_TRIGGERS),),
                ),
                Row(
                    name="on_change_field_ids",
                    label="On change of",
                    type="fields",
                    comodel="ir.model.fields",
                    comodel_domain="[('model_id', '=', {model_id})]",
                    visible_when=(("trigger", ("on_change",)),),
                ),
                Row(
                    name="filter_pre_domain",
                    label="Before the update",
                    type="domain",
                    help="Only when the record matched this before the update.",
                    visible_when=(("trigger", WRITE_TRIGGERS),),
                ),
                Row(
                    name="filter_domain",
                    label="Only when",
                    type="domain",
                    help="Runs for every record that matches.",
                ),
            ),
        ),
        Section(
            "webhook",
            "Endpoint",
            (
                Row(name="url", label="URL", type="readonly"),
                Row(
                    name="record_getter",
                    label="Target record",
                    type="condition",
                    help="Which record the payload is about. Leave the default "
                    "when the caller sends _model and _id.",
                ),
                Row(name="log_webhook_calls", label="Log calls", type="toggle"),
            ),
            visible_when=(("trigger", ("on_webhook",)),),
        ),
    )
    _surface_templates = (
        (
            "run_code",
            "When a record is created or saved",
            "Run code of your own on every save.",
            {"trigger": "on_create_or_write", "steps": [{"state": "code"}]},
            ("name", "filter_domain"),
        ),
        (
            "set_field",
            "Set a field",
            "Update a field when a record is saved.",
            {"trigger": "on_create_or_write", "steps": [{"state": "object_write"}]},
            ("name", "filter_domain"),
        ),
        (
            "remind",
            "After a delay",
            "Create an activity some time after a record is created.",
            {
                "trigger": "on_time_created",
                "trg_date_range": 1,
                "trg_date_range_type": "day",
                "steps": [{"state": "next_activity"}],
            },
            ("name",),
        ),
        (
            "webhook_out",
            "Notify a URL",
            "POST the record to another system when it is saved.",
            {"trigger": "on_create_or_write", "steps": [{"state": "webhook"}]},
            ("name", "steps.0.webhook_url"),
        ),
        (
            "webhook_in",
            "New webhook",
            "A URL another system can POST to; what it sends is handled in code.",
            {"trigger": "on_webhook", "steps": [{"state": "code"}]},
            ("name",),
        ),
        ("blank", "Blank automation", "", {"trigger": "on_create_or_write"}, ("name",)),
    )

    DEFAULT_CODE = "# Available: env, model, record, records, log, UserError\n"

    # -- rows -----------------------------------------------------------------

    @api.model
    def _surface_domain(self, model_name, kwargs):
        domain = super()._surface_domain(model_name, kwargs)
        if kwargs.get("webhooks"):
            domain.append(("trigger", "=", "on_webhook"))
        else:
            domain.append(("trigger", "!=", "on_webhook"))
        return domain

    @api.model
    def templates(self, model_name=None):
        out = super().templates(model_name)
        # A webhook pane offers webhooks, an automation pane the rest; and
        # a step whose state this database lacks is not on offer.
        states = dict(
            self.env["ir.actions.server"]
            ._fields["state"]
            .get_description(self.env)["selection"]
        )
        return [
            t
            for t in out
            if all(step["state"] in states for step in t["values"].get("steps", []))
        ]

    @api.model
    def _section_json(self, section, model_name):
        data = super()._section_json(section, model_name)
        if section.id == "trigger":
            for spec in data["rows"]:
                if spec["name"] == "trigger":
                    spec["groups"] = TRIGGER_GROUPS
                    spec["advanced_only"] = list(ADVANCED_TRIGGERS)
        return data

    @api.model
    def _sentence(self, record):
        parts = [self._trigger_sentence(record)]
        if record.filter_domain and record.filter_domain.strip() not in ("[]", ""):
            parts.append(_("only when %s", record.filter_domain))
        steps = [self._step_label(step) for step in record.action_server_ids]
        if steps:
            parts.append("→ " + " · ".join(steps))
        return " · ".join(parts)

    @api.model
    def _trigger_sentence(self, record):
        label = dict(
            record._fields["trigger"].get_description(self.env)["selection"]
        ).get(record.trigger, record.trigger)
        if record.trigger in TIME_TRIGGERS and record.trg_date_range:
            unit = dict(
                record._fields["trg_date_range_type"].get_description(self.env)[
                    "selection"
                ]
            ).get(record.trg_date_range_type, "")
            return _(
                "%(n)s %(unit)s %(when)s",
                n=record.trg_date_range,
                unit=unit,
                when=label.lower(),
            )
        if record.trigger == "on_webhook":
            return _("POST to %s", record.url or "…")
        return label

    @api.model
    def _step_label(self, step):
        states = dict(step._fields["state"].get_description(self.env)["selection"])
        label = states.get(step.state, step.state)
        if step.state == "object_write" and step.update_path:
            return _("%(what)s: %(field)s", what=label, field=step.update_path)
        if (
            step.state == "mail_post"
            and "template_id" in step._fields
            and step.template_id
        ):
            return _(
                "%(what)s %(template)s", what=label, template=step.template_id.name
            )
        return label

    @api.model
    def _badges(self, record, owner):
        badges = super()._badges(record, owner)
        if record.trigger == "on_webhook":
            badges.append({"key": "webhook", "label": _("Webhook")})
        return badges

    @api.model
    def _row(self, record, package):
        row = super()._row(record, package)
        row["trigger"] = record.trigger
        return row

    # -- describe ------------------------------------------------------------

    @api.model
    def _describe_extra(self, record, package):
        Step = self.env["studio.automation.step"]
        return {
            # The steps as the sidebar's child list: described one by one
            # by their own surface, added and reordered through it.
            "children": {
                "surface": Step._name,
                "label": _("Then"),
                "one": _("step"),
                "items": [
                    Step.describe(step.id, package.id if package else None)
                    for step in record.action_server_ids.sorted("sequence")
                ],
                "kinds": Step._states(),
                "kind_field": "state",
                "add": "add_step",
                "move": "move_step",
                "empty": _("The automation needs something to do."),
            },
            "matches": self._check_domain(
                record.model_id.model, record.filter_domain or "[]"
            ),
        }

    @api.model
    def _actions(self, record, package):
        actions = super()._actions(record, package)
        owner = self._owner(record)
        if (
            record.trigger == "on_webhook"
            and owner["package"]
            and package
            and owner["package"] == package
        ):
            actions.append(
                {
                    "key": "rotate_secret",
                    "label": _("Rotate secret"),
                    "icon": "fa fa-refresh",
                    "enabled": package.writable,
                    "reason": "",
                    "danger": False,
                }
            )
        return actions

    @api.model
    def _notes(self, record, package):
        notes = []
        if record.trigger in ADVANCED_TRIGGERS:
            notes.append(
                _(
                    "The value this trigger waits for is set from Advanced: "
                    "it points at a record of another model."
                )
            )
        if record.trigger == "on_webhook":
            notes.append(
                _(
                    "The old URL stops working the moment the secret is rotated. "
                    "Neither is written to source."
                )
            )
        return notes

    @api.model
    def _run_rotate_secret(self, record, package):
        self._assert_editable(record, package)
        # Never captured: the serializer ignores webhook_uuid, so the file
        # is unchanged and no other database learns the new URL.
        record.write({"webhook_uuid": str(uuid.uuid4())})

    @api.model
    def _check_rule(self, record):
        """What a rule cannot run without, said before the file is written."""
        if record.trigger == "on_time" and not record.trg_date_id:
            raise UserError(_("Say which date the delay counts from (Counting from)."))

    @api.model
    def _after_write(self, record, package):
        self._check_rule(record)

    @api.model
    def _foreign_reason(self, record, module):
        return _(
            "Defined by %s. Shown here so you can see what runs; a copy in "
            "your package starts switched off, and the original keeps running "
            "until you switch it off in its own module.",
            module,
        )

    # -- create ----------------------------------------------------------------

    @api.model
    def _coerce(self, model_name, values, creating=False):
        values = dict(values)
        # Step values ride along on create and are handled after the rule.
        values.pop("steps", None)
        return super()._coerce(model_name, values, creating=creating)

    @api.model
    def create_record(self, model_name, package_id, values, template=None):
        values = dict(values or {})
        step_values = [
            dict(v) if isinstance(v, dict) else {} for v in values.pop("steps", [])
        ]
        # `steps.0.webhook_url` from the inline New form: a value on the
        # template's first step, which keeps the state the template gave it.
        for key in list(values):
            if key.startswith("steps."):
                _prefix, index, field = key.split(".", 2)
                index = int(index)
                while len(step_values) <= index:
                    step_values.append({})
                step_values[index][field] = values.pop(key)
        if template:
            tsteps = dict(self._template_raw(template)).get("steps", [])
            for index, step in enumerate(tsteps):
                if index < len(step_values):
                    step_values[index] = {**step, **step_values[index]}
                else:
                    step_values.append(dict(step))
        for step in step_values:
            step.setdefault("state", "code")
        return super(
            StudioAutomation, self.with_context(studio_surface_steps=step_values)
        ).create_record(model_name, package_id, values, template=template)

    @api.model
    def _template_raw(self, template):
        for key, _label, _help, tvalues, _needs in self._surface_templates:
            if key == template:
                return tvalues
        return {}

    @api.model
    def _template_values(self, template, model_name, values):
        tvalues = dict(self._template_raw(template))
        if not tvalues and template:
            raise UserError(_("There is no template called '%s'.", template))
        tvalues.pop("steps", None)
        return tvalues

    @api.model
    def _create_defaults(self, model_name, package, template, vals):
        return {"active": True}

    @api.model
    def _after_create(self, record, package, template):
        """The steps a template or the caller asked for, in order."""
        self._check_rule(record)
        Step = self.env["studio.automation.step"]
        for sequence, step in enumerate(
            self.env.context.get("studio_surface_steps") or [], 1
        ):
            Step._make(record, package, {**step, "sequence": sequence * 10})

    @api.model
    def _copy_defaults(self, record):
        defaults = super()._copy_defaults(record)
        defaults["name"] = _("%s (copy)", record.name)
        return defaults

    @api.model
    def _before_remove(self, record, package, force=False):
        # The steps go with the rule: Odoo cascades them, and the file
        # regenerates without both.
        return


class StudioAutomationStep(models.AbstractModel):
    """The ordered actions of one automation, as a surface keyed by the rule."""

    _name = "studio.automation.step"
    _inherit = ["studio.record.surface"]
    _description = "Studio Automation Step Surface"

    _surface_model = "ir.actions.server"
    _surface_model_field = "model_id"
    _surface_sections = (
        Section(
            "step",
            "Action",
            (
                Row(
                    name="state",
                    label="Do",
                    type="select",
                    selection_from="ir.actions.server.state",
                    required=True,
                    allow_empty=False,
                ),
                Row(name="name", label="Name", type="text"),
            ),
        ),
        Section(
            "code",
            "Code",
            (Row(name="code", label="Python", type="code", language="python"),),
            visible_when=(("state", ("code",)),),
        ),
        Section(
            "update",
            "Update the record",
            (
                Row(name="update_path", label="Field", type="field_path"),
                Row(
                    name="evaluation_type",
                    label="Value kind",
                    type="select",
                    selection_from="ir.actions.server.evaluation_type",
                ),
                Row(name="value", label="Value", type="textarea"),
                Row(
                    name="update_boolean_value",
                    label="Boolean value",
                    type="select",
                    selection_from="ir.actions.server.update_boolean_value",
                ),
                Row(
                    name="update_m2m_operation",
                    label="Tags operation",
                    type="select",
                    selection_from="ir.actions.server.update_m2m_operation",
                ),
            ),
            visible_when=(("state", ("object_write",)),),
        ),
        Section(
            "create",
            "Create a record",
            (
                Row(
                    name="crud_model_id",
                    label="Model",
                    type="many2one",
                    comodel="ir.model",
                ),
                Row(
                    name="link_field_id",
                    label="Link field",
                    type="many2one",
                    comodel="ir.model.fields",
                    comodel_domain="[('model_id', '=', {model_id})]",
                ),
                Row(name="value", label="Name", type="text"),
            ),
            visible_when=(("state", ("object_create",)),),
        ),
        Section(
            "webhook",
            "Send a webhook",
            (
                Row(name="webhook_url", label="URL", type="text", required=False),
                Row(
                    name="webhook_field_ids",
                    label="Fields to send",
                    type="fields",
                    comodel="ir.model.fields",
                    comodel_domain="[('model_id', '=', {model_id})]",
                ),
                Row(
                    name="webhook_sample_payload",
                    label="Sample payload",
                    type="readonly",
                ),
            ),
            visible_when=(("state", ("webhook",)),),
        ),
        Section(
            "mail",
            "Send an email",
            (
                Row(
                    name="template_id",
                    label="Template",
                    type="many2one",
                    comodel="mail.template",
                    comodel_domain="[('model_id', '=', {model_id})]",
                ),
                Row(
                    name="mail_post_method",
                    label="Send as",
                    type="select",
                    selection_from="ir.actions.server.mail_post_method",
                ),
                Row(
                    name="mail_post_autofollow",
                    label="Subscribe recipients",
                    type="toggle",
                ),
            ),
            visible_when=(("state", ("mail_post",)),),
        ),
        Section(
            "activity",
            "Create an activity",
            (
                Row(
                    name="activity_type_id",
                    label="Type",
                    type="many2one",
                    comodel="mail.activity.type",
                ),
                Row(name="activity_summary", label="Summary", type="text"),
                Row(name="activity_note", label="Note", type="textarea"),
                Row(
                    name="activity_date_deadline_range", label="Due in", type="integer"
                ),
                Row(
                    name="activity_date_deadline_range_type",
                    label="Due unit",
                    type="select",
                    selection_from="ir.actions.server.activity_date_deadline_range_type",
                ),
                Row(
                    name="activity_user_type",
                    label="Assigned to",
                    type="select",
                    selection_from="ir.actions.server.activity_user_type",
                ),
                Row(
                    name="activity_user_id",
                    label="User",
                    type="many2one",
                    comodel="res.users",
                    visible_when=(("activity_user_type", ("specific",)),),
                ),
                Row(
                    name="activity_user_field_name",
                    label="User field",
                    type="text",
                    visible_when=(("activity_user_type", ("generic",)),),
                ),
            ),
            visible_when=(("state", ("next_activity",)),),
        ),
        Section(
            "followers",
            "Followers",
            (
                Row(
                    name="partner_ids",
                    label="Contacts",
                    type="many2many",
                    comodel="res.partner",
                ),
            ),
            visible_when=(("state", ("followers", "remove_followers")),),
        ),
        Section(
            "sms",
            "Send an SMS",
            (
                Row(
                    name="sms_template_id",
                    label="Template",
                    type="many2one",
                    comodel="sms.template",
                    comodel_domain="[('model_id', '=', {model_id})]",
                ),
                Row(
                    name="sms_method",
                    label="Send as",
                    type="select",
                    selection_from="ir.actions.server.sms_method",
                ),
            ),
            visible_when=(("state", ("sms",)),),
        ),
    )

    @api.model
    def _states(self):
        field = self.env["ir.actions.server"]._fields["state"]
        return [
            [value, label]
            for value, label in field.get_description(self.env)["selection"]
            if value != "multi"
        ]

    @api.model
    def _section_json(self, section, model_name):
        data = super()._section_json(section, model_name)
        if section.id == "step":
            for spec in data["rows"]:
                if spec["name"] == "state":
                    # `multi` runs other actions: a container, not a step.
                    spec["choices"] = [c for c in spec["choices"] if c[0] != "multi"]
        return data

    @api.model
    def _surface_domain(self, model_name, kwargs):
        automation_id = kwargs.get("automation_id")
        if not automation_id:
            raise UserError(_("Steps belong to an automation; say which."))
        return [("base_automation_id", "=", int(automation_id))]

    @api.model
    def rows(self, model_name, package_id=None, **kwargs):
        rows = super().rows(model_name, package_id, **kwargs)
        # Steps keep the order the rule runs them in, not the alphabet's.
        order = {
            step.id: index
            for index, step in enumerate(
                self._model().search(self._surface_domain(model_name, kwargs))
            )
        }
        rows.sort(key=lambda r: order.get(r["id"], 0))
        return rows

    @api.model
    def _sentence(self, record):
        return self.env["studio.automation"]._step_label(record)

    @api.model
    def _actions(self, record, package):
        actions = super()._actions(record, package)
        if record.state == "code":
            reason = self.env["studio.graduate.code"].can_graduate(record)
            actions.append(
                {
                    "key": "graduate",
                    "label": _("Graduate to a method"),
                    "icon": "fa fa-graduation-cap",
                    "enabled": not reason and bool(package and package.writable),
                    "reason": reason or "",
                    "danger": False,
                }
            )
        return actions

    @api.model
    def _run_graduate(self, record, package):
        self.env["studio.graduate.code"].graduate(record.id, apply=True)

    @api.model
    def _make(self, automation, package, values):
        """One step on ``automation``, captured into ``package``."""
        state = values.get("state") or "code"
        vals = {
            "name": values.get("name") or automation.name,
            "model_id": automation.model_id.id,
            "state": state,
            "sequence": values.get("sequence", 10),
            "base_automation_id": automation.id,
            "usage": "base_automation",
        }
        if state == "code":
            vals["code"] = (
                values.get("code") or self.env["studio.automation"].DEFAULT_CODE
            )
        extra = {
            key: value
            for key, value in values.items()
            if key not in ("state", "name", "sequence", "code")
        }
        # Through the catalogue, so a value is checked the way the sidebar's
        # would be: a row this database lacks is refused, a reference the
        # file could not carry is refused before the write.
        vals.update(self._coerce(automation.model_id.model, extra))
        step = self._model().with_context(studio_package_id=package.id).create(vals)
        package.studio_capture(step)
        return step

    @api.model
    def add_step(self, automation_id, package_id, values):
        """A step appended to an automation this package owns."""
        self._assert_studio_manager()
        automation = self.env["base.automation"].browse(automation_id).exists()
        if not automation:
            raise UserError(_("That automation no longer exists."))
        package = self.env["studio.package"]._chosen(package_id)
        self.env["studio.automation"]._assert_editable(automation, package)
        last = max(automation.action_server_ids.mapped("sequence") or [0])
        step = self._make(automation, package, {**values, "sequence": last + 10})
        return self.describe(step.id, package.id)

    @api.model
    def move_step(self, step_id, before_id=None, package_id=None):
        """Reorder: ``step_id`` before ``before_id``, or last."""
        self._assert_studio_manager()
        step = self._record(step_id)
        package = self.env["studio.package"]._chosen(package_id)
        automation = step.base_automation_id
        self.env["studio.automation"]._assert_editable(automation, package)
        steps = [
            s for s in automation.action_server_ids.sorted("sequence") if s != step
        ]
        if before_id:
            index = next(
                (i for i, s in enumerate(steps) if s.id == before_id), len(steps)
            )
            steps.insert(index, step)
        else:
            steps.append(step)
        for sequence, entry in enumerate(steps, 1):
            entry.write({"sequence": sequence * 10})
        package.studio_capture(automation.action_server_ids)
        return [s.id for s in steps]

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approval rules as a record pane, with the gate they hang on.

A ``tier.definition`` says who approves and when; the model has to carry
the ``tier.validation`` mixin first, or the rule never fires. So the
catalogue reports the gate -- whether the model is gated, and which
selection fields could carry the transition -- and the pane's header
offers to turn approvals on before it offers a rule.
"""

from odoo import _, api, models

from odoo.addons.app_builder_base.tools.catalogue import Row, Section

from .studio_approval import MIXIN


class StudioApproval(models.AbstractModel):
    _name = "studio.approval"
    # The surface first: it carries the security mixin ``studio.approval``
    # already has, and Python's MRO wants the derived class before its base.
    _inherit = ["studio.record.surface", "studio.approval"]

    _surface_model = "tier.definition"
    _surface_model_field = "model_id"
    _surface_sections = (
        Section(
            "rule",
            "Rule",
            (
                Row(name="name", label="Name", type="text", required=True),
                Row(name="active", label="Active", type="toggle"),
                Row(
                    name="sequence",
                    label="Order",
                    type="integer",
                    help="Lower is asked first when approvals are sequential.",
                ),
            ),
        ),
        Section(
            "who",
            "Approved by",
            (
                Row(
                    name="review_type",
                    label="Who",
                    type="select",
                    selection_from="tier.definition.review_type",
                    required=True,
                    allow_empty=False,
                ),
                Row(
                    name="reviewer_id",
                    label="User",
                    type="many2one",
                    comodel="res.users",
                    visible_when=(("review_type", ("individual",)),),
                ),
                Row(
                    name="reviewer_group_id",
                    label="Group",
                    type="many2one",
                    comodel="res.groups",
                    visible_when=(("review_type", ("group",)),),
                ),
                Row(
                    name="reviewer_field_id",
                    label="Field",
                    type="many2one",
                    comodel="ir.model.fields",
                    comodel_domain="[('model_id', '=', {model_id}), "
                    "('relation', '=', 'res.users')]",
                    help="A user field of the record: its value approves.",
                    visible_when=(("review_type", ("field",)),),
                ),
            ),
        ),
        Section(
            "when",
            "Only when",
            (
                Row(
                    name="definition_domain",
                    label="Records",
                    type="domain",
                    help="Empty: every record that reaches the gate.",
                ),
            ),
        ),
        Section(
            "how",
            "How",
            (
                Row(
                    name="approve_sequence",
                    label="In order",
                    type="toggle",
                    help="Each reviewer waits for the one before.",
                ),
                Row(name="has_comment", label="Ask for a comment", type="toggle"),
                Row(
                    name="notify_on_pending", label="Notify when pending", type="toggle"
                ),
                Row(
                    name="notify_on_accepted",
                    label="Notify when approved",
                    type="toggle",
                ),
                Row(
                    name="notify_on_rejected",
                    label="Notify when rejected",
                    type="toggle",
                ),
            ),
        ),
    )
    _surface_templates = (
        (
            "approve_by_user",
            "A specific user approves",
            "",
            {"review_type": "individual"},
            ("name", "reviewer_id"),
        ),
        (
            "approve_by_group",
            "Anyone in a group approves",
            "",
            {"review_type": "group"},
            ("name", "reviewer_group_id"),
        ),
        (
            "approve_by_field",
            "The record's own user approves",
            "The manager, the responsible: whichever user field you pick.",
            {"review_type": "field"},
            ("name", "reviewer_field_id"),
        ),
    )

    # -- the gate ------------------------------------------------------------

    @api.model
    def _gated(self, model_name):
        return bool(
            model_name
            and model_name in self.env
            and MIXIN in self.env[model_name]._inherit_module
        )

    @api.model
    def catalogue(self, model_name=None):
        out = super().catalogue(model_name)
        gated = self._gated(model_name)
        out["gate"] = {
            "on": gated,
            "title": _("Approvals are not switched on for %s", model_name or "")
            if not gated
            else "",
            "help": _(
                "An approval rule gates a state change, and the model has to "
                "carry the gate first."
            )
            if not gated
            else "",
            "consequence": _(
                "Writes the tier.validation mixin into the model's class in the "
                "package; one reload. Turning it off later is an edit to the "
                "class."
            ),
            "state_fields": (
                self.candidate_state_fields(model_name)
                if model_name and model_name in self.env and not gated
                else []
            ),
            "call": "enable_gate",
        }
        return out

    @api.model
    def enable_gate(
        self,
        package_id,
        model_name,
        state_field="state",
        state_from=None,
        state_to=None,
        cancel_state=None,
    ):
        """Turn approvals on and reload: the pane's gate header."""
        return self.enable(
            package_id,
            model_name,
            state_field=state_field,
            state_from=state_from,
            state_to=state_to,
            cancel_state=cancel_state or None,
            apply=True,
        )

    # -- rows ------------------------------------------------------------------

    @api.model
    def _surface_domain(self, model_name, kwargs):
        # `model` is the stored related the engine matches on.
        return [("model", "=", model_name)]

    @api.model
    def _sentence(self, record):
        who = {
            "individual": record.reviewer_id.name,
            "group": record.reviewer_group_id.full_name,
            "field": record.reviewer_field_id.field_description,
        }.get(record.review_type) or _("nobody yet")
        parts = [_("%s approves", who)]
        if record.definition_domain and record.definition_domain.strip() not in (
            "",
            "[]",
        ):
            parts.append(_("only for %s", record.definition_domain))
        if record.approve_sequence:
            parts.append(_("in order"))
        return " · ".join(parts)

    @api.model
    def _describe_extra(self, record, package):
        return {
            "matches": self._check_domain(
                record.model_id.model, record.definition_domain or "[]"
            )
        }

    @api.model
    def _notes(self, record, package):
        return [
            _(
                "Removing a rule takes it out of security/%s_approval.xml; "
                "approvals already in flight are untouched.",
                (record.model_id.model or "").replace(".", "_"),
            )
        ]

    @api.model
    def _create_defaults(self, model_name, package, template, vals):
        return {"active": True, "definition_type": "domain"}

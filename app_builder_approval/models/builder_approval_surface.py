# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Approval rules as a record pane, with the gate they hang on.

A ``tier.definition`` says who approves and when; the model has to carry
the ``tier.validation`` mixin first, or the rule never fires. So the
catalogue reports the gate -- whether the model is gated, and which
selection fields could carry the transition -- and the pane's header
offers to turn approvals on before it offers a rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from odoo import api, models

from odoo.addons.app_builder_base.models.builder_record_surface import (
    RecordCatalogueJSON,
)
from odoo.addons.app_builder_base.tools.catalogue import Row, Section
from odoo.addons.app_builder_base.tools.i18n import _

from .builder_approval import MIXIN

if TYPE_CHECKING:
    # Only for annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime -- the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes. `MIXIN` and
    # `RecordCatalogueJSON` are real, top-level imports instead (above):
    # `MIXIN` is a plain constant read at runtime (`_gated`), and
    # `RecordCatalogueJSON` is a real base class of `ApprovalCatalogueJSON`
    # below (rule 9's TypedDict subclassing), both needing a real binding.
    from odoo.models import BaseModel

    from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
    from odoo.addons.app_builder_base.models.builder_record_surface import (
        BuilderRecordSurface,
    )
    from odoo.addons.base.models.ir_model import IrModel, IrModelFields
    from odoo.addons.base.models.res_users import Groups, Users
    from odoo.addons.base_tier_validation.models.tier_definition import TierDefinition

    from .builder_approval import BuilderApproval as BuilderApprovalBase

    # `.builder_approval`'s own module also declares a class named
    # `BuilderApproval` (the SAME "builder.approval" `_name`, merged into one
    # real model by the registry, but two separate classes as far as
    # pyright is concerned) -- aliased on import so this file's own `class
    # BuilderApproval` below does not collide with it. A plain `cast()`
    # target needs no runtime binding (rule 4/7), so this stays
    # `TYPE_CHECKING`-only rather than a real top-level import.
    from .builder_approval import (
        EnableApprovalJSON,
        GateConfigJSON,
        StateFieldJSON,
    )


class ApprovalGateJSON(TypedDict):
    """``catalogue()``'s own ``gate`` key: whether the model is gated yet,
    and what turning it on would take (``catalogue()``)."""

    on: bool
    title: str
    help: str
    consequence: str
    current: GateConfigJSON | None
    module: str
    off_consequence: str
    state_fields: list[StateFieldJSON]
    call: str
    update_call: str
    disable_call: str


class ApprovalCatalogueJSON(RecordCatalogueJSON):
    """``catalogue()``'s own return: the base surface catalogue plus the
    gate (rule 9's TypedDict subclassing -- the base's own closed shape
    plus one more key)."""

    gate: ApprovalGateJSON


class BuilderApproval(models.AbstractModel):
    _name = "builder.approval"
    # The surface first: it carries the security mixin ``builder.approval``
    # already has, and Python's MRO wants the derived class before its base.
    _inherit = ["builder.record.surface", "builder.approval"]

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
    def _gated(self, model_name: str | None) -> bool:
        # `_inherit_module`'s own stub gap is the identical one
        # `builder_approval.py`'s own `_empty_state` already documents.
        return bool(
            model_name
            and model_name in self.env
            and MIXIN in self.env[model_name]._inherit_module  # pyright: ignore[reportAttributeAccessIssue]
        )

    @api.model
    def _gate_module(self, model_name: str | None) -> str:
        """The module that put ``tier.validation`` into the model's class."""
        if not model_name or model_name not in self.env:
            return ""
        # `_inherit_module` maps each parent to the module that introduced it
        # (`odoo/models.py`); the stub gap is the one `_gated` documents.
        modules = cast(
            "dict[str, str]",
            self.env[model_name]._inherit_module,  # pyright: ignore[reportAttributeAccessIssue]
        )
        return modules.get(MIXIN, "")

    @api.model
    def catalogue(self, model_name: str | None = None) -> ApprovalCatalogueJSON:
        out = cast(
            "ApprovalCatalogueJSON",
            cast("BuilderRecordSurface", super()).catalogue(model_name),
        )
        gated = self._gated(model_name)
        base = cast("BuilderApprovalBase", self)
        out["gate"] = {
            "on": gated,
            "title": _("Approvals are not switched on for %s", model_name or "")
            if not gated
            else _("Approvals are on for %s", model_name or ""),
            "help": _(
                "An approval rule gates a state change, and the model has to "
                "carry the gate first."
            )
            if not gated
            else "",
            "consequence": _(
                "Writes the tier.validation mixin into the model's class in the "
                "package; one reload. Approval is asked for on every way into "
                "the states you pick -- from any other state, including one "
                "added later, and for a record created, imported or duplicated "
                "already in one -- because the status "
                "field is an ordinary writable field and a gate on one path "
                "only would be walked round. Rules decide who approves; with "
                "no rule, nothing is asked."
            ),
            # What is being enforced right now, for a model that is gated, so
            # a wrong transition can be seen and changed rather than guessed
            # at from the source.
            "current": base._live_gate_config(model_name)
            if gated and model_name
            else None,
            # Which module put the gate there: only that package's gate can be
            # changed or taken out from here (`disable`'s own refusal), so the
            # pane says so before the button rather than after it.
            "module": self._gate_module(model_name) if gated else "",
            # What turning approvals off does to data, said where the button
            # is -- the same split `disable()` and `_drops_only_the_gate` make.
            "off_consequence": _(
                "Takes the tier.validation mixin, its configuration and the "
                "creation guard back out of the model's class in the package; "
                "one reload. The approval rules stay as they are and never "
                "fire with no gate; the reviews already asked for stay in "
                "their history. The validation status column the gate added "
                "is the only stored field removed, and its values are kept "
                "under a renamed column, as for any confirmed removal. If "
                "anything else in the package is waiting to be removed, "
                "turning approvals off is refused until that removal has been "
                "applied on its own."
            ),
            # Offered when gated too: changing the transition picks from the
            # same fields enabling did.
            "state_fields": (
                base.candidate_state_fields(model_name)
                if model_name and model_name in self.env
                else []
            ),
            "call": "enable_gate",
            "update_call": "update_gate",
            "disable_call": "disable_gate",
        }
        return out

    @api.model
    def enable_gate(
        self,
        package_id: int,
        model_name: str,
        state_field: str = "state",
        state_from: list[str] | None = None,
        state_to: list[str] | None = None,
        cancel_state: str | None = None,
    ) -> EnableApprovalJSON:
        """Turn approvals on and reload: the pane's gate header."""
        return cast("BuilderApprovalBase", self).enable(
            package_id,
            model_name,
            state_field=state_field,
            # The pane sends False for "any state"; so does a bare RPC.
            state_from=state_from or None,
            state_to=state_to,
            cancel_state=cancel_state or None,
            apply=True,
        )

    @api.model
    def update_gate(
        self,
        package_id: int,
        model_name: str,
        state_field: str = "state",
        state_from: list[str] | None = None,
        state_to: list[str] | None = None,
        cancel_state: str | None = None,
    ) -> EnableApprovalJSON:
        """Change the gated transition and reload."""
        return cast("BuilderApprovalBase", self).reconfigure(
            package_id,
            model_name,
            state_field=state_field,
            state_from=state_from or None,
            state_to=state_to,
            cancel_state=cancel_state or None,
            apply=True,
        )

    @api.model
    def disable_gate(self, package_id: int, model_name: str) -> EnableApprovalJSON:
        """Take the gate out of the model's class and reload."""
        return cast("BuilderApprovalBase", self).disable(
            package_id, model_name, apply=True
        )

    # -- rows ------------------------------------------------------------------

    @api.model
    def _surface_domain(
        self, model_name: str, kwargs: dict[str, object]
    ) -> api.DomainType:
        # `model` is the stored related the engine matches on.
        return [("model", "=", model_name)]

    @api.model
    def _sentence(self, record: BaseModel) -> str:
        # `tier.definition` is `base_tier_validation`'s own model, never
        # given field annotations of its own -- `TierDefinition` (imported
        # under `TYPE_CHECKING` above) is that real, untyped class, cast in
        # the same way `tier_serializers.py`'s own `_group_model`/
        # `_sort_key` already cast the identical model.
        definition = cast("TierDefinition", record)
        who = {
            "individual": cast("Users", definition.reviewer_id).name,
            "group": cast("Groups", definition.reviewer_group_id).full_name,
            "field": cast(
                "IrModelFields", definition.reviewer_field_id
            ).field_description,
            # `.get()`'s key parameter wants a plain `str`; `review_type`'s
            # own declared type is `str | Literal[False]` like every
            # Selection field -- true by construction that a rule read back
            # here always has one of the three keys above, the same
            # "trust the runtime, cast for the type" idiom `_coerce_one`'s
            # own `int(cast("Any", value) or 0)` already uses.
        }.get(cast("str", definition.review_type)) or _("nobody yet")
        parts = [_("%s approves", who)]
        domain = definition.definition_domain
        if domain and domain.strip() not in ("", "[]"):
            parts.append(_("only for %s", domain))
        if definition.approve_sequence:
            parts.append(_("in order"))
        return " · ".join(parts)

    @api.model
    def _describe_extra(
        self, record: BaseModel, package: BuilderPackage
    ) -> dict[str, object]:
        definition = cast("TierDefinition", record)
        model = cast("IrModel", definition.model_id)
        return {
            "matches": cast("BuilderRecordSurface", self)._check_domain(
                model.model, definition.definition_domain or "[]"
            )
        }

    @api.model
    def _notes(self, record: BaseModel, package: BuilderPackage) -> list[object]:
        definition = cast("TierDefinition", record)
        model = cast("IrModel", definition.model_id)
        return [
            _(
                "Removing a rule takes it out of security/%s_approval.xml; "
                "approvals already in flight are untouched.",
                (model.model or "").replace(".", "_"),
            )
        ]

    @api.model
    def _create_defaults(
        self,
        model_name: str,
        package: BuilderPackage,
        template: str | None,
        vals: dict[str, object],
    ) -> dict[str, object]:
        return {"active": True, "definition_type": "domain"}

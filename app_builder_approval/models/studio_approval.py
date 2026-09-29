# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Turning approvals on for a model, as generated source.

**Odoo Studio asks "which button?"; this engine answers "which state
transition?"** That is the one thing to understand before using this, and it is
not a limitation we chose. ``base_tier_validation`` gates ``write()``: a rule
fires when the record's state field moves out of ``_state_from`` into
``_state_to``. There is no hook of any kind for gating a named method or a
button -- confirmed by reading all 972 lines of the mixin and grepping the
family -- so a surface that asked for a button would be promising something the
engine cannot deliver.

For most real approvals the two coincide: the button people mean is *Confirm*,
and confirming is a state change. Where they do not, this says so rather than
generating a rule that silently never fires.

Enabling produces **two** classes, not one:

* the gated model gains the ``tier.validation`` mixin and the four class
  attributes that configure it;
* ``tier.definition`` gains an override of ``_get_tier_validation_model_names``,
  because base returns ``[]`` and without it the model never appears in the
  approval rule's own model picker.

Both are plain declarative Python, which is why this is a code generator rather
than a pile of data records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, cast

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.app_builder_base.models.studio_package import StudioPackage
from odoo.addons.app_builder_base.models.studio_package_model import StudioPackageModel
from odoo.addons.app_builder_base.tools import modelspec, pycodegen, typed
from odoo.addons.app_builder_base.tools.i18n import _

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs `Selection` at runtime. `field` (`_selection_values`)
    # is read off a dynamically-named model's `_fields` dict, so its static
    # type is the base `Field`, which does not declare
    # `_description_selection` -- only its `Selection` subclass does (`odoo
    # /fields.py`). True by construction only for a field `enable()` and
    # `candidate_state_fields()` already established is a stored selection;
    # invisible to pyright the same way every other traced dynamic-field gap
    # in this migration is.
    from odoo.fields import Field, Selection

MIXIN = "tier.validation"


class ApprovalActionJSON(TypedDict):
    """``action_open()``'s return: base_tier_validation's own rule list, scoped."""

    type: str
    name: str
    res_model: str
    view_mode: str
    views: list[tuple[bool, str]]
    domain: list[tuple[str, str, object]]
    context: dict[str, object]
    help: str


class StateValueJSON(TypedDict):
    """One value a candidate state field can hold, as ``candidate_state_fields()``
    reports it."""

    value: str
    label: str


class StateFieldJSON(TypedDict):
    """One selection field ``enable()`` could gate on, as ``candidate_state_fields()``
    returns it."""

    name: str
    string: str
    values: list[StateValueJSON]


class EnableApprovalJSON(TypedDict):
    """``enable()``'s return: which model was gated, and whether it applied."""

    model: str
    applied: bool


class StudioApproval(models.AbstractModel):
    _name = "studio.approval"
    _inherit = ["studio.security.mixin"]
    _description = "Studio: Approval Rules"

    # -- the rules themselves ---------------------------------------------

    @api.model
    def action_open(
        self, model_name: str | None = None, package_id: int | None = None
    ) -> ApprovalActionJSON:
        """base_tier_validation's own rule list, scoped and with a package.

        The console's Approvals tab. Not a form of our own: the engine's
        form already knows which reviewer kinds exist and which fields can
        name one, and a second copy would drift from it. What the studio
        adds is the scope -- the rules *for the model on the canvas* -- and
        the package the rule created there is written into, so it is source
        rather than a row that gates records here and nowhere else: the
        console's own package when it names one, else the suggested one.

        A model that is not gated yet still gets its list: empty, with the
        help text saying that the gate comes first, since a rule on a model
        without the mixin is not an error -- it silently never fires.
        """
        typed.security(self)._assert_studio_user()
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        domain: list[tuple[str, str, object]] = []
        context: dict[str, object] = {"studio_package_id": package.id or False}
        if model_name:
            if model_name not in self.env:
                raise UserError(_("Unknown model '%s'.", model_name))
            model = typed.model(self.env, IrModel)._get(model_name)
            # `model` is the stored related the engine matches on, and the
            # column its own search view filters by.
            domain.append(("model", "=", model_name))
            context["default_model_id"] = model.id
        return {
            "type": "ir.actions.act_window",
            "name": _("Approvals"),
            "res_model": "tier.definition",
            "view_mode": "list,form",
            # Spelled out because the dict is returned over plain RPC, and
            # the client derives nothing from view_mode on that path.
            "views": [(False, "list"), (False, "form")],
            "domain": domain,
            "context": context,
            "help": self._empty_state(model_name),
        }

    @api.model
    def _empty_state(self, model_name: str | None) -> str:
        # `_inherit_module` (`odoo/models.py`) is assigned per concrete
        # model class by the registry-building metaclass, never declared as
        # a typed attribute on `BaseModel` itself -- a real, traced
        # vendor-stub gap (confirmed by reading `models.py`'s own class
        # body; there is no such declaration), not fixable from this side.
        # `self.env[model_name]` is the dynamically-named-model exception
        # (rule 2), so it stays the plain lookup its bare `BaseModel`
        # return type already implies.
        gated = model_name and MIXIN in self.env[model_name]._inherit_module  # pyright: ignore[reportAttributeAccessIssue]
        if model_name and not gated:
            return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
                _("Approvals are not switched on for %s yet", model_name),
                _(
                    "An approval rule gates a state change, and the model has "
                    "to carry the gate first: turn approvals on from the "
                    "studio, then come back here to say who approves what."
                ),
            )
        return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
            _("Say who must approve, and in what order"),
            _(
                "Rules you create here are written into your studio package, "
                "so they ship with the rest of your customisation."
            ),
        )

    # -- what a model needs before it can be gated ------------------------

    @api.model
    def candidate_state_fields(self, model_name: str) -> list[StateFieldJSON]:
        """Selection fields that could carry the transition being gated.

        A model with none cannot be gated at all: the engine's guard
        short-circuits on `self._state_field in self._fields`
        (`tier_validation.py:512`), so a rule on a stateless model is not an
        error -- it simply never fires, which is worse.
        """
        typed.security(self)._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        out: list[StateFieldJSON] = []
        fields_ = cast("dict[str, Field[Any]]", self.env[model_name]._fields)
        for name, field in sorted(fields_.items()):
            if field.type != "selection" or not field.store:
                continue
            out.append(
                {
                    "name": name,
                    "string": field.string or name,
                    "values": [
                        {"value": value, "label": label}
                        for value, label in self._selection_values(model_name, name)
                    ],
                }
            )
        return out

    @api.model
    def _selection_values(
        self, model_name: str, field_name: str
    ) -> list[tuple[str, str]]:
        field = cast("dict[str, Field[Any]]", self.env[model_name]._fields)[field_name]
        try:
            # See this file's own `TYPE_CHECKING` note: `_description_selection`
            # is `Selection`'s own, not the base `Field`'s -- true here only
            # because every real caller already established `field_name`
            # names a stored selection field. Its own return type is a wide,
            # partly-`Unknown` union (three branches: a callable's own
            # return, `ir.model.fields.get_field_selection`, or the raw
            # `selection` attribute) -- the same untyped-vendor-method gap
            # `studio_domain.py`'s own `fields_for` already documents for
            # the sibling accessor (`get_description(...).get("selection")`);
            # cast to what the method's own docstring promises ("pairs
            # (value, label)").
            selection = cast(
                "list[tuple[str, str]] | None",
                cast("Selection", field)._description_selection(self.env),
            )
            return selection or []
        except Exception:  # noqa: BLE001
            # A selection built by a callable can need a record to evaluate.
            # Offering no values is honest; guessing is not.
            return []

    @api.model
    def _validate_transition(
        self,
        model_name: str,
        state_field: str,
        state_from: list[str],
        state_to: list[str],
    ) -> None:
        values = {v for v, _label in self._selection_values(model_name, state_field)}
        if not values:
            return  # nothing to check against; the field may be dynamic
        unknown = (set(state_from) | set(state_to)) - values
        if unknown:
            raise UserError(
                _(
                    "%(model)s has no such value for %(field)s: %(unknown)s. A "
                    "rule naming a value the field does not have never fires, "
                    "which looks exactly like approvals being switched off.",
                    model=model_name,
                    field=state_field,
                    unknown=", ".join(sorted(unknown)),
                )
            )
        overlap = set(state_from) & set(state_to)
        if overlap:
            raise UserError(
                _(
                    "%s is on both sides of the transition, so there is no "
                    "moment at which approval could be asked for.",
                    ", ".join(sorted(overlap)),
                )
            )

    # -- enabling ---------------------------------------------------------

    @api.model
    def enable(
        self,
        package_id: int,
        model_name: str,
        state_field: str = "state",
        state_from: list[str] | None = None,
        state_to: list[str] | None = None,
        cancel_state: str | None = None,
        apply: bool = True,
    ) -> EnableApprovalJSON:
        """Give ``model_name`` an approval gate, as source.

        ``apply`` reloads the module, which is what makes the mixin live.
        Separable for the same reason it is in code graduation: `action_apply`
        commits, and a commit is unreachable from a `TransactionCase`.
        """
        typed.security(self)._assert_studio_manager()
        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this in."))
        package._assert_writable()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        state_from = list(state_from or ["draft"])
        state_to = list(state_to or [])
        if not state_to:
            raise UserError(
                _(
                    "Say which state needs approving into. This engine gates a "
                    "state change, not a button, so a rule with no destination "
                    "has nothing to attach to."
                )
            )
        if state_field not in self.env[model_name]._fields:
            raise UserError(
                _(
                    "%(model)s has no field called %(field)s, and approvals are "
                    "a gate on a state change. Add a status field first.",
                    model=model_name,
                    field=state_field,
                )
            )
        self._validate_transition(model_name, state_field, state_from, state_to)

        self._write_gated_model(
            package, model_name, state_field, state_from, state_to, cancel_state
        )
        self._write_model_picker(package, model_name)
        if apply:
            package.action_apply(reason=_("enable approvals on %s", model_name))
        return {"model": model_name, "applied": apply}

    @api.model
    def _write_gated_model(
        self,
        package: StudioPackage,
        model_name: str,
        state_field: str,
        state_from: list[str],
        state_to: list[str],
        cancel_state: str | None,
    ) -> StudioPackageModel:
        entry = typed.model(self.env, StudioPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", model_name)], limit=1
        )
        if entry and entry.source != "python":
            raise UserError(
                _(
                    "%s is managed as data records here, so there is no class "
                    "to add the mixin to.",
                    model_name,
                )
            )
        if not entry:
            entry = typed.model(self.env, StudioPackageModel)._adopt(
                package, model_name, extends=True
            )
        spec = entry._current_spec() or modelspec.ModelSpec(
            name=model_name,
            description="",
            class_name=pycodegen.class_name_for(model_name),
            extends=True,
        )
        if MIXIN in spec.inherit:
            raise UserError(_("%s already has approvals turned on.", model_name))

        attrs = dict(spec.class_attrs)
        attrs["_state_field"] = '"%s"' % state_field
        attrs["_state_from"] = repr(state_from)
        attrs["_state_to"] = repr(state_to)
        # Without this the mixin injects no buttons at all: the default is True,
        # which means "the model wires up its own UI" -- and a generated model
        # has nobody to do that.
        attrs["_tier_validation_manual_config"] = "False"
        if cancel_state:
            # A single string, never a list. The engine compares with `in`
            # against it in one place, so a list would make every state whose
            # name is a substring look like a cancellation.
            attrs["_cancel_state"] = '"%s"' % cancel_state

        from dataclasses import replace as _replace

        package._seed_source_for(
            model_name,
            _replace(
                spec,
                inherit=spec.inherit + (MIXIN,),
                class_attrs=tuple(attrs.items()),
            ),
        )
        return entry

    @api.model
    def _write_model_picker(
        self, package: StudioPackage, model_name: str
    ) -> StudioPackageModel:
        """Append the model to tier.definition's picker.

        ``_get_tier_validation_model_names`` returns ``[]`` in
        base_tier_validation, and its only caller is the domain on
        ``tier.definition.model_id``. Skip this and the mixin works while the
        rule cannot be created through Odoo's own form -- which is where we send
        people, so it is not optional.
        """
        entry = typed.model(self.env, StudioPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", "tier.definition")],
            limit=1,
        )
        if not entry:
            entry = typed.model(self.env, StudioPackageModel)._adopt(
                package, "tier.definition", extends=True
            )
        spec = entry._current_spec() or modelspec.ModelSpec(
            name="tier.definition",
            description="",
            class_name=pycodegen.class_name_for("tier.definition"),
            extends=True,
        )
        gated = sorted(set(self._gated_models(package)) | {model_name})
        method = modelspec.MethodSpec(
            name="_get_tier_validation_model_names",
            body="res = super()._get_tier_validation_model_names()\n"
            + "res.extend(%r)\n" % gated
            + "return res",
            doc="Models this package gates, so they can be picked in a rule.",
        )
        from dataclasses import replace as _replace

        package._seed_source_for("tier.definition", _replace(spec, methods=(method,)))
        return entry

    @api.model
    def _gated_models(self, package: StudioPackage) -> list[str]:
        """Models in this package that already carry the mixin."""
        out: list[str] = []
        for entry in cast("StudioPackageModel", package.model_ids):
            if entry.model == "tier.definition" or entry.source != "python":
                continue
            spec = entry._current_spec()
            if spec is not None and MIXIN in spec.inherit:
                out.append(cast("str", entry.model))
        return out


class TierDefinition(models.Model):
    """Rules created with a package in context belong to it at once.

    The Approvals tab opens the engine's own list with ``studio_package_id``
    in context, and a rule made there that stayed unowned would gate records
    in this database and ship nowhere -- and it would *work*, which is what
    makes that drift invisible. The engine's capture on create, the same one
    an automation or an access row gets; only when a package is named, so
    the engine's own form under Settings is unaffected.
    """

    _name = "tier.definition"
    _inherit = ["tier.definition", "studio.captured.on.create"]

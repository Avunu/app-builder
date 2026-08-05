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

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import modelspec, pycodegen

MIXIN = "tier.validation"


class StudioApproval(models.AbstractModel):
    _name = "studio.approval"
    _inherit = ["studio.security.mixin"]
    _description = "Studio: Approval Rules"

    # -- what a model needs before it can be gated ------------------------

    @api.model
    def candidate_state_fields(self, model_name):
        """Selection fields that could carry the transition being gated.

        A model with none cannot be gated at all: the engine's guard
        short-circuits on `self._state_field in self._fields`
        (`tier_validation.py:512`), so a rule on a stateless model is not an
        error -- it simply never fires, which is worse.
        """
        self._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        out = []
        for name, field in sorted(self.env[model_name]._fields.items()):
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
    def _selection_values(self, model_name, field_name):
        field = self.env[model_name]._fields[field_name]
        try:
            return field._description_selection(self.env) or []
        except Exception:  # noqa: BLE001
            # A selection built by a callable can need a record to evaluate.
            # Offering no values is honest; guessing is not.
            return []

    @api.model
    def _validate_transition(self, model_name, state_field, state_from, state_to):
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
        package_id,
        model_name,
        state_field="state",
        state_from=None,
        state_to=None,
        cancel_state=None,
        apply=True,
    ):
        """Give ``model_name`` an approval gate, as source.

        ``apply`` reloads the module, which is what makes the mixin live.
        Separable for the same reason it is in code graduation: `action_apply`
        commits, and a commit is unreachable from a `TransactionCase`.
        """
        self._assert_studio_manager()
        package = self.env["studio.package"].browse(package_id).exists()
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
        self, package, model_name, state_field, state_from, state_to, cancel_state
    ):
        entry = self.env["studio.package.model"].search(
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
            entry = self.env["studio.package.model"]._adopt(
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
    def _write_model_picker(self, package, model_name):
        """Append the model to tier.definition's picker.

        ``_get_tier_validation_model_names`` returns ``[]`` in
        base_tier_validation, and its only caller is the domain on
        ``tier.definition.model_id``. Skip this and the mixin works while the
        rule cannot be created through Odoo's own form -- which is where we send
        people, so it is not optional.
        """
        entry = self.env["studio.package.model"].search(
            [("package_id", "=", package.id), ("model", "=", "tier.definition")],
            limit=1,
        )
        if not entry:
            entry = self.env["studio.package.model"]._adopt(
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
    def _gated_models(self, package):
        """Models in this package that already carry the mixin."""
        out = []
        for entry in package.model_ids:
            if entry.model == "tier.definition" or entry.source != "python":
                continue
            spec = entry._current_spec()
            if spec is not None and MIXIN in spec.inherit:
                out.append(entry.model)
        return out

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

from dataclasses import replace as _replace
from typing import TYPE_CHECKING, Any, TypedDict, cast

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.tools import modelspec, pycodegen, typed
from odoo.addons.app_builder_base.tools.i18n import _
from odoo.addons.base.models.ir_model import IrModel

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

# What enabling writes into the gated class, and so what disabling takes out.
GATE_ATTRS = (
    "_state_field",
    "_state_from",
    "_state_to",
    "_cancel_state",
    "_tier_validation_manual_config",
)
CREATE_GUARD = "_create"
PICKER = "_get_tier_validation_model_names"
# "No cancelled state", spelled so the engine's substring test cannot match it.
NO_CANCEL_STATE = ""

# `_state_from`, as source: every value the state field has *when it is asked*
# that is not a destination. Not a list frozen at enable time, because a
# builder model's stages stay editable -- a status value added later and left
# out of a frozen list would be a free way round the gate (draft -> review ->
# done). The engine only ever reads `self._state_from` off a record (`in`
# tests, `_check_state_from_condition`), so a property on the class is read
# exactly where a list would be. The work is in a builder-owned method rather
# than in the attribute, because class attributes are written on one line and
# a long one would be rewrapped by any formatter run over the package.
ORIGINS = "_builder_gate_origins"
STATE_FROM_SOURCE = "property(lambda self: self.%s())" % ORIGINS


def _py_list(values: list[str]) -> str:
    """A list of strings as source, quoted the way the rest of the file is."""
    return "[%s]" % ", ".join(pycodegen._py(value) for value in values)


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


class GateConfigJSON(TypedDict):
    """The transition a gate asks approval for, as it is written to the class."""

    state_field: str
    state_from: list[str]
    state_to: list[str]
    cancel_state: str


class EnableApprovalJSON(TypedDict):
    """``enable()``, ``reconfigure()`` and ``disable()``'s return: which model,
    and whether the change was applied."""

    model: str
    applied: bool


class BuilderApproval(models.AbstractModel):
    _name = "builder.approval"
    _inherit = ["builder.security.mixin"]
    _description = "Builder: Approval Rules"

    # -- the rules themselves ---------------------------------------------

    @api.model
    def action_open(
        self, model_name: str | None = None, package_id: int | None = None
    ) -> ApprovalActionJSON:
        """base_tier_validation's own rule list, scoped and with a package.

        The console's Approvals tab. Not a form of our own: the engine's
        form already knows which reviewer kinds exist and which fields can
        name one, and a second copy would drift from it. What the builder
        adds is the scope -- the rules *for the model on the canvas* -- and
        the package the rule created there is written into, so it is source
        rather than a row that gates records here and nowhere else: the
        console's own package when it names one, else the suggested one.

        A model that is not gated yet still gets its list: empty, with the
        help text saying that the gate comes first, since a rule on a model
        without the mixin is not an error -- it silently never fires.
        """
        typed.security(self)._assert_builder_user()
        package = typed.model(self.env, BuilderPackage)._chosen(package_id)
        domain: list[tuple[str, str, object]] = []
        context: dict[str, object] = {"builder_package_id": package.id or False}
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
                    "builder, then come back here to say who approves what."
                ),
            )
        return "<p class='o_view_nocontent_smiling_face'>%s</p><p>%s</p>" % (
            _("Say who must approve, and in what order"),
            _(
                "Rules you create here are written into your builder package, "
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
        typed.security(self)._assert_builder_user()
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
            # `builder_domain.py`'s own `fields_for` already documents for
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
    def _resolve_transition(
        self,
        model_name: str,
        state_field: str,
        state_from: list[str] | None,
        state_to: list[str] | None,
        cancel_state: str | None,
    ) -> GateConfigJSON:
        """The transition as it will be written, or the reason it cannot be.

        **Every way into a gated state has to be an origin.** The engine asks
        for approval only when a ``write()`` moves the record out of
        ``_state_from`` into ``_state_to``, and a builder-made status field is
        an ordinary writable column with a clickable statusbar: a state left
        out of ``_state_from`` is a state anybody can step through to walk
        round the gate (draft -> in progress -> done, when only draft -> done
        was named). So the origins are *every* value that is not a
        destination, and a narrower list is refused rather than written as a
        gate that only looks like one. What is written is that rule, not the
        list it gives today (``STATE_FROM_SOURCE``), so a value added to the
        field later is an origin too.

        A field whose values cannot be listed is refused outright: coverage
        of every way in cannot be checked there, and the rule written into
        the class has to list them at run time.
        """
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
        ordered = [v for v, _label in self._selection_values(model_name, state_field)]
        values = set(ordered)
        if not values:
            # Not a selection, or one built by a callable that needs a record.
            # Nothing named could be checked, and no list of origins -- the
            # caller's or the run-time one -- could be shown to cover every
            # way in.
            raise UserError(
                _(
                    "The values of %(field)s cannot be listed, so there is no "
                    "way to make sure approval is asked on every way into "
                    "%(to)s. Gate a stored selection field whose values are "
                    "fixed.",
                    field=state_field,
                    to=", ".join(state_to),
                )
            )
        named = set(state_from or []) | set(state_to)
        if cancel_state:
            named.add(cancel_state)
        unknown = named - values
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
        if cancel_state and cancel_state in state_to:
            raise UserError(
                _(
                    "%s cannot be both a state that needs approving into and "
                    "the cancelled state, which drops the approvals asked for.",
                    cancel_state,
                )
            )
        origins = list(state_from or []) or [v for v in ordered if v not in state_to]
        overlap = set(origins) & set(state_to)
        if overlap:
            raise UserError(
                _(
                    "%s is on both sides of the transition, so there is no "
                    "moment at which approval could be asked for.",
                    ", ".join(sorted(overlap)),
                )
            )
        if not origins:
            raise UserError(
                _(
                    "Every value of %s needs approving into, so there is no "
                    "state a record could wait for its approval in.",
                    state_field,
                )
            )
        uncovered = [v for v in ordered if v not in origins and v not in state_to]
        if uncovered:
            raise UserError(
                _(
                    "Approval would not be asked for from: %(uncovered)s. "
                    "%(field)s is an ordinary writable field, so a record "
                    "could be moved there first and on into %(to)s with no "
                    "approval at all. Leave the origin states empty to gate "
                    "every way in, or add the missing ones.",
                    uncovered=", ".join(uncovered),
                    field=state_field,
                    to=", ".join(state_to),
                )
            )
        return {
            "state_field": state_field,
            "state_from": origins,
            "state_to": state_to,
            "cancel_state": cancel_state or NO_CANCEL_STATE,
        }

    # -- enabling, changing, disabling --------------------------------------

    @api.model
    def _writable_package(self, package_id: int, model_name: str) -> BuilderPackage:
        typed.security(self)._assert_builder_manager()
        package = typed.model(self.env, BuilderPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a builder package to record this in."))
        package._assert_writable()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        return package

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

        ``state_from`` left empty means every state that is not a
        destination, which is the only reading under which the gate cannot
        be walked round (`_resolve_transition`).

        ``apply`` reloads the module, which is what makes the mixin live.
        Separable for the same reason it is in code graduation: `action_apply`
        commits, and a commit is unreachable from a `TransactionCase`.
        """
        package = self._writable_package(package_id, model_name)
        config = self._resolve_transition(
            model_name, state_field, state_from, state_to, cancel_state
        )
        picker = self._model_picker(package)
        gated = self._gated_spec(package, model_name, config)
        self._commit_sources(
            package,
            {
                model_name: gated,
                "tier.definition": self._picker_spec(
                    picker, set(self._gated_models(package)) | {model_name}
                ),
            },
            apply=apply,
            reason=_("enable approvals on %s", model_name),
        )
        return {"model": model_name, "applied": apply}

    @api.model
    def reconfigure(
        self,
        package_id: int,
        model_name: str,
        state_field: str = "state",
        state_from: list[str] | None = None,
        state_to: list[str] | None = None,
        cancel_state: str | None = None,
        apply: bool = True,
    ) -> EnableApprovalJSON:
        """Change the transition a gated model asks approval for.

        The whole configuration is restated, as it is when enabling: four
        attributes that only make sense together are not something to patch
        one at a time.
        """
        package = self._writable_package(package_id, model_name)
        config = self._resolve_transition(
            model_name, state_field, state_from, state_to, cancel_state
        )
        picker = self._model_picker(package)
        gated = self._gated_spec(package, model_name, config, replace=True)
        self._commit_sources(
            package,
            {
                model_name: gated,
                "tier.definition": self._picker_spec(
                    picker, set(self._gated_models(package)) | {model_name}
                ),
            },
            apply=apply,
            reason=_("change approvals on %s", model_name),
        )
        return {"model": model_name, "applied": apply}

    @api.model
    def disable(
        self, package_id: int, model_name: str, apply: bool = True
    ) -> EnableApprovalJSON:
        """Take the gate back out of ``model_name``'s class.

        Exactly what enabling wrote, and nothing else: the mixin, its
        configuration, the creation guard and the model's line in the rule
        picker. The rules themselves are records and stay where they are --
        with no gate they never fire, and the pane says so -- because
        deleting somebody's rules as a side effect of a toggle is not a
        thing to do quietly.
        """
        package = self._writable_package(package_id, model_name)
        entry = self._gated_entry(package, model_name)
        spec = entry._current_spec() if entry else None
        if spec is None or MIXIN not in spec.inherit:
            raise UserError(self._not_gated_here(package, model_name))
        picker = self._model_picker(package)
        ungated = _replace(
            spec,
            inherit=tuple(i for i in spec.inherit if i != MIXIN),
            class_attrs=tuple(
                (k, v) for k, v in spec.class_attrs if k not in GATE_ATTRS
            ),
            methods=self._without_gate_methods(spec, model_name),
        )
        self._commit_sources(
            package,
            {
                model_name: ungated,
                "tier.definition": self._picker_spec(
                    picker, set(self._gated_models(package)) - {model_name}
                ),
            },
            apply=apply,
            reason=_("disable approvals on %s", model_name),
            ungating=model_name,
        )
        return {"model": model_name, "applied": apply}

    @api.model
    def _commit_sources(
        self,
        package: BuilderPackage,
        specs: dict[str, modelspec.ModelSpec],
        apply: bool,
        reason: str,
        ungating: str | None = None,
    ) -> None:
        """Put the rewritten classes on disk, through Apply when applying.

        Every refusal has been made by the time this is called, and Apply's
        own -- a stored field it would drop, a file that does not compile or
        read back -- is made before it writes anything, because the files go
        to it as an ``overlay`` rather than being written first. Written
        first, a refusal would leave source on disk that the database and
        the running registry never agreed to, and Apply's snapshot would
        record the new bytes as the ones to roll back to.

        Without ``apply`` (a test, or a caller that applies later) the files
        are written as they are for any other unapplied edit.
        """
        if not apply:
            for model_name, spec in specs.items():
                package._seed_source_for(model_name, spec)
            return
        overlay = {
            "models/%s" % pycodegen.module_file_for(model_name): (
                pycodegen.render_model(spec)
            )
            for model_name, spec in specs.items()
        }
        overlay["models/__init__.py"] = package._render_models_init(
            sorted(package._python_module_set() | set(specs))
        )
        overlay["__init__.py"] = pycodegen.render_package_init(True)
        package.action_apply(
            reason=reason,
            allow_destructive=bool(ungating)
            and self._drops_only_the_gate(package, ungating, overlay),
            overlay=overlay,
        )

    @api.model
    def _drops_only_the_gate(
        self, package: BuilderPackage, model_name: str, overlay: dict[str, str]
    ) -> bool:
        """Whether what this apply removes is the mixin's own fields and no more.

        Apply refuses to drop a stored field without being told to, and on a
        model the package declares the mixin's fields are the package's:
        taking the mixin out removes ``validation_status`` (and the reviews
        relation), so disabling would be refused by the very guard it has to
        pass. Nothing of the user's is in them -- one is computed from the
        reviews, which live in ``tier.review`` and stay -- so this says yes to
        exactly that and to nothing else: any other pending removal in the
        package still gets Apply's own refusal. The column is kept under
        another name, as it is for any confirmed removal.

        Asked of the files Apply is about to write -- the render plus the
        ``overlay`` -- not of the disk, which has not changed yet.
        """
        files = package._render_files()
        files.update(overlay)
        dropped = package._destructive_changes(files)
        if not dropped:
            return False
        mixin_fields = set(cast("dict[str, Field[Any]]", self.env[MIXIN]._fields))
        return set(dropped) == {model_name} and set(dropped[model_name]) <= mixin_fields

    @api.model
    def _not_gated_here(self, package: BuilderPackage, model_name: str) -> str:
        return _(
            "%(model)s does not have approvals turned on in %(package)s, so "
            "there is nothing here to change. A gate another module wrote is "
            "that module's to edit.",
            model=model_name,
            package=package.name,
        )

    @api.model
    def _gated_entry(
        self, package: BuilderPackage, model_name: str
    ) -> BuilderPackageModel:
        return typed.model(self.env, BuilderPackageModel).search(
            [("package_id", "=", package.id), ("model", "=", model_name)], limit=1
        )

    @api.model
    def _readable_spec(
        self, entry: BuilderPackageModel, model_name: str, package: BuilderPackage
    ) -> modelspec.ModelSpec:
        """The class as it is on disk, or a blank one if there is none yet.

        Never a blank one *instead of* a file that could not be read: the
        write that follows replaces the file, and replacing code the builder
        failed to understand deletes it. `_current_spec` freezes the row in
        that case, so the check is made after asking, not before.
        """
        spec = entry._current_spec()
        if spec is not None:
            return spec
        if entry.source != "python":
            raise UserError(
                _(
                    "%(model)s is not a class the builder can rewrite in "
                    "%(package)s (%(reason)s), so there is nowhere safe to "
                    "write the approval gate. Fix the file, or add the gate "
                    "to it by hand.",
                    model=model_name,
                    package=package.name,
                    reason=entry.parse_error or _("it is managed as data records"),
                )
            )
        return modelspec.ModelSpec(
            name=model_name,
            description="",
            class_name=pycodegen.class_name_for(model_name),
            extends=True,
        )

    @api.model
    def _gated_spec(
        self,
        package: BuilderPackage,
        model_name: str,
        config: GateConfigJSON,
        replace: bool = False,
    ) -> modelspec.ModelSpec:
        """The gated model's class with the gate in it, not yet written."""
        entry = self._gated_entry(package, model_name)
        if replace and not entry:
            raise UserError(self._not_gated_here(package, model_name))
        if not entry:
            entry = typed.model(self.env, BuilderPackageModel)._adopt(
                package, model_name, extends=True
            )
        spec = self._readable_spec(entry, model_name, package)
        gated = MIXIN in spec.inherit
        if gated and not replace:
            raise UserError(_("%s already has approvals turned on.", model_name))
        if replace and not gated:
            raise UserError(self._not_gated_here(package, model_name))

        attrs = dict(spec.class_attrs)
        # `_py`, never a bare '"%s"': these are written into a class body, and
        # a value with a quote in it would otherwise be source of its own.
        attrs["_state_field"] = pycodegen._py(config["state_field"])
        # The rule, not today's list: see STATE_FROM_SOURCE and `ORIGINS`.
        # `config` carries the list too, which is what `_resolve_transition`
        # checked.
        attrs["_state_from"] = STATE_FROM_SOURCE
        attrs["_state_to"] = _py_list(config["state_to"])
        # Without this the mixin injects no buttons at all: the default is True,
        # which means "the model wires up its own UI" -- and a generated model
        # has nobody to do that.
        attrs["_tier_validation_manual_config"] = "False"
        # Always written, even when there is none. The engine's default is
        # "cancel" and it tests `state in self._cancel_state` -- a substring
        # match on a string -- so a model with no cancelled state would have
        # its approvals dropped on entering any state spelled "can" or "c".
        # The empty string matches nothing: the engine returns before the
        # test when the new state is empty. A single string, never a list.
        attrs["_cancel_state"] = pycodegen._py(config["cancel_state"])

        return _replace(
            spec,
            inherit=spec.inherit if gated else spec.inherit + (MIXIN,),
            class_attrs=tuple(attrs.items()),
            methods=self._without_gate_methods(spec, model_name) + self._gate_methods(),
        )

    @api.model
    def _create_guard(self) -> modelspec.MethodSpec:
        """The gate on creation, which the engine does not have.

        ``tier.validation`` overrides ``write()`` and nothing else, so
        ``create({"state": "done"})`` lands a record past the gate without a
        question asked. This puts a new record that is already in a gated
        state through the engine's own write-time check: a reviewer creating
        it approves it in passing, exactly as on a write, and anybody else is
        told to ask. That includes a row imported in a gated state, and a
        duplicate that lands in one (a field named ``state`` is not copied by
        default, so usually it does not) -- both are records arriving past
        the gate.

        Module data is the exception: records a module ships, loaded by the
        superuser as it installs (``install_mode``), are what the package
        says they are, and a rule loaded before them must not make the
        package uninstallable. An import by a person also runs in
        ``install_mode``, but not as the superuser, so it is still asked.

        Generated into the class, not inherited from this addon: the package
        ships to databases the builder is not installed on, and a guard that
        lived here would stop guarding there. ``_create`` rather than
        ``create`` because the block's one ``create`` is the reference
        sequence's.
        """
        return modelspec.MethodSpec(
            name=CREATE_GUARD,
            args="data_list",
            doc="Ask for approval of a record created already in a gated state.",
            body=(
                "records = super()._create(data_list)\n"
                'if self.env.su and self.env.context.get("install_mode"):\n'
                "    return records\n"
                "for record in records.with_context(skip_check_state_condition=True):\n"
                "    state = record[record._state_field]\n"
                "    if state in record._state_to:\n"
                "        record._tier_validation_check_state_on_write(\n"
                "            {record._state_field: state}\n"
                "        )\n"
                "return records"
            ),
        )

    @api.model
    def _origins_method(self) -> modelspec.MethodSpec:
        """What ``_state_from`` reads: every value but the destinations, now.

        Builder-owned by its prefix; see STATE_FROM_SOURCE for why it exists.
        """
        return modelspec.MethodSpec(
            name=ORIGINS,
            doc="Every state but the gated ones, as the field has them now.",
            body=(
                "values = self._fields[self._state_field].get_values(self.env)\n"
                "return [v for v in values if v not in self._state_to]"
            ),
        )

    @api.model
    def _gate_methods(self) -> tuple[modelspec.MethodSpec, ...]:
        """The methods enabling writes into the gated class."""
        return (self._origins_method(), self._create_guard())

    @api.model
    def _without_gate_methods(
        self, spec: modelspec.ModelSpec, model_name: str
    ) -> tuple[modelspec.MethodSpec, ...]:
        """``spec``'s methods less the ones the gate wrote.

        Recognised by what they are, not only by their names: the parser
        accepts any ``_create`` in the block as generated, and one somebody
        wrote there themselves is theirs -- as is a gate method somebody has
        since edited. Replacing or dropping either would delete it without a
        word, so finding one is a refusal instead.
        """
        ours = {m.name: m for m in self._gate_methods()}
        kept: list[modelspec.MethodSpec] = []
        for method in spec.methods:
            expected = ours.get(method.name)
            if expected is None:
                kept.append(method)
                continue
            if (method.args, method.doc.strip(), method.body.strip()) != (
                expected.args,
                expected.doc.strip(),
                expected.body.strip(),
            ):
                raise UserError(
                    _(
                        "%(model)s has a %(method)s method in its class that "
                        "approvals did not write, or that has been changed "
                        "since. Turning approvals on, changing them or turning "
                        "them off would replace or remove it, so move it below "
                        "the builder's block, or make the change by hand.",
                        model=model_name,
                        method=method.name,
                    )
                )
        return tuple(kept)

    @api.model
    def _model_picker(
        self, package: BuilderPackage
    ) -> tuple[BuilderPackageModel, modelspec.ModelSpec]:
        """The package's tier.definition extension, read before anything is
        written.

        Enabling writes two files. If the second cannot be written -- the
        class is one the builder cannot read -- that has to be known before
        the first is, or the refusal leaves a gated model on disk that no
        rule can be created for.
        """
        entry = typed.model(self.env, BuilderPackageModel)._adopt(
            package, "tier.definition", extends=True
        )
        return entry, self._readable_spec(entry, "tier.definition", package)

    @api.model
    def _picker_spec(
        self,
        picker: tuple[BuilderPackageModel, modelspec.ModelSpec],
        gated: set[str],
    ) -> modelspec.ModelSpec:
        """tier.definition's class, with a picker offering exactly ``gated``.

        ``_get_tier_validation_model_names`` returns ``[]`` in
        base_tier_validation, and its only caller is the domain on
        ``tier.definition.model_id``. Skip this and the mixin works while the
        rule cannot be created through Odoo's own form -- which is where we send
        people, so it is not optional.

        ``gated`` is the package's gated models *after* the change being
        made, which the caller knows and the disk does not yet.
        """
        _entry, spec = picker
        # Only this one method is ours to replace. Anything else on the class
        # -- a graduated automation, a later feature's override -- stays.
        methods = tuple(m for m in spec.methods if m.name != PICKER)
        if gated:
            methods += (
                modelspec.MethodSpec(
                    name=PICKER,
                    body="res = super()._get_tier_validation_model_names()\n"
                    + "res.extend(%s)\n" % _py_list(sorted(gated))
                    + "return res",
                    doc="Models this package gates, so they can be picked in a rule.",
                ),
            )
        return _replace(spec, methods=methods)

    @api.model
    def gate_config(self, model_name: str) -> GateConfigJSON | None:
        """The transition a live gated model asks approval for, else ``None``.

        Read from the loaded class, which is what is being enforced -- the
        source may already say something else until the next reload.
        """
        typed.security(self)._assert_builder_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        return self._live_gate_config(model_name)

    @api.model
    def _live_gate_config(self, model_name: str) -> GateConfigJSON | None:
        model = self.env[model_name]
        # `_inherit_module`'s stub gap is the one `_empty_state` documents;
        # the four attributes are the mixin's own, on a dynamically-named
        # model, so they are read the way any dynamic attribute is.
        if MIXIN not in model._inherit_module:  # pyright: ignore[reportAttributeAccessIssue]
            return None
        return {
            "state_field": cast("str", getattr(model, "_state_field", "state")),
            "state_from": list(cast("list[str]", getattr(model, "_state_from", []))),
            "state_to": list(cast("list[str]", getattr(model, "_state_to", []))),
            "cancel_state": cast("str", getattr(model, "_cancel_state", "")),
        }

    @api.model
    def _gated_models(self, package: BuilderPackage) -> list[str]:
        """Models in this package that already carry the mixin."""
        out: list[str] = []
        for entry in cast("BuilderPackageModel", package.model_ids):
            if entry.model == "tier.definition" or entry.source != "python":
                continue
            spec = entry._current_spec()
            if spec is not None and MIXIN in spec.inherit:
                out.append(cast("str", entry.model))
        return out


class TierDefinition(models.Model):
    """Rules created with a package in context belong to it at once.

    The Approvals tab opens the engine's own list with ``builder_package_id``
    in context, and a rule made there that stayed unowned would gate records
    in this database and ship nowhere -- and it would *work*, which is what
    makes that drift invisible. The engine's capture on create, the same one
    an automation or an access row gets; only when a package is named, so
    the engine's own form under Settings is unaffected.
    """

    _name = "tier.definition"
    _inherit = ["tier.definition", "builder.captured.on.create"]

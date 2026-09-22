# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The edit buffer: what is staged on a Python model before anything is written.

A new column needs the class re-imported, so the studio cannot make each
keystroke live the way a manual field would. Rather than hide that, it is made
legible: edits accumulate here, the tray shows exactly what is pending, and one
Apply writes and reloads once for the whole changeset.

Deliberately a ``TransientModel``. The truth is the ``.py`` file on disk; a
buffer that survived the session would be a fourth thing claiming to be the
definition, alongside the file, the registry and the reflected metadata. It is
scratch paper, and it is allowed to be thrown away.

Every operation mutates ``spec_json`` and nothing else -- no ``ir.model.fields``
writes, so no ``setup_models``, and no cluster-wide registry invalidation until
the user actually asks for one.
"""

from __future__ import annotations

import difflib
import json
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypedDict, cast

# lxml ships no type stubs in this environment, the same gap `xml_writer.py`/
# `placement.py`/`studio_serializer.py` already document -- `reportMissingTypeStubs`
# only escalates to `error` under `tools/`'s own `executionEnvironments` override
# (`pyrightconfig.json`), not at this (model) level, so the one real hit here
# (`etree` itself, an unresolvable import symbol with no stub) is the only one
# that needs silencing.
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from typing_extensions import NotRequired

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_ui_view import View

from ..tools import modelspec, pycodegen, typed, xml_writer
from ..tools import placement as placement_tool
from .studio_package_model import StudioPackageModel

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from collections.abc import Mapping

    from odoo.fields import Field

    from ..tools.lxml_types import LxmlElement
    from ..tools.modelspec import (
        FieldSpec,
        FieldTypeJSON,
        ModelSpec,
        PlacementJSON,
        SpecDiff,
    )
    from .studio_package import StudioPackage


# -- wire types -----------------------------------------------------------
#
# Traced from what each method below actually builds, cross-checked against
# `app_builder_view/static/src/console/wire.ts`'s own hand-kept interfaces
# (`shell/draft_model.ts`'s cluster, TypeScript conversion 2b). Named
# `<Thing>JSON` per this migration's own convention even where `wire.ts`
# itself drops the suffix (`DraftPayload`, `InverseOptions`,
# `ResolveRelatedResult`) -- each docstring below cites the `wire.ts` name.


class DraftPackageJSON(TypedDict):
    """``load()``'s own ``package`` key (``wire.ts:DraftPackageJSON``)."""

    id: int
    name: str
    writable: bool
    reload_mode: str


class PendingChangeJSON(TypedDict):
    """One entry of ``DraftPayloadJSON.pending`` (``_own_changes()``/
    ``pending_changes()``, matching ``wire.ts:PendingChangeJSON``).
    ``destructive`` is only ever sent on a ``"removed"`` entry; ``model``
    only on a companion model's change, spliced in by ``pending_changes``
    -- this file's own change dicts never carry it."""

    kind: Literal["model", "added", "changed", "removed"]
    name: str
    detail: str
    destructive: NotRequired[bool]
    model: NotRequired[str]


class _PreviewUnavailableJSON(TypedDict):
    available: Literal[False]
    reason: str


class _PreviewAvailableJSON(TypedDict):
    available: Literal[True]
    res_model: str
    view_id: int | Literal[False]


#: ``_preview_view()``'s own answer: which view the live preview should
#: render, or why it cannot. No `wire.ts` cousin yet -- `load()`'s own
#: `view` key stays `unknown` there (nothing reads it yet, its own comment).
PreviewViewJSON: TypeAlias = _PreviewUnavailableJSON | _PreviewAvailableJSON


class AnchorJSON(TypedDict):
    """Where one staged field was dropped, keyed by field name in
    ``DraftPayloadJSON.anchors``. Only ``view_id`` is guaranteed by this
    file's own base implementation (``_anchors()``'s docstring) --
    ``app_builder_view``'s override supplies the rest of the shape."""

    view_id: int


class DraftPayloadJSON(TypedDict):
    """``load()``'s whole round trip (``wire.ts:DraftPayload``). ``spec``
    and each entry of ``fields`` stay ``dict[str, Any]``-shaped: both are
    built by spreading ``modelspec.spec_to_json()``'s own genuinely dynamic
    (``asdict()``) return, the same open-ended judgment call
    ``studio_record_surface.py`` already made for ``describe()``."""

    id: int
    model: str
    package: DraftPackageJSON
    spec: dict[str, Any]
    fields: list[dict[str, Any]]
    pending: list[PendingChangeJSON]
    change_count: int
    field_types: list[FieldTypeJSON]
    errors: list[str]
    view: PreviewViewJSON
    anchors: dict[str, AnchorJSON]


class InverseCandidateJSON(TypedDict):
    """One entry of ``InverseOptionsJSON.candidates``."""

    name: str
    string: str


class InverseOptionsJSON(TypedDict):
    """``inverse_options()``'s whole return (``wire.ts:InverseOptions``)."""

    candidates: list[InverseCandidateJSON]
    can_create: bool
    suggested: str
    reason: str


class _ResolveRelatedOkJSON(TypedDict):
    ok: Literal[True]
    ttype: str
    comodel: str
    string: str
    stored: bool


class _ResolveRelatedFailJSON(TypedDict):
    ok: Literal[False]
    reason: str


#: ``resolve_related()``'s whole return (``wire.ts:ResolveRelatedResult``).
ResolveRelatedJSON: TypeAlias = _ResolveRelatedOkJSON | _ResolveRelatedFailJSON


class ModelDraftApplyJSON(TypedDict):
    """``action_apply()``'s whole return: what changed, and whether a
    restart is needed before it takes effect. No `wire.ts` cousin yet --
    nothing on the TypeScript side reads this call's result shape."""

    apply_id: int
    state: str
    applied: bool
    restart_required: bool
    placed: bool


class StudioModelDraft(models.TransientModel):
    _name = "studio.model.draft"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Model Draft"

    # Scratch paper, but not confetti. The server default is one hour of idle
    # time (``transient_age_limit``), measured on ``write_date``, and the daily
    # autovacuum then deletes whatever has aged out -- so a draft left open
    # over lunch could be gone by the afternoon, taking the drops the user
    # placed on the canvas with it. Pending placements have to survive a
    # working week; a week of idleness is long enough to mean "abandoned".
    #
    # `_transient_max_hours` is declared `@lazy_classproperty` on
    # `models.py` (`BaseModel`), typed `lazy_classproperty[Unknown | None]`.
    # The plain-int override every `TransientModel` subclass writes --
    # Odoo's own documented idiom, throughout core -- is not assignable to
    # that descriptor type under this stub: a real, traced vendor-stub gap
    # (TYPING.md's own "Known traps"), not fixable from this side.
    _transient_max_hours = 168  # pyright: ignore[reportAssignmentType]

    package_model_id = fields.Many2one(
        "studio.package.model", required=True, ondelete="cascade"
    )
    package_id = fields.Many2one(
        "studio.package", related="package_model_id.package_id", readonly=True
    )
    model = fields.Char(related="package_model_id.model", readonly=True)

    base_spec_json = fields.Text(
        readonly=True, help="The spec as it was when this draft was opened."
    )
    spec_json = fields.Text(help="The spec with the pending edits applied.")
    placement_json = fields.Text(
        default="{}",
        help="Which views each staged field should appear in. View intent, "
        "not class definition, so it is kept out of the spec.",
    )
    # Scaffold features staged on this draft (``scaffold.FEATURES`` keys).
    # Their fields and model options are already in the spec; what is
    # remembered here is the work a feature owes the views once its
    # columns exist -- a kanban for stages, a chatter node -- which
    # ``_apply_features`` does after the reload, like placement.
    features_json = fields.Text(default="[]")

    # A related list needs a field on the *other* model pointing back, and that
    # field has to exist by the time the registry is rebuilt or setup fails on
    # the inverse it cannot resolve. So the other model's edit is staged here
    # too, and both are written before the single reload.
    parent_draft_id = fields.Many2one(
        "studio.model.draft", ondelete="cascade", readonly=True
    )
    companion_ids = fields.One2many(
        "studio.model.draft", "parent_draft_id", readonly=True
    )

    dirty = fields.Boolean(compute="_compute_dirty")
    change_count = fields.Integer(compute="_compute_dirty")

    # -- lifecycle --------------------------------------------------------

    @api.model
    def open_for(self, package_model: StudioPackageModel) -> StudioModelDraft:
        """A draft holding whatever is on disk right now."""
        typed.security(self)._assert_studio_manager()
        payload = self._payload_for(package_model)
        vals = {
            "package_model_id": package_model.id,
            "base_spec_json": payload,
            "spec_json": payload,
        }
        # `create()` only declares `list[ValuesType]`; the single-dict form
        # is accepted at runtime (`@api.model_create_multi`), the same
        # decorator-stub gap `studio_package_model.py`'s own `_adopt`
        # already documents.
        return self.create(vals)  # pyright: ignore[reportArgumentType]

    @api.model
    def _payload_for(self, package_model: StudioPackageModel) -> str:
        """The on-disk spec as the JSON a draft stores, or why there is none."""
        spec = package_model._current_spec()
        if spec is None:
            raise UserError(
                _(
                    "%(model)s cannot be edited in the builder: %(why)s",
                    model=package_model.model,
                    why=package_model.parse_error
                    or _("its source is missing or code-owned."),
                )
            )
        return json.dumps(modelspec.spec_to_json(spec), sort_keys=True)

    @api.model
    def open_for_model(self, model_name: str) -> DraftPayloadJSON:
        """This user's draft for a model, found or made, as ``load()`` returns it.

        The view editor knows a model name and a drop location, not a draft
        id; opening a fresh draft on every drop would scatter one changeset
        across many buffers and many Applies. So the newest draft this user
        already has for the model is reused, whatever its state -- a dirty
        one holds work that must not be lost, and a clean one keeps its id so
        the console can address it -- with one refinement: a clean draft is
        re-read from disk on the way out. It has nothing to lose, and its
        baseline may predate an Apply that happened since it was opened;
        staging on a stale baseline would later splice the old block over the
        new one. Its companions and placements go the way they do on
        discard: a companion exists only to serve an edit the clean draft no
        longer has, and one that lingered would be written back by the next
        Apply from *its* baseline -- the other model as it was then, minus
        whatever has been applied to it since. A dirty draft cannot be
        refreshed the same way without discarding edits, which is the user's
        call and not this method's.

        Drafts are per user (``create_uid``; the model has no owner field
        because the editor never needed one), so two people building the
        same model do not see each other's tray. Companions are not
        candidates: they exist to serve another draft's edit.

        Only a model this package defines in Python can be staged; a live
        ``x_`` field belongs to the view editor's own path, and reaching here
        with one of those is a caller bug worth naming rather than a draft
        that could never be applied.
        """
        typed.security(self)._assert_studio_manager()
        package_model = typed.model(self.env, StudioPackageModel).search(
            [("model", "=", model_name), ("source", "in", ("python", "frozen"))],
            limit=1,
        )
        if not package_model:
            raise UserError(
                _(
                    "%s is not a model any package defines in Python, so there "
                    "is nothing to stage: add the field directly instead.",
                    model_name,
                )
            )
        draft = self.search(
            [
                ("package_model_id", "=", package_model.id),
                ("create_uid", "=", self.env.uid),
                ("parent_draft_id", "=", False),
            ],
            order="id desc",
            limit=1,
        )
        if not draft:
            draft = self.open_for(package_model)
        elif not draft.dirty:
            payload = self._payload_for(package_model)
            cast("StudioModelDraft", draft.companion_ids).unlink()
            draft.write(
                {
                    "base_spec_json": payload,
                    "spec_json": payload,
                    "placement_json": "{}",
                }
            )
        return draft.load()

    # `load` collides with `BaseModel.load(fields, data)` (the CSV-import
    # endpoint) on signature only -- an unrelated method that happens to
    # share this name, not an override in the RPC sense. Renaming is out of
    # scope for a type-only pass (the console already calls this one by
    # name over RPC); flagged, not fixed.
    def load(self) -> DraftPayloadJSON:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Everything the console needs of the draft, in one round trip."""
        self.ensure_one()
        spec = self._spec()
        placement = self._placement()
        package = cast("StudioPackage", self.package_id)
        package_model = cast("StudioPackageModel", self.package_model_id)
        return {
            "id": cast("int", self.id),
            "model": cast("str", self.model),
            "package": {
                "id": cast("int", package.id),
                "name": cast("str", package.name),
                "writable": package.writable,
                # Compute-only (`_compute_reload_mode`), never actually
                # `False` in practice -- the same "declared optional, never
                # actually absent" cast as every required-field read
                # elsewhere; `wire.ts:DraftPackageJSON` already assumes a
                # plain `string` here too.
                "reload_mode": cast("str", package.reload_mode),
            },
            "spec": modelspec.spec_to_json(spec),
            "fields": [
                {
                    # `spec_to_json`'s own declared param is `ModelSpec`,
                    # but `asdict()` (its real implementation,
                    # `modelspec.py`) is generic over any dataclass -- `f`
                    # here is a `FieldSpec`, the same frozen-dataclass
                    # shape, reused deliberately for one field's own JSON
                    # rather than the whole model's. Not a signature this
                    # file can narrow (`modelspec.py` is Phase 1b, out of
                    # scope); the same reuse `update_field`'s own `merged`
                    # makes below.
                    **modelspec.spec_to_json(f),  # pyright: ignore[reportArgumentType]
                    "type_label": self._type_label(f.ttype),
                    "placement": placement.get(
                        f.name, modelspec.default_placement(f.ttype)
                    ),
                }
                for f in spec.fields
            ],
            "pending": self.pending_changes(),
            "change_count": self.change_count,
            "field_types": modelspec.available_field_types(spec),
            "errors": self.validate(),
            "view": self._preview_view(package_model),
            "anchors": self._anchors(),
        }

    @api.model
    def _preview_view(self, package_model: StudioPackageModel) -> PreviewViewJSON:
        """Which view the live preview should render, or why it cannot.

        A model with no access rule is a normal state -- it is exactly what a
        freshly adopted one looks like -- and it is not something to crash over.
        Rendering the preview would raise an AccessError the user cannot act on
        from a modal, so the question is asked here and answered in words.

        Falls back to whatever Odoo would synthesize when there is no form
        view, so a model whose form was deleted still previews as something.
        """
        model_name = package_model.model
        if model_name not in self.env:
            return {
                "available": False,
                "reason": _(
                    "This model is not loaded yet. Apply your changes, or "
                    "reload the package."
                ),
            }
        try:
            self.env[cast("str", model_name)].check_access("read")
        except AccessError:
            return {
                "available": False,
                "reason": _(
                    "No access rule grants read on %s yet, so there is nothing "
                    "to preview. Editing still works -- add a rule and it will "
                    "appear.",
                    model_name,
                ),
            }
        view = typed.model(self.env, View).search(
            [("model", "=", model_name), ("type", "=", "form")],
            order="priority,id",
            limit=1,
        )
        return {
            "available": True,
            "res_model": cast("str", model_name),
            "view_id": cast("int", view.id) or False,
        }

    def _spec(self) -> ModelSpec:
        self.ensure_one()
        return modelspec.spec_from_json(json.loads(cast("str", self.spec_json)))

    def _base_spec(self) -> ModelSpec:
        self.ensure_one()
        return modelspec.spec_from_json(json.loads(cast("str", self.base_spec_json)))

    def _store(self, spec: ModelSpec) -> Literal[True]:
        self.ensure_one()
        self.spec_json = json.dumps(modelspec.spec_to_json(spec), sort_keys=True)
        return True

    @api.depends(
        "spec_json",
        "base_spec_json",
        "companion_ids.spec_json",
        "companion_ids.base_spec_json",
    )
    def _compute_dirty(self) -> None:
        for draft in self:
            # Companions count: staging a related list changes two models, and
            # an Apply button that stayed grey would be lying about it.
            count = 0
            for staged in draft | draft.companion_ids:
                diff = modelspec.diff_specs(staged._base_spec(), staged._spec())
                count += len(
                    diff.added + diff.removed + diff.changed + diff.model_changed
                )
            draft.change_count = count
            draft.dirty = bool(count)

    # -- operations -------------------------------------------------------

    def add_field(self, values: dict[str, Any]) -> Literal[True]:
        """Stage a new field. ``values`` is a FieldSpec-shaped dict.

        ``placement`` rides along but is not part of the spec: it says which
        views should show the field, which is a fact about the arch and not
        about the class.
        """
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        placement = values.pop("placement", None) if isinstance(values, dict) else None
        create_inverse = (
            values.pop("create_inverse", False) if isinstance(values, dict) else False
        )
        # The picker sends an entry key, which may be a preset -- "priority"
        # rather than "selection". Expanding it here means the spec only ever
        # holds real field types, and the widget the entry implies rides along
        # with placement, where view intent belongs.
        picker_key = (values or {}).get("ttype")
        values, widget = modelspec.apply_preset(values)
        values = self._resolve_computed(values)
        spec_field = modelspec.field_spec_from_json(values)
        spec = self._spec()
        if spec.field(spec_field.name):
            raise UserError(
                _("This model already has a field called '%s'.", spec_field.name)
            )
        placement = dict(placement or {})
        placement.setdefault("widget", widget)
        self._set_placement(
            spec_field.name, modelspec.clean_placement(placement, picker_key)
        )
        self._store(modelspec.with_field(spec, spec_field))
        if create_inverse and spec_field.ttype == "one2many":
            self._stage_inverse(spec_field)
        return True

    @api.model
    def _resolve_computed(self, values: Mapping[str, Any] | None) -> dict[str, Any]:
        """Give a compute body the method name and dependencies it needs.

        The field editor asks for the body, because that is the part somebody has an
        opinion about. The method name is derived -- ``pycodegen`` already owns
        the convention and generating two different answers to "what is this
        method called" is how a graduated field stops being found.

        ``depends`` is split from the comma-separated string the panel offers.
        Odoo will not recompute without it, and a stored computed field that
        never recomputes is the most confusing thing this can produce: correct
        on creation and quietly wrong forever after.
        """
        values = dict(values or {})
        body = (values.get("compute_body") or "").strip()
        if not body:
            # Clearing the body clears the whole compute, or the spec would
            # declare a method the generator has nothing to write.
            if "compute_body" in values:
                values["compute"] = None
                values["compute_body"] = None
                values["depends"] = ()
            return values
        values["compute"] = pycodegen.compute_method_name(values["name"])
        depends = values.get("depends") or ()
        if isinstance(depends, str):
            depends = [part.strip() for part in depends.split(",") if part.strip()]
        values["depends"] = tuple(depends)
        # A computed field is not stored unless somebody says so, and an
        # unstored one cannot be searched or grouped -- so the panel's answer is
        # taken literally rather than defaulted behind their back.
        values.setdefault("store", False)
        return values

    def resolve_related(self, path: str) -> ResolveRelatedJSON:
        """What a related path points at, so the picker can fill in the rest.

        A related field has no type of its own: ``partner_id.email`` is a char
        because ``email`` is, and asking the user to say so as well is asking
        them to know something the model already knows -- and to be right about
        it, since a mismatch is a registry error at load time rather than a
        message they can act on.

        Walks the chain rather than trusting it, and reports where it broke, so
        a typo in the middle names the step that failed instead of failing the
        whole Apply later.
        """
        typed.security(self)._assert_studio_user()
        self.ensure_one()
        steps = [part for part in (path or "").split(".") if part]
        if not steps:
            return {"ok": False, "reason": _("Choose a field to follow.")}
        model_name = self.model
        field = None
        for index, step in enumerate(steps):
            if model_name not in self.env:
                return {
                    "ok": False,
                    "reason": _("%s is not a model this database has.", model_name),
                }
            field = self.env[cast("str", model_name)]._fields.get(step)
            if field is None:
                return {
                    "ok": False,
                    "reason": _(
                        "%(step)s is not a field of %(model)s.",
                        step=step,
                        model=model_name,
                    ),
                }
            if index < len(steps) - 1:
                model_name = getattr(field, "comodel_name", None)
                if not model_name:
                    return {
                        "ok": False,
                        "reason": _(
                            "%s is not a relation, so nothing can follow it.", step
                        ),
                    }
        # `steps` is non-empty (checked above), so the loop always runs at
        # least once and assigns `field` before falling through here --
        # pyright cannot see that a `for` loop over a non-literal-length
        # list always executes, so the guarantee is asserted with a cast
        # rather than left as `Field | None`.
        field = cast("Field", field)
        return {
            "ok": True,
            "ttype": field.type,
            "comodel": getattr(field, "comodel_name", None) or "",
            "string": field.string or steps[-1],
            "stored": bool(field.store),
        }

    # -- relationships ----------------------------------------------------

    def inverse_options(self, comodel: str) -> InverseOptionsJSON:
        """What could link ``comodel`` back to this model, for the picker.

        Odoo needs a many2one on the other side before a related list can
        exist. Asking the user to go and build it there first is the gesture
        every studio gets wrong, so the options are: reuse a link that already
        points back, or have one made -- and if neither is possible, say why
        in the same breath rather than failing on Apply.
        """
        self.ensure_one()
        out: InverseOptionsJSON = {
            "candidates": [],
            "can_create": False,
            "suggested": "",
            "reason": "",
        }
        if not comodel:
            return out
        sibling = self._sibling(comodel)
        for name, label in self._links_back_from(comodel, sibling).items():
            out["candidates"].append({"name": name, "string": label})
        out["candidates"].sort(key=lambda entry: entry["name"])
        if sibling:
            out["can_create"] = True
            out["suggested"] = self._suggest_inverse_name(comodel)
        elif not out["candidates"]:
            out["reason"] = _(
                "%(comodel)s is not a model this package defines in Python, so "
                "the builder cannot add the link back to %(model)s for you. Add "
                "a link to %(model)s on %(comodel)s first, then pick it here.",
                comodel=comodel,
                model=self.model,
            )
        return out

    def _sibling(self, comodel: str) -> StudioPackageModel:
        """The package model for ``comodel``, if we may write to its class."""
        self.ensure_one()
        package = cast("StudioPackage", self.package_id)
        model_ids = cast("StudioPackageModel", package.model_ids)
        return model_ids.filtered(
            lambda m: m.model == comodel and m.source == "python"
        )[:1]

    def _links_back_from(
        self, comodel: str, sibling: StudioPackageModel
    ) -> dict[str, str]:
        """``{name: label}`` for every many2one on ``comodel`` aimed here.

        Read from the sibling's *file* when we own it, and only from the
        registry otherwise. A model we own may not be in the registry at all --
        that is exactly the state a just-adopted model is in, before anything
        has imported its class -- and the file is the definition regardless.
        """
        self.ensure_one()
        if sibling:
            spec = sibling._current_spec()
            return {
                f.name: f.string or f.name
                for f in (spec.fields if spec else ())
                if f.ttype == "many2one" and f.comodel == self.model
            }
        if comodel in self.env:
            return {
                name: field.string or name
                for name, field in self.env[comodel]._fields.items()
                if field.type == "many2one" and field.comodel_name == self.model
            }
        return {}

    def _names_on(self, comodel: str, sibling: StudioPackageModel) -> set[str]:
        """Every field name already used on ``comodel``, from the same source."""
        self.ensure_one()
        if sibling:
            spec = sibling._current_spec()
            return {f.name for f in (spec.fields if spec else ())}
        return set(self.env[comodel]._fields) if comodel in self.env else set()

    def _suggest_inverse_name(self, comodel: str) -> str:
        """``workshop.project`` linked from its lines becomes ``project_id``."""
        base = cast("str", self.model).rsplit(".", 1)[-1]
        taken = self._names_on(comodel, self._sibling(comodel))
        candidate = "%s_id" % base
        suffix = 2
        while candidate in taken:
            candidate = "%s_%d_id" % (base, suffix)
            suffix += 1
        return candidate

    def _companion_for(self, package_model: StudioPackageModel) -> StudioModelDraft:
        """The staged edit for another model, created on first need."""
        self.ensure_one()
        existing = cast("StudioModelDraft", self.companion_ids).filtered(
            lambda d: d.package_model_id == package_model
        )
        if existing:
            return existing[:1]
        companion = self.open_for(package_model)
        companion.parent_draft_id = self.id
        return companion

    def _stage_inverse(self, spec_field: FieldSpec) -> StudioModelDraft:
        """Put the many2one that makes ``spec_field`` resolvable on the other
        model, in the same changeset so one Apply covers both."""
        self.ensure_one()
        # `comodel`/`inverse_name` are both required for a one2many by
        # `validate_spec` (`modelspec.py`) -- both genuinely `str` by the
        # time a one2many reaches here, the same "declared optional, never
        # actually absent" cast as every required-field read elsewhere.
        sibling = self._sibling(cast("str", spec_field.comodel))
        if not sibling:
            raise UserError(
                _(
                    "The link back from %(comodel)s cannot be created here: it "
                    "is not a model this package defines in Python.",
                    comodel=spec_field.comodel,
                )
            )
        companion = self._companion_for(sibling)
        if companion._spec().field(cast("str", spec_field.inverse_name)):
            # Already there -- reusing it is exactly what the picker offers.
            return companion
        companion.add_field(
            {
                "name": spec_field.inverse_name,
                "ttype": "many2one",
                "comodel": self.model,
                "string": self._spec().description or self.model,
                # The lines of a record are meaningless once it is gone, and
                # 'set null' would leave them orphaned in every list view.
                "ondelete": "cascade",
                "index": True,
            }
        )
        return companion

    # -- placement --------------------------------------------------------

    def _placement(self) -> dict[str, Any]:
        self.ensure_one()
        return json.loads(self.placement_json or "{}")

    def _set_placement(self, name: str, values: PlacementJSON) -> Literal[True]:
        data = self._placement()
        data[name] = values
        self.placement_json = json.dumps(data, sort_keys=True)
        return True

    def set_placement(
        self, name: str, values: Mapping[str, object] | None
    ) -> Literal[True]:
        """Change which views a staged field will appear in."""
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        spec_field = self._spec().field(name)
        if not spec_field:
            raise UserError(_("There is no field called '%s' to place.", name))
        return self._set_placement(
            name, modelspec.clean_placement(values, spec_field.ttype)
        )

    def update_field(self, name: str, values: dict[str, Any]) -> Literal[True]:
        """Replace one field, keeping its position in the class."""
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        placement = values.pop("placement", None) if isinstance(values, dict) else None
        spec = self._spec()
        existing = spec.field(name)
        if not existing:
            raise UserError(_("There is no field called '%s' to change.", name))
        picker_key = (values or {}).get("ttype", existing.ttype)
        values, widget = modelspec.apply_preset(values)
        values = self._resolve_computed({**values, "name": name})
        if placement is not None:
            placement = dict(placement)
            # Only when the entry brings one and the user has not chosen: a
            # re-edit that changed nothing must not silently reinstate a widget
            # somebody deliberately cleared.
            if widget and "widget" not in placement:
                placement["widget"] = widget
            self._set_placement(name, modelspec.clean_placement(placement, picker_key))
        # Same `spec_to_json`-on-a-`FieldSpec` reuse as `load()`'s own
        # `fields` comprehension above -- see its comment for why this is a
        # deliberate, safe (if narrowly-typed) call rather than a bug.
        merged = {
            **modelspec.spec_to_json(existing),  # pyright: ignore[reportArgumentType]
            **values,
            "name": name,
        }
        return self._store(
            modelspec.with_field(spec, modelspec.field_spec_from_json(merged))
        )

    def remove_field(self, name: str) -> Literal[True]:
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        spec = self._spec()
        if not spec.field(name):
            raise UserError(_("There is no field called '%s' to remove.", name))
        data = self._placement()
        if data.pop(name, None) is not None:
            self.placement_json = json.dumps(data, sort_keys=True)
        return self._store(modelspec.without_field(spec, name))

    def move_field(self, name: str, before: str | None = None) -> Literal[True]:
        """Reorder. Field order is class order, which is the order the
        scaffolded views show them in -- so this is a layout gesture."""
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        spec = self._spec()
        moving = spec.field(name)
        if not moving:
            raise UserError(_("There is no field called '%s' to move.", name))
        rest = [f for f in spec.fields if f.name != name]
        if before is None:
            ordered = rest + [moving]
        else:
            index = next((i for i, f in enumerate(rest) if f.name == before), len(rest))
            ordered = rest[:index] + [moving] + rest[index:]
        from dataclasses import replace as _replace

        return self._store(_replace(spec, fields=tuple(ordered)))

    def set_model_options(self, values: dict[str, Any]) -> Literal[True]:
        """Change what the class says about itself: order, display field, mixins."""
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        allowed = {
            "description",
            "order",
            "rec_name",
            "active_name",
            "inherit",
            "sequence_code",
            "sequence_field",
        }
        unknown = set(values) - allowed
        if unknown:
            raise UserError(
                _("Not something the builder sets: %s", ", ".join(sorted(unknown)))
            )
        data = modelspec.spec_to_json(self._spec())
        data.update(values)
        if "inherit" in values:
            data["inherit"] = tuple(values["inherit"])
        return self._store(modelspec.spec_from_json(data))

    # -- features ---------------------------------------------------------

    def _features(self) -> list[str]:
        self.ensure_one()
        try:
            return cast("list[str]", list(json.loads(self.features_json or "[]")))
        except ValueError:
            return []

    def stage_feature(self, key: str) -> list[str]:
        """Remember that ``key`` was added; its fields are staged separately."""
        self.ensure_one()
        keys = self._features()
        if key not in keys:
            keys.append(key)
            self.features_json = json.dumps(keys)
        return keys

    def _apply_features(self) -> bool:
        """The view work a feature owes once its columns are live.

        Nothing here: a package without the view editor has no way to add
        a view or a chatter node, and the feature's fields are already on
        screen through placement. The view addon overrides this.
        """
        self.ensure_one()
        self.features_json = "[]"
        return False

    # -- what the tray shows ----------------------------------------------

    def pending_changes(self) -> list[PendingChangeJSON]:
        """One entry per staged edit, in the order a person would read them.

        Companion edits are listed with their model, because "you are also
        about to change workshop.task" is exactly the thing a user would be
        annoyed to discover only in the diff.
        """
        self.ensure_one()
        out = self._own_changes()
        for companion in cast("StudioModelDraft", self.companion_ids):
            for change in companion._own_changes():
                out.append({**change, "model": cast("str", companion.model)})
        return out

    def _own_changes(self) -> list[PendingChangeJSON]:
        self.ensure_one()
        before, after = self._base_spec(), self._spec()
        diff = modelspec.diff_specs(before, after)
        out: list[PendingChangeJSON] = []
        for attr in diff.model_changed:
            out.append(
                {
                    "kind": "model",
                    "name": attr,
                    "detail": _(
                        "%(attr)s: %(old)s → %(new)s",
                        attr=attr,
                        old=getattr(before, attr) or _("unset"),
                        new=getattr(after, attr) or _("unset"),
                    ),
                }
            )
        for name in diff.added:
            # `name` comes from `diff.added`, which `diff_specs`
            # (`modelspec.py`) only ever populates with names already
            # present in `after` -- `.field(name)` is therefore never
            # `None` here, unlike its general `FieldSpec | None` signature.
            spec_field = cast("FieldSpec", after.field(name))
            out.append(
                {
                    "kind": "added",
                    "name": name,
                    "detail": _(
                        "%(label)s (%(type)s)",
                        label=spec_field.string or name,
                        type=self._type_label(spec_field.ttype),
                    ),
                }
            )
        for name in diff.changed:
            out.append({"kind": "changed", "name": name, "detail": _("edited")})
        for name in diff.removed:
            destructive = name in diff.dropped_columns
            out.append(
                {
                    "kind": "removed",
                    "name": name,
                    "destructive": destructive,
                    "detail": _("removed — its data would be kept aside")
                    if destructive
                    else _("removed"),
                }
            )
        return out

    @api.model
    def _type_label(self, ttype: str) -> str:
        entry = modelspec.FIELD_TYPES_BY_TTYPE.get(ttype)
        return entry.label if entry else ttype

    @api.model
    def field_types(self, spec_json: str | None = None) -> list[FieldTypeJSON]:
        """The picker's contents, for the current draft state."""
        spec = (
            modelspec.spec_from_json(json.loads(spec_json))
            if spec_json
            else self._spec()
        )
        return modelspec.available_field_types(spec)

    def preview_source(self) -> str:
        """The block exactly as Apply would write it."""
        self.ensure_one()
        return pycodegen.render_block(self._spec())

    def preview_diff(self) -> str:
        """A unified diff of every block Apply will write, so it is never a
        leap of faith -- including the one on the other model."""
        self.ensure_one()
        chunks = []
        for draft in self | self.companion_ids:
            base = pycodegen.render_block(draft._base_spec())
            before = base.splitlines(keepends=True)
            after = pycodegen.render_block(draft._spec()).splitlines(keepends=True)
            body = "".join(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile="%s (before)" % draft.model,
                    tofile="%s (after)" % draft.model,
                    n=3,
                )
            )
            if body:
                chunks.append(body)
        return "\n".join(chunks)

    def validate(self) -> list[str]:
        """Problems the user can still fix, before anything is written.

        Companions are validated too: they apply in the same transaction, so a
        problem on the other model is a problem with *this* Apply, and finding
        it afterwards would mean finding it during a rollback.
        """
        self.ensure_one()
        known = set(
            cast(
                "list[str]",
                typed.model(self.env, IrModel).sudo().search([]).mapped("model"),
            )
        )
        out: list[str] = []
        for draft in self | self.companion_ids:
            errors = modelspec.validate_spec(
                draft._spec(), taken_model_names=known - {cast("str", draft.model)}
            )
            prefix = "" if draft == self else "%s: " % draft.model
            out.extend("%s%s" % (prefix, error) for error in errors)
        return out

    # -- commit -----------------------------------------------------------

    def action_apply(self, allow_destructive: bool = False) -> ModelDraftApplyJSON:
        """Write every staged block and reload, once, for the whole changeset.

        A related list and the link back are two files and must be one reload:
        writing only the one2many would leave the registry resolving an
        inverse that does not exist yet, and the setup it fails is the setup
        that was meant to create it.
        """
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        errors = self.validate()
        if errors:
            raise UserError(
                _("This change cannot be applied:\n\n%s", "\n".join(errors))
            )
        package = cast("StudioPackage", self.package_id)
        package._assert_writable()

        drafts = self | self.companion_ids
        payload: dict[str, str] = {}
        planned: list[tuple[StudioModelDraft, ModelSpec, SpecDiff]] = []
        for draft in drafts:
            spec = draft._spec()
            package_model = cast("StudioPackageModel", draft.package_model_id)
            payload[cast("str", package_model.python_path)] = draft._rewritten_source(
                spec
            )
            diff = modelspec.diff_specs(draft._base_spec(), spec)
            planned.append((draft, spec, diff))

        # Removals go first, and that ordering is not stylistic. The upgrade
        # re-imports the package's view files, so a <field> naming a column
        # this apply drops would fail the import and roll the whole thing back.
        # Taking it out of the arch now means the file rendered *by* the apply
        # is already consistent. Removing a field from a view is safe to do
        # before the reload; adding one is not.
        for draft, _spec, diff in planned:
            draft._retract_from_views(diff)

        # The rewritten sources travel as an overlay rather than being
        # written here first: the apply snapshots what is on disk before it
        # writes, and a file written ahead of it would be "restored" to the
        # very change a rollback is meant to undo.
        applied = package.action_apply(
            reason=_("edit %s", self.model),
            allow_destructive=allow_destructive,
            overlay=payload,
        )
        if applied.state == "awaiting_restart":
            # Written, committed, not loaded: the columns do not exist yet,
            # so the views cannot name them and the baseline must not move
            # -- the draft stays dirty until `place_pending` runs after the
            # restart, which is the honest state of a change not yet live.
            return {
                "apply_id": cast("int", applied.id),
                "state": cast("str", applied.state),
                "applied": False,
                "restart_required": True,
                "placed": False,
            }
        # Additions can only go in afterwards: the registry has to have the
        # column before a view naming it will validate.
        for draft, spec, diff in planned:
            draft._place_in_views(spec, diff)
            draft._apply_features()
        # The file is the definition, so each draft's baseline moves with it.
        for draft in drafts:
            draft.base_spec_json = draft.spec_json
        return {
            "apply_id": cast("int", applied.id),
            "state": cast("str", applied.state),
            "applied": True,
            "restart_required": False,
            "placed": True,
        }

    def _rewritten_source(self, spec: ModelSpec) -> str:
        """This model's file with the studio block replaced by ``spec``."""
        self.ensure_one()
        package_model = cast("StudioPackageModel", self.package_model_id)
        package = cast("StudioPackage", self.package_id)
        source = package._read_source(cast("str", package_model.python_path))
        if source is None:
            raise UserError(
                _("%s has no source file to write into.", package_model.model)
            )
        return pycodegen.ensure_imports(
            pycodegen.splice_block(source, pycodegen.render_block(spec), spec), spec
        )

    # -- views ------------------------------------------------------------

    def _owned_views(self) -> dict[str, View]:
        """The views this package owns for this model, by type."""
        views = typed.model(self.env, View).search(
            [
                ("model", "=", self.model),
                ("mode", "=", "primary"),
                ("studio_package_id", "=", cast("StudioPackage", self.package_id).id),
                ("type", "in", ("form", "list", "search")),
            ]
        )
        return {cast("str", view.type): view for view in views}

    def _retract_from_views(self, diff: SpecDiff) -> bool:
        """Take dropped fields out of the arches, before the reload sees them."""
        if not diff.removed:
            return False
        touched = typed.model(self.env, View).browse()
        for view in self._owned_views().values():
            root = xml_writer.parse_arch(cast("str", view.arch))
            changed = False
            for name in diff.removed:
                changed |= placement_tool.remove_field(root, name)
            if changed:
                self._write_arch(view, root)
                touched |= view
        if touched:
            cast("StudioPackage", self.package_id).studio_capture(touched)
        # Deliberately no file write: the apply that follows renders the whole
        # package anyway, and these arches are part of what it renders.
        return bool(touched)

    def _anchors(self) -> dict[str, AnchorJSON]:
        """Where each staged field was dropped, keyed by field name.

        Nothing here: the slots in ``placement_json`` say *which* views show a
        field, never where in them. A drop location is a fact about one arch
        -- a view id and a position inside it -- and minting or resolving one
        is the view editor's business, so ``app_builder_view`` stores the
        anchors and overrides this to return them. Every entry carries the
        ``view_id`` it belongs to; the rest of its shape is the overrider's.
        """
        self.ensure_one()
        return {}

    def _place_anchored(
        self, view: View, name: str, anchor: AnchorJSON, widget: str
    ) -> bool:
        """Put one field exactly where it was dropped, or say it could not.

        The hook ``_place_in_views`` tries before the balanced placement.
        Returning ``False`` here is not a failure: this addon cannot route an
        insertion through the view editor, because it must not depend on
        ``app_builder_view``, and the balanced slot is the honest fallback --
        the field still appears, just not at the remembered spot. The
        override is expected to write the view itself, so a ``True`` means
        "done, and the arch has changed underneath you".
        """
        self.ensure_one()
        return False

    def _place_in_views(self, spec: ModelSpec, diff: SpecDiff) -> bool:
        """Put added fields on screen, now that the columns exist.

        Safe to run twice. Under a ``restart`` reload the request can die
        between the reload and this step, and the console re-runs placement
        once it reconnects; a field the arch already names is left where it
        is rather than rendered a second time.
        """
        if not diff.added:
            return False
        placement = self._placement()
        anchors = self._anchors()
        touched = typed.model(self.env, View).browse()
        anchored = False
        for view_type, view in self._owned_views().items():
            # Anchored fields go first and through the hook, which writes the
            # view on its own. The arch the balanced fallback edits is parsed
            # only afterwards, so writing it back cannot clobber the hook's.
            fallback: list[tuple[str, FieldSpec, Any, str]] = []
            for name in diff.added:
                spec_field = spec.field(name)
                if not spec_field or spec_field.name in placement_tool.NEVER_PLACE:
                    continue
                where = placement.get(
                    name, modelspec.default_placement(spec_field.ttype)
                )
                widget = where.get("widget") or ""
                anchor = anchors.get(name)
                if (
                    anchor
                    and anchor.get("view_id") == view.id
                    and not self._arch_names(view, name)
                    and self._place_anchored(view, name, anchor, widget)
                ):
                    anchored = True
                    continue
                fallback.append((name, spec_field, where, widget))
            if not fallback:
                continue
            root = xml_writer.parse_arch(cast("str", view.arch))
            changed = False
            for name, spec_field, where, widget in fallback:
                label = spec_field.string or name
                if view_type == "form" and where.get("form"):
                    changed |= placement_tool.place_in_form(
                        root, name, spec_field.ttype, label, widget
                    )
                elif view_type == "list" and where.get("list"):
                    changed |= placement_tool.place_in_list(root, name, widget)
                elif view_type == "search":
                    if where.get("search"):
                        changed |= placement_tool.place_in_search(root, name)
                    if where.get("group_by"):
                        changed |= placement_tool.place_group_by(root, name, label)
            if changed:
                self._write_arch(view, root)
                touched |= view
        if touched:
            cast("StudioPackage", self.package_id).studio_capture(touched)
        if touched or anchored:
            # Views are data: they take effect immediately and need no reload,
            # so writing the files here keeps git in step without a second one.
            cast("StudioPackage", self.package_id).action_write_files()
        return bool(touched or anchored)

    @api.model
    def _arch_names(self, view: View, name: str) -> bool:
        """Whether a view's own arch already shows ``name`` anywhere.

        Anywhere, subviews included: a field rendered twice in one form is the
        bug users report as "it saved my value in the wrong box".
        """
        return bool(
            xml_writer.parse_arch(cast("str", view.arch)).xpath(
                ".//field[@name='%s']" % name
            )
        )

    def _write_arch(self, view: View, root: LxmlElement) -> View:
        xml_writer.canonicalize_attributes(root)
        xml_writer.indent(root)
        try:
            view.write({"arch": etree.tostring(root, encoding="unicode")})
        except ValidationError as err:
            raise UserError(
                _(
                    "%(model)s was changed, but its %(type)s view could not be "
                    "updated to match:\n\n%(err)s",
                    model=self.model,
                    type=view.type,
                    err=err,
                )
            ) from err
        return view

    def action_discard(self) -> Literal[True]:
        self.ensure_one()
        self.spec_json = self.base_spec_json
        self.placement_json = "{}"
        self.features_json = "[]"
        # A companion exists only to serve an edit on this draft, so discarding
        # that edit leaves nothing for it to do.
        cast("StudioModelDraft", self.companion_ids).unlink()
        return True

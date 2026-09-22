# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for model metadata: ``ir.model`` and its fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from odoo import api, models

from ...tools import typed
from ..studio_package_model import StudioPackageModel
from ..studio_serializer import SEQ_FIELD, SEQ_MODEL, SEQ_SELECTION

if TYPE_CHECKING:
    # Only used inside annotations/casts below (`from __future__ import
    # annotations` defers all of them to strings), never at runtime -- same
    # bargain every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.models import BaseModel

    # Core Odoo, reached only through the merged odoo-nix tree -- the
    # fully-qualified `odoo.addons....` form is correct here, not same-addon
    # (TYPING.md's "Known traps"/house conventions), the same as
    # `studio_package.py`'s own `IrModel`/`IrModelFields`/`IrModelSelection`
    # imports.
    from odoo.addons.base.models.ir_model import (
        IrModel,
        IrModelFields,
        IrModelSelection,
    )

    # Same-addon cross-file import, so relative (house convention). Only
    # needed for the `super()` cast -- see its own comment. `StudioPackageModel`
    # (above, real import) needs no such guard: `typed.model()` reads `cls
    # ._name` at *runtime*, so it needs a real, module-level binding, not a
    # `TYPE_CHECKING`-only one (confirmed by ruff's TC004 -- "Import is used
    # for more than type hinting" -- once `typed.model(self.env,
    # StudioPackageModel)` below was written).
    from ..studio_serializer import StudioSerializer


class IrModelSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model"

    _studio_model = "ir.model"
    _studio_sequence = SEQ_MODEL
    _studio_dir = "models"
    _studio_fields = ("name", "model", "info", "order", "transient")
    _studio_ignored = (
        # Defaults to 'manual', which is what _ownable already requires, and
        # emitting a readonly field would be noise in every diff.
        "state",
        # Fields, ACLs and record rules each have a serializer of their own and
        # are emitted as their own records; writing the inverse side as well
        # would define every one of them twice.
        "field_id",
        "access_ids",
        "rule_ids",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        # `model` (`ir.model`) is a required Char, so it is never really the
        # `Literal[False]` half of the field's own `str | Literal[False]`
        # read type -- same reasoning as `pycodegen.py`'s own `model_name`.
        return cast("str", cast("IrModel", record).model)

    @api.model
    def _ownable(self, record: BaseModel) -> bool:
        model = cast("IrModel", record)
        # Only custom models. A base model reflected from Python code is owned
        # by the addon that declares it, not by a studio package.
        if model.state != "manual":
            return False
        # And never one a package already defines as a Python class. Such a row
        # is a reconciliation artefact, not a definition -- emitting it would
        # give _add_manual_models a second class competing for the same _name.
        return not typed.model(self.env, StudioPackageModel)._is_python_owned(
            model.model
        )

    @api.model
    def _should_skip(self, record: BaseModel, fname: str) -> bool:
        if fname == "info" and self._is_inherited_docstring(
            cast("IrModel", record).info
        ):
            # _reflect_model_params fills 'info' from the first docstring in the
            # class MRO (ir_model.py:433), so a model the user never documented
            # comes back carrying models.Model's own docstring. That is an
            # artifact of reflection, not content worth committing.
            return True
        # `IrModelSerializer`'s only real Python base is `models.AbstractModel`
        # -- `StudioSerializer` is composed in only via Odoo's registry-level
        # `_inherit`, never a literal Python base class, so it is absent from
        # the MRO pyright can see and `super()._should_skip` resolves against
        # `object` alone. Same underlying "_inherit-mixin-invisible-to-pyright"
        # gap `typed.security()` exists for, applied to `super()` instead of
        # `self` -- at runtime, Odoo's registry builds the real merged class
        # with `StudioSerializer` genuinely in the MRO, so `super()` resolves
        # this exactly as it always did.
        return cast("StudioSerializer", super())._should_skip(record, fname)

    @api.model
    def _is_inherited_docstring(self, info: str | Literal[False]) -> bool:
        if not info:
            return True
        base_doc = (models.Model.__doc__ or "").strip()
        return bool(base_doc) and info.strip() == base_doc


class IrModelFieldsSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model.fields"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model.fields"

    _studio_model = "ir.model.fields"
    _studio_sequence = SEQ_FIELD
    _studio_dir = "models"
    # Ordered to read like a field definition: identity, then type, then
    # behaviour, then the type-specific tail. Mirrors _instanciate_attrs in
    # odoo/addons/base/models/ir_model.py.
    _studio_fields = (
        "name",
        "model_id",
        "field_description",
        "ttype",
        "help",
        "required",
        "readonly",
        "index",
        "copied",
        "store",
        "translate",
        "selectable",
        "group_expand",
        "related",
        "compute",
        "depends",
        "relation",
        "relation_field",
        "relation_table",
        "column1",
        "column2",
        "domain",
        "on_delete",
        "size",
        "currency_field",
        "sanitize",
        "sanitize_overridable",
        "sanitize_tags",
        "sanitize_attributes",
        "sanitize_style",
        "sanitize_form",
        "strip_style",
        "strip_classes",
        # Definitional rather than decorative: _instanciate_attrs passes it
        # straight to the field, and a company-dependent column stores a value
        # per company. Readonly in the UI, but reachable through create() --
        # and losing it would change what the column *is*, silently.
        "company_dependent",
    )
    _studio_ignored = (
        # Always 'manual' here -- _ownable refuses anything else.
        "state",
        # Derived in create() from model_id (ir_model.py:1044), so emitting it
        # would restate what model_id already says.
        "model",
        # The selection values have a serializer of their own.
        "selection_ids",
        # Computed from `related` / `relation_field`, both of which are emitted.
        "related_field_id",
        "relation_field_id",
        # Vestigial in core: `groups` is marked "CLEANME unimplemented field
        # (empty table)" at ir_model.py:588, and `complete_name` has no writer
        # anywhere in base. Neither can carry a decision because nothing can
        # set them.
        "groups",
        "complete_name",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        field = cast("IrModelFields", record)
        # `model_id` (`ir.model.fields`) is a plain-string-comodel Many2one in
        # core -- same `_Relational.__get__` gap as `studio_package.py`'s own
        # `_suggest_xmlid` already hit on this exact field.
        model = cast("IrModel", field.model_id)  # pyright: ignore[reportUnknownMemberType]
        return cast("str", model.model)

    @api.model
    def _ownable(self, record: BaseModel) -> bool:
        field = cast("IrModelFields", record)
        # Excludes the magic columns and any field declared in Python.
        if field.state != "manual":
            return False
        # A field on a Python-defined model belongs to that class, even while
        # its metadata row still says manual.
        model = cast("IrModel", field.model_id)  # pyright: ignore[reportUnknownMemberType]
        return not typed.model(self.env, StudioPackageModel)._is_python_owned(
            model.model
        )

    @api.model
    def _should_skip(self, record: BaseModel, fname: str) -> bool:
        field = cast("IrModelFields", record)
        # HTML sanitize flags only mean anything on html fields, and several
        # default to True -- emitting them on a char field would be pure noise
        # that also survives round-trip, so filter by type rather than value.
        if fname.startswith(("sanitize", "strip_")) and field.ttype != "html":
            return True
        if fname == "copied":
            # 'copied' is computed (ir_model.py:651) rather than defaulted, so
            # the generic default comparison cannot see it. Emit it only when
            # the user overrode what the compute would have produced.
            computed = (field.ttype != "one2many") and not (
                field.related or field.compute
            )
            return field.copied == computed
        if fname == "size" and field.ttype != "char":
            return True
        if fname == "currency_field" and field.ttype != "monetary":
            return True
        if fname in ("relation_field",) and field.ttype != "one2many":
            return True
        if fname in ("relation_table", "column1", "column2") and (
            field.ttype != "many2many"
        ):
            return True
        if fname == "on_delete" and field.ttype != "many2one":
            return True
        if fname == "translate" and field.ttype not in ("char", "text", "html"):
            return True
        return cast("StudioSerializer", super())._should_skip(record, fname)


class IrModelFieldsSelectionSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model.fields.selection"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model.fields.selection"

    _studio_model = "ir.model.fields.selection"
    _studio_sequence = SEQ_SELECTION
    _studio_dir = "models"
    _studio_fields = ("field_id", "value", "name", "sequence")

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        selection = cast("IrModelSelection", record)
        # Same gap as `IrModelFieldsSerializer._group_model` above, one level
        # up: `field_id` (`ir.model.fields.selection`) is also a
        # plain-string-comodel Many2one.
        field = cast("IrModelFields", selection.field_id)  # pyright: ignore[reportUnknownMemberType]
        model = cast("IrModel", field.model_id)  # pyright: ignore[reportUnknownMemberType]
        return cast("str", model.model)

    @api.model
    def _ownable(self, record: BaseModel) -> bool:
        selection = cast("IrModelSelection", record)
        # ir.model.fields.selection has no state of its own, so inherit the
        # field's. Once the field is code-defined, its values are declared by
        # the Python class and emitting <record> rows as well would define the
        # same selection twice.
        field = cast("IrModelFields", selection.field_id)  # pyright: ignore[reportUnknownMemberType]
        return field.state == "manual"

    @api.model
    def _sort_key(self, record: BaseModel, xmlid: str) -> tuple[int, int, str, str]:
        # Selection order is semantic (it drives the dropdown), so sort by the
        # declared sequence first; `value` breaks ties the same way pycodegen
        # does, so the XML and the graduated Python agree.
        #
        # A wider tuple than the base's own declared `tuple[int, str]` --
        # true, not narrowed, of every real `_sort_key` override in this file
        # set (`ir_ui_menu.py`, `ir_actions.py`, `ir_ui_view.py`,
        # `app_builder_approval/models/tier_serializers.py` all return a
        # 3-or-4-tuple too); flagged, not silently squeezed back to two
        # elements, which would either drop a real sort key or lie about the
        # type. See this file's own PR notes.
        selection = cast("IrModelSelection", record)
        return (
            self._studio_sequence,
            selection.sequence,
            cast("str", selection.value),
            xmlid,
        )

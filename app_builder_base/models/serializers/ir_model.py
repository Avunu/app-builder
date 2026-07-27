# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for model metadata: ``ir.model`` and its fields."""

from odoo import api, models

from ..studio_serializer import SEQ_FIELD, SEQ_MODEL, SEQ_SELECTION


class IrModelSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model"

    _studio_model = "ir.model"
    _studio_sequence = SEQ_MODEL
    _studio_dir = "models"
    # 'state' is deliberately omitted: it defaults to 'manual', which is what we
    # always want, and emitting a readonly field would be noise in every diff.
    _studio_fields = ("name", "model", "info", "order", "transient")

    @api.model
    def _group_model(self, record):
        return record.model

    @api.model
    def _ownable(self, record):
        # Only custom models. A base model reflected from Python code is owned
        # by the addon that declares it, not by a studio package.
        return record.state == "manual"

    @api.model
    def _should_skip(self, record, fname):
        if fname == "info" and self._is_inherited_docstring(record.info):
            # _reflect_model_params fills 'info' from the first docstring in the
            # class MRO (ir_model.py:433), so a model the user never documented
            # comes back carrying models.Model's own docstring. That is an
            # artifact of reflection, not content worth committing.
            return True
        return super()._should_skip(record, fname)

    @api.model
    def _is_inherited_docstring(self, info):
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
    )

    @api.model
    def _group_model(self, record):
        return record.model_id.model

    @api.model
    def _ownable(self, record):
        # Excludes the magic columns and any field declared in Python.
        return record.state == "manual"

    @api.model
    def _should_skip(self, record, fname):
        # HTML sanitize flags only mean anything on html fields, and several
        # default to True -- emitting them on a char field would be pure noise
        # that also survives round-trip, so filter by type rather than value.
        if fname.startswith(("sanitize", "strip_")) and record.ttype != "html":
            return True
        if fname == "copied":
            # 'copied' is computed (ir_model.py:651) rather than defaulted, so
            # the generic default comparison cannot see it. Emit it only when
            # the user overrode what the compute would have produced.
            computed = (record.ttype != "one2many") and not (
                record.related or record.compute
            )
            return record.copied == computed
        if fname == "size" and record.ttype != "char":
            return True
        if fname == "currency_field" and record.ttype != "monetary":
            return True
        if fname in ("relation_field",) and record.ttype != "one2many":
            return True
        if fname in ("relation_table", "column1", "column2") and (
            record.ttype != "many2many"
        ):
            return True
        if fname == "on_delete" and record.ttype != "many2one":
            return True
        if fname == "translate" and record.ttype not in ("char", "text", "html"):
            return True
        return super()._should_skip(record, fname)


class IrModelFieldsSelectionSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model.fields.selection"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model.fields.selection"

    _studio_model = "ir.model.fields.selection"
    _studio_sequence = SEQ_SELECTION
    _studio_dir = "models"
    _studio_fields = ("field_id", "value", "name", "sequence")

    @api.model
    def _group_model(self, record):
        return record.field_id.model_id.model

    @api.model
    def _ownable(self, record):
        # ir.model.fields.selection has no state of its own, so inherit the
        # field's. Once the field is code-defined, its values are declared by
        # the Python class and emitting <record> rows as well would define the
        # same selection twice.
        return record.field_id.state == "manual"

    @api.model
    def _sort_key(self, record, xmlid):
        # Selection order is semantic (it drives the dropdown), so sort by the
        # declared sequence first; `value` breaks ties the same way pycodegen
        # does, so the XML and the graduated Python agree.
        return (self._studio_sequence, record.sequence, record.value, xmlid)

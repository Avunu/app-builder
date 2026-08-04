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
    def _group_model(self, record):
        return record.model

    @api.model
    def _ownable(self, record):
        # Only custom models. A base model reflected from Python code is owned
        # by the addon that declares it, not by a studio package.
        if record.state != "manual":
            return False
        # And never one a package already defines as a Python class. Such a row
        # is a reconciliation artefact, not a definition -- emitting it would
        # give _add_manual_models a second class competing for the same _name.
        return not self.env["studio.package.model"]._is_python_owned(record.model)

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
    def _group_model(self, record):
        return record.model_id.model

    @api.model
    def _ownable(self, record):
        # Excludes the magic columns and any field declared in Python.
        if record.state != "manual":
            return False
        # A field on a Python-defined model belongs to that class, even while
        # its metadata row still says manual.
        return not self.env["studio.package.model"]._is_python_owned(
            record.model_id.model
        )

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

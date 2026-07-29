# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The edit buffer: what the composer changes before anything is written.

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

import difflib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import modelspec, pycodegen


class StudioModelDraft(models.TransientModel):
    _name = "studio.model.draft"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Model Draft"

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

    dirty = fields.Boolean(compute="_compute_dirty")
    change_count = fields.Integer(compute="_compute_dirty")

    # -- lifecycle --------------------------------------------------------

    @api.model
    def open_for(self, package_model):
        """A draft holding whatever is on disk right now."""
        self._assert_studio_manager()
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
        payload = json.dumps(modelspec.spec_to_json(spec), sort_keys=True)
        return self.create(
            {
                "package_model_id": package_model.id,
                "base_spec_json": payload,
                "spec_json": payload,
            }
        )

    def _spec(self):
        self.ensure_one()
        return modelspec.spec_from_json(json.loads(self.spec_json))

    def _base_spec(self):
        self.ensure_one()
        return modelspec.spec_from_json(json.loads(self.base_spec_json))

    def _store(self, spec):
        self.ensure_one()
        self.spec_json = json.dumps(modelspec.spec_to_json(spec), sort_keys=True)
        return True

    @api.depends("spec_json", "base_spec_json")
    def _compute_dirty(self):
        for draft in self:
            diff = modelspec.diff_specs(draft._base_spec(), draft._spec())
            draft.change_count = len(
                diff.added + diff.removed + diff.changed + diff.model_changed
            )
            draft.dirty = bool(draft.change_count)

    # -- operations -------------------------------------------------------

    def add_field(self, values):
        """Stage a new field. ``values`` is a FieldSpec-shaped dict."""
        self._assert_studio_manager()
        self.ensure_one()
        spec_field = modelspec.field_spec_from_json(values)
        spec = self._spec()
        if spec.field(spec_field.name):
            raise UserError(
                _("This model already has a field called '%s'.", spec_field.name)
            )
        return self._store(modelspec.with_field(spec, spec_field))

    def update_field(self, name, values):
        """Replace one field, keeping its position in the class."""
        self._assert_studio_manager()
        self.ensure_one()
        spec = self._spec()
        existing = spec.field(name)
        if not existing:
            raise UserError(_("There is no field called '%s' to change.", name))
        merged = {**modelspec.spec_to_json(existing), **values, "name": name}
        return self._store(
            modelspec.with_field(spec, modelspec.field_spec_from_json(merged))
        )

    def remove_field(self, name):
        self._assert_studio_manager()
        self.ensure_one()
        spec = self._spec()
        if not spec.field(name):
            raise UserError(_("There is no field called '%s' to remove.", name))
        return self._store(modelspec.without_field(spec, name))

    def move_field(self, name, before=None):
        """Reorder. Field order is class order, which is the order the
        scaffolded views show them in -- so this is a layout gesture."""
        self._assert_studio_manager()
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

    def set_model_options(self, values):
        """Change what the class says about itself: order, display field, mixins."""
        self._assert_studio_manager()
        self.ensure_one()
        allowed = {"description", "order", "rec_name", "active_name", "inherit"}
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

    # -- what the tray shows ----------------------------------------------

    def pending_changes(self):
        """One entry per staged edit, in the order a person would read them."""
        self.ensure_one()
        before, after = self._base_spec(), self._spec()
        diff = modelspec.diff_specs(before, after)
        out = []
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
            spec_field = after.field(name)
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
    def _type_label(self, ttype):
        entry = modelspec.FIELD_TYPES_BY_TTYPE.get(ttype)
        return entry.label if entry else ttype

    @api.model
    def field_types(self, spec_json=None):
        """The picker's contents, for the current draft state."""
        spec = (
            modelspec.spec_from_json(json.loads(spec_json))
            if spec_json
            else self._spec()
        )
        return modelspec.available_field_types(spec)

    def preview_source(self):
        """The block exactly as Apply would write it."""
        self.ensure_one()
        return pycodegen.render_block(self._spec())

    def preview_diff(self):
        """A unified diff of the block, so Apply is never a leap of faith."""
        self.ensure_one()
        before = pycodegen.render_block(self._base_spec()).splitlines(keepends=True)
        after = pycodegen.render_block(self._spec()).splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(before, after, fromfile="before", tofile="after", n=3)
        )

    def validate(self):
        """Problems the user can still fix, before anything is written."""
        self.ensure_one()
        taken = set(self.env["ir.model"].sudo().search([]).mapped("model")) - {
            self.model
        }
        return modelspec.validate_spec(self._spec(), taken_model_names=taken)

    # -- commit -----------------------------------------------------------

    def action_apply(self, allow_destructive=False):
        """Write the block and reload, once, for everything staged."""
        self._assert_studio_manager()
        self.ensure_one()
        errors = self.validate()
        if errors:
            raise UserError(
                _("This change cannot be applied:\n\n%s", "\n".join(errors))
            )
        package_model = self.package_model_id
        package = package_model.package_id
        package._assert_writable()

        source = package._read_source(package_model.python_path)
        if source is None:
            raise UserError(
                _("%s has no source file to write into.", package_model.model)
            )
        spec = self._spec()
        rewritten = pycodegen.ensure_imports(
            pycodegen.splice_block(source, pycodegen.render_block(spec), spec), spec
        )
        package._write_files({package_model.python_path: rewritten})

        applied = package.action_apply(
            reason=_("edit %s", package_model.model),
            allow_destructive=allow_destructive,
        )
        # The file is the definition, so the draft's baseline moves with it.
        self.base_spec_json = self.spec_json
        return applied

    def action_discard(self):
        self.ensure_one()
        self.spec_json = self.base_spec_json
        return True

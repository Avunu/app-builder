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

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..tools import modelspec, pycodegen, xml_writer
from ..tools import placement as placement_tool


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
    placement_json = fields.Text(
        default="{}",
        help="Which views each staged field should appear in. View intent, "
        "not class definition, so it is kept out of the spec.",
    )

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

    @api.model
    def open_action(self, package_model_id):
        """The client action for editing one model."""
        draft = self.open_for(self.env["studio.package.model"].browse(package_model_id))
        return {
            "type": "ir.actions.client",
            "tag": "app_builder_composer",
            "name": draft.model,
            "params": {"draft_id": draft.id},
            # URL-resumable: Apply rebuilds the registry, and a page that could
            # not be reopened from its address would lose the session on every
            # save.
            "context": {"studio_draft_id": draft.id},
        }

    def load(self):
        """Everything the composer needs, in one round trip."""
        self.ensure_one()
        spec = self._spec()
        placement = self._placement()
        return {
            "id": self.id,
            "model": self.model,
            "package": {
                "id": self.package_id.id,
                "name": self.package_id.name,
                "writable": self.package_id.writable,
                "reload_mode": self.package_id.reload_mode,
            },
            "spec": modelspec.spec_to_json(spec),
            "fields": [
                {
                    **modelspec.spec_to_json(f),
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
            "view": self._preview_view(self.package_model_id),
        }

    @api.model
    def _preview_view(self, package_model):
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
            self.env[model_name].check_access("read")
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
        view = self.env["ir.ui.view"].search(
            [("model", "=", model_name), ("type", "=", "form")],
            order="priority,id",
            limit=1,
        )
        return {
            "available": True,
            "res_model": model_name,
            "view_id": view.id or False,
        }

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

    @api.depends(
        "spec_json",
        "base_spec_json",
        "companion_ids.spec_json",
        "companion_ids.base_spec_json",
    )
    def _compute_dirty(self):
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

    def add_field(self, values):
        """Stage a new field. ``values`` is a FieldSpec-shaped dict.

        ``placement`` rides along but is not part of the spec: it says which
        views should show the field, which is a fact about the arch and not
        about the class.
        """
        self._assert_studio_manager()
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
    def _resolve_computed(self, values):
        """Give a compute body the method name and dependencies it needs.

        The composer asks for the body, because that is the part somebody has an
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

    def resolve_related(self, path):
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
        self._assert_studio_user()
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
            field = self.env[model_name]._fields.get(step)
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
        return {
            "ok": True,
            "ttype": field.type,
            "comodel": getattr(field, "comodel_name", None) or "",
            "string": field.string or steps[-1],
            "stored": bool(field.store),
        }

    # -- relationships ----------------------------------------------------

    def inverse_options(self, comodel):
        """What could link ``comodel`` back to this model, for the picker.

        Odoo needs a many2one on the other side before a related list can
        exist. Asking the user to go and build it there first is the gesture
        every studio gets wrong, so the options are: reuse a link that already
        points back, or have one made -- and if neither is possible, say why
        in the same breath rather than failing on Apply.
        """
        self.ensure_one()
        out = {"candidates": [], "can_create": False, "suggested": "", "reason": ""}
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

    def _sibling(self, comodel):
        """The package model for ``comodel``, if we may write to its class."""
        self.ensure_one()
        return self.package_id.model_ids.filtered(
            lambda m: m.model == comodel and m.source == "python"
        )[:1]

    def _links_back_from(self, comodel, sibling):
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

    def _names_on(self, comodel, sibling):
        """Every field name already used on ``comodel``, from the same source."""
        self.ensure_one()
        if sibling:
            spec = sibling._current_spec()
            return {f.name for f in (spec.fields if spec else ())}
        return set(self.env[comodel]._fields) if comodel in self.env else set()

    def _suggest_inverse_name(self, comodel):
        """``workshop.project`` linked from its lines becomes ``project_id``."""
        base = self.model.rsplit(".", 1)[-1]
        taken = self._names_on(comodel, self._sibling(comodel))
        candidate = "%s_id" % base
        suffix = 2
        while candidate in taken:
            candidate = "%s_%d_id" % (base, suffix)
            suffix += 1
        return candidate

    def _companion_for(self, package_model):
        """The staged edit for another model, created on first need."""
        self.ensure_one()
        existing = self.companion_ids.filtered(
            lambda d: d.package_model_id == package_model
        )
        if existing:
            return existing[:1]
        companion = self.open_for(package_model)
        companion.parent_draft_id = self.id
        return companion

    def _stage_inverse(self, spec_field):
        """Put the many2one that makes ``spec_field`` resolvable on the other
        model, in the same changeset so one Apply covers both."""
        self.ensure_one()
        sibling = self._sibling(spec_field.comodel)
        if not sibling:
            raise UserError(
                _(
                    "The link back from %(comodel)s cannot be created here: it "
                    "is not a model this package defines in Python.",
                    comodel=spec_field.comodel,
                )
            )
        companion = self._companion_for(sibling)
        if companion._spec().field(spec_field.inverse_name):
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

    def _placement(self):
        self.ensure_one()
        return json.loads(self.placement_json or "{}")

    def _set_placement(self, name, values):
        data = self._placement()
        data[name] = values
        self.placement_json = json.dumps(data, sort_keys=True)
        return True

    def set_placement(self, name, values):
        """Change which views a staged field will appear in."""
        self._assert_studio_manager()
        self.ensure_one()
        spec_field = self._spec().field(name)
        if not spec_field:
            raise UserError(_("There is no field called '%s' to place.", name))
        return self._set_placement(
            name, modelspec.clean_placement(values, spec_field.ttype)
        )

    def update_field(self, name, values):
        """Replace one field, keeping its position in the class."""
        self._assert_studio_manager()
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
        data = self._placement()
        if data.pop(name, None) is not None:
            self.placement_json = json.dumps(data, sort_keys=True)
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
        """One entry per staged edit, in the order a person would read them.

        Companion edits are listed with their model, because "you are also
        about to change workshop.task" is exactly the thing a user would be
        annoyed to discover only in the diff.
        """
        self.ensure_one()
        out = self._own_changes()
        for companion in self.companion_ids:
            for change in companion._own_changes():
                out.append({**change, "model": companion.model})
        return out

    def _own_changes(self):
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

    def validate(self):
        """Problems the user can still fix, before anything is written.

        Companions are validated too: they apply in the same transaction, so a
        problem on the other model is a problem with *this* Apply, and finding
        it afterwards would mean finding it during a rollback.
        """
        self.ensure_one()
        known = set(self.env["ir.model"].sudo().search([]).mapped("model"))
        out = []
        for draft in self | self.companion_ids:
            errors = modelspec.validate_spec(
                draft._spec(), taken_model_names=known - {draft.model}
            )
            prefix = "" if draft == self else "%s: " % draft.model
            out.extend("%s%s" % (prefix, error) for error in errors)
        return out

    # -- commit -----------------------------------------------------------

    def action_apply(self, allow_destructive=False):
        """Write every staged block and reload, once, for the whole changeset.

        A related list and the link back are two files and must be one reload:
        writing only the one2many would leave the registry resolving an
        inverse that does not exist yet, and the setup it fails is the setup
        that was meant to create it.
        """
        self._assert_studio_manager()
        self.ensure_one()
        errors = self.validate()
        if errors:
            raise UserError(
                _("This change cannot be applied:\n\n%s", "\n".join(errors))
            )
        package = self.package_id
        package._assert_writable()

        drafts = self | self.companion_ids
        payload = {}
        planned = []
        for draft in drafts:
            spec = draft._spec()
            payload[draft.package_model_id.python_path] = draft._rewritten_source(spec)
            diff = modelspec.diff_specs(draft._base_spec(), spec)
            planned.append((draft, spec, diff))
        package._write_files(payload)

        # Removals go first, and that ordering is not stylistic. The upgrade
        # re-imports the package's view files, so a <field> naming a column
        # this apply drops would fail the import and roll the whole thing back.
        # Taking it out of the arch now means the file rendered *by* the apply
        # is already consistent. Removing a field from a view is safe to do
        # before the reload; adding one is not.
        for draft, _spec, diff in planned:
            draft._retract_from_views(diff)

        applied = package.action_apply(
            reason=_("edit %s", self.model),
            allow_destructive=allow_destructive,
        )
        # Additions can only go in afterwards: the registry has to have the
        # column before a view naming it will validate.
        for draft, spec, diff in planned:
            draft._place_in_views(spec, diff)
        # The file is the definition, so each draft's baseline moves with it.
        for draft in drafts:
            draft.base_spec_json = draft.spec_json
        return applied

    def _rewritten_source(self, spec):
        """This model's file with the studio block replaced by ``spec``."""
        self.ensure_one()
        package_model = self.package_model_id
        source = self.package_id._read_source(package_model.python_path)
        if source is None:
            raise UserError(
                _("%s has no source file to write into.", package_model.model)
            )
        return pycodegen.ensure_imports(
            pycodegen.splice_block(source, pycodegen.render_block(spec), spec), spec
        )

    # -- views ------------------------------------------------------------

    def _owned_views(self):
        """The views this package owns for this model, by type."""
        views = self.env["ir.ui.view"].search(
            [
                ("model", "=", self.model),
                ("mode", "=", "primary"),
                ("studio_package_id", "=", self.package_id.id),
                ("type", "in", ("form", "list", "search")),
            ]
        )
        return {view.type: view for view in views}

    def _retract_from_views(self, diff):
        """Take dropped fields out of the arches, before the reload sees them."""
        if not diff.removed:
            return False
        touched = self.env["ir.ui.view"].browse()
        for view in self._owned_views().values():
            root = xml_writer.parse_arch(view.arch)
            changed = False
            for name in diff.removed:
                changed |= placement_tool.remove_field(root, name)
            if changed:
                self._write_arch(view, root)
                touched |= view
        if touched:
            self.package_id.studio_capture(touched)
        # Deliberately no file write: the apply that follows renders the whole
        # package anyway, and these arches are part of what it renders.
        return bool(touched)

    def _place_in_views(self, spec, diff):
        """Put added fields on screen, now that the columns exist."""
        if not diff.added:
            return False
        placement = self._placement()
        touched = self.env["ir.ui.view"].browse()
        for view_type, view in self._owned_views().items():
            root = xml_writer.parse_arch(view.arch)
            changed = False
            for name in diff.added:
                spec_field = spec.field(name)
                if not spec_field or spec_field.name in placement_tool.NEVER_PLACE:
                    continue
                where = placement.get(
                    name, modelspec.default_placement(spec_field.ttype)
                )
                label = spec_field.string or name
                widget = where.get("widget") or ""
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
            self.package_id.studio_capture(touched)
            # Views are data: they take effect immediately and need no reload,
            # so writing the files here keeps git in step without a second one.
            self.package_id.action_write_files()
        return bool(touched)

    def _write_arch(self, view, root):
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

    def action_discard(self):
        self.ensure_one()
        self.spec_json = self.base_spec_json
        self.placement_json = "{}"
        # A companion exists only to serve an edit on this draft, so discarding
        # that edit leaves nothing for it to do.
        self.companion_ids.unlink()
        return True

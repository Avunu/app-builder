# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The contract behind every record pane of the console.

An automation, an access line, a record rule, an approval rule, a report, a
menu: each is a row of some Odoo model that a studio package can own, and
the console shows each kind the same way -- cards or rows in the content
slot, label|control rows in the sidebar, Odoo's own form one button away.
What differs per kind is data: which model, which of its fields are rows,
how a record is summed up in a sentence, what a foreign record is offered
instead of an edit. A surface declares that data and inherits the rest.

Rows are ``catalogue.Row`` and never carry a function, the property that
let the field-option catalogue move off the client; a pane in an addon
that does not depend on the console's addon registers nothing but the
surface's name and renders these rows with the console's own editors.

Ownership is ``ir.model.data.module``, as everywhere in the studio. A record
the chosen package owns is edited here and written to its file; one owned
by another module is shown as facts, with the honest alternative each
surface names -- a copy, a line of one's own -- because the studio's whole
point is that nothing edits another module's source in place.
"""

import ast

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from ..tools import catalogue


class StudioRecordSurface(models.AbstractModel):
    _name = "studio.record.surface"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Record Surface"

    # The Odoo model whose records this surface lists.
    _surface_model = None
    # How a record names the model it is about: a many2one to ``ir.model``
    # (``model_id``) or a Char holding the model name (``model``).
    _surface_model_field = "model_id"
    # tuple[catalogue.Section]: what the sidebar shows and what `write_record` takes.
    _surface_sections = ()
    # Row names that are not fields of the surface model: the surface reads
    # them in `_virtual_value` and writes them in `_coerce_virtual`.
    _surface_virtual = ()
    # Templates the "New ..." tiles offer: (key, label, help, values, needs).
    _surface_templates = ()

    # -- reading ------------------------------------------------------------

    @api.model
    def catalogue(self, model_name=None):
        """The sections and templates, resolved for ``model_name``.

        A ``selection_from`` row reads its choices from the live field, so
        the catalogue cannot fall behind the model; a ``comodel_domain``
        has ``{model}`` and ``{model_id}`` filled in when a model is known.
        """
        self._assert_studio_user()
        return {
            "model": model_name or "",
            "sections": [
                self._section_json(section, model_name)
                for section in self._sections(model_name)
            ],
            "templates": self.templates(model_name),
        }

    @api.model
    def _sections(self, model_name=None):
        """The sections that apply -- a surface may drop rows whose fields
        this database does not have."""
        available = self.env[self._surface_model]._fields
        out = []
        for section in self._surface_sections:
            rows = tuple(
                row
                for row in section.rows
                if row.name in available or row.name in self._surface_virtual
            )
            if rows:
                out.append(
                    catalogue.Section(
                        section.id, section.title, rows, section.visible_when
                    )
                )
        return out

    @api.model
    def _section_json(self, section, model_name):
        data = section.to_json(self.env._)
        for row, spec in zip(section.rows, data["rows"], strict=True):
            if row.selection_from:
                spec["choices"] = self._selection_choices(row.selection_from)
            if row.comodel_domain and model_name:
                ir_model = (
                    self.env["ir.model"]
                    .sudo()
                    .search([("model", "=", model_name)], limit=1)
                )
                spec["comodel_domain"] = row.comodel_domain.replace(
                    "{model}", model_name
                ).replace("{model_id}", str(ir_model.id or 0))
        return data

    @api.model
    def _selection_choices(self, spec):
        model_name, _sep, field_name = spec.rpartition(".")
        if model_name not in self.env:
            return []
        field = self.env[model_name]._fields.get(field_name)
        if field is None or field.type != "selection":
            return []
        return [
            [value, label]
            for value, label in field.get_description(self.env)["selection"]
        ]

    @api.model
    def templates(self, model_name=None):
        self._assert_studio_user()
        return [
            {
                "key": key,
                "label": self.env._(label),
                "help": self.env._(help_) if help_ else "",
                "values": dict(values),
                "needs": list(needs),
            }
            for key, label, help_, values, needs in self._surface_templates
        ]

    @api.model
    def rows(self, model_name, package_id=None, **kwargs):
        """One row per record of ``model_name``, owned or not.

        Archived records are listed too: the pane shows them dimmed behind a
        filter, since a switched-off rule is still a rule that ships.
        """
        self._assert_studio_user()
        package = self.env["studio.package"]._chosen(package_id)
        records = (
            self._model()
            .with_context(active_test=False)
            .search(self._surface_domain(model_name, kwargs))
        )
        rows = [self._row(record, package) for record in records]
        # Owned by this package first, then the rest, each by name.
        rows.sort(key=lambda r: (not r["owned"], (r["title"] or "").lower()))
        return rows

    @api.model
    def _model(self):
        """The surface model, as superuser.

        The studio's guards are the authorisation: a Studio Administrator
        builds rules and automations whether or not the ACLs of ``ir.rule``
        would let their user write one by hand, and a Studio Builder reads
        them. Every entry point here checks the guard first.
        """
        return self.env[self._surface_model].sudo()

    @api.model
    def _surface_domain(self, model_name, kwargs):
        if self._surface_model_field == "model":
            return [("model", "=", model_name)]
        return [("%s.model" % self._surface_model_field, "=", model_name)]

    @api.model
    def describe(self, record_id, package_id=None):
        self._assert_studio_user()
        record = self._record(record_id)
        package = (
            self.env["studio.package"]._chosen(package_id)
            or self._owner(record)["package"]
            or self.env["studio.package"]
        )
        model_name = self._subject_model(record)
        out = {
            "row": self._row(record, package),
            "values": self._values(record),
            "sections": [
                self._section_json(section, model_name)
                for section in self._sections(model_name)
            ],
            "actions": self._actions(record, package),
            "notes": self._notes(record, package),
            "advanced": {
                "res_model": record._name,
                "res_id": record.id,
                "context": {"studio_package_id": package.id if package else False},
            },
            "sentence": self._sentence(record),
        }
        out.update(self._describe_extra(record, package))
        return out

    @api.model
    def _describe_extra(self, record, package):
        return {}

    # -- the row ----------------------------------------------------------------

    @api.model
    def _row(self, record, package):
        owner = self._owner(record)
        owned = bool(package) and owner["package"] == package
        editable = owned and package.writable
        if owned and not package.writable:
            reason = _("%s is read-only.", package.name)
        elif owner["package"]:
            reason = _(
                "Belongs to %s. Switch to that package to edit it.",
                owner["package"].name,
            )
        elif owner["module"]:
            reason = self._foreign_reason(record, owner["module"])
        else:
            reason = _("Not in source. Add it to a package to edit it here.")
        return {
            "id": record.id,
            "title": record.display_name,
            "sentence": self._sentence(record),
            "badges": self._badges(record, owner),
            "active": record["active"] if "active" in record._fields else True,
            "owned": owned,
            "owner": owner["module"],
            "in_source": bool(owner["module"]),
            "editable": editable,
            "reason": "" if editable else reason,
            "model": self._subject_model(record),
        }

    @api.model
    def _badges(self, record, owner):
        badges = []
        if "active" in record._fields and not record.active:
            badges.append({"key": "inactive", "label": _("Inactive")})
        if owner["module"] and not owner["package"]:
            badges.append({"key": "foreign", "label": _("From %s", owner["module"])})
        elif not owner["module"]:
            badges.append({"key": "unsourced", "label": _("Not in source")})
        return badges

    @api.model
    def _sentence(self, record):
        """What the card says under the title; a surface overrides it."""
        return ""

    @api.model
    def _subject_model(self, record):
        value = record[self._surface_model_field]
        return value.model if isinstance(value, models.BaseModel) else (value or "")

    @api.model
    def _owner(self, record):
        """Who the record belongs to: a studio package, a module, or nobody."""
        data = (
            self.env["ir.model.data"]
            .sudo()
            .search(
                [("model", "=", record._name), ("res_id", "=", record.id)],
                order="id",
            )
        )
        # An export or an import leaves an xmlid too (`__export__`), and
        # that is not ownership; a studio package's xmlid outranks any other.
        modules = [d.module for d in data if not d.module.startswith("__")]
        Package = self.env["studio.package"]
        packages = Package.search([("name", "in", modules)]) if modules else Package
        if packages:
            package = packages[:1]
            return {"module": package.name, "package": package}
        return {"module": modules[0] if modules else "", "package": False}

    @api.model
    def _foreign_reason(self, record, module):
        """Why a record of another module is not edited here, and what is
        offered instead. Surfaces say it in their own words."""
        return _(
            "Defined by %s. Shown here so you can see what applies; edit it "
            "in that module.",
            module,
        )

    @api.model
    def _actions(self, record, package):
        """Buttons the sidebar offers besides Advanced and Remove."""
        owner = self._owner(record)
        actions = []
        if not owner["module"] and package and package.writable:
            actions.append(
                {
                    "key": "capture",
                    "label": _("Add to %s", package.name),
                    "icon": "fa fa-plus",
                    "enabled": True,
                    "reason": "",
                    "danger": False,
                }
            )
        return actions

    @api.model
    def _notes(self, record, package):
        return []

    # -- values in and out ---------------------------------------------------------

    @api.model
    def _rows_by_name(self, model_name=None):
        return {
            row.name: row
            for section in self._sections(model_name)
            for row in section.rows
        }

    @api.model
    def _values(self, record):
        """The record's value for every row, in the shape the row's editor reads."""
        out = {}
        for name, row in self._rows_by_name(self._subject_model(record)).items():
            if name not in record._fields:
                if name in self._surface_virtual:
                    out[name] = self._virtual_value(record, name)
                continue
            value = record[name]
            if row.type in ("many2one",):
                out[name] = (
                    {"id": value.id, "display_name": value.display_name}
                    if value
                    else False
                )
            elif row.type in ("many2many", "groups", "fields"):
                out[name] = [
                    {"id": rec.id, "display_name": rec.display_name} for rec in value
                ]
            elif row.type == "toggle":
                out[name] = bool(value)
            else:
                out[name] = value if value not in (None, False) else ""
        return out

    @api.model
    def _coerce(self, model_name, values, creating=False):
        """Row values as the ORM wants them, checked as the row says.

        Unknown keys are refused rather than passed through: the catalogue
        is the contract, and a value the sidebar could not have produced is
        a call this surface did not agree to.
        """
        rows = self._rows_by_name(model_name)
        vals = {}
        for name, value in values.items():
            row = rows.get(name)
            if row is None:
                raise UserError(_("Not something the studio sets here: %s", name))
            if row.type == "readonly":
                raise UserError(_("%s is not editable here.", row.label))
            if name in self._surface_virtual:
                vals.update(self._coerce_virtual(row, value, model_name))
                continue
            vals[name] = self._coerce_one(row, value, model_name)
        if creating:
            for name, row in rows.items():
                if row.required and not vals.get(name):
                    raise UserError(_("%s is required.", self.env._(row.label)))
        return vals

    @api.model
    def _domain_eval_context(self, model_name):
        """Names a domain of this surface may use, or ``None`` for a plain
        literal. A record rule's domain speaks of ``user``; a filter's
        does not."""
        return

    @api.model
    def _check_domain(self, model_name, domain):
        """Does the domain search? The count, or the complaint."""
        if not model_name or model_name not in self.env:
            return {"valid": True, "count": 0}
        context = self._domain_eval_context(model_name)
        try:
            if context is None:
                parsed = ast.literal_eval(domain or "[]")
            else:
                parsed = safe_eval(domain or "[]", context)
            model = self.env[model_name].sudo()
            count = model.search_count(parsed)
            total = model.search_count([])
        except Exception as err:  # noqa: BLE001 - any failure is the same answer
            return {"valid": False, "reason": str(err)}
        return {"valid": True, "count": count, "total": total}

    @api.model
    def _virtual_value(self, record, name):
        """The value of a row that is not a field; surfaces override."""
        return ""

    @api.model
    def _coerce_virtual(self, row, value, model_name):
        """ORM values for a row that is not a field; surfaces override."""
        raise UserError(_("%s is not editable here.", row.label))

    @api.model
    def _coerce_one(self, row, value, model_name):
        if row.type == "toggle":
            return bool(value)
        if row.type == "integer":
            try:
                return int(value or 0)
            except (TypeError, ValueError) as err:
                raise UserError(_("%s must be a whole number.", row.label)) from err
        if row.type == "many2one":
            if isinstance(value, dict):
                value = value.get("id")
            value = int(value) if value else False
            if value:
                self._assert_in_source(row, [value])
            return value
        if row.type in ("many2many", "groups", "fields"):
            ids = [v.get("id") if isinstance(v, dict) else v for v in (value or [])]
            ids = [int(i) for i in ids if i]
            self._assert_in_source(row, ids)
            return [(6, 0, ids)]
        if row.type == "domain":
            domain = (value or "").strip() or "[]"
            check = self._check_domain(model_name, domain)
            if not check["valid"]:
                raise UserError(
                    _(
                        "This condition does not search, so it would raise "
                        "every time it was evaluated: %s",
                        check["reason"],
                    )
                )
            return domain
        return value if value is not None else False

    @api.model
    def _assert_in_source(self, row, ids):
        """A reference the file could not carry is refused before the write.

        The serializer emits a many2one as ``ref="module.name"``; a record
        that only this database has -- a template made by hand, a user --
        has no such name, and the failure would otherwise surface from deep
        inside the write, worded for a developer.
        """
        if not row.comodel or row.comodel not in self.env or not ids:
            return
        records = self.env[row.comodel].sudo().browse(ids).exists()
        xmlids = records.get_external_id()
        for record in records:
            if not xmlids.get(record.id):
                raise UserError(
                    _(
                        "%(record)s is only in this database: it has no "
                        "external id, so the package's file could not point "
                        "at it. Pick one that comes from a module or a package.",
                        record=record.display_name,
                    )
                )

    # -- writing ---------------------------------------------------------------

    @api.model
    def _record(self, record_id):
        record = (
            self._model().with_context(active_test=False).browse(record_id).exists()
        )
        if not record:
            raise UserError(_("That record no longer exists."))
        return record

    @api.model
    def _assert_editable(self, record, package):
        """The record is the chosen package's to edit, or here is why not."""
        owner = self._owner(record)
        if not owner["module"]:
            raise UserError(
                _(
                    "%s is not in source. Add it to a package first, so that the "
                    "change is written somewhere.",
                    record.display_name,
                )
            )
        if not owner["package"]:
            raise UserError(self._foreign_reason(record, owner["module"]))
        if package and owner["package"] != package:
            raise UserError(
                _(
                    "%(record)s belongs to %(owner)s. Switch to that package to "
                    "edit it.",
                    record=record.display_name,
                    owner=owner["package"].name,
                )
            )
        owner["package"]._assert_writable()
        return owner["package"]

    @api.model
    def write_record(self, record_id, values, package_id=None):
        self._assert_studio_manager()
        record = self._record(record_id)
        package = self.env["studio.package"]._chosen(package_id)
        owner = self._assert_editable(record, package)
        vals = self._coerce(self._subject_model(record), values)
        if vals:
            record.write(vals)
            self._after_write(record, owner)
            owner.studio_capture(record)
        return self._row(record, owner)

    @api.model
    def _after_write(self, record, package):
        return

    @api.model
    def _subject_vals(self, model_name):
        if self._surface_model_field == "model":
            return {"model": model_name}
        ir_model = (
            self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
        )
        if not ir_model:
            raise UserError(_("Unknown model '%s'.", model_name))
        return {self._surface_model_field: ir_model.id}

    @api.model
    def create_record(self, model_name, package_id, values, template=None):
        self._assert_studio_manager()
        package = self.env["studio.package"]._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to record this in first."))
        package._assert_writable()
        merged = {}
        if template:
            merged.update(self._template_values(template, model_name, values))
        merged.update(values or {})
        vals = self._coerce(model_name, merged, creating=True)
        vals.update(self._subject_vals(model_name))
        vals.update(self._create_defaults(model_name, package, template, vals))
        record = self._model().with_context(studio_package_id=package.id).create(vals)
        self._after_create(record, package, template)
        package.studio_capture(record)
        return self._row(record, package)

    @api.model
    def _template_values(self, template, model_name, values):
        for key, _label, _help, tvalues, _needs in self._surface_templates:
            if key == template:
                return dict(tvalues)
        raise UserError(_("There is no template called '%s'.", template))

    @api.model
    def _create_defaults(self, model_name, package, template, vals):
        """Values a new record needs that no row supplies."""
        return {}

    @api.model
    def _after_create(self, record, package, template):
        return

    @api.model
    def remove_record(self, record_id, package_id=None, force=False):
        """Take a record out of the database and, at the next write, out of
        the file. A surface that wants a question asked first raises
        ``StudioConfirmRequired`` from ``_before_remove`` unless ``force``."""
        self._assert_studio_manager()
        record = self._record(record_id)
        package = self.env["studio.package"]._chosen(package_id)
        owner = self._assert_editable(record, package)
        self._before_remove(record, owner, force)
        record.unlink()
        # Gone from the database, so the next write leaves it out of the file.
        owner.action_write_files()
        return True

    @api.model
    def _before_remove(self, record, package, force=False):
        return

    @api.model
    def duplicate_record(self, record_id, package_id=None):
        """A copy of the record, in the chosen package.

        The honest answer for a record another module owns: the copy starts
        the way ``_copy_defaults`` says -- switched off, for anything that
        runs -- and the original goes on as it was.
        """
        self._assert_studio_manager()
        record = self._record(record_id)
        package = self.env["studio.package"]._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to copy this into first."))
        package._assert_writable()
        copy = record.with_context(studio_package_id=package.id).copy(
            self._copy_defaults(record)
        )
        package.studio_capture(copy)
        return self._row(copy, package)

    @api.model
    def _copy_defaults(self, record):
        defaults = {}
        if "active" in record._fields:
            defaults["active"] = False
        return defaults

    @api.model
    def run(self, record_id, key, package_id=None):
        """A named action on one record, from ``describe().actions``."""
        self._assert_studio_manager()
        record = self._record(record_id)
        package = self.env["studio.package"]._chosen(package_id)
        handler = getattr(self, "_run_%s" % key, None)
        if handler is None:
            raise UserError(_("There is no action called '%s'.", key))
        handler(record, package)
        return self.describe(record.id, package.id if package else None)

    @api.model
    def _run_capture(self, record, package):
        """Give a database-only record an xmlid in the package, and a file."""
        if not package:
            raise UserError(_("Choose a package to add this to first."))
        package.studio_capture(record)

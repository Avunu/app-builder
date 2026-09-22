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

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypedDict, cast

from typing_extensions import NotRequired

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from odoo.addons.base.models.ir_model import IrModel, IrModelData

from ..tools import catalogue, typed
from .studio_package import StudioPackage

if TYPE_CHECKING:
    # Only used inside annotations (`from __future__ import annotations`
    # defers all of them to strings), never at runtime -- same bargain
    # `studio_serializer.py`'s own `TYPE_CHECKING`-guarded imports make.
    # `IrModel`/`IrModelData` and `StudioPackage` are real, top-level
    # imports instead (above): `typed.model()` reads `cls._name` at
    # *runtime*, which needs a real binding, the same reason
    # `studio_package.py` imports them for real too.
    from odoo.models import BaseModel


# -- wire types -------------------------------------------------------------
#
# The shapes every real "surface" subclass (`studio_security_surfaces.py`,
# `studio_menu_surface.py`, `studio_automation_surface.py`,
# `studio_report_surface.py`, `studio_approval_surface.py` -- none of them
# converted yet) inherits and extends. Traced from what each method here
# actually builds, cross-checked against `app_builder_view/static/src/
# console/wire.ts`'s own hand-kept `Record*JSON` interfaces (written when
# TypeScript cluster 2 converted `record_pane_model.ts`, well before this
# file's own conversion) -- the two independently arrived at the same
# shapes, which is the closest thing to an existing, external check this
# migration has had so far for a "model case" file.


class RecordTemplateJSON(TypedDict):
    """One row of ``catalogue()``'s ``templates`` -- what the New tiles
    offer (``templates()``, matching ``wire.ts:RecordTemplateJSON``)."""

    key: str
    label: str
    help: str
    values: dict[str, object]
    needs: list[str]


class RecordCatalogueJSON(TypedDict):
    """``catalogue()``'s whole return (``wire.ts:RecordCatalogueJSON``)."""

    model: str
    sections: list[catalogue.SectionJSON]
    templates: list[RecordTemplateJSON]


class RecordBadgeJSON(TypedDict):
    """One badge on a row's card (``_badges()``,
    matching ``wire.ts:RecordBadgeJSON``)."""

    key: str
    label: str


class RecordRowJSON(TypedDict):
    """One entry of ``rows()``: a record as a card (``_row()``, matching
    ``wire.ts:RecordRowJSON`` -- this base contributes exactly these eleven
    keys; `wire.ts`'s own optional `depth`/`parent_id`/`view_id` are added
    only by real subclass overrides of `_row`/`rows`, none of them
    converted yet, so they are not part of this file's own contract."""

    id: int
    title: str
    sentence: str
    badges: list[RecordBadgeJSON]
    active: bool
    owned: bool
    owner: str
    in_source: bool
    editable: bool
    reason: str
    model: str


class RecordActionJSON(TypedDict):
    """One button ``describe()``'s ``actions`` offers besides Advanced/
    Remove (``_actions()``, matching ``wire.ts:RecordActionJSON``)."""

    key: str
    label: str
    icon: str
    enabled: bool
    reason: str
    danger: bool


class RecordOwnerJSON(TypedDict):
    """``_owner()``'s own return: who a record belongs to. Never itself
    sent over the wire whole (`_row`/`_badges`/`_actions` each read one key
    out of it into their own JSON shapes), so it has no `wire.ts` cousin of
    its own."""

    module: str
    package: StudioPackage | Literal[False]


class _RecordCheckDomainInvalidJSON(TypedDict):
    valid: Literal[False]
    reason: str


class _RecordCheckDomainValidJSON(TypedDict):
    valid: Literal[True]
    count: int
    # The early "unknown model" return (`_check_domain`'s own first line)
    # sends `{"valid": True, "count": 0}` with no `total` at all, while the
    # real search path always sends both -- a genuine, pre-existing
    # inconsistency (see findings), typed honestly rather than papered over
    # with a value that was never actually sent.
    total: NotRequired[int]


#: ``_check_domain()``'s own answer shape. Traced separately from
#: `studio_domain.py`'s own `CheckDomainJSON` rather than reused: that one
#: has no `total` key at all (checked directly against its definition, per
#: TYPING.md's own instruction for this file) -- a different, narrower
#: contract for a different RPC method, not the same type under a different
#: name.
RecordCheckDomainJSON: TypeAlias = (
    _RecordCheckDomainInvalidJSON | _RecordCheckDomainValidJSON
)


class StudioRecordSurface(models.AbstractModel):
    _name = "studio.record.surface"
    _inherit = ["studio.security.mixin"]
    _description = "Studio Record Surface"

    # The Odoo model whose records this surface lists. `str | None` is the
    # honest declared type -- `None` only at this abstract base, always a
    # real model name on every concrete subclass, the identical shape
    # `studio_serializer.py`'s own `_studio_model` already established
    # (cast to `str` at each read site below, not narrowed here).
    _surface_model: str | None = None
    # How a record names the model it is about: a many2one to ``ir.model``
    # (``model_id``) or a Char holding the model name (``model``).
    _surface_model_field: str = "model_id"
    # tuple[catalogue.Section]: what the sidebar shows and what `write_record` takes.
    _surface_sections: tuple[catalogue.Section, ...] = ()
    # Row names that are not fields of the surface model: the surface reads
    # them in `_virtual_value` and writes them in `_coerce_virtual`.
    _surface_virtual: tuple[str, ...] = ()
    # Templates the "New ..." tiles offer: (key, label, help, values, needs).
    _surface_templates: tuple[
        tuple[str, str, str, dict[str, object], tuple[str, ...]], ...
    ] = ()

    # -- reading ------------------------------------------------------------

    @api.model
    def catalogue(self, model_name: str | None = None) -> RecordCatalogueJSON:
        """The sections and templates, resolved for ``model_name``.

        A ``selection_from`` row reads its choices from the live field, so
        the catalogue cannot fall behind the model; a ``comodel_domain``
        has ``{model}`` and ``{model_id}`` filled in when a model is known.
        """
        typed.security(self)._assert_studio_user()
        return {
            "model": model_name or "",
            "sections": [
                self._section_json(section, model_name)
                for section in self._sections(model_name)
            ],
            "templates": self.templates(model_name),
        }

    @api.model
    def _sections(self, model_name: str | None = None) -> list[catalogue.Section]:
        """The sections that apply -- a surface may drop rows whose fields
        this database does not have."""
        available = self.env[cast("str", self._surface_model)]._fields
        out: list[catalogue.Section] = []
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
    def _section_json(
        self, section: catalogue.Section, model_name: str | None
    ) -> catalogue.SectionJSON:
        data = section.to_json(self.env._)
        for row, spec in zip(section.rows, data["rows"], strict=True):
            if row.selection_from:
                # `RowJSON.choices` is `list[tuple[str, str]]`
                # (`catalogue.py`), already a required key `to_json` just
                # filled with `self.choices`' own (empty, at every row here)
                # default; this overwrites it with the live selection. The
                # cast is honest about a real, pre-existing quirk of
                # `_selection_choices` (see its own docstring/findings): it
                # builds plain two-element lists, not tuples, which is the
                # same JSON array either way but not the identical Python
                # type `RowJSON.choices` declares.
                spec["choices"] = cast(
                    "list[tuple[str, str]]",
                    self._selection_choices(row.selection_from),
                )
            if row.comodel_domain and model_name:
                ir_model = (
                    typed.model(self.env, IrModel)
                    .sudo()
                    .search([("model", "=", model_name)], limit=1)
                )
                spec["comodel_domain"] = row.comodel_domain.replace(
                    "{model}", model_name
                ).replace("{model_id}", str(ir_model.id or 0))
        return data

    @api.model
    def _selection_choices(self, spec: str) -> list[list[str]]:
        model_name, _sep, field_name = spec.rpartition(".")
        if model_name not in self.env:
            return []
        field = self.env[model_name]._fields.get(field_name)
        if field is None or field.type != "selection":
            return []
        # `get_description` (`odoo/fields.py`) carries no annotation of its
        # own, on either its parameters or its return, so pyright infers
        # `dict[Unknown, Unknown]` for it -- a genuine untyped hole, not a
        # gap this migration introduces (the identical trap `studio_domain
        # .py:fields_for` already documents and works around the same way).
        # Indexed with `[...]`, not `.get(...)`, to keep the exact original
        # KeyError-on-a-genuinely-missing-key behavior -- the `field.type
        # != "selection"` guard above is what actually makes "selection"
        # safe to assume present, not a defensive `.get`.
        return [
            [value, label]
            for value, label in cast(
                "list[tuple[str, str]]",
                field.get_description(self.env)["selection"],
            )
        ]

    @api.model
    def templates(self, model_name: str | None = None) -> list[RecordTemplateJSON]:
        typed.security(self)._assert_studio_user()
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
    def rows(
        self, model_name: str, package_id: int | None = None, **kwargs: object
    ) -> list[RecordRowJSON]:
        """One row per record of ``model_name``, owned or not.

        Archived records are listed too: the pane shows them dimmed behind a
        filter, since a switched-off rule is still a rule that ships.
        """
        typed.security(self)._assert_studio_user()
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
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
    def _model(self) -> BaseModel:
        """The surface model, as superuser.

        The studio's guards are the authorisation: a Studio Administrator
        builds rules and automations whether or not the ACLs of ``ir.rule``
        would let their user write one by hand, and a Studio Builder reads
        them. Every entry point here checks the guard first.
        """
        return self.env[cast("str", self._surface_model)].sudo()

    @api.model
    def _surface_domain(
        self, model_name: str, kwargs: dict[str, object]
    ) -> api.DomainType:
        if self._surface_model_field == "model":
            return [("model", "=", model_name)]
        return [("%s.model" % self._surface_model_field, "=", model_name)]

    @api.model
    def describe(
        self, record_id: int, package_id: int | None = None
    ) -> dict[str, object]:
        typed.security(self)._assert_studio_user()
        record = self._record(record_id)
        package = (
            typed.model(self.env, StudioPackage)._chosen(package_id)
            or self._owner(record)["package"]
            or typed.model(self.env, StudioPackage)
        )
        model_name = self._subject_model(record)
        out: dict[str, object] = {
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
        # `_describe_extra`'s own base contract is `{}`, but every real
        # subclass override widens it with keys of its own (`"matches"`,
        # `"children"`, ...) that this base has no way to enumerate -- the
        # same genuinely-open-ended shape `wire.ts`'s own
        # `RecordDescription` interface already models with a `[key:
        # string]: unknown` index signature (no Python TypedDict equivalent
        # exists). `describe()` therefore stays `dict[str, object]` rather
        # than a closed TypedDict, the same judgment call this migration
        # already made for `_describe_extra` itself.
        out.update(self._describe_extra(record, package))
        return out

    @api.model
    def _describe_extra(
        self, record: BaseModel, package: StudioPackage
    ) -> dict[str, object]:
        return {}

    # -- the row ----------------------------------------------------------------

    @api.model
    def _row(self, record: BaseModel, package: StudioPackage) -> RecordRowJSON:
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
            "id": cast("int", record.id),
            "title": cast("str", record.display_name),
            "sentence": self._sentence(record),
            "badges": self._badges(record, owner),
            "active": (
                cast("bool", record["active"]) if "active" in record._fields else True
            ),
            "owned": owned,
            "owner": owner["module"],
            "in_source": bool(owner["module"]),
            "editable": editable,
            "reason": "" if editable else reason,
            "model": self._subject_model(record),
        }

    @api.model
    def _badges(
        self, record: BaseModel, owner: RecordOwnerJSON
    ) -> list[RecordBadgeJSON]:
        badges: list[RecordBadgeJSON] = []
        # `active` is a per-model field, not one `BaseModel` itself
        # declares (only present when the concrete surface model happens to
        # have it, guarded at runtime the same way `_row` guards its own
        # `record["active"]` read) -- the identical "no real class in this
        # codebase's own tree carries the attribute" shape TYPING.md's own
        # `_inherits`/`delegate=True` trap already documents a `cast("Any",
        # record)` fix for.
        if "active" in record._fields and not cast("Any", record).active:
            badges.append({"key": "inactive", "label": _("Inactive")})
        if owner["module"] and not owner["package"]:
            badges.append({"key": "foreign", "label": _("From %s", owner["module"])})
        elif not owner["module"]:
            badges.append({"key": "unsourced", "label": _("Not in source")})
        return badges

    @api.model
    def _sentence(self, record: BaseModel) -> str:
        """What the card says under the title; a surface overrides it."""
        return ""

    @api.model
    def _subject_model(self, record: BaseModel) -> str:
        value = record[self._surface_model_field]
        # `value.model` is `ir.model`'s own Char field, `str | Literal
        # [False]` by the field descriptor's own declared type -- but every
        # real caller only ever puts a many2one to `ir.model` behind
        # `_surface_model_field`, whose `.model` is never actually empty
        # for a record fetched this way. True by construction, the same
        # idiom `studio_domain.py:fields_for` already uses for `field
        # .comodel_name`.
        return (
            cast("str", cast("IrModel", value).model)
            if isinstance(value, models.BaseModel)
            else (value or "")
        )

    @api.model
    def _owner(self, record: BaseModel) -> RecordOwnerJSON:
        """Who the record belongs to: a studio package, a module, or nobody."""
        data = (
            typed.model(self.env, IrModelData)
            .sudo()
            .search(
                [("model", "=", record._name), ("res_id", "=", record.id)],
                order="id",
            )
        )
        # An export or an import leaves an xmlid too (`__export__`), and
        # that is not ownership; a studio package's xmlid outranks any other.
        # `IrModelData.module` is `required=True` in the real model, so
        # `cast("str", ...)` here is the same true-by-construction idiom as
        # `_subject_model`'s own `.model` cast above, not a new invariant.
        modules = [
            cast("str", d.module)
            for d in data
            if not cast("str", d.module).startswith("__")
        ]
        Package = typed.model(self.env, StudioPackage)
        packages = Package.search([("name", "in", modules)]) if modules else Package
        if packages:
            package = packages[:1]
            return {"module": cast("str", package.name), "package": package}
        return {"module": modules[0] if modules else "", "package": False}

    @api.model
    def _foreign_reason(self, record: BaseModel, module: str) -> str:
        """Why a record of another module is not edited here, and what is
        offered instead. Surfaces say it in their own words."""
        return _(
            "Defined by %s. Shown here so you can see what applies; edit it "
            "in that module.",
            module,
        )

    @api.model
    def _actions(
        self, record: BaseModel, package: StudioPackage
    ) -> list[RecordActionJSON]:
        """Buttons the sidebar offers besides Advanced and Remove."""
        owner = self._owner(record)
        actions: list[RecordActionJSON] = []
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
    def _notes(self, record: BaseModel, package: StudioPackage) -> list[object]:
        return []

    # -- values in and out ---------------------------------------------------------

    @api.model
    def _rows_by_name(self, model_name: str | None = None) -> dict[str, catalogue.Row]:
        return {
            row.name: row
            for section in self._sections(model_name)
            for row in section.rows
        }

    @api.model
    def _values(self, record: BaseModel) -> dict[str, object]:
        """The record's value for every row, in the shape the row's editor reads."""
        out: dict[str, object] = {}
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
    def _coerce(
        self, model_name: str, values: dict[str, object], creating: bool = False
    ) -> dict[str, object]:
        """Row values as the ORM wants them, checked as the row says.

        Unknown keys are refused rather than passed through: the catalogue
        is the contract, and a value the sidebar could not have produced is
        a call this surface did not agree to.
        """
        rows = self._rows_by_name(model_name)
        vals: dict[str, object] = {}
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
    def _domain_eval_context(self, model_name: str) -> dict[str, object] | None:
        """Names a domain of this surface may use, or ``None`` for a plain
        literal. A record rule's domain speaks of ``user``; a filter's
        does not."""
        return

    @api.model
    def _check_domain(
        self, model_name: str | Literal[False], domain: str | None
    ) -> RecordCheckDomainJSON:
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
    def _virtual_value(self, record: BaseModel, name: str) -> str:
        """The value of a row that is not a field; surfaces override."""
        return ""

    @api.model
    def _coerce_virtual(
        self, row: catalogue.Row, value: object, model_name: str
    ) -> dict[str, object]:
        """ORM values for a row that is not a field; surfaces override."""
        raise UserError(_("%s is not editable here.", row.label))

    @api.model
    def _coerce_one(self, row: catalogue.Row, value: object, model_name: str) -> object:
        if row.type == "toggle":
            return bool(value)
        if row.type == "integer":
            try:
                # `value` is a genuinely heterogeneous RPC payload value
                # (`object`); the `try`/`except (TypeError, ValueError)`
                # around this call is the real runtime guard, already
                # exactly as strict as it needs to be -- the cast only
                # tells pyright what the `except` already handles.
                return int(cast("Any", value) or 0)
            except (TypeError, ValueError) as err:
                raise UserError(_("%s must be a whole number.", row.label)) from err
        if row.type == "many2one":
            if isinstance(value, dict):
                value = value.get("id")
            value = int(cast("Any", value)) if value else False
            if value:
                self._assert_in_source(row, [cast("int", value)])
            return value
        if row.type in ("many2many", "groups", "fields"):
            ids = [
                v.get("id") if isinstance(v, dict) else v
                for v in (cast("Any", value) or [])
            ]
            ids = [int(i) for i in ids if i]
            self._assert_in_source(row, ids)
            return [(6, 0, ids)]
        if row.type == "domain":
            domain = (cast("Any", value) or "").strip() or "[]"
            check = self._check_domain(model_name, domain)
            if not check["valid"]:
                # `not check["valid"]` does not, on its own, narrow the
                # `RecordCheckDomainJSON` union the way an `is False`/`==
                # False` comparison would -- confirmed with a real pyright
                # run rather than assumed; the cast states the same thing
                # the runtime branch already guarantees.
                raise UserError(
                    _(
                        "This condition does not search, so it would raise "
                        "every time it was evaluated: %s",
                        cast("_RecordCheckDomainInvalidJSON", check)["reason"],
                    )
                )
            return domain
        return value if value is not None else False

    @api.model
    def _assert_in_source(self, row: catalogue.Row, ids: list[int]) -> None:
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
    def _record(self, record_id: int) -> BaseModel:
        record = (
            self._model().with_context(active_test=False).browse(record_id).exists()
        )
        if not record:
            raise UserError(_("That record no longer exists."))
        return record

    @api.model
    def _assert_editable(
        self, record: BaseModel, package: StudioPackage
    ) -> StudioPackage:
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
    def write_record(
        self, record_id: int, values: dict[str, object], package_id: int | None = None
    ) -> RecordRowJSON:
        typed.security(self)._assert_studio_manager()
        record = self._record(record_id)
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        owner = self._assert_editable(record, package)
        vals = self._coerce(self._subject_model(record), values)
        if vals:
            record.write(vals)
            self._after_write(record, owner)
            owner.studio_capture(record)
        return self._row(record, owner)

    @api.model
    def _after_write(self, record: BaseModel, package: StudioPackage) -> None:
        return

    @api.model
    def _subject_vals(self, model_name: str) -> dict[str, object]:
        if self._surface_model_field == "model":
            return {"model": model_name}
        ir_model = (
            typed.model(self.env, IrModel)
            .sudo()
            .search([("model", "=", model_name)], limit=1)
        )
        if not ir_model:
            raise UserError(_("Unknown model '%s'.", model_name))
        return {self._surface_model_field: ir_model.id}

    @api.model
    def create_record(
        self,
        model_name: str,
        package_id: int | None,
        values: dict[str, object] | None,
        template: str | None = None,
    ) -> RecordRowJSON:
        typed.security(self)._assert_studio_manager()
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to record this in first."))
        package._assert_writable()
        merged: dict[str, object] = {}
        if template:
            merged.update(self._template_values(template, model_name, values))
        merged.update(values or {})
        vals = self._coerce(model_name, merged, creating=True)
        vals.update(self._subject_vals(model_name))
        vals.update(self._create_defaults(model_name, package, template, vals))
        # `@api.model_create_multi` (`odoo/api.py`) is a bare passthrough
        # decorator that does not widen `create()`'s own declared `list
        # [ValuesType]`-only signature to also cover the single-dict
        # calling form it genuinely accepts at runtime -- the documented
        # stub gap (TYPING.md's own "Known traps"), kept as the exact
        # original single-dict call rather than rewritten to `create(
        # [vals])`.
        record = (
            self._model().with_context(studio_package_id=package.id).create(vals)  # pyright: ignore[reportArgumentType]
        )
        self._after_create(record, package, template)
        package.studio_capture(record)
        return self._row(record, package)

    @api.model
    def _template_values(
        self, template: str, model_name: str, values: dict[str, object] | None
    ) -> dict[str, object]:
        for key, _label, _help, tvalues, _needs in self._surface_templates:
            if key == template:
                return dict(tvalues)
        raise UserError(_("There is no template called '%s'.", template))

    @api.model
    def _create_defaults(
        self,
        model_name: str,
        package: StudioPackage,
        template: str | None,
        vals: dict[str, object],
    ) -> dict[str, object]:
        """Values a new record needs that no row supplies."""
        return {}

    @api.model
    def _after_create(
        self, record: BaseModel, package: StudioPackage, template: str | None
    ) -> None:
        return

    @api.model
    def remove_record(
        self, record_id: int, package_id: int | None = None, force: bool = False
    ) -> bool:
        """Take a record out of the database and, at the next write, out of
        the file. A surface that wants a question asked first raises
        ``StudioConfirmRequired`` from ``_before_remove`` unless ``force``."""
        typed.security(self)._assert_studio_manager()
        record = self._record(record_id)
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        owner = self._assert_editable(record, package)
        self._before_remove(record, owner, force)
        record.unlink()
        # Gone from the database, so the next write leaves it out of the file.
        owner.action_write_files()
        return True

    @api.model
    def _before_remove(
        self, record: BaseModel, package: StudioPackage, force: bool = False
    ) -> None:
        return

    @api.model
    def duplicate_record(
        self, record_id: int, package_id: int | None = None
    ) -> RecordRowJSON:
        """A copy of the record, in the chosen package.

        The honest answer for a record another module owns: the copy starts
        the way ``_copy_defaults`` says -- switched off, for anything that
        runs -- and the original goes on as it was.
        """
        typed.security(self)._assert_studio_manager()
        record = self._record(record_id)
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to copy this into first."))
        package._assert_writable()
        copy = record.with_context(studio_package_id=package.id).copy(
            self._copy_defaults(record)
        )
        package.studio_capture(copy)
        return self._row(copy, package)

    @api.model
    def _copy_defaults(self, record: BaseModel) -> dict[str, object]:
        defaults: dict[str, object] = {}
        if "active" in record._fields:
            defaults["active"] = False
        return defaults

    @api.model
    def run(
        self, record_id: int, key: str, package_id: int | None = None
    ) -> dict[str, object]:
        """A named action on one record, from ``describe().actions``."""
        typed.security(self)._assert_studio_manager()
        record = self._record(record_id)
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        handler = getattr(self, "_run_%s" % key, None)
        if handler is None:
            raise UserError(_("There is no action called '%s'.", key))
        handler(record, package)
        # `record`/`package` are both already-existing, `.exists()`-backed
        # records here (`_record`/`_chosen`), so `.id` is true by
        # construction a real `int`, never `NewId`/`Literal[False]` -- the
        # same cast `_row` already makes on `record.id`.
        return self.describe(
            cast("int", record.id),
            cast("int", package.id) if package else None,
        )

    @api.model
    def _run_capture(self, record: BaseModel, package: StudioPackage) -> None:
        """Give a database-only record an xmlid in the package, and a file."""
        if not package:
            raise UserError(_("Choose a package to add this to first."))
        package.studio_capture(record)

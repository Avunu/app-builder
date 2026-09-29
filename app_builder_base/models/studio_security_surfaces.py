# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Access lines and record rules as record panes.

Both are base models, both are serialized by this addon, so both surfaces
live here and are the first producers of the record-pane contract. What
each refuses for a row another module owns is the honest thing about
security: lines add up and rules combine, so a core module's row is never
loosened from a package -- only joined by a row of the package's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_rule import IrRule
from odoo.addons.base.models.res_users import Groups

from ..tools import compat, typed
from ..tools.catalogue import Row, Section
from ..tools.i18n import _
from .studio_record_surface import RecordRowJSON

if TYPE_CHECKING:
    # Only used inside annotations/casts below (`from __future__ import
    # annotations` defers all of them to strings), never at runtime -- same
    # bargain every other Phase 1c file's `TYPE_CHECKING` block makes.
    # `IrRule`/`Groups` are real, top-level imports instead (above):
    # `typed.model()` reads `cls._name` at *runtime*, the same reason
    # `studio_record_surface.py` imports `IrModel`/`IrModelData` for real.
    from odoo.fields import Field
    from odoo.models import BaseModel

    from odoo.addons.base.models.ir_model import IrModel, IrModelAccess

    from .studio_package import StudioPackage
    from .studio_record_surface import RecordTemplateJSON, StudioRecordSurface

_PERMS = ("perm_read", "perm_write", "perm_create", "perm_unlink")


class AccessRowJSON(RecordRowJSON):
    """``StudioAccessSurface._row``'s own return: the base row plus the two
    keys only an access line's card carries."""

    title: str
    perms: dict[str, bool]


class StudioAccessSurface(models.AbstractModel):
    _name = "studio.access.surface"
    _inherit = ["studio.record.surface"]
    _description = "Studio Access Control Surface"

    _surface_model = "ir.model.access"
    _surface_model_field = "model_id"
    _surface_sections = (
        Section(
            "line",
            "Access line",
            (
                Row(
                    name="group_id",
                    label="Group",
                    type="many2one",
                    comodel="res.groups",
                    help="No group means everyone, which is rarely what you want.",
                ),
                Row(name="perm_read", label="Read", type="toggle"),
                Row(name="perm_write", label="Write", type="toggle"),
                Row(name="perm_create", label="Create", type="toggle"),
                Row(name="perm_unlink", label="Delete", type="toggle"),
                Row(
                    name="name",
                    label="Name",
                    type="text",
                    help="Filled in from the model and the group when left empty.",
                ),
                Row(name="active", label="Active", type="toggle"),
            ),
        ),
    )
    _surface_templates = (
        (
            "read_only",
            "Read only",
            "Can see the records and nothing else.",
            {
                "perm_read": True,
                "perm_write": False,
                "perm_create": False,
                "perm_unlink": False,
            },
            ("group_id",),
        ),
        (
            "read_write",
            "Read, write and create",
            "Everything but deleting.",
            {
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": False,
            },
            ("group_id",),
        ),
        (
            "full",
            "Full access",
            "Read, write, create and delete.",
            {
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            },
            ("group_id",),
        ),
    )

    @api.model
    def _sentence(self, record: BaseModel) -> str:
        letters = "".join(
            letter if record[perm] else "–"
            for letter, perm in zip("RWCD", _PERMS, strict=True)
        )
        access = cast("IrModelAccess", record)
        group = cast("Groups", access.group_id)
        # `full_name` is a computed Char, `str | Literal[False]` by the
        # field descriptor's own declared type -- but `_compute_full_name`
        # (`res_users.py`) always sets a real string, never leaves it
        # `False`, the same true-by-construction cast `_subject_model`'s own
        # `.model` read already makes (`studio_record_surface.py`).
        who = cast("str", group.full_name) if group else _("Everyone")
        return "%s · %s" % (who, letters)

    @api.model
    def _row(self, record: BaseModel, package: StudioPackage) -> AccessRowJSON:
        row = cast(
            "AccessRowJSON", cast("StudioRecordSurface", super())._row(record, package)
        )
        access = cast("IrModelAccess", record)
        group = cast("Groups", access.group_id)
        row["title"] = cast("str", group.full_name) if group else _("Everyone")
        row["perms"] = {perm: bool(record[perm]) for perm in _PERMS}
        return row

    @api.model
    def _foreign_reason(self, record: BaseModel, module: str) -> str:
        return _(
            "Access lines add up: a line in your package can only grant more "
            "than %s does, never less. Add a line of your own here; to narrow "
            "what a group sees, add a record rule.",
            module,
        )

    @api.model
    def _create_defaults(
        self,
        model_name: str,
        package: StudioPackage,
        template: str | None,
        vals: dict[str, object],
    ) -> dict[str, object]:
        defaults: dict[str, object] = {"active": True}
        if not vals.get("name"):
            group = typed.model(self.env, Groups).browse(
                cast("Any", vals.get("group_id")) or []
            )
            defaults["name"] = "%s %s" % (
                model_name,
                group.full_name if group else _("everyone"),
            )
        return defaults


class StudioRuleSurface(models.AbstractModel):
    _name = "studio.rule.surface"
    _inherit = ["studio.record.surface"]
    _description = "Studio Record Rule Surface"

    _surface_model = "ir.rule"
    _surface_model_field = "model_id"
    _surface_virtual = ("groups",)
    _surface_sections = (
        Section(
            "rule",
            "Rule",
            (
                Row(name="name", label="Name", type="text", required=True),
                Row(name="active", label="Active", type="toggle"),
                Row(
                    name="groups",
                    label="Applies to",
                    type="many2many",
                    comodel="res.groups",
                    help="Leave empty for a global rule: it applies to everyone, "
                    "the administrator included, and combines with other global "
                    "rules by AND. Rules of one group combine by OR.",
                ),
            ),
        ),
        Section(
            "condition",
            "Condition",
            (
                Row(
                    name="domain_force",
                    label="Lets through",
                    type="domain",
                    help="Which records the rule lets through, for these groups.",
                ),
            ),
        ),
        Section(
            "perms",
            "Applies to",
            (
                Row(name="perm_read", label="Read", type="toggle"),
                Row(name="perm_write", label="Write", type="toggle"),
                Row(name="perm_create", label="Create", type="toggle"),
                Row(name="perm_unlink", label="Delete", type="toggle"),
            ),
        ),
    )
    _surface_templates = (
        (
            "own_records",
            "Only their own records",
            "Each user sees what they created.",
            {"domain_force": "[('create_uid', '=', user.id)]"},
            ("name", "groups"),
        ),
        (
            "assigned_to_me",
            "Only records assigned to them",
            "Needs a Responsible (user_id) field on the model.",
            {"domain_force": "[('user_id', '=', user.id)]"},
            ("name", "groups"),
        ),
        (
            "own_company",
            "Only their company",
            "Needs a Company (company_id) field on the model.",
            {"domain_force": "[('company_id', 'in', company_ids)]"},
            ("name", "groups"),
        ),
        ("blank", "Blank rule", "", {"domain_force": "[]"}, ("name",)),
    )

    @api.model
    def _groups_field(self) -> str:
        return compat.groups_field(self.env, "ir.rule")

    @api.model
    def _sentence(self, record: BaseModel) -> str:
        groups = record[self._groups_field()]
        who = (
            ", ".join(groups.mapped("full_name")) if groups else _("Everyone (global)")
        )
        letters = "".join(
            letter if record[perm] else "–"
            for letter, perm in zip("RWCD", _PERMS, strict=True)
        )
        rule = cast("IrRule", record)
        return "%s · %s · %s" % (who, rule.domain_force or "[]", letters)

    @api.model
    def _virtual_value(
        self, record: BaseModel, name: str
    ) -> list[dict[str, object]] | str:
        # Base declares `-> str` (`""`, the base default); this override
        # widens it to the list of refs a "groups" row actually needs -- no
        # LSP/override-compatibility check applies to `_inherit`-only
        # composition (TYPING.md, confirmed elsewhere in this migration), so
        # the honest, wider return type here is the correct annotation, not
        # a `# pyright: ignore`.
        if name == "groups":
            return [
                {"id": group.id, "display_name": group.full_name}
                for group in record[self._groups_field()]
            ]
        return cast("StudioRecordSurface", super())._virtual_value(record, name)

    @api.model
    def _coerce_virtual(
        self, row: Row, value: object, model_name: str
    ) -> dict[str, object]:
        if row.name == "groups":
            ids: list[Any] = [
                v.get("id") if isinstance(v, dict) else v
                for v in cast("list[Any]", value or [])
            ]
            return {self._groups_field(): [(6, 0, [int(i) for i in ids if i])]}
        return cast("StudioRecordSurface", super())._coerce_virtual(
            row, value, model_name
        )

    @api.model
    def _coerce(
        self, model_name: str, values: dict[str, object], creating: bool = False
    ) -> dict[str, object]:
        vals = cast("StudioRecordSurface", super())._coerce(
            model_name, values, creating=creating
        )
        if any(perm in vals for perm in _PERMS) and not any(
            vals.get(perm, True) for perm in _PERMS
        ):
            raise UserError(
                _(
                    "A rule that applies to nothing -- no read, write, create or "
                    "delete -- does nothing."
                )
            )
        return vals

    @api.model
    def _foreign_reason(self, record: BaseModel, module: str) -> str:
        return _(
            "Rules of one group are OR-ed and global rules AND-ed, so a rule "
            "of %s cannot be loosened from your package -- only tightened by "
            "adding a rule of your own here.",
            module,
        )

    @api.model
    def _domain_eval_context(self, model_name: str) -> dict[str, object] | None:
        # What ir.rule itself evaluates a domain with: user, company_ids, time.
        return cast("dict[str, object]", typed.model(self.env, IrRule)._eval_context())

    @api.model
    def _describe_extra(
        self, record: BaseModel, package: StudioPackage
    ) -> dict[str, object]:
        rule = cast("IrRule", record)
        model = cast("IrModel", rule.model_id)
        # `_check_domain` is declared on `studio.record.surface`, reached
        # only via `_inherit` -- invisible to pyright on `self` the same way
        # `super()._method()` is invisible on a bare `super()` (rule 4/6).
        check = cast("StudioRecordSurface", self)._check_domain(
            model.model, rule.domain_force or "[]"
        )
        return {"matches": check}

    @api.model
    def templates(self, model_name: str | None = None) -> list[RecordTemplateJSON]:
        """Only the presets whose field the model has."""
        out = cast("StudioRecordSurface", super()).templates(model_name)
        if not model_name or model_name not in self.env:
            return out
        fields_ = cast("dict[str, Field[Any]]", self.env[model_name]._fields)
        needs = {"assigned_to_me": "user_id", "own_company": "company_id"}
        return [t for t in out if t["key"] not in needs or needs[t["key"]] in fields_]

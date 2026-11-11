# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Reports as a record pane: the model's reports, ours and everybody's.

Somebody else's report is the one worth showing: its settings are its
module's, but its layout is editable from the canvas, and the edit lands
in a view of the package that inherits the template -- so the original
keeps receiving fixes, and *Reset layout* is one action that deletes the
patch. A report made here is written whole: action, template, Print
entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
from odoo.addons.app_builder_base.models.builder_record_surface import RecordRowJSON
from odoo.addons.app_builder_base.tools import compat, scaffold, typed
from odoo.addons.app_builder_base.tools.catalogue import Row, Section
from odoo.addons.app_builder_base.tools.i18n import _
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_ui_view import View

if TYPE_CHECKING:
    # Only used inside annotations (`from __future__ import annotations`
    # defers all of them to strings), never at runtime -- the same bargain
    # `builder_record_surface.py`'s own `TYPE_CHECKING`-guarded imports
    # make. `IrModel`/`View`/`BuilderPackage`/`RecordRowJSON` are real,
    # top-level imports instead (above): `typed.model()` reads `cls._name`
    # at *runtime*, and `RecordRowJSON` is a real base class of
    # `ReportRowJSON` below (rule 8's TypedDict subclassing), both needing
    # a real binding.
    from odoo.models import BaseModel

    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.app_builder_base.models.builder_record_surface import (
        BuilderRecordSurface,
        RecordActionJSON,
        RecordBadgeJSON,
        RecordOwnerJSON,
        RecordTemplateJSON,
    )
    from odoo.addons.base.models.ir_actions import IrActions
    from odoo.addons.base.models.ir_actions_report import IrActionsReport
    from odoo.addons.base.models.report_paperformat import (
        report_paperformat as ReportPaperformat,
    )

    # `.builder_report`'s own module also declares a class named
    # `BuilderReport` (the SAME "builder.report" `_name`, merged into one
    # real model by the registry, but two separate classes as far as
    # pyright is concerned) -- aliased on import so this file's own
    # `class BuilderReport` below does not collide with it. A plain
    # `cast()` target needs no runtime binding (rule 4), so this stays
    # `TYPE_CHECKING`-only rather than a real top-level import.
    from .builder_report import BuilderReport as BuilderReportBase


class ReportRowJSON(RecordRowJSON):
    """``_row()``'s own return: the base card plus the report's template
    and Print-menu status (`wire.ts`'s own optional `view_id`, per
    `builder_record_surface.py`'s own docstring)."""

    view_id: int | Literal[False]
    report_name: str
    patched: bool


class BuilderReport(models.AbstractModel):
    _name = "builder.report"
    # The surface first: it carries the security mixin ``builder.report``
    # already has, and Python's MRO wants the derived class before its base.
    _inherit = ["builder.record.surface", "builder.report"]

    _surface_model = "ir.actions.report"
    _surface_model_field = "model"
    _surface_virtual = ("in_print_menu", "groups", "layout")
    _surface_sections = (
        Section(
            "report",
            "Report",
            (
                Row(name="name", label="Name", type="text", required=True),
                Row(
                    name="report_type",
                    label="Format",
                    type="select",
                    selection_from="ir.actions.report.report_type",
                ),
                Row(
                    name="paperformat_id",
                    label="Paper",
                    type="many2one",
                    comodel="report.paperformat",
                    help="Empty: the company's default.",
                ),
                Row(
                    name="in_print_menu",
                    label="In the Print menu",
                    type="toggle",
                    help="Off: only reachable from code or a button.",
                ),
                Row(
                    name="groups",
                    label="Visible to",
                    type="many2many",
                    comodel="res.groups",
                    help="Empty: everyone who can see the record.",
                ),
                Row(
                    name="attachment_use",
                    label="Reuse the saved copy",
                    type="toggle",
                    help="Print once, then hand out the attachment it saved.",
                ),
            ),
        ),
    )
    _surface_templates = ()

    # -- templates: the layouts --------------------------------------------------

    @api.model
    def templates(self, model_name: str | None = None) -> list[RecordTemplateJSON]:
        typed.security(self)._assert_builder_user()
        return [
            {
                "key": layout["key"],
                "label": layout["label"],
                "help": layout["help"],
                "values": {"layout": layout["key"]},
                "needs": ["name"],
            }
            for layout in scaffold.report_layouts_json()
        ]

    @api.model
    def _template_values(
        self, template: str, model_name: str, values: dict[str, object] | None
    ) -> dict[str, object]:
        if template not in scaffold.REPORT_LAYOUTS_BY_KEY:
            raise UserError(_("'%s' is not a report layout.", template))
        return {"layout": template}

    # -- rows ------------------------------------------------------------------

    @api.model
    def _groups_field(self) -> str:
        return compat.groups_field(self.env, "ir.actions.report")

    @api.model
    def _patch_of(self, report: IrActionsReport, package: BuilderPackage) -> View:
        """The package's inheriting view on the report's template, if any."""
        Views = typed.model(self.env, View)
        view = cast("BuilderReportBase", self)._template_of(report)
        if not view or not package:
            return Views
        return Views.sudo().search(
            [("inherit_id", "=", view.id), ("builder_package_id", "=", package.id)],
            limit=1,
        )

    @api.model
    def _row(self, record: BaseModel, package: BuilderPackage) -> ReportRowJSON:
        # `super()._row()` builds the eleven base keys; the cast states the
        # target shape (this file's own `ReportRowJSON`, rule 8's TypedDict
        # subclassing) before the three extra keys below are actually set,
        # the same mutate-after-call order the original always had.
        row = cast(
            "ReportRowJSON", cast("BuilderRecordSurface", super())._row(record, package)
        )
        report = cast("IrActionsReport", record)
        view = cast("BuilderReportBase", self)._template_of(report)
        row["view_id"] = cast("int", view.id) or False
        # `report_name` is `required=True`, so never actually `False` --
        # same true-by-construction idiom as `_subject_model`'s own
        # `.model` cast (`builder_record_surface.py`).
        row["report_name"] = cast("str", report.report_name)
        row["patched"] = bool(self._patch_of(report, package))
        return row

    @api.model
    def _badges(
        self, record: BaseModel, owner: RecordOwnerJSON
    ) -> list[RecordBadgeJSON]:
        badges = cast("BuilderRecordSurface", super())._badges(record, owner)
        report = cast("IrActionsReport", record)
        if not cast("BuilderReportBase", self)._template_of(report):
            badges.append({"key": "no_template", "label": _("No template")})
        # `binding_model_id` lives on `ir.actions.actions`
        # (`_inherit = 'ir.actions.actions'`, registry-level, never a real
        # Python base of `IrActionsReport`) -- same gap `builder_report.py`'s
        # own `reports_for`/`edit_action` already cast `IrActions` for.
        if cast("IrActions", report).binding_model_id:
            badges.append({"key": "print", "label": _("Print menu")})
        return badges

    @api.model
    def _sentence(self, record: BaseModel) -> str:
        report = cast("IrActionsReport", record)
        # `report_type` is `required=True` with a default, so never
        # actually `False` -- same true-by-construction idiom as
        # `_row`'s own `report_name` cast above.
        report_type = cast("str", report.report_type)
        kinds = dict(
            cast(
                "list[tuple[str, str]]",
                report._fields["report_type"].get_description(self.env)["selection"],
            )
        )
        parts = [kinds.get(report_type, report_type)]
        if report.paperformat_id:
            # `paperformat_id` is a plain-string-comodel `Many2one` (rule
            # 5): its declaration stays untouched, and the real class is
            # cast in at the read site instead.
            parts.append(
                cast("str", cast("ReportPaperformat", report.paperformat_id).name)
            )
        view = cast("BuilderReportBase", self)._template_of(report)
        parts.append(
            _("template %s", report.report_name) if view else _("no template to edit")
        )
        return " · ".join(parts)

    @api.model
    def _foreign_reason(self, record: BaseModel, module: str) -> str:
        return _(
            "From %s. Its settings are its module's; its layout you can edit "
            "from the canvas, and the change lands in a view of your own that "
            "inherits theirs, so the original keeps receiving fixes.",
            module,
        )

    @api.model
    def _virtual_value(
        self, record: BaseModel, name: str
    ) -> bool | list[dict[str, object]] | str:
        if name == "in_print_menu":
            return bool(cast("object", cast("IrActions", record).binding_model_id))
        if name == "groups":
            return [
                {"id": group.id, "display_name": group.full_name}
                for group in record[self._groups_field()]
            ]
        if name == "layout":
            return ""
        return cast("BuilderRecordSurface", super())._virtual_value(record, name)

    @api.model
    def _coerce_virtual(
        self, row: Row, value: object, model_name: str
    ) -> dict[str, object]:
        if row.name == "in_print_menu":
            ir_model = (
                typed.model(self.env, IrModel)
                .sudo()
                .search([("model", "=", model_name)], limit=1)
            )
            return {
                "binding_model_id": ir_model.id if value and ir_model else False,
                "binding_type": "report",
            }
        if row.name == "groups":
            ids: list[Any] = [
                v.get("id") if isinstance(v, dict) else v
                for v in (cast("list[Any]", value) or [])
            ]
            ids = [int(i) for i in ids if i]
            # `_assert_in_source` lives on `builder.record.surface`
            # (`builder_record_surface.py`, a *different* file's class body
            # for the same `_inherit`-composed model) -- invisible to
            # pyright on plain `self` the same way `_assert_builder_user`
            # is on `builder.security.mixin` (rule 6, `typed.py`'s own
            # docstring).
            cast("BuilderRecordSurface", self)._assert_in_source(row, ids)
            return {self._groups_field(): [(6, 0, ids)]}
        if row.name == "layout":
            return {"_layout": value}
        return cast("BuilderRecordSurface", super())._coerce_virtual(
            row, value, model_name
        )

    @api.model
    def _actions(
        self, record: BaseModel, package: BuilderPackage
    ) -> list[RecordActionJSON]:
        actions = cast("BuilderRecordSurface", super())._actions(record, package)
        if self._patch_of(cast("IrActionsReport", record), package):
            actions.append(
                {
                    "key": "reset_layout",
                    "label": _("Reset layout"),
                    "icon": "fa fa-undo",
                    "enabled": bool(package and package.writable),
                    "reason": "" if package and package.writable else _("Read-only."),
                    "danger": True,
                }
            )
        return actions

    @api.model
    def _notes(self, record: BaseModel, package: BuilderPackage) -> list[object]:
        notes: list[object] = []
        if self._patch_of(cast("IrActionsReport", record), package):
            notes.append(
                _(
                    "Your layout changes live in a view of %s that inherits the "
                    "template. Reset deletes that patch; the original was never "
                    "changed.",
                    package.name,
                )
            )
        return notes

    @api.model
    def _run_reset_layout(self, record: BaseModel, package: BuilderPackage) -> None:
        if not package:
            raise UserError(_("Choose a package first."))
        package._assert_writable()
        patch = self._patch_of(cast("IrActionsReport", record), package)
        if patch:
            patch.unlink()
            package.action_write_files()

    # -- create ------------------------------------------------------------------

    @api.model
    def create_record(
        self,
        model_name: str,
        package_id: int | None,
        values: dict[str, object] | None,
        template: str | None = None,
    ) -> ReportRowJSON:
        """A report is made whole by ``create_report``: action, qweb
        template and Print entry, named so the three agree."""
        typed.security(self)._assert_builder_manager()
        values = dict(values or {})
        # `.pop()` on a `dict[str, object]` gives `object`; the value is a
        # genuinely heterogeneous RPC payload one either way, always
        # str-shaped by construction once the `or` chain runs -- same
        # "trust the runtime, cast for the type" idiom `_coerce_one`'s own
        # `int(cast("Any", value) or 0)` already uses.
        layout = cast("str", values.pop("layout", None) or template or "external")
        # `_coerce` lives on `builder.record.surface` -- same rule 6 gap as
        # `_assert_in_source` above.
        vals = cast("BuilderRecordSurface", self)._coerce(
            model_name, values, creating=True
        )
        vals.pop("_layout", None)
        name = cast("str", vals.pop("name", ""))
        if not name:
            raise UserError(_("Name is required."))
        package = typed.model(self.env, BuilderPackage)._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to record this in first."))
        made = cast("BuilderReportBase", self).create_report(
            cast("int", package.id),
            model_name,
            name,
            layout=layout,
            paperformat_id=cast("int | None", vals.pop("paperformat_id", None)) or None,
        )
        report = cast("BuilderRecordSurface", self)._model().browse(made["report_id"])
        if vals:
            report.write(vals)
            package.builder_capture(report)
        return self._row(report, package)

    @api.model
    def remove_record(
        self, record_id: int, package_id: int | None = None, force: bool = False
    ) -> bool:
        # `_record` lives on `builder.record.surface` -- same rule 6 gap as
        # `_assert_in_source`/`_coerce` above.
        record = cast("BuilderRecordSurface", self)._record(record_id)
        package = typed.model(self.env, BuilderPackage)._chosen(package_id)
        view = cast("BuilderReportBase", self)._template_of(
            cast("IrActionsReport", record)
        )
        result = cast("BuilderRecordSurface", super()).remove_record(
            record_id, package_id, force=force
        )
        if (
            view
            and package
            and cast("BuilderOwnedMixin", view).builder_package_id == package
        ):
            view.unlink()
            package.action_write_files()
        return result

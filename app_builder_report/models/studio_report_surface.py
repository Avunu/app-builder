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

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import compat, scaffold
from odoo.addons.app_builder_base.tools.catalogue import Row, Section


class StudioReport(models.AbstractModel):
    _name = "studio.report"
    # The surface first: it carries the security mixin ``studio.report``
    # already has, and Python's MRO wants the derived class before its base.
    _inherit = ["studio.record.surface", "studio.report"]

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
    def templates(self, model_name=None):
        self._assert_studio_user()
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
    def _template_values(self, template, model_name, values):
        if template not in scaffold.REPORT_LAYOUTS_BY_KEY:
            raise UserError(_("'%s' is not a report layout.", template))
        return {"layout": template}

    # -- rows ------------------------------------------------------------------

    @api.model
    def _groups_field(self):
        return compat.groups_field(self.env, "ir.actions.report")

    @api.model
    def _patch_of(self, report, package):
        """The package's inheriting view on the report's template, if any."""
        view = self._template_of(report)
        if not view or not package:
            return self.env["ir.ui.view"]
        return (
            self.env["ir.ui.view"]
            .sudo()
            .search(
                [("inherit_id", "=", view.id), ("studio_package_id", "=", package.id)],
                limit=1,
            )
        )

    @api.model
    def _row(self, record, package):
        row = super()._row(record, package)
        view = self._template_of(record)
        row["view_id"] = view.id or False
        row["report_name"] = record.report_name
        row["patched"] = bool(self._patch_of(record, package))
        return row

    @api.model
    def _badges(self, record, owner):
        badges = super()._badges(record, owner)
        if not self._template_of(record):
            badges.append({"key": "no_template", "label": _("No template")})
        if record.binding_model_id:
            badges.append({"key": "print", "label": _("Print menu")})
        return badges

    @api.model
    def _sentence(self, record):
        kinds = dict(
            record._fields["report_type"].get_description(self.env)["selection"]
        )
        parts = [kinds.get(record.report_type, record.report_type)]
        if record.paperformat_id:
            parts.append(record.paperformat_id.name)
        view = self._template_of(record)
        parts.append(
            _("template %s", record.report_name) if view else _("no template to edit")
        )
        return " · ".join(parts)

    @api.model
    def _foreign_reason(self, record, module):
        return _(
            "From %s. Its settings are its module's; its layout you can edit "
            "from the canvas, and the change lands in a view of your own that "
            "inherits theirs, so the original keeps receiving fixes.",
            module,
        )

    @api.model
    def _virtual_value(self, record, name):
        if name == "in_print_menu":
            return bool(record.binding_model_id)
        if name == "groups":
            return [
                {"id": group.id, "display_name": group.full_name}
                for group in record[self._groups_field()]
            ]
        if name == "layout":
            return ""
        return super()._virtual_value(record, name)

    @api.model
    def _coerce_virtual(self, row, value, model_name):
        if row.name == "in_print_menu":
            ir_model = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", model_name)], limit=1)
            )
            return {
                "binding_model_id": ir_model.id if value and ir_model else False,
                "binding_type": "report",
            }
        if row.name == "groups":
            ids = [v.get("id") if isinstance(v, dict) else v for v in (value or [])]
            ids = [int(i) for i in ids if i]
            self._assert_in_source(row, ids)
            return {self._groups_field(): [(6, 0, ids)]}
        if row.name == "layout":
            return {"_layout": value}
        return super()._coerce_virtual(row, value, model_name)

    @api.model
    def _actions(self, record, package):
        actions = super()._actions(record, package)
        if self._patch_of(record, package):
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
    def _notes(self, record, package):
        notes = []
        if self._patch_of(record, package):
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
    def _run_reset_layout(self, record, package):
        if not package:
            raise UserError(_("Choose a package first."))
        package._assert_writable()
        patch = self._patch_of(record, package)
        if patch:
            patch.unlink()
            package.action_write_files()

    # -- create ------------------------------------------------------------------

    @api.model
    def create_record(self, model_name, package_id, values, template=None):
        """A report is made whole by ``create_report``: action, qweb
        template and Print entry, named so the three agree."""
        self._assert_studio_manager()
        values = dict(values or {})
        layout = values.pop("layout", None) or template or "external"
        vals = self._coerce(model_name, values, creating=True)
        vals.pop("_layout", None)
        name = vals.pop("name", "")
        if not name:
            raise UserError(_("Name is required."))
        package = self.env["studio.package"]._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to record this in first."))
        made = self.create_report(
            package.id,
            model_name,
            name,
            layout=layout,
            paperformat_id=vals.pop("paperformat_id", None) or None,
        )
        report = self._model().browse(made["report_id"])
        if vals:
            report.write(vals)
            package.studio_capture(report)
        return self._row(report, package)

    @api.model
    def remove_record(self, record_id, package_id=None, force=False):
        record = self._record(record_id)
        package = self.env["studio.package"]._chosen(package_id)
        view = self._template_of(record)
        result = super().remove_record(record_id, package_id, force=force)
        if view and package and view.studio_package_id == package:
            view.unlink()
            package.action_write_files()
        return result

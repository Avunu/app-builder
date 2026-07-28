# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Guided creation of a model and the app around it.

A thin dialog over ``studio.app.builder``, which does the real work: write the
class, install and reload the package, then build the views, action, menu and
ACL against the live model.

The model it makes is a real ``models.Model`` from the first save -- there is no
later conversion step, and no ``x_`` prefix. What the builder owns is the marked
block inside the class; everything else in that file is yours from the moment it
exists.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import scaffold


class StudioModelWizard(models.TransientModel):
    _name = "studio.model.wizard"
    _description = "Studio: New Model"

    package_id = fields.Many2one("studio.package", required=True)
    name = fields.Char(string="Label", required=True, help="Human-readable name.")
    model = fields.Char(
        string="Technical Name",
        help="Left empty, this is derived from the label.",
    )

    add_chatter = fields.Boolean(
        string="Messaging & activities",
        default=True,
        help="Adds mail.thread and mail.activity.mixin, so records carry a "
        "message log and scheduled activities.",
    )
    add_stage = fields.Boolean(
        string="Status bar",
        help="A draft/in progress/done selection, shown as a statusbar.",
    )
    add_user = fields.Boolean(
        string="Responsible",
        help="A user field, defaulted to whoever creates the record.",
    )
    add_reference = fields.Boolean(
        string="Reference numbers",
        help="A sequence-backed reference, filled in on create.",
    )
    add_date = fields.Boolean(string="Date")

    groups_ids = fields.Many2many(
        "res.groups",
        string="Who can use this",
        help="Groups that get read/write/create access. A model with no access "
        "rule is invisible to everyone except the administrator who built it.",
    )

    @api.onchange("name")
    def _onchange_name(self):
        if self.name and not self.model:
            self.model = self.env["studio.app.builder"].technical_name(
                self.name, self.package_id
            )

    @api.onchange("package_id")
    def _onchange_package_id(self):
        # The derived name carries the package prefix, so it has to follow it.
        if self.name:
            self.model = self.env["studio.app.builder"].technical_name(
                self.name, self.package_id
            )

    def action_create(self):
        self.ensure_one()
        if not self.package_id.writable:
            raise UserError(
                _(
                    "The package directory is not writable, so nothing can be "
                    "built. This is normal on a production deployment: build in "
                    "a development environment and ship through git."
                )
            )
        options = scaffold.ScaffoldOptions(
            chatter=self.add_chatter,
            activities=self.add_chatter,
            stage=self.add_stage,
            user=self.add_user,
            reference=self.add_reference,
            date=self.add_date,
        )
        groups = self.groups_ids or self.env.ref("base.group_user")
        built = self.env["studio.app.builder"].create_app(
            self.package_id,
            self.name,
            model_name=self.model or None,
            options=options,
            groups=groups,
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": built["model"].model,
            "view_mode": "list,form",
            "target": "current",
        }


class StudioFieldWizard(models.TransientModel):
    _name = "studio.field.wizard"
    _description = "Studio: New Field"

    package_id = fields.Many2one("studio.package", required=True)
    model_id = fields.Many2one("ir.model", required=True)
    name = fields.Char(required=True)
    field_description = fields.Char(string="Label", required=True)
    ttype = fields.Selection(
        selection=lambda self: self.env["ir.model.fields"]._fields["ttype"].selection,
        string="Field Type",
        required=True,
        default="char",
    )
    relation = fields.Char(string="Related Model")
    relation_field = fields.Char(string="Inverse Field")
    required = fields.Boolean()
    store = fields.Boolean(default=True)
    compute = fields.Text(
        help="Python expression evaluated against 'self'. Stored as data on "
        "ir.model.fields, so it needs no code file and no server restart."
    )
    depends = fields.Char(help="Comma-separated field names the compute reads.")

    @api.onchange("field_description")
    def _onchange_label(self):
        if self.field_description and not self.name:
            slug = "".join(
                c if c.isalnum() else "_" for c in self.field_description.lower()
            )
            self.name = "x_%s" % slug.strip("_")

    def action_create(self):
        self.ensure_one()
        if not self.name.startswith("x_"):
            raise UserError(_("A custom field name must start with 'x_'."))
        values = {
            "name": self.name,
            "field_description": self.field_description,
            "ttype": self.ttype,
            "model_id": self.model_id.id,
            "required": self.required,
            "store": self.store,
        }
        if self.ttype in ("many2one", "one2many", "many2many"):
            if not self.relation:
                raise UserError(_("A relational field needs a related model."))
            values["relation"] = self.relation
        if self.ttype == "one2many":
            if not self.relation_field:
                raise UserError(_("A one2many field needs an inverse field."))
            values["relation_field"] = self.relation_field
        if self.compute:
            values.update({"compute": self.compute, "depends": self.depends or False})

        field = (
            self.env["ir.model.fields"]
            .with_context(studio_skip_autocapture=True)
            .create(values)
        )
        self.package_id.studio_capture(field)
        return {"type": "ir.actions.act_window_close"}

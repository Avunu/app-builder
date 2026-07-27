# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Guided creation of a custom model with its default UI.

Follows the shape proven by OCA's ``bi_sql_editor``: one definition record
materialises the model, its fields, an ACL, list and form views, an action and
a menu. The difference is that every artefact is captured into a studio package
and written to source in the same transaction.
"""

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StudioModelWizard(models.TransientModel):
    _name = "studio.model.wizard"
    _description = "Studio: New Model"

    package_id = fields.Many2one("studio.package", required=True)
    name = fields.Char(string="Label", required=True, help="Human-readable name.")
    model = fields.Char(
        required=True,
        help="Technical name. Odoo requires custom models to start with 'x_'.",
    )
    add_views = fields.Boolean(
        string="Generate list & form views",
        default=True,
    )
    add_menu = fields.Boolean(string="Add to the Studio menu", default=True)
    add_access = fields.Boolean(string="Grant access to Internal Users", default=True)

    @api.onchange("name")
    def _onchange_name(self):
        if self.name and not self.model:
            slug = "".join(c if c.isalnum() else "_" for c in self.name.lower())
            self.model = "x_%s" % slug.strip("_")

    def action_create(self):
        self.ensure_one()
        if not self.model.startswith("x_"):
            raise UserError(_("A custom model name must start with 'x_'."))

        package = self.package_id
        model = self.env["ir.model"].create(
            {
                "name": self.name,
                "model": self.model,
                "field_id": [
                    (
                        0,
                        0,
                        {
                            "name": "x_name",
                            "field_description": "Name",
                            "ttype": "char",
                            "required": True,
                        },
                    )
                ],
            }
        )
        # A list, not a recordset: these span several models and Odoo refuses
        # to concatenate recordsets of different models.
        captured = [model, model.field_id.filtered(lambda f: f.state == "manual")]

        if self.add_access:
            captured.append(
                self.env["ir.model.access"].create(
                    {
                        "name": "%s all" % self.model,
                        "model_id": model.id,
                        "group_id": self.env.ref("base.group_user").id,
                        "perm_read": True,
                        "perm_write": True,
                        "perm_create": True,
                        "perm_unlink": True,
                    }
                )
            )

        action = False
        if self.add_views:
            captured.append(self._build_views(model))
            action = self.env["ir.actions.act_window"].create(
                {
                    "name": self.name,
                    "res_model": self.model,
                    "view_mode": "list,form",
                }
            )
            captured.append(action)

        if self.add_menu and action:
            captured.append(
                self.env["ir.ui.menu"].create(
                    {
                        "name": self.name,
                        "parent_id": self.env.ref(
                            "app_builder_base.menu_studio_root"
                        ).id,
                        "action": "ir.actions.act_window,%d" % action.id,
                        "sequence": 50,
                    }
                )
            )

        package.studio_capture(captured)

        if action:
            return {
                "type": "ir.actions.act_window",
                "res_model": self.model,
                "view_mode": "list,form",
                "name": self.name,
            }
        return {"type": "ir.actions.act_window_close"}

    def _build_views(self, model):
        View = self.env["ir.ui.view"]
        # The label is user input going into an XML attribute: a name containing
        # &, < or a quote would otherwise produce an arch that does not parse.
        label = escape(self.name)
        list_view = View.create(
            {
                "name": "%s.list" % self.model,
                "model": self.model,
                "arch": '<list string="%s"><field name="x_name"/></list>' % label,
            }
        )
        form_view = View.create(
            {
                "name": "%s.form" % self.model,
                "model": self.model,
                "arch": (
                    '<form string="%s"><sheet><group>'
                    '<field name="x_name"/>'
                    "</group></sheet></form>"
                )
                % label,
            }
        )
        return list_view + form_view


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

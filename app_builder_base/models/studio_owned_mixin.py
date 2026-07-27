# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package ownership, as a mixin any studio-managed record can inherit.

Lives in the engine rather than in a builder module: ``app_builder_ui`` inherits
it for menus, actions and rules without having any reason to depend on the
model builder, and a mixin defined in a module you do not depend on aborts the
registry at install time.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StudioOwnedMixin(models.AbstractModel):
    _name = "studio.owned.mixin"
    _description = "Studio Owned Record"

    studio_package_id = fields.Many2one(
        "studio.package",
        string="Studio Package",
        compute="_compute_studio_package_id",
        inverse="_inverse_studio_package_id",
        store=False,
        help="The package whose source files this record is written into.",
    )

    def _compute_studio_package_id(self):
        Data = self.env["ir.model.data"]
        Package = self.env["studio.package"]
        for record in self:
            entry = Data.search(
                [("model", "=", record._name), ("res_id", "=", record.id)], limit=1
            )
            record.studio_package_id = (
                Package.search([("name", "=", entry.module)], limit=1)
                if entry
                else Package
            )

    def _inverse_studio_package_id(self):
        for record in self:
            package = record.studio_package_id
            if not package:
                continue
            if not record._studio_assignable():
                raise UserError(
                    _(
                        "%(name)s is defined in Python code and belongs to the "
                        "module that declares it. Only custom (manual) records "
                        "can be owned by a studio package.",
                        name=record.display_name,
                    )
                )
            owner = record._studio_current_package()
            if owner and owner != package:
                raise UserError(
                    _(
                        "%(name)s already belongs to package '%(owner)s'. Move it "
                        "there, or remove it from that package first -- a record "
                        "can only be written into one addon.",
                        name=record.display_name,
                        owner=owner.name,
                    )
                )
            package.studio_capture(record)

    def _studio_current_package(self):
        """The package that already owns this record, if any."""
        self.ensure_one()
        entry = self.env["ir.model.data"].search(
            [("model", "=", self._name), ("res_id", "=", self.id)], limit=1
        )
        if not entry:
            return self.env["studio.package"]
        return self.env["studio.package"].search([("name", "=", entry.module)], limit=1)

    def _studio_assignable(self):
        """Whether this record may be taken over by a package."""
        self.ensure_one()
        return True

    def action_studio_write(self):
        """Flush the owning package to disk."""
        for package in self.mapped("studio_package_id"):
            package.action_write_files()
        return True


class IrUiView(models.Model):
    _name = "ir.ui.view"
    _inherit = ["ir.ui.view", "studio.owned.mixin"]

    def _studio_assignable(self):
        self.ensure_one()
        # Any view can be owned: a studio package legitimately contains both new
        # views and extensions of core ones. What it must never do is rewrite a
        # view another module declares -- enforced by only ever creating
        # inheriting views, in studio.view.editor.
        return True


class IrModel(models.Model):
    _name = "ir.model"
    _inherit = ["ir.model", "studio.owned.mixin"]

    def _studio_assignable(self):
        self.ensure_one()
        return self.state == "manual"


class IrModelFields(models.Model):
    _name = "ir.model.fields"
    _inherit = ["ir.model.fields", "studio.owned.mixin"]

    def _studio_assignable(self):
        self.ensure_one()
        return self.state == "manual"

    @api.model_create_multi
    def create(self, vals_list):
        """Keep a new field in the same package as the model it extends.

        Without this, adding a field through the studio would create it in the
        database and leave it out of the source tree until somebody remembered
        to assign it -- exactly the drift the project exists to prevent.
        """
        records = super().create(vals_list)
        if self.env.context.get("studio_skip_autocapture"):
            return records
        for record in records:
            if record.state != "manual":
                continue
            package = record.model_id.studio_package_id
            if package:
                package.studio_capture(record)
        return records

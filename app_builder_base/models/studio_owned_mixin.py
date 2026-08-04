# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package ownership, as a mixin any studio-managed record can inherit.

Lives in the engine rather than in a builder module: ``app_builder_ui`` inherits
it for menus, actions and rules without having any reason to depend on the
model builder, and a mixin defined in a module you do not depend on aborts the
registry at install time.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StudioOwnedMixin(models.AbstractModel):
    _name = "studio.owned.mixin"
    _description = "Studio Owned Record"

    studio_package_id = fields.Many2one(
        "studio.package",
        string="Studio Package",
        compute="_compute_studio_package_id",
        inverse="_inverse_studio_package_id",
        search="_search_studio_package_id",
        store=False,
        help="The package whose source files this record is written into.",
    )

    @api.model
    def _search_studio_package_id(self, operator, value):
        """Resolve ownership through ir.model.data, where it actually lives.

        Not optional, and not merely an optimisation. A non-stored field with
        no search method does not make a domain fail -- the ORM logs an error
        and **drops the leaf** (``expression.py:1179-1187``), so
        ``[("studio_package_id", "=", pkg.id)]`` silently degrades from "views
        this package owns" to "every view". ``studio_model_draft._owned_views``
        is built on exactly that domain, which means field placement would have
        rewritten a *primary view belonging to another module* in place: the
        single thing this project exists not to do.
        """
        if operator not in ("=", "!=", "in", "not in"):
            raise UserError(_("Studio Package cannot be searched with '%s'.", operator))
        negate = operator in ("!=", "not in")
        Package = self.env["studio.package"]
        if not value:
            # "owned by nobody" is the complement of "owned by anybody", so it
            # is answered against every package rather than against none.
            owned = self._studio_owned_ids(Package.search([]))
            return [("id", "in" if negate else "not in", owned)]
        if isinstance(value, str):
            packages = Package.search([("name", "=", value)])
        else:
            packages = Package.browse(value if isinstance(value, list) else [value])
        owned = self._studio_owned_ids(packages.exists())
        return [("id", "not in" if negate else "in", owned)]

    @api.model
    def _studio_owned_ids(self, packages):
        """Ids of this model's records carried by any of ``packages``."""
        if not packages:
            return []
        entries = self.env["ir.model.data"].search(
            [("model", "=", self._name), ("module", "in", packages.mapped("name"))]
        )
        return entries.mapped("res_id")

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

        The model's own package is only the *first* place to look. A manual
        field added to a core model -- ``res.partner``, the single most likely
        thing anyone does here -- resolves to no package at all, because
        ``res.partner`` belongs to ``base``. Falling back to the package the
        caller is editing in is what stops that field from being created live
        and written nowhere.
        """
        records = super().create(vals_list)
        if self.env.context.get("studio_skip_autocapture"):
            return records
        fallback = (
            self.env["studio.package"]
            .browse(self.env.context.get("studio_package_id") or [])
            .exists()
        )
        for record in records:
            if record.state != "manual":
                continue
            package = record.model_id.studio_package_id or fallback
            if package:
                package.studio_capture(record)
            else:
                # Warn rather than raise: creating a manual field outside any
                # package is legitimate for callers that are not the studio,
                # and they must not be forced into one. The studio surfaces the
                # orphan count separately so this is not the only signal.
                _logger.warning(
                    "Manual field %s.%s was created outside any studio package "
                    "and will not be written to source.",
                    record.model,
                    record.name,
                )
        return records

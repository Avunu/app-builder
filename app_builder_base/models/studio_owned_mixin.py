# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Package ownership, as a mixin any studio-managed record can inherit.

Lives in the engine rather than in a builder module: ``app_builder_ui`` inherits
it for menus, actions and rules without having any reason to depend on the
model builder, and a mixin defined in a module you do not depend on aborts the
registry at install time. The same goes for capture on create, which
``app_builder_approval`` needs for the engine's approval rules without any
reason to depend on ``app_builder_ui``: one rule, in the one module both
depend on, rather than a copy per builder that drifts unnoticed because each
copy works.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_model import IrModelData

from ..tools import typed
from .studio_package import StudioPackage

if TYPE_CHECKING:
    from odoo.api import Self, ValuesType

    # Aliased: this file defines its own ``IrModel``/``IrModelFields``
    # classes below (``_inherit``-composed with ``studio.owned.mixin`` at the
    # registry level, never a real Python base class), so importing the
    # *core* classes under their own bare names would shadow those local
    # definitions. Same classes ``pycodegen.py``/``studio_package.py`` already
    # import for the identical "cast a plain-string-comodel read to its real
    # class" purpose -- renamed only because this file, uniquely so far, also
    # declares classes of the same name for a different reason (extend and
    # mix in, not a type-only import).
    from odoo.addons.base.models.ir_model import IrModel as CoreIrModel
    from odoo.addons.base.models.ir_model import IrModelFields as CoreIrModelFields

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
    def _search_studio_package_id(self, operator: str, value: object) -> api.DomainType:
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
        Package = typed.model(self.env, StudioPackage)
        if not value:
            # "owned by nobody" is the complement of "owned by anybody", so it
            # is answered against every package rather than against none.
            owned = self._studio_owned_ids(Package.search([]))
            return [("id", "in" if negate else "not in", owned)]
        if isinstance(value, str):
            packages = Package.search([("name", "=", value)])
        else:
            # Every real caller passes either a single id or a list of ids,
            # the two shapes ``browse()`` itself accepts, once the
            # string-name branch above has ruled out anything else -- honest
            # about what a domain leaf's value actually carries, not a new
            # runtime check.
            ids = cast("list[int]", value if isinstance(value, list) else [value])
            packages = Package.browse(ids)
        owned = self._studio_owned_ids(packages.exists())
        return [("id", "not in" if negate else "in", owned)]

    @api.model
    def _studio_owned_ids(self, packages: StudioPackage) -> list[int]:
        """Ids of this model's records carried by any of ``packages``."""
        if not packages:
            return []
        entries = typed.model(self.env, IrModelData).search(
            [("model", "=", self._name), ("module", "in", packages.mapped("name"))]
        )
        return cast("list[int]", entries.mapped("res_id"))

    def _compute_studio_package_id(self) -> None:
        Data = typed.model(self.env, IrModelData)
        Package = typed.model(self.env, StudioPackage)
        for record in self:
            entry = Data.search(
                [("model", "=", record._name), ("res_id", "=", record.id)], limit=1
            )
            record.studio_package_id = (
                Package.search([("name", "=", entry.module)], limit=1)
                if entry
                else Package
            )

    def _inverse_studio_package_id(self) -> None:
        for record in self:
            package = cast("StudioPackage", record.studio_package_id)
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

    def _studio_current_package(self) -> StudioPackage:
        """The package that already owns this record, if any."""
        self.ensure_one()
        entry = typed.model(self.env, IrModelData).search(
            [("model", "=", self._name), ("res_id", "=", self.id)], limit=1
        )
        if not entry:
            return typed.model(self.env, StudioPackage)
        return typed.model(self.env, StudioPackage).search(
            [("name", "=", entry.module)], limit=1
        )

    def _studio_assignable(self) -> bool:
        """Whether this record may be taken over by a package."""
        self.ensure_one()
        return True

    def action_studio_write(self) -> bool:
        """Flush the owning package to disk."""
        for package in cast("StudioPackage", self.mapped("studio_package_id")):
            package.action_write_files()
        return True


class StudioCapturedOnCreate(models.AbstractModel):
    """Records that belong to the package the studio is working in.

    Same reasoning as ``ir.model.fields``: a rule created through the studio and
    left unassigned exists in this database and nowhere else, which is exactly
    the drift the project exists to prevent -- and it is invisible, because the
    rule *works*. It works here, forever, and never anywhere else.

    Only when a package is named in context, so ordinary use of Settings →
    Technical is unaffected. A warning rather than an error for the same reason
    the field mixin warns: callers that are not the studio must not be forced
    into a package they never asked for.
    """

    _name = "studio.captured.on.create"
    _description = "Studio Captured On Create"

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        if self.env.context.get("studio_skip_autocapture"):
            return records
        package = (
            typed.model(self.env, StudioPackage)
            .browse(self.env.context.get("studio_package_id") or [])
            .exists()
        )
        if package and package.writable:
            package.studio_capture(records)
        elif self.env.context.get("studio_package_id"):
            _logger.warning(
                "%s was created for a studio package that is missing or "
                "read-only, so it will not be written to source.",
                records._name,
            )
        return records


class IrUiView(models.Model):
    _name = "ir.ui.view"
    _inherit = ["ir.ui.view", "studio.owned.mixin"]

    def _studio_assignable(self) -> bool:
        self.ensure_one()
        # Any view can be owned: a studio package legitimately contains both new
        # views and extensions of core ones. What it must never do is rewrite a
        # view another module declares -- enforced by only ever creating
        # inheriting views, in studio.view.editor.
        return True


class IrModel(models.Model):
    _name = "ir.model"
    _inherit = ["ir.model", "studio.owned.mixin"]

    def _studio_assignable(self) -> bool:
        self.ensure_one()
        return cast("CoreIrModel", self).state == "manual"


class IrModelFields(models.Model):
    _name = "ir.model.fields"
    _inherit = ["ir.model.fields", "studio.owned.mixin"]

    def _studio_assignable(self) -> bool:
        self.ensure_one()
        return cast("CoreIrModelFields", self).state == "manual"

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
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
            typed.model(self.env, StudioPackage)
            .browse(self.env.context.get("studio_package_id") or [])
            .exists()
        )
        for record in records:
            core_record = cast("CoreIrModelFields", record)
            if core_record.state != "manual":
                continue
            model = cast("StudioOwnedMixin", core_record.model_id)  # pyright: ignore[reportUnknownMemberType]
            package = cast("StudioPackage", model.studio_package_id) or fallback
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
                    core_record.model,
                    core_record.name,
                )
        return records

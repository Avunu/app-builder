# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Automation code, promoted out of a sandboxed string into real source.

``ir.actions.server.code`` is a text column evaluated by ``safe_eval``. That is
what makes an automation work with no code file and no restart, and it is the
right trade for getting started. It is the wrong place for it to stay:

* nothing imports it, so no linter reads it, no test covers it and no reviewer
  sees it in a diff;
* it cannot be broken into functions, cannot be called from anywhere else, and
  cannot have a breakpoint put in it;
* ``safe_eval`` forbids most of Python, so the code that survives there is
  written around the sandbox rather than for the problem.

Odoo Studio's answer is that this is simply how automations are. Ours is that a
builder whose output is source code should be able to hand it over: the body
becomes a method on a class in the package, and the action calls it. The
sandboxed string that remains is one line long.

This is the same move the composer already makes for a compute -- and it needed
the same thing that made *that* possible for a model the package does not own,
which is why it could not be built until ``ModelSpec.extends`` existed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.tools import modelspec, pycodegen, typed
from odoo.addons.app_builder_base.tools.i18n import _
from odoo.addons.base.models.ir_actions import IrActionsServer

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime -- the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    # `BuilderPackageModel` is a real, top-level import instead (above):
    # `typed.model()` reads `cls._name` at runtime.
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from odoo.addons.app_builder_base.models.builder_package import BuilderPackage
    from odoo.addons.base.models.ir_model import IrModel


class GraduateJSON(TypedDict):
    """``graduate()``'s return: the method it wrote, and where."""

    method: str
    model: str
    applied: bool


class BuilderGraduateCode(models.AbstractModel):
    _name = "builder.graduate.code"
    _inherit = ["builder.security.mixin"]
    _description = "Builder: Promote Automation Code to Source"

    @api.model
    def can_graduate(self, action: IrActionsServer) -> str:
        """Why this action's code cannot become a method, or nothing."""
        if action.state != "code":
            return _("Only an Execute Code action has code to promote.")
        if not (action.code or "").strip():
            return _("There is no code here to promote.")
        if not action.model_id:
            return _("The action does not say which model it runs on.")
        # `builder_package_id` is a field from `builder.owned.mixin`, composed
        # onto `ir.actions.server` in `app_builder_ui/models/builder_owned.py`
        # (`_inherit`, never a real Python base class) -- invisible to
        # pyright on `action` itself without the first cast, same idiom as
        # `typed.security()`'s own docstring. The second cast is the plain-
        # string-comodel one (rule 5, `typed.py`'s own docstring): the field
        # is declared `Many2one("builder.package", ...)`, unsubscripted, so
        # its read type is the bound `BaseModel`, not `BuilderPackage`.
        package = cast(
            "BuilderPackage", cast("BuilderOwnedMixin", action).builder_package_id
        )
        if not package:
            return _(
                "This action does not belong to a builder package, so there is "
                "no source tree to write the method into."
            )
        if not package.writable:
            return _(
                "%s is read-only, which is what a production checkout should "
                "be. Promote the code where you build, and ship it through "
                "git.",
                package.name,
            )
        if self._already_promoted(action):
            return _("This action already calls a method in your source.")
        return ""

    @api.model
    def _already_promoted(self, action: IrActionsServer) -> bool:
        """A one-line body that is just a call is one we wrote."""
        body = (action.code or "").strip()
        prefix = "(records or record).%s" % modelspec.BUILDER_METHOD_PREFIX
        return body.startswith(prefix)

    @api.model
    def graduate(self, action_id: int, apply: bool = True) -> GraduateJSON:
        """Move the body into a method and leave the action calling it.

        ``apply`` writes the source *and* reloads the module, which is what
        makes the method callable -- Python is the one thing in this project
        that does not go live on write. It is separable because
        ``action_apply`` commits, and a commit is unreachable from a
        ``TransactionCase``: the same reason the end-to-end probes exist. So the
        transformation is testable in the ordinary suite and the reload is
        exercised where reloads are.
        """
        typed.security(self)._assert_builder_manager()
        action = typed.model(self.env, IrActionsServer).browse(action_id).exists()
        if not action:
            raise UserError(_("That action no longer exists."))
        problem = self.can_graduate(action)
        if problem:
            raise UserError(problem)

        # Same `builder.owned.mixin` self-cast, and same plain-string-comodel
        # cast, as `can_graduate` above.
        package = cast(
            "BuilderPackage", cast("BuilderOwnedMixin", action).builder_package_id
        )
        # `model_id` is likewise `Many2one("ir.model", ...)`, unsubscripted;
        # `model` is `ir.model`'s own required Char, declared `str | False`
        # but never actually empty -- same cast as `ir_model.py`'s serializer.
        model_name = cast("str", cast("IrModel", action.model_id).model)
        entry = self._python_entry(package, model_name)
        spec = entry._current_spec()
        if spec is None:
            raise UserError(
                _(
                    "%(model)s has no source the builder can read: %(why)s",
                    model=model_name,
                    why=entry.parse_error or _("the file is missing"),
                )
            )

        method = modelspec.MethodSpec(
            name=self._unique_method_name(spec, cast("str", action.name)),
            # `code` is declared `str | False` (`odoo/fields.py`'s own `Text`
            # read type); `can_graduate` above already required it non-empty
            # -- same "declared too abstract for what is really there"
            # cast as every other required-by-validation read in this
            # migration.
            body=cast("str", action.code).strip("\n"),
            doc=_("Promoted from the automation %s.", action.name),
        )
        from dataclasses import replace as _replace

        package._seed_source_for(
            model_name, _replace(spec, methods=spec.methods + (method,))
        )
        # The call, not the body. `records` is the whole set in multi-mode and
        # `record` the single one; taking whichever is there means the method
        # sees a recordset either way and can be written as an ordinary one.
        action.code = "(records or record).%s()" % method.name
        if apply:
            package.action_apply(reason=_("promote %s to source", action.name))
        return {"method": method.name, "model": model_name, "applied": apply}

    @api.model
    def _python_entry(
        self, package: BuilderPackage, model_name: str
    ) -> BuilderPackageModel:
        """The package's Python class for this model, extending if need be.

        A model the package declares already has one. Anything else -- which is
        most automations, since they run on `sale.order` and its neighbours --
        gets an extension: `_inherit` with no `_name`, which adds to the model
        rather than competing with it.
        """
        PackageModel = typed.model(self.env, BuilderPackageModel)
        entry = PackageModel.search(
            [("package_id", "=", package.id), ("model", "=", model_name)], limit=1
        )
        if entry:
            if entry.source != "python":
                raise UserError(
                    _(
                        "%s is managed as data records here, so there is no "
                        "class to put a method on. Graduate the model first.",
                        model_name,
                    )
                )
            return entry
        entry = PackageModel._adopt(package, model_name, extends=True)
        package._seed_source_for(
            model_name,
            modelspec.ModelSpec(
                name=model_name,
                description="",
                class_name=pycodegen.class_name_for(model_name),
                extends=True,
            ),
        )
        return entry

    @api.model
    def _unique_method_name(self, spec: modelspec.ModelSpec, label: str) -> str:
        base = pycodegen.method_name_for(label)
        taken = {m.name for m in spec.methods}
        if base not in taken:
            return base
        index = 2
        while "%s_%d" % (base, index) in taken:
            index += 1
        return "%s_%d" % (base, index)

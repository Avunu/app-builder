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

import ast
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


#: What ``ir.actions.server`` code is written against, and what each name is
#: inside an ordinary method. ``safe_eval`` hands the code these as globals
#: (``IrActionsServer._get_eval_context`` and the ``ir.actions.actions`` one
#: under it); a method has none of them, so a body moved verbatim raised
#: ``NameError`` on its first line. Each entry is the statements that bind the
#: name to its real equivalent -- emitted only for the names a body actually
#: uses, so a two-line automation does not become a method with a twenty-line
#: header.
#:
#: Imports are local to the method on purpose: the generated file's own import
#: block belongs to ``pycodegen`` and knows nothing about a method body.
#: ``time``/``datetime``/``dateutil`` are the real modules rather than
#: ``safe_eval``'s wrapped ones -- the wrappers exist to keep sandboxed code
#: away from module internals, which no longer applies to code in a file.
_EVAL_CONTEXT_BINDINGS: dict[str, tuple[str, ...]] = {
    "env": ("env = self.env",),
    "model": ("model = self.browse()",),
    "records": ("records = self",),
    "record": ("record = self[:1]",),
    "uid": ("uid = self.env.uid",),
    "user": ("user = self.env.user",),
    "time": ("import time",),
    "datetime": ("import datetime",),
    "dateutil": (
        "import dateutil",
        "import dateutil.parser",
        "import dateutil.relativedelta",
        "import dateutil.rrule",
        "import dateutil.tz",
    ),
    "timezone": ("from pytz import timezone",),
    "float_compare": ("from odoo.tools import float_compare",),
    "b64encode": ("from base64 import b64encode",),
    "b64decode": ("from base64 import b64decode",),
    "Command": ("from odoo import Command",),
    "UserError": ("from odoo.exceptions import UserError",),
    "_logger": (
        "import logging",
        "_logger = logging.getLogger(__name__)",
    ),
    # The action's own `log()` inserts an `ir.logging` row keyed on the action
    # id, which a method does not have. The server log is where a developer
    # reading this file would look anyway.
    "log": (
        "import logging",
        "def log(message, level='info'):",
        "    logging.getLogger(__name__).log(",
        "        getattr(logging, str(level).upper(), logging.INFO), message",
        "    )",
    ),
}

#: Names that exist only while a webhook request is being served
#: (`base_automation`'s own `_get_eval_context`). There is nothing a method
#: called with no arguments could bind them to.
_UNPORTABLE_NAMES = ("payload",)

#: Where the preamble ends and the automation's own code starts.
_BODY_MARKER = "# -- the automation's code, as it was written --"


def _names_in(tree: ast.AST) -> set[str]:
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _assigns_action(tree: ast.Module) -> bool:
    """Does the code set ``action``, the one name a server action reads back?

    ``_run_action_code_multi`` returns ``eval_context.get("action")``: that is
    how an automation's code opens a window or shows a notification.
    """
    return any(
        isinstance(node, ast.Name)
        and node.id == "action"
        and isinstance(node.ctx, ast.Store)
        for node in ast.walk(tree)
    )


def method_body_for(code: str) -> tuple[str, bool]:
    """``code`` as a method body, and whether it hands back an ``action``.

    The body is the code unchanged, under the bindings it needs and -- when it
    assigns ``action`` -- over a ``return action``. Raises ``SyntaxError`` for
    code that does not parse and ``ValueError`` for code no method can run.
    """
    code = code.strip("\n")
    tree = ast.parse(code)
    used = _names_in(tree)
    for name in _UNPORTABLE_NAMES:
        if name in used:
            raise ValueError(name)
    returns_action = _assigns_action(tree)
    preamble: list[str] = []
    for name, statements in _EVAL_CONTEXT_BINDINGS.items():
        if name not in used:
            continue
        preamble.extend(line for line in statements if line not in preamble)
    if returns_action:
        # Bound up front so the `return` below is safe when the assignment
        # sits in a branch that did not run -- `eval_context.get("action")`
        # answered None for that too.
        preamble.append("action = None")
    lines = [*preamble, _BODY_MARKER, code] if preamble else [code]
    if returns_action:
        lines.append("return action")
    return "\n".join(lines), returns_action


class BuilderGraduateCode(models.AbstractModel):
    _name = "builder.graduate.code"
    _inherit = ["builder.security.mixin"]
    _description = "Builder: Promote Automation Code to Source"

    # `@api.private`: takes a recordset, so it was never callable over RPC
    # except by accident of failing on an id. Said outright rather than left
    # to that -- `builder.security.mixin`'s own rule is that every method
    # reachable over RPC opens with a guard, and this one has no business
    # being reachable.
    @api.private
    @api.model
    def can_graduate(self, action: IrActionsServer) -> str:
        """Why this action's code cannot become a method, or nothing."""
        typed.security(self)._assert_builder_user()
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
        try:
            method_body_for(cast("str", action.code))
        except SyntaxError as err:
            return _("This code does not parse, so it cannot be moved: %s", err.msg)
        except ValueError as err:
            return _(
                "This code reads '%s', which only exists while a webhook "
                "request is being served. A method has no such thing to read.",
                str(err),
            )
        return ""

    @api.model
    def _already_promoted(self, action: IrActionsServer) -> bool:
        """A one-line body that is just a call is one we wrote."""
        body = (action.code or "").strip().removeprefix("action = ")
        # The second form is what this wrote before it fell back to `model`;
        # an action promoted then is promoted still.
        return body.startswith(
            tuple(
                "(%s).%s" % (target, modelspec.BUILDER_METHOD_PREFIX)
                for target in ("records or record or model", "records or record")
            )
        )

    @api.model
    def graduate(self, action_id: int, apply: bool = True) -> GraduateJSON:
        """Move the body into a method and leave the action calling it.

        ``apply`` writes the source *and* reloads the module, which is what
        makes the method callable -- Python is the one thing in this project
        that does not go live on write.

        The body is not moved bare. Server-action code is written against the
        names ``safe_eval`` gives it (``record``, ``records``, ``env``,
        ``model``, ``log``, ``UserError``...), none of which exist in a method,
        so the method opens by binding the ones the code uses
        (``method_body_for``) and ends by returning ``action`` when the code
        sets it.

        It is separable because
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

        # `code` is declared `str | False` (`odoo/fields.py`'s own `Text` read
        # type); `can_graduate` above already required it non-empty and
        # portable -- same "declared too abstract for what is really there"
        # cast as every other required-by-validation read in this migration.
        body, returns_action = method_body_for(cast("str", action.code))
        method = modelspec.MethodSpec(
            name=self._unique_method_name(spec, cast("str", action.name)),
            body=body,
            doc=_("Promoted from the automation %s.", action.name),
        )
        from dataclasses import replace as _replace

        package._seed_source_for(
            model_name, _replace(spec, methods=spec.methods + (method,))
        )
        # The call, not the body. `records` is the whole set in multi-mode and
        # `record` the single one; taking whichever is there means the method
        # sees a recordset either way and can be written as an ordinary one.
        # `model` last: an action run with no record at all (a cron, a button
        # on nothing) has both of the others as None, and its code still ran.
        call = "(records or record or model).%s()" % method.name
        action.code = "action = %s" % call if returns_action else call
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

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Every public method of every builder model refuses a plain user.

``builder_security.py`` states the rule -- one guard, called first in every
builder method reachable over RPC -- and until now nothing held anybody to
it. A method added without its guard was found by review or not at all, and
on an ``AbstractModel`` there is no ACL behind it to fall back on.

So this enumerates rather than lists. It walks the registry for every
``builder.*`` model that any installed ``app_builder*`` addon defines or
extends, takes every method ``/web/dataset/call_kw`` would agree to
dispatch (``odoo.service.model.get_public_method``: no leading underscore,
no ``@api.private``), and calls each one as an internal user who is in
neither builder group, with placeholders for its arguments. The only
acceptable outcome is ``AccessError``. A ``TypeError`` from a placeholder is
a failure too: it means the method touched its arguments before it asked
who was calling.

It runs ``post_install`` so that the registry holds every addon of the
run, not just this one: installed alone it covers ``app_builder_base``,
installed with the suite it covers the suite.
"""

from __future__ import annotations

import inspect
from typing import Any

from odoo.exceptions import AccessError
from odoo.models import BaseModel
from odoo.tests import tagged

from .common import BuilderCase

#: Where a class has to come from for its methods to be ours to guard.
ADDON_PREFIX = "odoo.addons.app_builder"

#: ``(model, method)`` pairs that may answer a plain user, each with the
#: reason. Keep it short: an entry here is a method anybody who can log in
#: can call, portal users included. An entry whose model is installed but
#: whose method is gone fails the test, so the list cannot rot.
ALLOWED: dict[tuple[str, str], str] = {
    ("builder.captured.on.create", "create"): (
        "An ORM override on a mixin. `create` on the mixin's own abstract "
        "model makes nothing; on the models that inherit it the ORM's access "
        "check is `super().create()`, the first thing it calls, and the one "
        "thing it adds -- capturing into a package named in context -- goes "
        "through `builder.package.builder_capture`, which asserts the "
        "manager guard (TestSudoIsNotAWayIn covers exactly that path)."
    ),
    ("builder.package", "action_open_form"): (
        "Returns a constant `ir.actions.act_window` dict naming its own id "
        "and model: it reads no field and touches no file, and the form it "
        "names is behind the model's ACL."
    ),
}

#: What stands in for an argument. Never a recordset and never a real id:
#: a method that gets as far as using it has already failed this test.
PLACEHOLDER = 0


def _is_rpc_public(cls: type, name: str) -> bool:
    """``get_public_method``'s own rule, for one name on one class."""
    if name.startswith("_"):
        return False
    for klass in cls.mro():
        method = getattr(klass, name, None)
        if method is not None and getattr(method, "_api_private", False):
            return False
    return True


def _own_public_methods(cls: type) -> list[str]:
    """The RPC-callable methods this project put on ``cls``.

    Found on the classes of the MRO that come from an ``app_builder*``
    addon, so an ORM method counts exactly when one of them overrides it --
    which is when it runs this project's code before (or instead of) the
    ORM's own access check.
    """
    names: set[str] = set()
    for klass in cls.mro():
        if not klass.__module__.startswith(ADDON_PREFIX):
            continue
        for name, value in vars(klass).items():
            if isinstance(value, classmethod | staticmethod):
                value = value.__func__
            if inspect.isfunction(value) and _is_rpc_public(cls, name):
                names.add(name)
    return sorted(names)


def _placeholders(method: Any) -> list[Any]:
    """One placeholder per argument the bound method cannot do without."""
    out: list[Any] = []
    for parameter in inspect.signature(method).parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue
        if parameter.default is not inspect.Parameter.empty:
            continue
        out.append(PLACEHOLDER)
    return out


@tagged("post_install", "-at_install")
class TestGuardCoverage(BuilderCase):
    def _builder_models(self) -> list[str]:
        return sorted(
            name
            for name in self.registry
            if name == "builder" or name.startswith("builder.")
        )

    def test_the_enumeration_finds_the_builder(self):
        """The test below passes vacuously over an empty list; this one
        says the list is not empty and holds what it obviously should."""
        models = self._builder_models()
        self.assertIn("builder.workspace", models)
        self.assertIn("builder.package", models)
        workspace = _own_public_methods(type(self.env["builder.workspace"]))
        for name in ("packages", "create_package", "apply", "drift_diff"):
            self.assertIn(name, workspace)
        self.assertNotIn("_package", workspace)
        package = _own_public_methods(type(self.env["builder.package"]))
        self.assertIn("action_apply", package)

    def test_every_public_builder_method_refuses_a_plain_user(self):
        nobody = self.make_user("guard_nobody", ["base.group_user"])
        self.assertFalse(nobody.has_group("app_builder_base.group_builder_user"))
        problems: list[str] = []
        checked = 0
        used: set[tuple[str, str]] = set()
        for model_name in self._builder_models():
            model = self.env[model_name].with_user(nobody)
            for name in _own_public_methods(type(model)):
                key = (model_name, name)
                if key in ALLOWED:
                    used.add(key)
                    continue
                method = getattr(model, name)
                checked += 1
                try:
                    # A savepoint, so that a method that did get somewhere
                    # leaves nothing behind for the next one to trip on.
                    with self.cr.savepoint():
                        method(*_placeholders(method))
                except AccessError:
                    continue
                except Exception as err:  # noqa: BLE001 - reported below
                    problems.append(
                        "%s.%s raised %s before any access check: %s"
                        % (model_name, name, type(err).__name__, err)
                    )
                else:
                    problems.append(
                        "%s.%s answered a user who is in no builder group"
                        % (model_name, name)
                    )
        self.assertGreater(checked, 20, "the enumeration found almost nothing")
        self.assertFalse(
            problems,
            "public builder methods that do not call their guard first "
            "(builder_security.py); guard them, make them private, or add "
            "them to ALLOWED with a reason:\n  " + "\n  ".join(problems),
        )
        stale = sorted(
            "%s.%s" % key
            for key in ALLOWED
            if key not in used
            and key[0] in self.registry
            and not hasattr(type(self.env[key[0]]), key[1])
        )
        self.assertFalse(stale, "ALLOWED names methods that no longer exist")

    def test_every_stored_builder_model_is_closed_to_a_plain_user(self):
        """The ORM's own methods (``read``, ``write``, ``search``...) are not
        this project's to guard, and are not enumerated above unless one is
        overridden. What protects them is an ACL row, so every builder model
        that has a table must have none that lets a plain user in."""
        nobody = self.make_user("guard_nobody_acl", ["base.group_user"])
        open_models: list[str] = []
        for model_name in self._builder_models():
            model = self.env[model_name].with_user(nobody)
            if model._abstract:
                continue
            for operation in ("read", "write", "create", "unlink"):
                if model.has_access(operation):
                    open_models.append("%s (%s)" % (model_name, operation))
        self.assertFalse(
            open_models,
            "builder models a plain internal user has ACL access to:\n  "
            + "\n  ".join(open_models),
        )

    def test_orm_methods_stay_out_of_the_enumeration(self):
        """A sanity check on the walk itself: what ``BaseModel`` defines is
        only counted when an addon class overrides it."""
        workspace = type(self.env["builder.workspace"])
        self.assertNotIn("search", _own_public_methods(workspace))
        self.assertTrue(hasattr(BaseModel, "search"))

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Shared fixtures for the builder test suite."""

from __future__ import annotations

import ast
import contextlib
import io
import os
import tempfile
from typing import TYPE_CHECKING, Any, TypeVar, cast

from odoo import Command
from odoo.tests import HttpCase, TransactionCase
from odoo.tools.convert import convert_csv_import, convert_xml_import
from odoo.tools.translate import TranslationImporter

# The one the package itself uses. A second copy here had already drifted:
# it predated base.automation and ir.cron, and a wipe that deletes a server
# action while a cron still references it fails on the foreign key.
from odoo.addons.app_builder_base.models.builder_package import (
    UNLINK_ORDER,
    BuilderPackage,
)
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_base.tools.compat import groups_field
from odoo.addons.base.models.ir_actions import IrActionsActWindow
from odoo.addons.base.models.ir_model import (
    IrModel,
    IrModelAccess,
    IrModelData,
    IrModelFields,
    IrModelSelection,
)
from odoo.addons.base.models.ir_module import Module
from odoo.addons.base.models.ir_ui_menu import IrUiMenu
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.base.models.res_users import Users

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every Phase 1c file's own `TYPE_CHECKING` block makes. Phase 1d
    # ("tests stay `basic`, annotate only where it helps the checker read
    # `self.env` results") is why this file, unlike a Phase 1c model file,
    # only imports what its own fixture methods' return types need -- not
    # every model this suite ever touches.
    import unittest
    from contextlib import AbstractContextManager
    from unittest.case import _AssertRaisesContext


_E = TypeVar("_E", bound=BaseException)


def raises(case: unittest.TestCase, exception: type[_E]) -> _AssertRaisesContext[_E]:
    """``case.assertRaises(exception)``, typed through the ancestor
    ``unittest.TestCase`` rather than Odoo's own override (``odoo/tests
    /common.py``'s own ``BaseCase.assertRaises``).

    Odoo's own is one unannotated function branching on an optional
    ``func``: given one, it calls it and returns ``None``; without one
    (every real call in this suite -- always the context-manager form,
    ``with self.assertRaises(X) as caught:``), it returns the context
    manager. pyright infers the *union* of both branches for every call
    regardless of which branch a given call site actually takes, so a
    bare ``with self.assertRaises(X):`` reports "Object of type None
    cannot be used with with" tree-wide (``reportOptionalContextManager``)
    -- the exact class of gap ``typed.py``'s own ``ref()`` documents for
    ``Environment.ref``, just on the test framework's own base class
    instead of the ORM's.

    ``unittest.TestCase.assertRaises`` -- the real base ``BaseCase``
    itself inherits from -- is correctly overloaded for exactly this
    shape in typeshed: called with only an exception (no callable), it
    returns ``_AssertRaisesContext[_E]``, never ``None``. Typing this
    function's own ``case`` parameter as the ANCESTOR rather than
    ``BuilderCase``/``TransactionCase`` changes nothing about which method
    actually runs at runtime (Python always dispatches through ``case``'s
    real class, i.e. Odoo's own override, identical behavior for this
    call shape) -- only which stub pyright reads to type the result.
    """
    return case.assertRaises(exception)


def unchecked() -> AbstractContextManager[None]:
    """Run the enclosed code outside typeguard's checks (TYPING.md, Phase 1e).

    For a test that drives an annotated function *outside* its annotation on
    purpose -- ``groups_json("form")`` with its default resolver leaves labels
    lazy, and a test asserts exactly that, while ``OptionGroupJSON`` says
    ``str``. Named at the call site rather than excused globally, so every
    other use of the ``tools/`` modules stays strictly checked. A no-op when
    typeguard is not running, which is nearly always.
    """
    if os.environ.get("APP_BUILDER_TYPEGUARD"):
        # Optional test dependency: absent from a plain dev env.
        import typeguard  # pyright: ignore[reportMissingImports]

        return typeguard.suppress_type_checks()
    return contextlib.nullcontext()


def join_groups(users: Users, group_xmlids: list[str]) -> None:
    """Put ``users`` in the groups named by ``group_xmlids``, keeping the
    ones they already have."""
    env = users.env
    users.write(
        {
            groups_field(env): [
                Command.link(cast("int", typed.ref(env, xmlid).id))
                for xmlid in group_xmlids
            ]
        }
    )


# Reverse dependency order for teardown: dependants before their dependencies,
# so no unlink ever hits a restrict/cascade surprise.
class _NamedBytesIO(io.BytesIO):
    """BytesIO with a .name, which convert_xml_import reads for error reports."""

    def __init__(self, content: bytes, name: str) -> None:
        super().__init__(content)
        self.name = name


def prime_memoized_class_attributes() -> None:
    """Give every model class the three attributes ``setup_models``
    memoizes, before the leak detector takes its snapshot.

    ``TransactionCase.check_attrs`` compares the class attributes after
    each test with a snapshot taken in ``setUpClass``. A test that creates
    a manual model runs ``registry.setup_models``, whose
    ``_init_constraints_onchanges`` puts ``_onchange_methods`` (and its
    two siblings) on *every* class -- and after a preceding HttpCase some
    classes have been seen without them, so the snapshot lacks what the
    test then adds and every test of the class fails for nothing. Setting
    the same property objects here, the way ``setup_models`` does, makes
    the snapshot complete. Called before ``super().setUpClass()`` by every
    base class of this project's tests.
    """
    from odoo.models import BaseModel
    from odoo.modules.registry import Registry
    from odoo.tests.common import get_db_name

    for model in Registry(get_db_name()).values():
        for name in ("_constraint_methods", "_ondelete_methods", "_onchange_methods"):
            if name not in vars(model):
                setattr(model, name, getattr(BaseModel, name))


class BuilderHttpCase(HttpCase):
    """``HttpCase`` for the console's tours, with the snapshot primed."""

    @classmethod
    def setUpClass(cls) -> None:
        prime_memoized_class_attributes()
        super().setUpClass()


class BuilderCase(TransactionCase):
    """Base case for tests that create manual models.

    Test mode is required because ``registry.reset_changes()`` opens its own
    cursor to re-read custom models; without it that cursor would see the
    database as it was before the test started. Copied from Odoo's own
    ``TestIrModel``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        prime_memoized_class_attributes()
        super().setUpClass()
        cls.registry.enter_test_mode(cls.cr)
        cls.addClassCleanup(cls.registry.leave_test_mode)

    def setUp(self) -> None:
        # Must be registered before anything else so it runs last.
        self.addCleanup(self.registry.reset_changes)
        super().setUp()

    # -- fixtures ---------------------------------------------------------

    def make_package(
        self, name: str = "x_builder_demo", installed: bool = True, **overrides: object
    ) -> BuilderPackage:
        tmp = tempfile.mkdtemp(prefix="builder-test-")
        values: dict[str, object] = {
            "name": name,
            "display_name_": "Builder Demo",
            "root_path": tmp,
            "auto_commit": "off",
        }
        values.update(overrides)
        package = typed.model(self.env, BuilderPackage).create(values)  # pyright: ignore[reportArgumentType]
        if installed:
            self.register_module(cast("str", package.name))
        return package

    def make_user(
        self, login: str, group_xmlids: list[str], **overrides: object
    ) -> Users:
        """A user in exactly ``group_xmlids``, whichever field holds them
        (``groups_field``)."""
        User = typed.model(self.env, Users)
        values: dict[str, object] = {
            "name": login,
            "login": login,
            groups_field(self.env): [
                Command.set(
                    [
                        cast("int", typed.ref(self.env, xmlid).id)
                        for xmlid in group_xmlids
                    ]
                )
            ],
        }
        values.update(overrides)
        return User.create(values)  # pyright: ignore[reportArgumentType]

    def unwritable_path(self) -> str:
        """A path nothing can write to, whatever user the suite runs as.

        Deliberately not `chmod 0500`. This suite runs as root in CI, and root
        writes straight through mode bits -- which is how the read-only guard
        came to be covered by an assertion that only held for unprivileged
        developers, and stayed red in CI for days. A parent that is a regular
        file is refused for everybody, root included.
        """
        blocker = os.path.join(tempfile.mkdtemp(prefix="builder-test-ro-"), "blocker")
        with open(blocker, "w"):
            pass
        return os.path.join(blocker, "package")

    def register_module(self, name: str) -> Module:
        """Register the package as an installed module.

        Graduation refuses to run otherwise, and rightly so: Odoo only imports
        Python for installed modules, so demoting the metadata without one would
        leave the model with no definition at all. Tests have to satisfy the
        same precondition the UI does.
        """
        Module_ = typed.model(self.env, Module)
        existing = Module_.search([("name", "=", name)], limit=1)
        if existing:
            existing.state = "installed"
            return existing
        return Module_.create({"name": name, "state": "installed"})  # pyright: ignore[reportArgumentType]

    def build_demo_content(self, package: BuilderPackage) -> IrModel:
        """Create a representative slice of everything the builder can emit."""
        # `@api.model_create_multi`'s own stub gap (TYPING.md's "Known
        # traps"): every single-dict `.create(vals)` below needs the
        # `# pyright: ignore[reportArgumentType]` that idiom already
        # established -- assigned to a `vals` local first in each case, so
        # the ignore comment lands on the actual `create(vals)` call's own
        # line rather than somewhere inside a multi-line dict literal
        # pyright would not attribute the diagnostic to.
        model_vals: dict[str, object] = {
            "name": "Builder Demo Project",
            "model": "x_builder_project",
            "field_id": [
                Command.create(
                    {
                        "name": "x_name",
                        "ttype": "char",
                        "field_description": "Name",
                        "required": True,
                    }
                ),
                Command.create(
                    {
                        "name": "x_budget",
                        "ttype": "float",
                        "field_description": "Budget",
                    }
                ),
                Command.create(
                    {
                        "name": "x_active_flag",
                        "ttype": "boolean",
                        "field_description": "Is Active",
                    }
                ),
                Command.create(
                    {
                        "name": "x_partner_id",
                        "ttype": "many2one",
                        "field_description": "Customer",
                        "relation": "res.partner",
                        "on_delete": "set null",
                    }
                ),
                Command.create(
                    {
                        "name": "x_stage",
                        "ttype": "selection",
                        "field_description": "Stage",
                    }
                ),
            ],
        }
        model = typed.model(self.env, IrModel).create(model_vals)  # pyright: ignore[reportArgumentType]
        # A stored computed field: proof that "compute" is data, not code.
        field_vals: dict[str, object] = {
            "name": "x_budget_doubled",
            "field_description": "Budget Doubled",
            "ttype": "float",
            "model_id": model.id,
            "store": True,
            "depends": "x_budget",
            "compute": "for r in self:\n    r['x_budget_doubled'] = r.x_budget * 2",
        }
        typed.model(self.env, IrModelFields).create(field_vals)  # pyright: ignore[reportArgumentType]
        fields = cast("IrModelFields", model.field_id)
        stage_field = fields.filtered(lambda f: f.name == "x_stage")
        typed.model(self.env, IrModelSelection).create(
            [
                {
                    "field_id": stage_field.id,
                    "value": "draft",
                    "name": "Draft",
                    "sequence": 10,
                },
                {
                    "field_id": stage_field.id,
                    "value": "done",
                    "name": "Done",
                    "sequence": 20,
                },
            ]
        )
        view_vals: dict[str, object] = {
            "name": "x_builder_project.form",
            "model": "x_builder_project",
            "arch": """
                    <form>
                        <sheet>
                            <group>
                                <field name="x_name"/>
                                <field name="x_budget"/>
                                <field name="x_partner_id"/>
                                <field name="x_stage"/>
                            </group>
                        </sheet>
                    </form>
                """,
        }
        view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]
        action_vals: dict[str, object] = {
            "name": "Builder Demo Projects",
            "res_model": "x_builder_project",
            "view_mode": "list,form",
        }
        action = typed.model(self.env, IrActionsActWindow).create(action_vals)  # pyright: ignore[reportArgumentType]
        menu_vals: dict[str, object] = {
            "name": "Builder Demo Projects",
            "action": "ir.actions.act_window,%d" % action.id,
        }
        menu = typed.model(self.env, IrUiMenu).create(menu_vals)  # pyright: ignore[reportArgumentType]
        access_vals: dict[str, object] = {
            "name": "x_builder_project all",
            "model_id": model.id,
            "group_id": cast("int", typed.ref(self.env, "base.group_user").id),
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": False,
        }
        access = typed.model(self.env, IrModelAccess).create(access_vals)  # pyright: ignore[reportArgumentType]

        package._assign(model)
        package._assign(fields)
        package._assign(cast("IrModelSelection", stage_field.selection_ids))
        package._assign(view)
        package._assign(action)
        package._assign(menu)
        package._assign(access)
        return model

    # -- round-trip helpers ----------------------------------------------

    def wipe_package_records(self, package: BuilderPackage) -> None:
        """Remove every record the package owns, plus its xmlids."""
        data = typed.model(self.env, IrModelData).search(
            [("module", "=", package.name)]
        )
        by_model: dict[str, list[int]] = {}
        for entry in data:
            by_model.setdefault(cast("str", entry.model), []).append(
                cast("int", entry.res_id)
            )
        # Same flag Odoo's own _module_data_uninstall uses; without it
        # _prepare_update refuses to drop columns that carry module data.
        env = self.env(context=dict(self.env.context, _force_unlink=True))
        for model in UNLINK_ORDER:
            res_ids = by_model.pop(model, [])
            if res_ids and model in env:
                env[model].browse(res_ids).exists().unlink()
        for model, res_ids in by_model.items():
            if model in env:
                env[model].browse(res_ids).exists().unlink()
        data.exists().unlink()
        self.env.flush_all()

    def load_translations(
        self, package: BuilderPackage, files: dict[str, str]
    ) -> list[str]:
        """Load the generated PO files the way a module install would.

        `load_rendered` walks the manifest's `data`, and PO files are not in it
        -- Odoo discovers `i18n/*.po` by directory rather than by declaration
        (`ir_module.py:983`). So the round trip has to load them separately or
        it silently proves nothing about translations.
        """
        # `load` rather than `load_file`: the latter goes through `file_open`,
        # which refuses any path outside the addons root -- and swallows the
        # refusal with `suppress(FileNotFoundError)`, so a temp file loads
        # nothing and reports success.
        importer = TranslationImporter(self.env.cr, verbose=False)
        loaded: list[str] = []
        for relative, content in files.items():
            if not relative.startswith("i18n/") or not relative.endswith(".po"):
                continue
            lang = relative[len("i18n/") : -len(".po")]
            buffer = io.BytesIO(content.encode("utf-8"))
            # PoFileReader reads `.name` to look for a sibling .pot
            # (translate.py:816) and a bare BytesIO has none.
            buffer.name = relative
            importer.load(buffer, "po", lang)
            loaded.append(lang)
        if loaded:
            importer.save(overwrite=True)
            self.env.flush_all()
        return loaded

    def load_rendered(self, package: BuilderPackage, files: dict[str, str]) -> None:
        """Feed rendered content back through Odoo's own XML/CSV importer.

        Going through ``convert_xml_import`` rather than a bespoke loader is the
        point: it proves the output is consumable by the real install path, not
        merely by our own parser.
        """
        idref: dict[str, Any] = {}
        manifest = ast.literal_eval(files["__manifest__.py"])
        for relative in manifest["data"]:
            content = files[relative].encode("utf-8")
            if relative.endswith(".csv"):
                convert_csv_import(
                    self.env, package.name, relative, content, idref, "init", False
                )
            else:
                convert_xml_import(
                    self.env,
                    package.name,
                    _NamedBytesIO(content, "%s/%s" % (package.name, relative)),
                    idref,
                    "init",
                    False,
                )
        self.env.flush_all()

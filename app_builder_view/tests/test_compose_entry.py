# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Where "Compose" goes: the console, on a view the model has."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises

if TYPE_CHECKING:
    # `model_ids`' comodel is a plain string (`builder.package.model`), so
    # `self.package.model_ids` reads as an untyped union pyright cannot call
    # `.filtered()`/`.action_compose()` on -- same cast-at-the-read-site
    # idiom every Phase 1c model file uses. This addon's own `_inherit`
    # extension is the one whose `action_compose()` this suite actually
    # calls (a real `ComposeActionJSON`, not the base's `NoReturn`).
    from ..models.builder_package_model import (
        BuilderPackageModel,
    )


@tagged("post_install", "-at_install")
class TestComposeEntry(BuilderCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_compose_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_builder_project"])
        self.package_model = cast(
            "BuilderPackageModel", self.package.model_ids
        ).filtered(lambda m: m.model == "x_builder_project")

    def _views(self, view_type):
        return self.env["ir.ui.view"].search(
            [("model", "=", "x_builder_project"), ("type", "=", view_type)]
        )

    def test_compose_opens_the_console_on_the_models_form(self):
        """A Python model with a form is composed by dropping fields onto
        that form, so Compose lands in the console, full-screen, on the
        Views pane of its package; the console keeps that in its own URL."""
        action = self.package_model.action_compose()
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["target"], "fullscreen")
        self.assertEqual(action["params"]["pane"], "views")
        self.assertEqual(action["params"]["res_model"], "x_builder_project")
        self.assertEqual(action["params"]["view_type"], "form")
        self.assertEqual(action["params"]["package_id"], self.package.id)
        self.assertNotIn("context", action)

    def test_without_a_form_the_console_opens_on_what_the_model_has(self):
        """The class is edited from the View tab whatever the canvas shows,
        so a list will do; only a model with no view at all is refused, with
        a sentence rather than an error about a missing arch."""
        vals = {
            "name": "x_builder_project.list.compose",
            "model": "x_builder_project",
            "type": "list",
            "arch": "<list><field name='x_name'/></list>",
        }
        self.env["ir.ui.view"].create(vals)  # pyright: ignore[reportArgumentType]
        self._views("form").unlink()
        action = self.package_model.action_compose()
        self.assertEqual(action["tag"], "app_builder_console")
        self.assertEqual(action["params"]["view_type"], "list")
        for view_type in ("list", "kanban", "search"):
            self._views(view_type).unlink()
        # `common.py`'s own `raises()` only covers the 2-arg form; this
        # call's `msg=` has no typed equivalent there, so the diagnostic is
        # suppressed locally rather than dropping the failure message.
        with self.assertRaises(  # pyright: ignore[reportOptionalContextManager]
            UserError, msg="no view to open on"
        ):
            self.package_model.action_compose()

    def test_the_engine_alone_says_what_it_is_missing(self):
        """Without the override the engine has no builder to open, and it
        says which addon carries one rather than failing on an unknown tag."""
        Model = self.env.registry["builder.package.model"]
        for cls in Model.__mro__:
            if cls.__module__.endswith("app_builder_base.models.builder_package_model"):
                with raises(self, UserError):
                    cls.action_compose(self.package_model)
                break
        else:
            self.fail("the engine's action_compose was not found on the MRO")

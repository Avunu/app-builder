# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Surfacing the models that still need adopting.

The interesting case is not the package-built model -- that one was always
listed. It is the model somebody made by hand in Settings -> Technical, which
belongs to no package at all: nothing in the product mentioned it, and
``action_adopt`` refuses a model its package does not own, so there was no
path to adopting it whatsoever. The console's Adopt flow goes through
``builder.app.adoptable_models`` and ``adopt``, pinned here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModel

from ..models.builder_app import BuilderApp

if TYPE_CHECKING:
    # Only for the cast() below; with `from __future__ import annotations`
    # nothing here needs this at runtime.
    from odoo.addons.app_builder_base.models.builder_package_model import (
        BuilderPackageModel,
    )


@tagged("post_install", "-at_install")
class TestAdoptFlow(BuilderCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_adopt_pkg")
        self.builder = typed.model(self.env, BuilderApp)

    def _manual_model(self, model_name, label="Loose"):
        vals: dict[str, object] = {
            "name": label,
            "model": model_name,
            "field_id": [
                Command.create(
                    {
                        "name": "x_name",
                        "ttype": "char",
                        "field_description": "Name",
                    }
                )
            ],
        }
        return typed.model(self.env, IrModel).create(vals)  # pyright: ignore[reportArgumentType]

    def _offered(self):
        return {m["model"]: m for m in self.builder.adoptable_models()}

    # -- what shows up ----------------------------------------------------

    def test_a_model_belonging_to_no_package_is_still_offered(self):
        self._manual_model("x_loose_model")
        offered = self._offered()
        self.assertIn(
            "x_loose_model",
            offered,
            "a hand-made model had no way to be adopted at all",
        )
        self.assertEqual(offered["x_loose_model"]["origin"], "manual")
        self.assertIsNone(offered["x_loose_model"]["owner_package"])

    def test_a_model_already_owned_in_python_is_not_offered(self):
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_builder_project"])
        self.assertNotIn(
            "x_builder_project",
            self._offered(),
            "adopting twice would regenerate a class over the developer's file",
        )

    def test_the_preview_shows_the_class_that_would_be_written(self):
        self._manual_model("x_preview_model")
        preview = self._offered()["x_preview_model"]["preview"]
        self.assertIn("class", preview)
        self.assertIn("x_preview_model", preview)
        self.assertIn("x_name", preview)

    # -- adopting ---------------------------------------------------------

    def test_adopting_captures_a_loose_model_into_the_chosen_package(self):
        self._manual_model("x_capture_me")
        self.builder.adopt(cast("int", self.package.id), ["x_capture_me"], apply=False)
        self.assertIn("x_capture_me", self.package._owned_model_names())
        entry = cast("BuilderPackageModel", self.package.model_ids).filtered(
            lambda m: m.model == "x_capture_me"
        )
        self.assertEqual(entry.source, "python")

    def test_adopting_a_loose_model_writes_its_class(self):
        self._manual_model("x_written_model")
        self.builder.adopt(
            cast("int", self.package.id), ["x_written_model"], apply=False
        )
        entry = cast("BuilderPackageModel", self.package.model_ids).filtered(
            lambda m: m.model == "x_written_model"
        )
        source = self.package._read_source(cast("str", entry.python_path))
        self.assertIsNotNone(source, "adoption must leave a file behind")
        # `assertIsNotNone` is a runtime check only; it does not narrow
        # `source` for pyright the way an `if`/`assert` would.
        assert source is not None
        self.assertIn("x_name", source)

    def test_nothing_selected_is_refused(self):
        with raises(self, UserError):
            self.builder.adopt(cast("int", self.package.id), [], apply=False)

    def test_a_plain_user_cannot_adopt(self):
        """Adoption writes Python into an addons path, so it is exactly the
        kind of thing an ordinary user must not be able to reach by RPC."""
        self._manual_model("x_guarded_model")
        outsider = self.make_user("adopt_outsider", ["base.group_user"])
        with raises(self, AccessError):
            self.builder.with_user(outsider).adopt(
                cast("int", self.package.id), ["x_guarded_model"], apply=False
            )

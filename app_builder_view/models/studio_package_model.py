# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Compose opens the console.

A model the package defines in Python is edited by dropping fields onto the
view where they will actually be seen, and its class -- every field, in the
order it is written -- sits in the console's View tab. That is the one
builder: the field-list-beside-a-preview it replaced is gone, and with it
the second UI that had to keep up with the first.

The console needs a view to stand on: the form when there is one, else
whatever the model has. A model with no views at all is a scaffold that
has not happened yet, and the sentence says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    # This file is a pure `_inherit = "studio.package.model"` extension --
    # `source`/`model`/`package_id` are declared on the real class in
    # `app_builder_base/models/studio_package_model.py`, never on this one,
    # so `self.source` etc. below are invisible to pyright on a bare `self`.
    # Same self-cast as every other pure-`_inherit` file this migration has
    # converted.
    from odoo.addons.app_builder_base.models.studio_package import StudioPackage
    from odoo.addons.app_builder_base.models.studio_package_model import (
        StudioPackageModel as StudioPackageModelBase,
    )

# In the order the console prefers to open on: a form is where a field is
# dropped; a list or a kanban still shows the model and carries its draft.
CANVAS_TYPES = ("form", "list", "kanban")


class ComposeActionParamsJSON(TypedDict):
    """``action_compose()``'s ``params``: which pane and model the console
    opens on."""

    pane: str
    package_id: int
    res_model: str
    view_type: str
    opened_from: str


class ComposeActionJSON(TypedDict):
    """``action_compose()``'s return: opens the studio console on this
    model."""

    type: str
    tag: str
    name: str
    target: str
    params: ComposeActionParamsJSON


class StudioPackageModel(models.Model):
    _inherit = "studio.package.model"

    def action_compose(self) -> ComposeActionJSON:
        self.ensure_one()
        record = cast("StudioPackageModelBase", self)
        if record.source != "python":
            # The base's own `action_compose` is declared `-> NoReturn` (it
            # always raises); this override's own return type is this
            # branch's real shape, and no override-compatibility check fires
            # for `_inherit`-only composition (TYPING.md, confirmed
            # elsewhere in this migration).
            return cast("StudioPackageModelBase", super()).action_compose()
        # `model` is a required Char -- same "declared str | False, never
        # actually False" cast as the base file's own `record.model` reads.
        model_name = cast("str", record.model)
        model_view = typed.model(self.env, View)
        view_type = next(
            (t for t in CANVAS_TYPES if model_view.default_view(model_name, t)),
            None,
        )
        if not view_type:
            raise UserError(
                _(
                    "%s has no view to open the console on yet. Add one from "
                    "the app builder, or write one, and come back.",
                    model_name,
                )
            )
        # `package_id` is the circular relational field (TYPING.md's own
        # dependency map) -- cast at this real read site, same as the base
        # file's own `_current_spec`/`unlink`.
        package = cast("StudioPackage", record.package_id)
        return {
            "type": "ir.actions.client",
            "tag": "app_builder_console",
            "name": model_name,
            "target": "fullscreen",
            # The console keeps what it needs to come back after a reload
            # -- Apply rebuilds the registry -- in its own URL.
            "params": {
                "pane": "views",
                "package_id": cast("int", package.id),
                "res_model": model_name,
                "view_type": view_type,
                "opened_from": "model",
            },
        }

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

if TYPE_CHECKING:
    # Only used inside annotations/casts below (`from __future__ import
    # annotations` defers all of them to strings), never at runtime -- same
    # bargain every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.models import BaseModel

    # `app_builder_base/models/builder_workspace.py`'s own module also
    # declares a class named `BuilderWorkspace` (the SAME "builder.workspace"
    # `_name`, merged into one real model by the registry, but two separate
    # classes as far as pyright is concerned) -- aliased on import so this
    # file's own `class BuilderWorkspace` below does not collide with it. A
    # plain `cast()` target needs no runtime binding (rule 4), so this stays
    # `TYPE_CHECKING`-only rather than a real top-level import.
    from odoo.addons.app_builder_base.models.builder_workspace import (
        BuilderWorkspace as BuilderWorkspaceBase,
    )

    # `base_automation` (core, not this addon) adds `base_automation_id` to
    # `ir.actions.server` via its own `_inherit` extension -- not on the
    # base `IrActionsServer` (`odoo.addons.base.models.ir_actions`), so the
    # read below casts to this class instead.
    from odoo.addons.base_automation.models.ir_actions_server import ServerAction


class BuilderWorkspace(models.AbstractModel):
    _inherit = "builder.workspace"

    @api.model
    def _inventory_group(self, model_name: str, record: BaseModel | None) -> str:
        """An automation is one thing to the user, rule and actions alike."""
        if model_name == "base.automation":
            return "automations"
        if (
            model_name == "ir.actions.server"
            and record is not None
            and cast("ServerAction", record).base_automation_id
        ):
            return "automations"
        return cast("BuilderWorkspaceBase", super())._inventory_group(
            model_name, record
        )

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

if TYPE_CHECKING:
    from odoo.models import BaseModel

    # Aliased: this file's own class below is also `BuilderWorkspace` (same
    # `_name`, merged into one model at runtime, two Python classes as far
    # as pyright is concerned) -- rule 7's same-class-name-collision fix,
    # same shape as `builder_package_model.py`'s own `BuilderPackageModel`
    # alias.
    from odoo.addons.app_builder_base.models.builder_workspace import (
        BuilderWorkspace as BuilderWorkspaceBase,
    )


class BuilderWorkspace(models.AbstractModel):
    _inherit = "builder.workspace"

    @api.model
    def _inventory_group(self, model_name: str, record: BaseModel | None) -> str:
        if model_name == "tier.definition":
            return "approvals"
        return cast("BuilderWorkspaceBase", super())._inventory_group(
            model_name, record
        )

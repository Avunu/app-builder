# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

if TYPE_CHECKING:
    from odoo.models import BaseModel

    # Aliased: this file's own class below is also `StudioWorkspace` (same
    # `_name`, merged into one model at runtime, two Python classes as far
    # as pyright is concerned) -- rule 7's same-class-name-collision fix,
    # same shape as `studio_package_model.py`'s own `StudioPackageModel`
    # alias.
    from odoo.addons.app_builder_base.models.studio_workspace import (
        StudioWorkspace as StudioWorkspaceBase,
    )


class StudioWorkspace(models.AbstractModel):
    _inherit = "studio.workspace"

    @api.model
    def _inventory_group(self, model_name: str, record: BaseModel | None) -> str:
        if model_name == "tier.definition":
            return "approvals"
        return cast("StudioWorkspaceBase", super())._inventory_group(model_name, record)

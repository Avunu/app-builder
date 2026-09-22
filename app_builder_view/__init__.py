from __future__ import annotations

from typing import TYPE_CHECKING

from . import models

if TYPE_CHECKING:
    from odoo import api


def uninstall_hook(env: api.Environment) -> None:
    """The Studio root menu belongs to app_builder_base; this addon pointed it
    at the console. Uninstalled, the action goes with it and the reference
    would dangle."""
    root = env.ref("app_builder_base.menu_studio_root", raise_if_not_found=False)
    if root:
        root.write({"action": False})

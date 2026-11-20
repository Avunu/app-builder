from __future__ import annotations

import os
from typing import TYPE_CHECKING

if os.environ.get("APP_BUILDER_TYPEGUARD"):
    # Must run before `tools` is imported (typeguard rewrites a module as it
    # loads). Test/CI only -- see `_typeguard_hook.py`.
    from . import _typeguard_hook

    _typeguard_hook.install()

from . import models, tools

if TYPE_CHECKING:
    from odoo import api


def uninstall_hook(env: api.Environment) -> None:
    """Say what uninstalling the builder leaves behind: the packages that
    were never installed as modules, whose records lose the only thing that
    knew they belonged together. See ``_warn_orphans_on_uninstall``."""
    from .models.builder_package import BuilderPackage
    from .tools import typed

    typed.model(env, BuilderPackage)._warn_orphans_on_uninstall()

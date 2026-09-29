import os

if os.environ.get("APP_BUILDER_TYPEGUARD"):
    # Must run before `tools` is imported (typeguard rewrites a module as it
    # loads). Test/CI only -- see `_typeguard_hook.py`.
    from . import _typeguard_hook

    _typeguard_hook.install()

from . import models, tools

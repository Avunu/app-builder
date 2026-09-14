from . import models


def uninstall_hook(env):
    """The Studio root menu belongs to app_builder_base; this addon pointed it
    at the console. Uninstalled, the action goes with it and the reference
    would dangle."""
    root = env.ref("app_builder_base.menu_studio_root", raise_if_not_found=False)
    if root:
        root.write({"action": False})

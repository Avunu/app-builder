from . import base_automation_serializer
from . import (
    studio_automation,
    studio_graduate_code,
    studio_owned,
    studio_security_surface,
)
from . import studio_automation_surface, studio_menu_surface, studio_workspace

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "base_automation_serializer",
    "studio_automation",
    "studio_automation_surface",
    "studio_graduate_code",
    "studio_menu_surface",
    "studio_owned",
    "studio_security_surface",
    "studio_workspace",
]

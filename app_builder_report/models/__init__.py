from . import studio_report
from . import studio_report_surface
from . import studio_report_preview
from . import ir_actions_report

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "ir_actions_report",
    "studio_report",
    "studio_report_preview",
    "studio_report_surface",
]

from . import studio_view_edit, studio_view_editor  # isort:skip
from . import studio_report_ops
from . import studio_package_model, studio_view_canvas
from . import studio_view_new_field
from . import studio_model_draft

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "studio_model_draft",
    "studio_package_model",
    "studio_report_ops",
    "studio_view_canvas",
    "studio_view_edit",
    "studio_view_editor",
    "studio_view_new_field",
]

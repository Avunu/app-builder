from . import (
    ir_actions,
    ir_cron,
    ir_default,
    ir_model,
    ir_security,
    ir_sequence,
    ir_ui_menu,
    ir_ui_view,
)

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "ir_actions",
    "ir_cron",
    "ir_default",
    "ir_model",
    "ir_security",
    "ir_sequence",
    "ir_ui_menu",
    "ir_ui_view",
]

from . import studio_app_builder

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "studio_app_builder",
]

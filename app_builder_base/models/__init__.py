# studio_security first: registry.load builds models in import order, so an
# abstract parent must be imported before anything that _inherits it.
from . import studio_security  # isort: skip
from . import (
    serializers,
    studio_owned_mixin,
    studio_model_draft,
    studio_package,
    studio_package_apply,
    studio_package_model,
    studio_serializer,
)
from . import res_users, studio_domain, studio_record_surface  # isort: skip
from . import studio_security_surfaces, studio_workspace

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "res_users",
    "serializers",
    "studio_domain",
    "studio_model_draft",
    "studio_owned_mixin",
    "studio_package",
    "studio_package_apply",
    "studio_package_model",
    "studio_record_surface",
    "studio_security",
    "studio_security_surfaces",
    "studio_serializer",
    "studio_workspace",
]

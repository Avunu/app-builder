from . import mail_serializers

# Importing a model module is what registers its models with the registry;
# nothing reads the names. Listed so that is stated, not reported as unused.
__all__ = [
    "mail_serializers",
]

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""18.0.2.0.0 is the first supported schema of the builder.

Before it the builder's own models were called ``studio.*``; 2.0.0 renamed
them to ``builder.*`` (``studio.package`` -> ``builder.package`` and so on)
in the same modules. Odoo treats a changed ``_name`` as a new model, so an
upgrade from 1.x creates empty ``builder_*`` tables and leaves the
``studio_*`` ones behind, orphaned. That registry is not migrated: the
pre-2.0 releases were never published, the generated addon directories on
disk are the source of truth, and the registry is rebuilt from them by
creating the package again and adopting its models. What this script does is
say so, loudly, instead of letting the upgrade look like data loss.

It is also the convention for every later release. A change to the builder's
own stored state -- ``builder.package``, ``builder.package.file`` checksums,
``builder.package.apply`` history, ``builder.view.edit`` -- ships with a
script under ``migrations/<new version>/`` in the addon that owns the model,
in the same commit as the change and the manifest version bump, and with a
test that runs it. ``pre-*`` scripts run before the module's models are
loaded (rename tables and columns here, so the ORM finds them); ``post-*``
scripts run after (convert values here, with the ORM available).
"""

import logging

_logger = logging.getLogger(__name__)

LEGACY_TABLES = (
    "studio_package",
    "studio_package_file",
    "studio_package_apply",
    "studio_package_apply_file",
    "studio_package_model",
    "studio_model_draft",
)


def legacy_tables(cr):
    """The pre-2.0 tables still present in this database."""
    cr.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = ANY(%s)
        ORDER BY table_name
        """,
        (list(LEGACY_TABLES),),
    )
    return [row[0] for row in cr.fetchall()]


def migrate(cr, version):
    if not version:
        return
    found = legacy_tables(cr)
    if found:
        _logger.warning(
            "App Builder %s was installed here and its registry (%s) is not "
            "carried over: 18.0.2.0.0 is the first supported schema. The "
            "packages themselves are untouched on disk; create each package "
            "again in the Builder and adopt its models. The old tables are "
            "left in place and can be dropped once that is done.",
            version,
            ", ".join(found),
        )

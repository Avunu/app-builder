# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Move graduated_models from a comma-joined char to studio.package.model rows.

The char column could not carry per-model state -- where the definition lives,
whether the file still parses -- and was doing double duty as both an ownership
registry and a rendering flag. Nothing is lost: every name it held becomes a row
with source='python', which is exactly what "graduated" meant.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'studio_package' AND column_name = 'graduated_models'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        "SELECT id, graduated_models FROM studio_package "
        "WHERE graduated_models IS NOT NULL AND graduated_models != ''"
    )
    rows = cr.fetchall()
    created = 0
    for package_id, joined in rows:
        for name in {m.strip() for m in joined.split(",") if m.strip()}:
            cr.execute(
                """
                INSERT INTO studio_package_model (package_id, model, source)
                VALUES (%s, %s, 'python')
                ON CONFLICT (package_id, model) DO NOTHING
                """,
                (package_id, name),
            )
            created += cr.rowcount
    cr.execute("ALTER TABLE studio_package DROP COLUMN graduated_models")
    _logger.info(
        "app_builder_base: migrated %d graduated model(s) from %d package(s) "
        "into studio.package.model",
        created,
        len(rows),
    )

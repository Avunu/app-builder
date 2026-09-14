# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Re-home the capture mixin's xmlid from app_builder_ui to app_builder_base.

``studio.captured.on.create`` moved into the engine so that app_builder_ui and
app_builder_approval inherit one rule instead of two copies. The model row
already exists on an upgraded database, under the xmlid app_builder_ui minted
when it still declared the class. Left alone, the next upgrade of
app_builder_ui finds that xmlid unreferenced and ``_process_end`` deletes the
``ir.model`` row it names -- and every ``ir.model.inherit`` row of the models
that mix it in goes with it, so the registry no longer loads.

The same script ships in both modules, because either may be upgraded first
and each has to leave the database in a state the other can load.
"""

import logging

_logger = logging.getLogger(__name__)

XMLID_NAME = "model_studio_captured_on_create"


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT module FROM ir_model_data WHERE model = 'ir.model' AND name = %s",
        (XMLID_NAME,),
    )
    modules = {row[0] for row in cr.fetchall()}
    if "app_builder_ui" not in modules:
        return
    if "app_builder_base" in modules:
        # Both exist: the engine's is the one to keep. Only the stale xmlid
        # goes, never the record.
        cr.execute(
            "DELETE FROM ir_model_data "
            "WHERE module = 'app_builder_ui' AND model = 'ir.model' AND name = %s",
            (XMLID_NAME,),
        )
    else:
        cr.execute(
            "UPDATE ir_model_data SET module = 'app_builder_base' "
            "WHERE module = 'app_builder_ui' AND model = 'ir.model' AND name = %s",
            (XMLID_NAME,),
        )
    _logger.info("studio.captured.on.create is now owned by app_builder_base")

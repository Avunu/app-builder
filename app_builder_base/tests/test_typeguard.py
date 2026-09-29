# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The typeguard hook (TYPING.md, Phase 1e) is really on when it says it is.

A run "under typeguard" whose hook silently never installed -- it has to
precede the first import of ``tools/``, so an ordering slip in
``app_builder_base/__init__.py`` would do it -- passes every test exactly as
a real one does. So when ``APP_BUILDER_TYPEGUARD`` is set, prove a bad call to
a ``tools/`` function is refused; when it is not, say so rather than pass.
"""

from __future__ import annotations

import os
from typing import Any, cast

from odoo.tests import BaseCase, tagged

from odoo.addons.app_builder_base.tools import modelspec

from .common import raises


@tagged("post_install", "-at_install")
class TestTypeguardHook(BaseCase):
    def test_tools_refuse_a_call_that_breaks_their_annotations(self):
        if not os.environ.get("APP_BUILDER_TYPEGUARD"):
            self.skipTest("APP_BUILDER_TYPEGUARD is not set: tools/ is not checked")
        # Optional test dependency: absent from a plain dev env.
        from typeguard import TypeCheckError  # pyright: ignore[reportMissingImports]

        # `spec_to_json` is `(ModelSpec | FieldSpec) -> dict`; an int is neither.
        # Without the hook `asdict(1)` raises a bare TypeError instead, so the
        # exception class is what tells the two apart.
        with raises(self, TypeCheckError):
            modelspec.spec_to_json(cast("Any", 1))

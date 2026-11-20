# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Running the report canvas's hoot unit tests as part of this addon's suite.

The tour drives a report that renders; the hoot tests under ``static/tests``
pin what it cannot reach -- that the rendered document stays inside its
sandboxed frame, and that a template which does not render still opens. They
run the way ``app_builder_view``'s do (its ``tests/test_js.py`` has the full
account): the hoot runner on ``/web/tests``, filtered to this addon's suites
by an exact-string query, green when it prints its success line *and* reports
that something ran.
"""

from __future__ import annotations

from urllib.parse import quote

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderHttpCase
from odoo.addons.app_builder_view.tests.test_js import (
    _RUNBOT,
    NO_TESTS,
    RE_PASSED,
    _RunnerLines,
)
from odoo.addons.web.tests.test_js import unit_test_error_checker

SUITE_PREFIX = "@app_builder_report/"


@tagged("post_install", "-at_install")
class TestReportJs(BuilderHttpCase):
    def test_hoot_suite(self):
        """Every hoot test under ``static/tests`` passes, and at least one
        of them ran."""
        query = quote('"%s"' % SUITE_PREFIX, safe="")
        lines = _RunnerLines()
        logger = self._logger
        level = logger.level
        if logger.getEffectiveLevel() > _RUNBOT:
            logger.setLevel(_RUNBOT)
        logger.addHandler(lines)
        try:
            self.browser_js(
                "/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&filter=%s"
                % query,
                "",
                "",
                login="admin",
                timeout=600,
                success_signal="[HOOT] Test suite succeeded",
                error_checker=unit_test_error_checker,
            )
        finally:
            logger.removeHandler(lines)
            logger.setLevel(level)

        self.assertFalse(
            [m for m in lines.messages if NO_TESTS in m],
            "the filter %r matched no hoot suite" % SUITE_PREFIX,
        )
        counts = [
            int(match.group(1))
            for match in map(RE_PASSED.search, lines.messages)
            if match
        ]
        self.assertTrue(counts, "the runner did not report how many tests passed")
        self.assertGreater(counts[-1], 0, "the runner passed an empty run")

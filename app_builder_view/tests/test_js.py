# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Running the console's hoot unit tests as part of this addon's suite.

The tours drive the console the way a person does; the hoot tests under
``static/tests`` pin the contracts with the web client the console cannot see
from a tour -- that the derived view classes never save, that a class token
reaches the element it was minted for. They run in the browser the way
``web``'s own do (``odoo/addons/web/tests/test_js.py``): the hoot runner is
opened on ``/web/tests`` with a filter that keeps it to this addon's suites,
and the run is green when it prints its success line.

The filter is an exact-string query, ``"@app_builder_view/"`` in quotes: the
runner's plain query is fuzzy, and ``app_builder_view`` unquoted would match
any suite whose name contains those letters in that order.

The success line alone is not enough: the runner prints it for an empty run
too, ``Passed 0 tests`` after ``no tests to run``, so a filter that matched
nothing -- the suite naming changed, a manifest glob went stale -- would
keep this test green while running nothing. The runner's count line is read
back from the browser log and has to say that something ran.
"""

import logging
import re
from urllib.parse import quote

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioHttpCase
from odoo.addons.web.tests.test_js import unit_test_error_checker

# The suite prefix hoot gives the files of this addon: ``@<addon>/<file>``,
# with the ``static/tests/`` part elided.
SUITE_PREFIX = "@app_builder_view/"

# What the runner prints once for the whole run, as ``console.dir``.
RE_PASSED = re.compile(r"\[HOOT\] Passed (\d+) tests?\b")
NO_TESTS = "[HOOT] no tests to run"


class _RunnerLines(logging.Handler):
    """Collect the browser's console lines as ``browser_js`` relays them.

    A handler rather than ``assertLogs``: that one turns propagation off for
    the logger it watches, and the hoot output would then be missing from
    the server log exactly when a failure makes it worth reading.
    """

    def __init__(self):
        super().__init__(logging.RUNBOT)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@tagged("post_install", "-at_install")
class TestJs(StudioHttpCase):
    def test_hoot_suite(self):
        """Every hoot test under ``static/tests`` passes, and at least one
        of them ran."""
        query = quote('"%s"' % SUITE_PREFIX, safe="")
        lines = _RunnerLines()
        # The browser logs under this test's logger, at INFO for plain
        # output and at RUNBOT for the runner's ``console.dir`` lines; the
        # level is lowered only when the running configuration would drop
        # those, and put back afterwards.
        logger = self._logger
        level = logger.level
        if logger.getEffectiveLevel() > logging.RUNBOT:
            logger.setLevel(logging.RUNBOT)
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

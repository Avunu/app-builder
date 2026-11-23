# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""In CI, a test that skips is a failure unless it is listed here.

About twenty tests of these addons call ``skipTest`` when the database lacks
something: an addon, a writable addons directory, an environment variable. On
a developer's database that is the honest answer. In CI it is how coverage
disappears without anybody noticing: a runner whose checkout turned read-only,
or a shell that stopped exporting ``APP_BUILDER_TYPEGUARD``, would turn tests
off and leave the gate green.

So when ``APP_BUILDER_STRICT_SKIPS`` is set (flake.nix sets it under
``ODOO_NIX_CI``), every skip of a test of these addons that ``EXPECTED`` does
not name is reported as that test's failure, with the reason it gave. A test
that is *known* not to run on CI's database is listed in ``EXPECTED`` with why,
which also makes the list the place to read what CI does not cover.

Importing this module installs the hook, and ``tests/__init__.py`` imports it
before any test module, so it is on from the first test
of ``app_builder_base`` -- the addon every other one depends on -- and covers
a run that tests them all, as the gate does.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

ENV = "APP_BUILDER_STRICT_SKIPS"
#: Only these addons' tests are held to it: Odoo's own skip freely.
PREFIX = "odoo.addons.app_builder"

#: The tests that skip on the gate's database (every addon of this repository
#: and its dependencies, with demo data), and why each does.
EXPECTED: Mapping[str, str] = {
    "odoo.addons.app_builder_base.tests.test_serializer_coverage"
    ".TestReferencePortability"
    ".test_a_many2one_reference_resolves_through_its_model_field": (
        "res.partner has no tag field to trigger on unless a CRM-like addon "
        "is installed"
    ),
    "odoo.addons.app_builder_view.tests.test_add_view"
    ".TestAddView.test_without_owned_actions_no_action_is_changed": (
        "app_builder_ui is installed, so window actions have owners; the "
        "behaviour with owners is app_builder_ui's TestAddViewActions. The "
        "ownerless guard it observes runs only on a database with "
        "app_builder_view but not app_builder_ui, which CI does not build"
    ),
    "odoo.addons.app_builder_view.tests.test_add_view"
    ".TestViewTypeDiscovery.test_a_timeline_reports_what_it_needs": (
        "web_timeline is not a dependency of any addon here"
    ),
    "odoo.addons.app_builder_view.tests.test_add_view"
    ".TestViewTypeDiscovery"
    ".test_a_type_without_a_scaffold_says_so_rather_than_vanishing": (
        "every view type installed on the gate's database has a scaffold"
    ),
    "odoo.addons.app_builder_model.tests.test_model_builder"
    ".TestRelatedAndComputed.test_a_broken_path_names_the_step_that_failed": (
        "the demo model is not package-managed on a fresh database"
    ),
    "odoo.addons.app_builder_model.tests.test_model_builder"
    ".TestRelatedAndComputed.test_a_related_path_reports_the_type_it_lands_on": (
        "the demo model is not package-managed on a fresh database"
    ),
    "odoo.addons.app_builder_model.tests.test_model_builder"
    ".TestRelatedAndComputed.test_following_a_non_relation_is_refused": (
        "the demo model is not package-managed on a fresh database"
    ),
}


_state = {"installed": False}


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether skips are held to ``EXPECTED``: the variable, set to anything
    but "", 0 or false."""
    value = (os.environ if environ is None else environ).get(ENV, "")
    return value.strip().lower() not in ("", "0", "false")


#: Odoo's ``HttpCase.browser_js`` raises ``SkipTest`` when Chrome itself fails
#: to start or answer (odoo/tests/common.py). Such a skip of a tour of ours
#: still fails -- the tour's coverage is lost all the same -- but its message
#: says it is the runner's Chrome, so a flake is told apart from a test that
#: stopped running.
BROWSER_REASONS = (
    "chrome devtools port",
    "chrome headless connection",
    "chrome connection",
    "chrome dev tools",
    "chrome executable not found",
    "websocket-client module is not installed",
)


def test_id(test: Any) -> str:
    """``module.Class.method`` of a test case, or of a subtest's case.

    A ``SkipTest`` from ``setUpClass`` or ``setUpModule`` reaches ``addSkip``
    as an ``_ErrorHolder`` that only carries a description such as
    ``setUpClass (odoo.addons.app_builder_x.tests.test_y.TestZ)``: that
    description is its name.
    """
    case = getattr(test, "test_case", test)
    if not hasattr(case, "_testMethodName") and isinstance(
        getattr(case, "description", None), str
    ):
        return case.description
    cls = type(case)
    method = getattr(case, "_testMethodName", "")
    return f"{cls.__module__}.{cls.__qualname__}.{method}"


def unexpected(name: str, expected: Mapping[str, str] | None = None) -> bool:
    """Whether a skip of the test called ``name`` is one nobody signed off.

    A test's own name starts with ``PREFIX``; a class- or module-level skip's
    name has it inside the parentheses, so the prefix may be anywhere.
    """
    listed = EXPECTED if expected is None else expected
    return PREFIX in name and name not in listed


def is_browser_failure(reason: str) -> bool:
    """Whether ``reason`` is one of Odoo's own skips for a Chrome that failed."""
    lowered = reason.lower()
    return any(marker in lowered for marker in BROWSER_REASONS)


def message(name: str, reason: str) -> str:
    if is_browser_failure(reason):
        return (
            f"{name} was skipped in CI because the runner's browser failed "
            f"({reason}). This is infrastructure, not the test: re-run the job. "
            f"{ENV} still fails it, since a tour that did not run covers nothing."
        )
    return (
        f"{name} was skipped in CI ({reason}). A skip here removes coverage "
        f"without failing the gate, so {ENV} turns it into a failure. Make the "
        "test run on CI's database, or add it to EXPECTED in "
        "app_builder_base/tests/strict_skips.py with the reason it cannot."
    )


def on_skip(result: Any, test: Any, reason: str) -> bool:
    """Report an unexpected skip as the test's failure. Returns whether it did."""
    name = test_id(test)
    if not unexpected(name):
        return False
    try:
        raise AssertionError(message(name, reason))
    except AssertionError:
        result.addFailure(test, sys.exc_info())
    return True


def install(environ: Mapping[str, str] | None = None) -> bool:
    """Hold every later skip to ``EXPECTED``, once. Returns whether it is on."""
    if not enabled(environ):
        return False
    # Deferred: nothing outside a test run needs Odoo's test machinery.
    from odoo.tests.result import OdooTestResult

    if _state["installed"]:
        return True
    original = OdooTestResult.addSkip

    def addSkip(self: Any, test: Any, reason: str) -> None:
        original(self, test, reason)
        on_skip(self, test, reason)

    OdooTestResult.addSkip = addSkip
    _state["installed"] = True
    return True


# On import: tests/__init__.py imports this first, before any test can skip.
install()

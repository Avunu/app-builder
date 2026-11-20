# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A skip in CI is a failure unless ``strict_skips.EXPECTED`` names the test.

The hook itself only runs where ``APP_BUILDER_STRICT_SKIPS`` is set, so these
drive its parts directly: they hold on a developer's database too.
"""

from __future__ import annotations

import importlib
import importlib.util

from odoo.tests import BaseCase, tagged

from . import strict_skips


class _Result:
    """Stands in for ``OdooTestResult``: records what was failed."""

    def __init__(self):
        self.failed = []

    def addFailure(self, test, err):
        self.failed.append((test, err))


class _SubTest:
    """What ``addSkip`` receives for a ``subTest``: the case is one level in."""

    def __init__(self, test_case):
        self.test_case = test_case


@tagged("post_install", "-at_install")
class TestStrictSkips(BaseCase):
    def test_it_is_off_unless_the_variable_says_so(self):
        self.assertFalse(strict_skips.enabled({}))
        for off in ("", "0", "false", " False "):
            self.assertFalse(strict_skips.enabled({strict_skips.ENV: off}), off)
        self.assertTrue(strict_skips.enabled({strict_skips.ENV: "1"}))
        self.assertFalse(strict_skips.install({}))

    def test_a_test_is_named_by_module_class_and_method(self):
        name = strict_skips.test_id(self)
        self.assertEqual(
            name,
            "odoo.addons.app_builder_base.tests.test_strict_skips"
            ".TestStrictSkips.test_a_test_is_named_by_module_class_and_method",
        )
        self.assertEqual(strict_skips.test_id(_SubTest(self)), name)

    def test_an_unlisted_skip_of_ours_fails_the_test(self):
        result = _Result()
        self.assertTrue(strict_skips.on_skip(result, self, "no such addon"))
        self.assertEqual(len(result.failed), 1)
        test, (kind, error, _tb) = result.failed[0]
        self.assertIs(test, self)
        self.assertIs(kind, AssertionError)
        self.assertIn("no such addon", str(error))
        self.assertIn(strict_skips.test_id(self), str(error))

    def test_a_listed_skip_and_another_addons_skip_pass(self):
        name = strict_skips.test_id(self)
        self.assertTrue(strict_skips.unexpected(name))
        self.assertFalse(strict_skips.unexpected(name, {name: "known"}))
        self.assertFalse(
            strict_skips.unexpected("odoo.addons.base.tests.test_x.TestX.test_y")
        )
        for listed in strict_skips.EXPECTED:
            self.assertFalse(strict_skips.unexpected(listed), listed)

    def test_every_listed_test_exists(self):
        """A renamed or removed test must leave ``EXPECTED``: an entry nothing
        can match would excuse a skip nobody decided to excuse."""
        for name, why in strict_skips.EXPECTED.items():
            self.assertTrue(why, name)
            module_name, cls_name, method = name.rsplit(".", 2)
            addon = module_name.split(".")[2]
            if importlib.util.find_spec(f"odoo.addons.{addon}") is None:
                continue
            cls = getattr(importlib.import_module(module_name), cls_name, None)
            self.assertIsNotNone(cls, name)
            self.assertTrue(callable(getattr(cls, method, None)), name)

    def test_a_class_level_skip_is_named_by_its_description(self):
        """``setUpClass`` raising ``SkipTest`` reaches ``addSkip`` as an
        ``_ErrorHolder``: it must not slip past the check."""
        from odoo.tests.suite import _ErrorHolder

        ours = _ErrorHolder(
            "setUpClass (odoo.addons.app_builder_base.tests.test_x.TestX)"
        )
        self.assertEqual(strict_skips.test_id(ours), ours.description)
        self.assertTrue(strict_skips.unexpected(strict_skips.test_id(ours)))
        result = _Result()
        self.assertTrue(strict_skips.on_skip(result, ours, "no such addon"))
        self.assertEqual(len(result.failed), 1)

        theirs = _ErrorHolder("setUpClass (odoo.addons.base.tests.test_x.TestX)")
        self.assertFalse(strict_skips.unexpected(strict_skips.test_id(theirs)))

    def test_a_browser_failure_says_it_is_the_runner(self):
        name = strict_skips.test_id(self)
        flake = strict_skips.message(name, "Cannot connect to chrome dev tools")
        self.assertIn("runner's browser failed", flake)
        self.assertNotIn("add it to EXPECTED", flake)
        missing = strict_skips.message(name, "app_builder_view is not installed")
        self.assertNotIn("runner's browser", missing)
        self.assertIn("add it to EXPECTED", missing)

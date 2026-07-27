# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Manifest rendering and hand-edit tolerance."""

import ast

from odoo.tests import TransactionCase, tagged

from ..tools import manifest as manifest_tools


@tagged("post_install", "-at_install")
class TestManifest(TransactionCase):
    def test_render_is_parseable(self):
        values = {"name": "Demo", "depends": ["base"], "data": ["views/a.xml"]}
        text = manifest_tools.render_manifest(values)
        self.assertEqual(ast.literal_eval(text), values)

    def test_key_order_is_declared_not_alphabetical(self):
        text = manifest_tools.render_manifest(
            {"data": [], "name": "Demo", "version": "1.0", "depends": []}
        )
        self.assertLess(text.index('"name"'), text.index('"version"'))
        self.assertLess(text.index('"version"'), text.index('"depends"'))
        self.assertLess(text.index('"depends"'), text.index('"data"'))

    def test_render_is_deterministic(self):
        values = {"name": "Demo", "depends": ["b", "a"], "data": ["z.xml", "a.xml"]}
        self.assertEqual(
            manifest_tools.render_manifest(values),
            manifest_tools.render_manifest(dict(reversed(list(values.items())))),
        )

    def test_output_uses_double_quotes(self):
        """Generated source must already be canonical under ruff format.

        Otherwise the project's own pre-commit rewrites it on the next commit
        and every package reports as drifted with nothing actually changed.
        """
        text = manifest_tools.render_manifest(
            {"name": "Demo", "depends": ["base"], "data": ["views/a.xml"]}
        )
        self.assertIn('"name": "Demo"', text)
        self.assertNotIn("'", text)

    def test_merge_preserves_unknown_keys(self):
        """A developer's hand-added key must survive the next write."""
        existing = {"name": "Old", "post_init_hook": "_setup", "custom_flag": True}
        merged = manifest_tools.merge_manifest(existing, {"name": "New"})
        self.assertEqual(merged["name"], "New")
        self.assertEqual(merged["post_init_hook"], "_setup")
        self.assertTrue(merged["custom_flag"])

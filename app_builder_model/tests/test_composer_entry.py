# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""There has to be a way in.

The composer shipped complete and unreachable: its menu used an xmlid that
``studio_menus.xml`` already used for the technical model list, and that file
loads later, so the menu was quietly replaced and nothing pointed at the
composer at all. Odoo does not warn when a data file redefines another's
xmlid -- the record is simply overwritten -- so the only symptom was an absent
menu, which reads as an incomplete deployment rather than a bug.

Both halves are pinned here: the entry point exists, and no module redefines
one of its own xmlids again.
"""

import os
from collections import Counter

from lxml import etree

from odoo.modules.module import get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestComposerEntryPoint(TransactionCase):
    def test_the_composer_is_reachable_from_a_menu(self):
        menu = self.env.ref("app_builder_model.menu_studio_composer")
        self.assertEqual(
            menu.action,
            self.env.ref("app_builder_model.studio_package_model_action"),
            "the menu must open the model list the Compose button lives on",
        )
        self.assertTrue(menu.parent_id, "it belongs under the Studio root")

    def test_the_technical_model_list_kept_its_own_menu(self):
        """The two are different surfaces and both should exist."""
        menu = self.env.ref("app_builder_model.menu_studio_models")
        self.assertEqual(menu.name, "Custom Models")

    def test_an_administrator_can_see_the_way_in(self):
        """The root menu is group-gated, so 'no menu anywhere' is also what a
        missing group implication looks like. base.group_system has to reach
        it, or the person who installed the studio cannot open it."""
        menu = self.env.ref("app_builder_model.menu_studio_composer")
        visible = self.env["ir.ui.menu"].with_user(self.env.ref("base.user_admin"))
        self.assertIn(menu.id, visible.search([]).ids)


@tagged("post_install", "-at_install")
class TestNoRedefinedXmlids(TransactionCase):
    """A redefined xmlid is silent, so it needs a test rather than a review."""

    def _module_root(self, module):
        """Ask Odoo where the module is, rather than walking up from here.

        Under an editable install ``__file__`` sits inside a ``build/__editable__``
        shim, so a relative path lands nowhere and every module gets skipped --
        a scan that silently checks nothing and passes.
        """
        return get_module_path(module)

    def test_no_studio_module_redefines_one_of_its_own_xmlids(self):
        checked = 0
        for module in (
            "app_builder_base",
            "app_builder_model",
            "app_builder_view",
            "app_builder_ui",
        ):
            root = self._module_root(module)
            self.assertTrue(
                root and os.path.isdir(root),
                "cannot locate %s, so this test would check nothing" % module,
            )
            checked += 1
            ids = []
            for dirpath, _dirs, names in os.walk(root):
                if "tests" in dirpath.split(os.sep):
                    continue
                for name in sorted(names):
                    if not name.endswith(".xml"):
                        continue
                    tree = etree.parse(os.path.join(dirpath, name))
                    for node in tree.iter():
                        if node.tag in ("record", "menuitem", "template"):
                            value = node.get("id")
                            if value and "." not in value:
                                ids.append(value)
            repeated = [name for name, count in Counter(ids).items() if count > 1]
            self.assertFalse(
                repeated,
                "%s defines %s more than once; the last file loaded wins and "
                "the earlier definition disappears without a warning"
                % (module, ", ".join(sorted(repeated))),
            )
        self.assertEqual(checked, 4, "every studio module must actually be scanned")

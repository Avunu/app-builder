# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""There has to be a way in.

The composer shipped complete and unreachable: its menu used an xmlid that
``builder_menus.xml`` already used for the technical model list, and that file
loads later, so the menu was quietly replaced and nothing pointed at the
composer at all. Odoo does not warn when a data file redefines another's
xmlid -- the record is simply overwritten -- so the only symptom was an absent
menu, which reads as an incomplete deployment rather than a bug.

Both halves are pinned here: the entry point exists, and no module redefines
one of its own xmlids again.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.modules.module import get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_ui_menu import IrUiMenu


@tagged("post_install", "-at_install")
class TestComposerEntryPoint(TransactionCase):
    def test_the_composer_is_reachable_from_a_menu(self):
        menu = cast(
            "IrUiMenu", typed.ref(self.env, "app_builder_model.menu_builder_composer")
        )
        self.assertEqual(
            menu.action,
            self.env.ref("app_builder_model.builder_package_model_action"),
            "the menu must open the model list the Compose button lives on",
        )
        self.assertTrue(menu.parent_id, "it belongs under the Builder root")

    def test_the_technical_model_list_kept_its_own_menu(self):
        """The two are different surfaces and both should exist."""
        menu = cast(
            "IrUiMenu", typed.ref(self.env, "app_builder_model.menu_builder_models")
        )
        self.assertEqual(menu.name, "Custom Models")

    def test_an_administrator_can_see_the_way_in(self):
        """The root menu is group-gated, so 'no menu anywhere' is also what a
        missing group implication looks like. base.group_system has to reach
        it, or the person who installed the builder cannot open it. The
        composer list itself is developer-mode only: the console is the
        way in, and this list is the rows behind its cards."""
        root = typed.ref(self.env, "app_builder_base.menu_builder_root")
        menu = typed.ref(self.env, "app_builder_model.menu_builder_composer")
        admin = self.env.ref("base.user_admin")
        visible = self.env["ir.ui.menu"].with_user(admin)
        self.assertIn(root.id, visible.search([]).ids)
        self.assertNotIn(menu.id, visible.search([]).ids)
        debug = visible.with_context(**{"ir.ui.menu.full_list": True})
        self.assertIn(menu.id, debug.search([]).ids)


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

    def test_no_builder_module_redefines_one_of_its_own_xmlids(self):
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
            # The assertTrue above raises if `root` is falsy -- same
            # "invariant guaranteed by the check just above, not provable
            # from here" shape as `builder_package.py`'s own
            # `cast("str", self.root_path)`.
            for dirpath, _dirs, names in os.walk(cast("str", root)):
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
        self.assertEqual(checked, 4, "every builder module must actually be scanned")

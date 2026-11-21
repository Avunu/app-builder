# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A report edit is a spec in a sequence, the same as a form edit.

The report operations used to decide "already there" by looking at the
spec: a block with the same locator holding a span for the same expression
meant the value was printed. A spec remembers every value this package
ever placed -- including the ones a later spec removed -- so placing a
value, taking it out and placing it back did nothing and reported success.
The same lookup folded a second value into the *first* block at that
anchor, ahead of whatever had been placed in between. On a report the
package owns the question was asked of the whole arch instead, so a value
printed anywhere could not be placed anywhere else.

These are the sequences that went wrong, on both paths, plus the guards
every edit of a report shares with the view editor: a read-only package is
not edited, and undo and redo refuse to throw away what they did not write.
"""

from __future__ import annotations

from typing import cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.builder_view_edit import BuilderViewEdit
from odoo.addons.app_builder_view.models.builder_view_editor import BuilderViewEditor
from odoo.addons.base.models.ir_model import IrModel, IrModelFields
from odoo.addons.base.models.ir_ui_view import View

from ..models.builder_report import BuilderReport

PAGE = "//div[hasclass('page')]"


class ReportSequenceCase(BuilderCase):
    """A report made by one package and edited by another, so every edit is
    a spec appended to an extension of the template -- or, with ``foreign``
    off, a report the editing package owns and edits in place."""

    foreign = True

    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.history = typed.model(self.env, BuilderViewEdit)
        owner = self.make_package(name="x_report_owner")
        self.build_demo_content(owner)
        self.package = (
            self.make_package(name="x_report_editor") if self.foreign else owner
        )
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        line_vals: dict[str, object] = {
            "name": "x_line_ids",
            "ttype": "one2many",
            "field_description": "Lines",
            "model_id": model.id,
            "model": "x_builder_project",
            "relation": "res.partner",
            "relation_field": "parent_id",
        }
        typed.model(self.env, IrModelFields).create(line_vals)  # pyright: ignore[reportArgumentType]
        made = typed.model(self.env, BuilderReport).create_report(
            cast("int", owner.id), "x_builder_project", "Job Sheet"
        )
        self.view = typed.model(self.env, View).browse(made["view_id"])
        self.view_id = cast("int", self.view.id)
        self.package_id = cast("int", self.package.id)

    # -- helpers ---------------------------------------------------------------

    def _apply(self, operation: dict[str, object]):
        return self.editor.apply_operation(self.view_id, self.package_id, operation)

    def _place(self, name: str, xpath: str = PAGE, position: str = "inside", **extra):
        operation: dict[str, object] = {
            "type": "add_report_field",
            "xpath": xpath,
            "position": position,
            "model": "x_builder_project",
            "name": name,
        }
        operation.update(extra)
        return self._apply(operation)

    def _table(self, columns: list[str], xpath: str = PAGE, position: str = "inside"):
        return self._apply(
            {
                "type": "add_report_table",
                "xpath": xpath,
                "position": position,
                "model": "x_builder_project",
                "name": "x_line_ids",
                "columns": columns,
            }
        )

    def _combined(self):
        return etree.fromstring(
            typed.model(self.env, View)
            .browse(self.view_id)
            .with_context(lang=None)
            .get_combined_arch()
            .encode()
        )

    def _page(self):
        return self._combined().xpath("//div[contains(@class, 'page')]")[0]

    def _printed(self) -> list[str]:
        """Every ``t-field`` in the page, in document order."""
        return [n.get("t-field") for n in self._page().iter() if n.get("t-field")]

    def _page_children(self) -> list[str]:
        """What the page holds, one word per child, in order."""
        out = []
        for child in self._page():
            if not isinstance(child.tag, str):
                continue
            if child.tag == "table":
                out.append("table:%s" % len(child.findall(".//th")))
                continue
            field = child.get("t-field") or next(
                (n.get("t-field") for n in child.iter() if n.get("t-field")), None
            )
            out.append(field or child.tag)
        return out

    def _remove(self, xpath: str):
        return self._apply({"type": "remove_node", "xpath": xpath})

    def _entries(self):
        return self.history.history_for(self.view_id)


@tagged("post_install", "-at_install")
class TestReportReAdd(ReportSequenceCase):
    def test_a_removed_value_can_be_placed_back(self):
        """Place, something else, remove, place again. The spec still holds
        the first span; the re-add has to read the tree, not the spec.

        The edit in between is elsewhere, so the removal cannot simply take
        the insertion back and has to be a ``replace``."""
        self._place("x_budget")
        self._place(
            "x_name", xpath="//span[@t-field='doc.display_name']", position="after"
        )
        self._remove("//span[@t-field='doc.x_budget']")
        self.assertNotIn("doc.x_budget", self._printed())
        result = self._place("x_budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertIn("doc.x_budget", result["combined_arch"])
        self.assertEqual(len(self._entries()), 4)

    def test_a_removed_labelled_value_can_be_placed_back(self):
        """A labelled value is a unit, removed by the locator the console
        mints for it -- the div holding the span."""
        self._place("x_budget", label="Budget")
        self._place("x_name")
        self._remove("//div[span[@t-field='doc.x_budget']]")
        self.assertNotIn("doc.x_budget", self._printed())
        self._place("x_budget", label="Budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertEqual(
            [s.text for s in self._page().iter("strong")].count("Budget"), 1
        )

    def test_a_value_removed_right_after_it_was_placed_comes_back(self):
        """The removal took the insertion back; the re-add is a plain add."""
        self._place("x_budget")
        self._remove("//span[@t-field='doc.x_budget']")
        self._place("x_budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)

    def test_values_placed_in_turn_print_in_that_order(self):
        """A second value at the same anchor is a new spec, after whatever
        came in between -- not folded into the first block, ahead of it."""
        self._place("x_budget")
        self._table(["name"])
        self._place("x_name")
        self.assertEqual(
            self._page_children(),
            ["h2", "doc.display_name", "doc.x_budget", "table:1", "doc.x_name"],
        )

    def test_the_same_value_twice_is_printed_once(self):
        self._place("x_budget")
        self._place("x_budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertEqual(len(self._entries()), 1)

    def test_a_value_already_where_it_would_go_creates_no_patch(self):
        """The scaffold prints the display name as the page's last line."""
        self._apply(
            {
                "type": "add_report_field",
                "xpath": "//div[span[@t-field='doc.display_name']]",
                "position": "inside",
                "model": "x_builder_project",
                "name": "display_name",
            }
        )
        self.assertFalse(self.editor._find_extension(self.view, self.package))
        self.assertEqual(self._entries(), [])

    def test_the_same_value_with_another_label_is_refused(self):
        """Already there, so inserting would print it twice and dropping
        the request would claim a label that was not set."""
        self._place("x_budget", label="Budget")
        with raises(self, UserError):
            self._place("x_budget", label="Cost")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)

    def test_a_value_may_be_printed_in_two_places(self):
        """Beside the display name and again at the end of the page: two
        places, two values. Only the same place twice is a replay."""
        self._place("x_budget")
        self._place(
            "x_budget",
            xpath="//span[@t-field='doc.display_name']",
            position="after",
        )
        self.assertEqual(self._printed().count("doc.x_budget"), 2)

    def test_a_value_is_placed_before_its_anchor(self):
        self._place("x_budget")
        self._place(
            "x_name", xpath="//span[@t-field='doc.x_budget']", position="before"
        )
        self._place(
            "x_name", xpath="//span[@t-field='doc.x_budget']", position="before"
        )
        printed = self._printed()
        self.assertEqual(printed.count("doc.x_name"), 1)
        self.assertEqual(printed.index("doc.x_name") + 1, printed.index("doc.x_budget"))

    def test_a_replace_or_attributes_position_is_refused(self):
        """A value goes before, after or inside something; ``replace`` would
        delete the anchor and ``attributes`` is not a place at all."""
        for position in ("replace", "attributes"):
            with raises(self, UserError):
                self._place("x_budget", position=position)
        self.assertFalse(self.editor._find_extension(self.view, self.package))

    def test_a_locator_that_finds_nothing_is_refused(self):
        with raises(self, UserError):
            self._place("x_budget", xpath="//span[@t-field='doc.nope']")
        self.assertFalse(self.editor._find_extension(self.view, self.package))


@tagged("post_install", "-at_install")
class TestReportGenericOps(ReportSequenceCase):
    """Remove, move and attributes are the view editor's own operations; on
    a report they have to reach the value that stands there *now*."""

    def _readded(self, **attrs):
        self._place("x_budget")
        if attrs:
            self._apply(
                {
                    "type": "set_attributes",
                    "xpath": "//span[@t-field='doc.x_budget']",
                    "attrs": attrs,
                }
            )
        self._place(
            "x_name", xpath="//span[@t-field='doc.display_name']", position="after"
        )
        self._remove("//span[@t-field='doc.x_budget']")
        self._place("x_budget")

    def test_attributes_reach_a_value_that_was_removed_and_put_back(self):
        """The first value had attributes of its own; they went with it, and
        the new block reaches the value that stands there now."""
        self._readded(**{"class": "fw-bold"})
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//span[@t-field='doc.x_budget']",
                "attrs": {"class": "text-end"},
            }
        )
        spans = self._page().xpath(".//span[@t-field='doc.x_budget']")
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].get("class"), "text-end")

    def test_a_value_put_back_can_be_moved(self):
        self._readded()
        self._apply(
            {
                "type": "move_node",
                "xpath": "//span[@t-field='doc.x_budget']",
                "target_xpath": "//h2",
                "position": "before",
            }
        )
        self.assertEqual(self._page_children()[0], "doc.x_budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)

    def test_a_value_put_back_can_be_removed_again(self):
        self._readded()
        self._remove("//span[@t-field='doc.x_budget']")
        self.assertNotIn("doc.x_budget", self._printed())
        self.assertIn("doc.x_name", self._printed())


@tagged("post_install", "-at_install")
class TestReportTableSequence(ReportSequenceCase):
    def test_the_same_table_twice_is_one_table(self):
        self._table(["name", "email"])
        self._table(["name", "email"])
        self.assertEqual(len(self._page().findall(".//table")), 1)
        self.assertEqual(len(self._entries()), 1)

    def test_a_removed_table_can_be_placed_back(self):
        self._table(["name"])
        self._place("x_name")
        self._remove("//table[.//tr[@t-foreach='doc.x_line_ids']]")
        self.assertEqual(self._page().findall(".//table"), [])
        self._table(["name"])
        self.assertEqual(len(self._page().findall(".//table")), 1)

    def test_the_same_list_with_other_columns_is_refused(self):
        self._table(["name"])
        with raises(self, UserError):
            self._table(["name", "email"])
        self.assertEqual(len(self._page().findall(".//table")), 1)


@tagged("post_install", "-at_install")
class TestReportOwnedSequence(ReportSequenceCase):
    """The report belongs to the package editing it: each edit is merged
    into the template itself."""

    foreign = False

    def _arch(self) -> str:
        self.view.invalidate_recordset()
        return cast("str", self.view.arch)

    def test_the_same_value_twice_is_printed_once(self):
        self._place("x_budget")
        self._place("x_budget")
        self.assertEqual(self._arch().count('t-field="doc.x_budget"'), 1)
        self.assertEqual(len(self._entries()), 1)

    def test_a_value_may_be_printed_in_two_places(self):
        """It used to be refused anywhere once it was printed somewhere."""
        self._place("x_budget")
        self._place(
            "x_budget",
            xpath="//span[@t-field='doc.display_name']",
            position="after",
        )
        self.assertEqual(self._arch().count('t-field="doc.x_budget"'), 2)

    def test_a_removed_value_can_be_placed_back(self):
        self._place("x_budget")
        self._remove("//span[@t-field='doc.x_budget']")
        self.assertNotIn("doc.x_budget", self._arch())
        self._place("x_budget")
        self.assertEqual(self._arch().count('t-field="doc.x_budget"'), 1)

    def test_the_same_table_twice_is_one_table(self):
        self._table(["name"])
        self._table(["name"])
        self.assertEqual(self._arch().count("<table"), 1)

    def test_the_display_name_already_on_the_page_is_not_added_again(self):
        self._apply(
            {
                "type": "add_report_field",
                "xpath": "//div[span[@t-field='doc.display_name']]",
                "position": "inside",
                "model": "x_builder_project",
                "name": "display_name",
            }
        )
        self.assertEqual(self._arch().count('t-field="doc.display_name"'), 1)
        self.assertEqual(self._entries(), [])


@tagged("post_install", "-at_install")
class TestReportGuards(ReportSequenceCase):
    """What every edit of a view is held to, held for a report template."""

    def _freeze(self):
        self.package.root_path = self.unwritable_path()
        self.package.invalidate_recordset()
        self.assertFalse(self.package.writable, "fixture")

    def _entry(self, index: int = 0) -> BuilderViewEdit:
        return self.history.browse(self._entries()[index]["id"])

    def test_an_edit_on_a_read_only_package_is_refused_and_leaves_nothing(self):
        self._freeze()
        for operation in (
            {
                "type": "add_report_field",
                "xpath": PAGE,
                "position": "inside",
                "model": "x_builder_project",
                "name": "x_budget",
            },
            {
                "type": "add_report_table",
                "xpath": PAGE,
                "position": "inside",
                "model": "x_builder_project",
                "name": "x_line_ids",
                "columns": ["name"],
            },
            {"type": "remove_node", "xpath": "//span[@t-field='doc.display_name']"},
        ):
            with raises(self, UserError):
                self._apply(cast("dict[str, object]", operation))
        self.assertFalse(self.editor._find_extension(self.view, self.package))
        self.assertEqual(self._entries(), [])

    def test_undo_and_redo_on_a_read_only_package_are_refused(self):
        self._place("x_budget")
        entry = self._entry()
        self._freeze()
        with raises(self, UserError):
            entry.action_undo()
        self.assertFalse(entry.undone)
        self.assertIn("doc.x_budget", self._printed())

    def test_undo_then_redo_puts_a_value_back(self):
        """The edit that created the patch: undo removes it, redo makes it
        again -- under the same key, so the source does not churn."""
        self._place("x_budget")
        extension = self.editor._find_extension(self.view, self.package)
        key = extension.key
        entry = self._entry()
        entry.action_undo()
        self.assertNotIn("doc.x_budget", self._printed())
        self.assertFalse(self.editor._find_extension(self.view, self.package))
        entry.action_redo()
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertEqual(self.editor._find_extension(self.view, self.package).key, key)

    def test_undo_refuses_to_discard_a_change_made_outside_the_builder(self):
        self._place("x_budget")
        self._place("x_name")
        extension = self.editor._find_extension(self.view, self.package)
        tampered = cast("str", extension.arch).replace("doc.x_name", "doc.x_stage")
        extension.with_context(lang=None).write({"arch": tampered})
        with raises(self, UserError):
            self._entry().action_undo()
        self.assertIn("doc.x_stage", self._printed())

    def test_redo_refuses_to_discard_a_change_made_outside_the_builder(self):
        self._place("x_budget")
        self._place("x_name")
        latest = self._entry()
        latest.action_undo()
        extension = self.editor._find_extension(self.view, self.package)
        tampered = cast("str", extension.arch).replace("doc.x_budget", "doc.x_stage")
        extension.with_context(lang=None).write({"arch": tampered})
        with raises(self, UserError):
            latest.action_redo()
        self.assertTrue(latest.undone)

    def test_a_stale_version_is_refused(self):
        version = self.editor.arch_version(self.view_id)
        self._place("x_budget")
        with raises(self, UserError):
            self.editor.apply_operation(
                self.view_id,
                self.package_id,
                {
                    "type": "add_report_field",
                    "xpath": PAGE,
                    "position": "inside",
                    "model": "x_builder_project",
                    "name": "x_name",
                },
                expected_arch_version=version,
            )
        self.assertNotIn("doc.x_name", self._printed())

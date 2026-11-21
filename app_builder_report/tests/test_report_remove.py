# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Taking a value out of a report, with what belongs to it.

The canvas used to have no Remove at all: a value could be taken out only by
a raw ``remove_node`` or by Undo. And a raw ``remove_node`` on the span of a
labelled value took the span and left its ``<strong>`` printing a label for
nothing. ``remove_report_element`` removes a unit -- the value, the value and
its label, a builder table's column with its header, the table -- read off the
tree the spec applies to, so a value removed can be placed back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.builder_report_ops import (
    BuilderViewEditor as ReportOps,
)

from ..models.builder_report_preview import BuilderReportPreview
from .test_report_sequence import ReportSequenceCase

if TYPE_CHECKING:
    from ..models.builder_report_preview import _LocateExpressionFoundJSON

BUDGET = "//span[@t-field='doc.x_budget']"
EMAIL = "//span[@t-field='line.email']"
NAME = "//span[@t-field='line.name']"
SLOT = "//div[hasclass('o_slot')]"


class ReportRemoveCase(ReportSequenceCase):
    def _take_out(self, xpath: str, unit: str = "value", **extra):
        operation: dict[str, object] = {
            "type": "remove_report_element",
            "xpath": xpath,
            "unit": unit,
        }
        return self.editor.apply_operation(
            self.view_id, self.package_id, operation, **extra
        )

    def _labels(self) -> list[str]:
        return [cast("str", s.text) for s in self._page().iter("strong")]

    def _headers(self) -> list[str]:
        return [cast("str", th.text) for th in self._page().iter("th")]

    def _cells(self) -> list[str]:
        """The ``t-field`` of each body cell of the builder table, in order."""
        return [
            cast("str", span.get("t-field"))
            for span in self._page().iter("span")
            if cast("str", span.get("t-field") or "").startswith("line.")
        ]

    def _nest_in_outer_table(self) -> None:
        """Give the page a hand-written table, header row and all, with a
        slot in its first cell for a builder table to go in."""
        tree = etree.fromstring(cast("str", self.view.arch).encode())
        page = tree.xpath("//div[contains(@class, 'page')]")[0]
        page.append(
            etree.fromstring(
                "<table class='o_outer'><thead><tr><th>Outer</th><th>Side</th>"
                "</tr></thead><tbody><tr><td><div class='o_slot'/></td>"
                "<td>side</td></tr></tbody></table>"
            )
        )
        self.view.write({"arch": etree.tostring(tree, encoding="unicode")})
        self.view.invalidate_recordset()

    def _outer(self):
        found = self._page().xpath("//table[hasclass('o_outer')]")
        return found[0] if found else None

    def _removals(self, expression: str) -> list[str]:
        found = typed.model(self.env, BuilderReportPreview).locate_expression(
            self.view_id, expression
        )
        self.assertTrue(found["found"])
        return list(cast("_LocateExpressionFoundJSON", found)["removals"])


@tagged("post_install", "-at_install")
class TestReportRemove(ReportRemoveCase):
    """A report another package made: each removal is a spec appended to
    this package's extension of it."""

    def test_a_removed_value_can_be_placed_back(self):
        self._place("x_budget")
        self._place(
            "x_name", xpath="//span[@t-field='doc.display_name']", position="after"
        )
        self._take_out(BUDGET)
        self.assertNotIn("doc.x_budget", self._printed())
        self.assertIn("doc.x_name", self._printed())
        self._place("x_budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertEqual(len(self._entries()), 4)

    def test_a_labelled_value_goes_with_its_label(self):
        """Removed by its value -- what the console has selected -- and the
        label goes too: the whole unit, no orphan ``<strong>``."""
        self._place("x_budget", label="Budget")
        self._place("x_name")
        self._take_out(BUDGET, "labelled")
        self.assertNotIn("doc.x_budget", self._printed())
        self.assertNotIn("Budget", self._labels())
        self._place("x_budget", label="Budget")
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertEqual(self._labels().count("Budget"), 1)

    def test_a_raw_remove_of_a_labelled_value_takes_the_label(self):
        """The known gap: ``remove_node`` on the span alone left the
        label printed beside nothing."""
        self._place("x_budget", label="Budget")
        self._place("x_name")
        self._remove(BUDGET)
        self.assertNotIn("doc.x_budget", self._printed())
        self.assertNotIn("Budget", self._labels())
        self.assertIn("doc.x_name", self._printed())

    def test_a_value_removed_right_after_it_was_placed_is_taken_back(self):
        """The last spec placed the unit: it is taken out of that spec,
        not replaced by a second one."""
        self._place("x_budget", label="Budget")
        self._take_out(BUDGET)
        extension = self.editor._find_extension(self.view, self.package)
        self.assertNotIn('position="replace"', cast("str", extension.arch))
        self.assertNotIn("Budget", self._labels())
        self._place("x_budget", label="Budget")
        self.assertEqual(self._labels().count("Budget"), 1)

    def test_a_column_goes_with_its_header(self):
        self._table(["name", "email"])
        self._place("x_name")
        self._take_out(EMAIL, "column")
        self.assertEqual(len(self._page().findall(".//table")), 1)
        self.assertNotIn("line.email", self._printed())
        self.assertIn("line.name", self._printed())
        name = self.env["res.partner"]._fields["name"].string
        self.assertEqual(self._headers(), [name])
        # What is left is still a table the builder made, of one column.
        editor = typed.model(self.env, ReportOps)
        table = self._page().find(".//table")
        self.assertEqual(editor._tabled_columns(table, "doc.x_line_ids"), ["name"])

    def test_the_first_column_can_go(self):
        self._table(["name", "email"])
        self._place("x_name")
        self._take_out(NAME, "column")
        email = self.env["res.partner"]._fields["email"].string
        self.assertEqual(self._headers(), [email])
        self.assertEqual(
            [p for p in self._printed() if p.startswith("line.")], ["line.email"]
        )

    def test_a_middle_column_goes_with_its_header(self):
        """Header and body cell are located on both sides of the gap."""
        self._table(["name", "email", "phone"])
        self._place("x_name")
        self._take_out(EMAIL, "column")
        fields = self.env["res.partner"]._fields
        self.assertEqual(
            self._headers(), [fields["name"].string, fields["phone"].string]
        )
        self.assertEqual(self._cells(), ["line.name", "line.phone"])

    def test_a_column_of_a_nested_table_leaves_the_outer_table(self):
        """The table nearest the value, not every table wrapping it: core
        takes the first match, which would be the outer one."""
        self._nest_in_outer_table()
        self._table(["name", "email"], xpath=SLOT)
        self._take_out(EMAIL, "column")
        self.assertIsNotNone(self._outer())
        self.assertEqual(
            [
                th.text
                for th in self._page().xpath("//table[hasclass('o_outer')]/thead/tr/th")
            ],
            ["Outer", "Side"],
        )
        name = self.env["res.partner"]._fields["name"].string
        self.assertEqual(self._headers(), ["Outer", "Side", name])
        self.assertEqual(self._cells(), ["line.name"])

    def test_a_nested_table_goes_and_the_outer_one_stays(self):
        self._nest_in_outer_table()
        self._table(["name", "email"], xpath=SLOT)
        self._take_out(EMAIL, "table")
        self.assertIsNotNone(self._outer())
        self.assertEqual(len(self._page().findall(".//table")), 1)
        self.assertEqual(self._cells(), [])
        self.assertEqual(self._page().xpath(SLOT)[0].findall("table"), [])

    def test_the_last_column_of_a_nested_table_leaves_the_outer_table(self):
        self._nest_in_outer_table()
        self._table(["name"], xpath=SLOT)
        self._take_out(NAME, "column")
        self.assertIsNotNone(self._outer())
        self.assertEqual(len(self._page().findall(".//table")), 1)

    def test_the_last_column_takes_the_table(self):
        self._table(["name"])
        self._place("x_name")
        self._take_out(NAME, "column")
        self.assertEqual(self._page().findall(".//table"), [])
        self._table(["name"])
        self.assertEqual(len(self._page().findall(".//table")), 1)

    def test_a_table_is_removed_by_one_of_its_values(self):
        self._table(["name", "email"])
        self._place("x_name")
        self._take_out(EMAIL, "table")
        self.assertEqual(self._page().findall(".//table"), [])
        self.assertIn("doc.x_name", self._printed())
        self._table(["name", "email"])
        self.assertEqual(len(self._page().findall(".//table")), 1)

    def test_what_can_be_removed_is_offered_with_the_selection(self):
        self._place("x_budget", label="Budget")
        self._place("x_name")
        self._table(["name", "email"])
        self.assertEqual(self._removals("doc.x_budget"), ["labelled"])
        self.assertEqual(self._removals("doc.x_name"), ["value"])
        self.assertEqual(self._removals("line.email"), ["column", "table"])

    def test_a_tables_last_column_is_offered_as_the_table(self):
        """Removing it removes the table, so that is what it is called."""
        self._table(["name"])
        self.assertEqual(self._removals("line.name"), ["table"])

    def test_a_hand_written_table_offers_no_column(self):
        """Its columns are whatever its ``t-if``s and ``colspan``s make
        them; the table, or the value alone, can still go."""
        editor = typed.model(self.env, ReportOps)
        table = etree.fromstring(
            "<table><tbody><tr t-foreach='doc.x_line_ids' t-as='l'>"
            "<td colspan='2'><span t-field='l.name'/></td>"
            "</tr></tbody></table>"
        )
        span = table.find(".//span")
        self.assertEqual(editor._report_removals(span), ["value", "table"])
        self.assertIsNone(editor._builder_column(span))

    def test_a_column_of_a_value_outside_a_table_is_refused(self):
        self._place("x_budget")
        with raises(self, UserError):
            self._take_out(BUDGET, "column")
        with raises(self, UserError):
            self._take_out(BUDGET, "table")
        with raises(self, UserError):
            self._take_out(BUDGET, "everything")
        self.assertIn("doc.x_budget", self._printed())

    def test_a_stale_version_is_refused(self):
        self._place("x_budget")
        version = self.editor.arch_version(self.view_id)
        self._place("x_name")
        with raises(self, UserError):
            self._take_out(BUDGET, expected_arch_version=version)
        self.assertIn("doc.x_budget", self._printed())
        current = self.editor.arch_version(self.view_id)
        self._take_out(BUDGET, expected_arch_version=current)
        self.assertNotIn("doc.x_budget", self._printed())

    def test_a_replayed_removal_changes_nothing(self):
        self._place("x_budget")
        self._place("x_name")
        self._take_out(BUDGET)
        count = len(self._entries())
        self._take_out(BUDGET)
        self.assertEqual(len(self._entries()), count)

    def test_undo_puts_the_value_and_its_label_back(self):
        self._place("x_budget", label="Budget")
        self._place("x_name")
        self._take_out(BUDGET)
        entry = self.history.browse(self._entries()[0]["id"])
        self.assertIn("doc.x_budget", cast("str", entry.summary))
        entry.action_undo()
        self.assertEqual(self._printed().count("doc.x_budget"), 1)
        self.assertEqual(self._labels().count("Budget"), 1)
        entry.action_redo()
        self.assertNotIn("doc.x_budget", self._printed())
        self.assertNotIn("Budget", self._labels())

    def test_a_read_only_package_removes_nothing(self):
        self._place("x_budget")
        self.package.root_path = self.unwritable_path()
        self.package.invalidate_recordset()
        with raises(self, UserError):
            self._take_out(BUDGET)
        self.assertIn("doc.x_budget", self._printed())


@tagged("post_install", "-at_install")
class TestReportRemoveOwned(ReportRemoveCase):
    """The report belongs to the package editing it: each removal is merged
    into the template itself."""

    foreign = False

    def _arch(self) -> str:
        self.view.invalidate_recordset()
        return cast("str", self.view.arch)

    def test_a_labelled_value_goes_with_its_label_and_comes_back(self):
        self._place("x_budget", label="Budget")
        self._place("x_name")
        self._take_out(BUDGET)
        self.assertNotIn("doc.x_budget", self._arch())
        self.assertNotIn("<strong>Budget</strong>", self._arch())
        self._place("x_budget", label="Budget")
        self.assertEqual(self._arch().count('t-field="doc.x_budget"'), 1)
        self.assertEqual(self._arch().count("<strong>Budget</strong>"), 1)

    def test_a_raw_remove_of_a_labelled_value_takes_the_label(self):
        self._place("x_budget", label="Budget")
        self._remove(BUDGET)
        self.assertNotIn("doc.x_budget", self._arch())
        self.assertNotIn("Budget", self._arch())

    def test_a_column_goes_with_its_header(self):
        self._table(["name", "email"])
        self._take_out(EMAIL, "column")
        self.assertEqual(self._arch().count("<th>"), 1)
        self.assertNotIn("line.email", self._arch())
        self.assertIn("line.name", self._arch())

    def test_a_middle_column_goes_with_its_header(self):
        self._table(["name", "email", "phone"])
        self._take_out(EMAIL, "column")
        fields = self.env["res.partner"]._fields
        self.assertEqual(
            self._headers(), [fields["name"].string, fields["phone"].string]
        )
        self.assertEqual(self._cells(), ["line.name", "line.phone"])

    def test_a_column_of_a_nested_table_leaves_the_outer_table(self):
        self._nest_in_outer_table()
        self._table(["name", "email"], xpath=SLOT)
        self._take_out(EMAIL, "column")
        name = self.env["res.partner"]._fields["name"].string
        self.assertEqual(self._headers(), ["Outer", "Side", name])
        self.assertEqual(self._cells(), ["line.name"])

    def test_a_nested_table_goes_and_the_outer_one_stays(self):
        self._nest_in_outer_table()
        self._table(["name", "email"], xpath=SLOT)
        self._take_out(NAME, "table")
        self.assertIsNotNone(self._outer())
        self.assertEqual(self._arch().count("<table"), 1)
        self.assertEqual(self._cells(), [])

    def test_undo_puts_a_removed_table_back(self):
        self._table(["name", "email"])
        self._take_out(NAME, "table")
        self.assertNotIn("<table", self._arch())
        self.history.browse(self._entries()[0]["id"]).action_undo()
        self.assertEqual(self._arch().count("<table"), 1)
        self.assertEqual(self._arch().count("<th>"), 2)

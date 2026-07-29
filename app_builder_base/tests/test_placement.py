# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Placement: a field the builder adds has to end up somewhere visible."""

from lxml import etree

from odoo.tests.common import TransactionCase

from ..tools import placement


def _arch(source):
    return etree.fromstring(source)


FORM = """
<form>
  <sheet>
    <div class="oe_title"><h1><field name="name"/></h1></div>
    <group>
      <group><field name="user_id"/></group>
      <group/>
    </group>
  </sheet>
  <chatter/>
</form>
"""


class TestFormPlacement(TransactionCase):
    def test_a_scalar_lands_in_the_emptier_column(self):
        root = _arch(FORM)
        self.assertTrue(placement.place_in_form(root, "date", "date", "Date"))
        columns = root.findall(".//sheet/group/group")
        self.assertEqual(
            [f.get("name") for f in columns[1].findall("field")],
            ["date"],
            "the second column was empty, so that is where it belongs",
        )

    def test_columns_stay_balanced(self):
        root = _arch(FORM)
        for name in ("a", "b", "c"):
            placement.place_in_form(root, name, "char", name)
        left, right = root.findall(".//sheet/group/group")
        self.assertEqual(
            [f.get("name") for f in left.findall("field")], ["user_id", "b"]
        )
        self.assertEqual([f.get("name") for f in right.findall("field")], ["a", "c"])

    def test_a_related_list_gets_its_own_page(self):
        root = _arch(FORM)
        placement.place_in_form(root, "line_ids", "one2many", "Lines")
        page = root.find(".//sheet/notebook/page")
        self.assertEqual(page.get("string"), "Lines")
        self.assertEqual(page.find("field").get("name"), "line_ids")
        self.assertIsNone(
            root.find(".//sheet/group/group/field[@name='line_ids']"),
            "a one2many in a two-column group is unreadable",
        )

    def test_placing_twice_is_a_no_op(self):
        root = _arch(FORM)
        self.assertTrue(placement.place_in_form(root, "date", "date", "Date"))
        self.assertFalse(placement.place_in_form(root, "date", "date", "Date"))
        self.assertEqual(len(root.xpath(".//field[@name='date']")), 1)

    def test_a_group_created_late_stays_above_the_notebook(self):
        root = _arch(
            "<form><sheet><notebook><page string='Notes'/></notebook></sheet></form>"
        )
        placement.place_in_form(root, "date", "date", "Date")
        children = [child.tag for child in root.find("sheet")]
        self.assertEqual(children, ["group", "notebook"])


class TestListAndSearchPlacement(TransactionCase):
    def test_the_status_badge_stays_last(self):
        root = _arch(
            '<list><field name="name"/><field name="state" widget="badge"/></list>'
        )
        placement.place_in_list(root, "date")
        self.assertEqual(
            [f.get("name") for f in root.findall("field")],
            ["name", "date", "state"],
        )

    def test_a_search_field_goes_after_the_other_fields(self):
        root = _arch(
            '<search><field name="name"/><filter name="mine" domain="[]"/></search>'
        )
        placement.place_in_search(root, "user_id")
        self.assertEqual(
            [child.get("name") for child in root],
            ["name", "user_id", "mine"],
            "a field after a filter reads as a filter",
        )

    def test_group_by_creates_the_group_it_needs(self):
        root = _arch('<search><field name="name"/></search>')
        placement.place_group_by(root, "user_id", "Owner")
        node = root.find("./group/filter")
        self.assertEqual(node.get("context"), "{'group_by': 'user_id'}")
        self.assertEqual(node.get("name"), "group_by_user_id")


class TestRemoval(TransactionCase):
    """A <field> naming a dropped column fails view validation, which fails the
    reload, which rolls the whole apply back. Removal is not cosmetic."""

    def test_a_removed_field_leaves_no_node_behind(self):
        root = _arch(FORM)
        self.assertTrue(placement.remove_field(root, "user_id"))
        self.assertEqual(root.xpath(".//field[@name='user_id']"), [])

    def test_an_emptied_page_and_notebook_go_too(self):
        root = _arch(
            "<form><sheet><notebook><page string='Lines'>"
            '<field name="line_ids"/></page></notebook></sheet></form>'
        )
        placement.remove_field(root, "line_ids")
        self.assertIsNone(root.find(".//page"), "a tab onto nothing")
        self.assertIsNone(root.find(".//notebook"), "and an empty tab strip")

    def test_a_group_by_naming_the_dropped_field_goes_too(self):
        root = _arch(
            '<search><field name="user_id"/><group>'
            "<filter name=\"group_by_user_id\" context=\"{'group_by': 'user_id'}\"/>"
            "</group></search>"
        )
        placement.remove_field(root, "user_id")
        self.assertEqual(root.xpath(".//filter"), [])

    def test_removing_something_absent_changes_nothing(self):
        root = _arch(FORM)
        self.assertFalse(placement.remove_field(root, "nope"))

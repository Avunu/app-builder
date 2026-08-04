# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Placement: a field the builder adds has to end up somewhere visible."""

from lxml import etree

from odoo.tests import BaseCase, tagged
from odoo.tests.common import TransactionCase

from ..tools import modelspec, placement, scaffold


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


@tagged("standard", "at_install")
class TestFeatureRegistry(BaseCase):
    """Features were nine booleans and a chain of ifs.

    Fine while they were independent, which they are not: Monetary value is
    meaningless without a currency, Date & Calendar means a field *and* a view.
    Each of those is a sentence about how two features interact, and a boolean
    has nowhere to write one down.
    """

    def test_defaults_match_the_old_hand_written_ones(self):
        options = scaffold.ScaffoldOptions()
        for key in ("chatter", "activities", "ordering", "active", "description"):
            self.assertTrue(getattr(options, key), key)
        for key in ("reference", "stage", "user", "date", "contact", "monetary"):
            self.assertFalse(getattr(options, key), key)

    def test_a_feature_arrives_with_what_it_implies(self):
        options = scaffold.ScaffoldOptions.from_keys(["chatter"])
        self.assertTrue(
            options.activities, "a chatter with no activities is half of one"
        )

    def test_from_keys_takes_nothing_it_was_not_given(self):
        options = scaffold.ScaffoldOptions.from_keys(["stage"])
        self.assertTrue(options.stage)
        self.assertFalse(options.chatter)

    def test_an_unknown_feature_is_refused(self):
        with self.assertRaises(ValueError):
            scaffold.ScaffoldOptions(nonsense=True)

    def test_a_feature_can_ask_for_a_view(self):
        self.assertIn(
            "calendar", scaffold.ScaffoldOptions.from_keys(["date"]).view_types
        )
        self.assertIn(
            "kanban", scaffold.ScaffoldOptions.from_keys(["stage"]).view_types
        )

    def test_monetary_brings_its_currency(self):
        """fields.Monetary raises without one, so this is not tidiness."""
        spec = scaffold.scaffold_spec(
            "probe.model", "Probe", scaffold.ScaffoldOptions.from_keys(["monetary"])
        )
        names = [f.name for f in spec.fields]
        self.assertIn("currency_id", names)
        self.assertLess(
            names.index("currency_id"),
            names.index("amount"),
            "the currency has to be defined before the amount that names it",
        )
        self.assertEqual(spec.field("amount").currency_field, "currency_id")

    def test_contact_details_are_related_not_copied(self):
        """An address that goes stale when the contact is corrected is worse
        than no address."""
        spec = scaffold.scaffold_spec(
            "probe.model", "Probe", scaffold.ScaffoldOptions.from_keys(["contact"])
        )
        self.assertEqual(spec.field("partner_email").related, "partner_id.email")

    def test_a_pipeline_gets_more_than_a_status_field(self):
        spec = scaffold.scaffold_spec(
            "probe.model", "Probe", scaffold.ScaffoldOptions.from_keys(["stage"])
        )
        names = {f.name for f in spec.fields}
        self.assertIn("state", names)
        self.assertIn("priority", names)
        self.assertIn("kanban_state", names)
        self.assertIn("color", names)

    def test_responsible_is_limited_to_internal_users(self):
        spec = scaffold.scaffold_spec(
            "probe.model", "Probe", scaffold.ScaffoldOptions.from_keys(["user"])
        )
        self.assertIn("share", spec.field("user_id").domain or "")

    def test_every_scaffolded_spec_validates(self):
        """Each feature alone, and all of them together."""
        keys = list(scaffold.WIZARD_FEATURES)
        for subset in ([k] for k in keys):
            options = scaffold.ScaffoldOptions.from_keys(subset)
            spec = scaffold.scaffold_spec("probe.model", "Probe", options)
            self.assertFalse(
                modelspec.validate_spec(spec), "%s alone: %s" % (subset, spec)
            )
        everything = scaffold.ScaffoldOptions.from_keys(keys)
        spec = scaffold.scaffold_spec("probe.model", "Probe", everything)
        self.assertFalse(modelspec.validate_spec(spec))

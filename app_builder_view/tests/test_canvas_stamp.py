# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Naming the nodes of a view, on a string, with no database in sight.

The stamp is what lets a rendered element point back at a node of the
definition, so what matters is that it is *stable* -- the same arch always
names its nodes the same way -- and that it names exactly the nodes an edit
may touch: nothing under a field, nothing that has no DOM to carry a name.
"""

from __future__ import annotations

from typing import Any, cast

# lxml ships no type stubs in this environment, the same gap `test_xml_writer.py`
# and every Phase 1c model file already document -- `etree` itself is an
# unresolvable import symbol with no stub.
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.tests import TransactionCase, tagged

from odoo.addons.app_builder_view.tools import canvas_stamp

FORM = """
<form string="Demo" js_class="custom_form">
    <header>
        <button name="go" type="object" string="Go"/>
    </header>
    <sheet>
        <div name="button_box" class="oe_button_box">
            <button name="stats" type="object" class="oe_stat_button"/>
        </div>
        <group name="outer" class="mt-2">
            <group name="left">
                <field name="name"/>
                <field name="email" invisible="1"/>
            </group>
            <group name="right">
                <field name="child_ids">
                    <list>
                        <field name="name"/>
                        <field name="email"/>
                    </list>
                </field>
            </group>
        </group>
        <notebook>
            <page string="Notes" name="notes">
                <separator string="A rule"/>
                <field name="comment"/>
                <button name="plain" type="object" string="Plain"/>
            </page>
        </notebook>
    </sheet>
</form>
"""

KANBAN = """
<kanban>
    <field name="is_company"/>
    <templates>
        <t t-name="card" class="flex-row">
            <aside>
                <field name="avatar_128" class="w-100" widget="image"/>
            </aside>
            <main>
                <t t-if="record.is_company.raw_value">
                    <field name="name" class="fw-bold"/>
                </t>
                <div>
                    <field name="email"/>
                </div>
            </main>
        </t>
    </templates>
</kanban>
"""

LIST = """
<list editable="bottom" multi_edit="1">
    <field name="name"/>
    <field name="email" optional="hide"/>
</list>
"""

GROUPED_LIST = """
<list>
    <field name="name"/>
    <groupby name="partner_id">
        <field name="country_id"/>
        <button name="edit" type="edit" string="Edit"/>
    </groupby>
    <field name="email"/>
</list>
"""

LEGACY_KANBAN = """
<kanban>
    <templates>
        <t t-name="kanban-box">
            <div class="oe_kanban_card">
                <field name="name"/>
            </div>
        </t>
    </templates>
</kanban>
"""


def _by_name(result, name):
    return next(t for t, n in result.nodes.items() if n["name"] == name)


@tagged("post_install", "-at_install")
class TestCanvasStamp(TransactionCase):
    def _stamp(self, arch, view_type=None):
        root = etree.fromstring(arch)
        return root, canvas_stamp.stamp(root, view_type)

    # -- stability ---------------------------------------------------------

    def test_tokens_are_ordinals_in_document_order(self):
        """A token is a position in the walk and nothing else, so it can
        be recomputed from the arch by anybody."""
        _root, result = self._stamp(FORM, "form")
        tokens = list(result.nodes)
        self.assertEqual(result.root, "o_builder_n_0")
        self.assertEqual(
            tokens, ["o_builder_n_%d" % i for i in range(len(tokens))], tokens
        )
        self.assertEqual(
            [result.nodes[t]["tag"] for t in tokens[:6]],
            ["form", "header", "button", "sheet", "div", "button"],
        )

    def test_two_stampings_of_one_arch_agree(self):
        _root, first = self._stamp(FORM, "form")
        _root, second = self._stamp(FORM, "form")
        self.assertEqual(first.nodes, second.nodes)
        self.assertEqual(
            etree.tostring(first.arch), etree.tostring(second.arch), "byte-stable"
        )

    def test_the_original_tree_is_not_touched(self):
        root = etree.fromstring(FORM)
        before = etree.tostring(root)
        result = canvas_stamp.stamp(root, "form")
        self.assertEqual(etree.tostring(root), before)
        self.assertNotIn(b"o_builder_n_", before)
        self.assertIn(b"o_builder_n_", etree.tostring(result.arch))

    def test_elements_point_into_the_original_tree(self):
        """A token has to resolve to the very node the editor will edit,
        not to its copy."""
        root, result = self._stamp(FORM, "form")
        token = _by_name(result, "comment")
        element = result.elements[token]
        # `LxmlElement.getroottree()` (`lxml_types.py`) only declares
        # `getpath()`, the one method its other two readers need; `getroot()`
        # is real lxml but outside that narrow Protocol, and out of this
        # file's own scope to extend it.
        self.assertIs(cast("Any", element.getroottree()).getroot(), root)
        self.assertEqual(element.get("name"), "comment")
        self.assertIsNone(element.get("class"), "the original carries no token")

    # -- what is named -----------------------------------------------------

    def test_an_existing_class_is_kept(self):
        _root, result = self._stamp(FORM, "form")
        token = _by_name(result, "outer")
        stamped = result.arch.xpath("//group[@name='outer']")[0]
        self.assertEqual(stamped.get("class"), "mt-2 %s" % token)
        self.assertEqual(
            result.nodes[token]["attrs"]["class"], "mt-2", "attrs are the original"
        )

    def test_nothing_under_a_field_is_named_but_the_field_is(self):
        _root, result = self._stamp(FORM, "form")
        names = [n["name"] for n in result.nodes.values()]
        self.assertIn("child_ids", names)
        self.assertEqual(names.count("name"), 1, "the sublist's name column is not")
        self.assertEqual(names.count("email"), 1)
        sublist = result.arch.xpath("//field[@name='child_ids']/list")[0]
        self.assertIsNone(sublist.get("class"))
        for field in sublist:
            self.assertIsNone(field.get("class"))

    def test_a_groupby_is_a_leaf_like_a_field(self):
        """A list's <groupby> is a nested view of the comodel: its fields
        are not columns of the list, and a drop beside one would land in a
        group header, so nothing under it is addressable."""
        _root, result = self._stamp(GROUPED_LIST, "list")
        names = [n["name"] for n in result.nodes.values()]
        self.assertEqual(names, [None, "name", "partner_id", "email"])
        groupby = result.nodes[_by_name(result, "partner_id")]
        self.assertEqual(groupby["tag"], "groupby")
        self.assertFalse(groupby["container"])
        self.assertFalse(groupby["dom"])
        self.assertEqual(groupby["children"], [])
        self.assertIsNone(result.arch.xpath("//groupby/field")[0].get("class"))
        columns = result.nodes[result.root]["children"]
        self.assertEqual(
            [result.nodes[t]["name"] for t in columns], ["name", "partner_id", "email"]
        )

    def test_the_label_the_builder_emits_is_not_a_container(self):
        """`_op_add_label` writes `<div class="o_form_label">text</div>`; a
        field dropped "inside" it would be glued to the text."""
        arch = '<form><div class="o_form_label" name="hint">Hint</div></form>'
        _root, result = self._stamp(arch, "form")
        label = result.nodes[_by_name(result, "hint")]
        self.assertEqual(label["kind"], "label")
        self.assertFalse(label["container"])
        self.assertEqual(label["accepts"], [])
        self.assertEqual(label["string"], "Hint")

    def test_comments_are_skipped(self):
        _root, result = self._stamp("<form><!-- note --><sheet/></form>", "form")
        self.assertEqual([n["tag"] for n in result.nodes.values()], ["form", "sheet"])

    def test_the_root_is_kind_root(self):
        _root, result = self._stamp(FORM, "form")
        root = result.nodes[result.root]
        self.assertEqual(root["kind"], "root")
        self.assertEqual(root["tag"], "form")
        self.assertTrue(root["container"])
        self.assertFalse(root["movable"])
        self.assertIsNone(root["parent"])

    def test_kinds_by_tag(self):
        _root, result = self._stamp(FORM, "form")
        kinds = {(n["tag"], n["name"]): n["kind"] for n in result.nodes.values()}
        self.assertEqual(kinds[("div", "button_box")], "button_box")
        self.assertEqual(kinds[("field", "email")], "field")
        self.assertEqual(kinds[("page", "notes")], "page")
        self.assertEqual(kinds[("separator", None)], "separator")
        self.assertEqual(kinds[("notebook", None)], "notebook")
        self.assertEqual(kinds[("sheet", None)], "sheet")
        self.assertEqual(kinds[("header", None)], "header")

    def test_a_list_field_is_a_column(self):
        _root, result = self._stamp(LIST, "list")
        self.assertEqual(result.nodes[_by_name(result, "name")]["kind"], "column")

    def test_parent_children_and_index_describe_the_tree(self):
        _root, result = self._stamp(FORM, "form")
        left = _by_name(result, "left")
        name, email = _by_name(result, "name"), _by_name(result, "email")
        self.assertEqual(result.nodes[left]["children"], [name, email])
        self.assertEqual(result.nodes[name]["parent"], left)
        self.assertEqual(result.nodes[name]["index"], 0)
        self.assertEqual(result.nodes[email]["index"], 1)

    def test_a_group_holding_groups_is_a_row(self):
        _root, result = self._stamp(FORM, "form")
        self.assertEqual(result.nodes[_by_name(result, "outer")]["orientation"], "row")
        self.assertEqual(
            result.nodes[_by_name(result, "left")]["orientation"], "column"
        )

    def test_the_static_string_of_a_node_is_reported(self):
        _root, result = self._stamp(FORM, "form")
        self.assertEqual(result.nodes[_by_name(result, "notes")]["string"], "Notes")
        separator = next(n for n in result.nodes.values() if n["tag"] == "separator")
        self.assertEqual(separator["string"], "A rule")

    # -- where a field's label comes from --------------------------------------

    LABELS = """
    <form>
        <sheet>
            <group name="columns">
                <group name="left">
                    <field name="in_group"/>
                    <field name="switched_off" nolabel="1"/>
                    <field name="off_but_labelled" nolabel="1"/>
                </group>
                <field name="in_columns"/>
            </group>
            <label for="off_but_labelled"/>
            <label for="on_sheet" string="Named"/>
            <field name="on_sheet"/>
            <field name="bare"/>
            <notebook>
                <page string="Notes" name="notes">
                    <field name="in_page"/>
                </page>
            </notebook>
        </sheet>
    </form>
    """

    def test_a_field_in_an_inner_group_is_labelled_by_the_group(self):
        _root, result = self._stamp(self.LABELS, "form")
        label = result.nodes[_by_name(result, "in_group")]["label"]
        self.assertEqual(
            label, {"shown": True, "by": "group", "token": None, "in_group": True}
        )

    def test_nolabel_switches_the_group_label_off(self):
        _root, result = self._stamp(self.LABELS, "form")
        label = result.nodes[_by_name(result, "switched_off")]["label"]
        self.assertEqual(
            label, {"shown": False, "by": None, "token": None, "in_group": True}
        )

    def test_a_label_for_counts_wherever_it_stands(self):
        _root, result = self._stamp(self.LABELS, "form")
        label_tokens = {
            node["attrs"].get("for"): token
            for token, node in result.nodes.items()
            if node["tag"] == "label"
        }
        # A label is a node of its own -- not *named* for its field, or the
        # first node called `x` would be the label rather than the field --
        # but it is captioned for it.
        self.assertIn("off_but_labelled", label_tokens)
        self.assertIsNone(result.nodes[label_tokens["off_but_labelled"]]["name"])
        self.assertEqual(
            result.nodes[label_tokens["off_but_labelled"]]["string"], "off_but_labelled"
        )
        self.assertEqual(result.nodes[label_tokens["on_sheet"]]["string"], "Named")
        # `BuilderNode["label"]` is `FieldLabel | None`; only a `field` node
        # ever carries one, and both fields read here do (asserted above via
        # `label_tokens`), so the cast just names what the test already
        # relies on.
        off = cast(
            "canvas_stamp.FieldLabel",
            result.nodes[_by_name(result, "off_but_labelled")]["label"],
        )
        self.assertEqual(off["by"], "label")
        self.assertEqual(off["token"], label_tokens["off_but_labelled"])
        self.assertTrue(off["in_group"])
        on_sheet = cast(
            "canvas_stamp.FieldLabel",
            result.nodes[_by_name(result, "on_sheet")]["label"],
        )
        self.assertEqual(on_sheet["by"], "label")
        self.assertFalse(on_sheet["in_group"])

    def test_outside_a_group_a_field_has_no_label(self):
        _root, result = self._stamp(self.LABELS, "form")
        for name in ("in_columns", "bare", "in_page"):
            label = result.nodes[_by_name(result, name)]["label"]
            self.assertEqual(
                label,
                {"shown": False, "by": None, "token": None, "in_group": False},
                name,
            )

    def test_only_a_form_field_knows_its_label(self):
        _root, result = self._stamp(FORM, "form")
        for node in result.nodes.values():
            if node["tag"] != "field":
                self.assertIsNone(node["label"], node["tag"])
        _root, result = self._stamp(LIST, "list")
        for node in result.nodes.values():
            self.assertIsNone(node["label"])

    def test_nodes_never_carry_an_xpath(self):
        _root, result = self._stamp(FORM, "form")
        for node in result.nodes.values():
            self.assertNotIn("xpath", node)
            for value in node.values():
                if isinstance(value, str):
                    self.assertFalse(value.startswith("/"), value)

    # -- kanban ------------------------------------------------------------

    def test_the_card_template_carries_its_token(self):
        """The arch parser reads `class` off <t t-name="card"> and puts it on
        the rendered .o_kanban_record (kanban_arch_parser.js:161,
        kanban_record.js:281), so the card is stamped like any node --
        merged with the class it already has."""
        _root, result = self._stamp(KANBAN, "kanban")
        token, card = next(
            (t, n) for t, n in result.nodes.items() if n["kind"] == "card"
        )
        self.assertTrue(card["dom"])
        self.assertTrue(card["container"])
        self.assertTrue(card["selectable"])
        self.assertFalse(card["movable"])
        self.assertIn("main", card["accepts"])
        self.assertEqual(card["name"], "card")
        self.assertEqual(
            result.arch.xpath("//t[@t-name='card']")[0].get("class"),
            "flex-row %s" % token,
        )

    def test_the_legacy_kanban_box_is_listed_without_a_dom(self):
        """kanban_arch_parser.js:161 ignores the class of a kanban-box, so
        the token would go nowhere; the card is still a place to drop into,
        with its rectangle taken from the rendered record."""
        _root, result = self._stamp(LEGACY_KANBAN, "kanban")
        card = next(n for n in result.nodes.values() if n["kind"] == "card")
        self.assertFalse(card["dom"])
        self.assertTrue(card["container"])
        self.assertTrue(card["selectable"])
        self.assertIsNone(
            result.arch.xpath("//t[@t-name='kanban-box']")[0].get("class")
        )
        self.assertIn("o_builder_n_", result.arch.xpath("//div")[0].get("class"))

    def test_card_fields_are_stamped_directly(self):
        _root, result = self._stamp(KANBAN, "kanban")
        token = _by_name(result, "avatar_128")
        stamped = result.arch.xpath("//field[@name='avatar_128']")[0]
        self.assertEqual(stamped.get("class"), "w-100 %s" % token)
        # Through a <t t-if> wrapper, which is not itself a place.
        name = result.nodes[_by_name(result, "name")]
        self.assertEqual(
            result.nodes[cast("canvas_stamp.Token", name["parent"])]["tag"], "main"
        )
        self.assertEqual(
            [n["name"] for n in result.nodes.values() if n["tag"] == "t"],
            ["card"],
            "the card is the only <t> listed",
        )

    def test_a_field_declared_at_the_kanban_root_has_no_dom(self):
        _root, result = self._stamp(KANBAN, "kanban")
        declared = result.nodes[_by_name(result, "is_company")]
        self.assertFalse(declared["dom"])
        self.assertFalse(declared["movable"])
        self.assertIsNone(
            result.arch.xpath("//kanban/field[@name='is_company']")[0].get("class")
        )

    # -- what goes where ---------------------------------------------------

    def test_accepts_refuses_a_page_in_a_group_and_takes_one_in_a_notebook(self):
        self.assertFalse(canvas_stamp.accepts("group", "page"))
        self.assertTrue(canvas_stamp.accepts("notebook", "page"))
        self.assertTrue(canvas_stamp.accepts("group", "field"))
        self.assertFalse(canvas_stamp.accepts("notebook", "field"))
        self.assertFalse(canvas_stamp.accepts("field", "field"), "a leaf takes nothing")

    def test_accepts_is_served_verbatim_on_the_node(self):
        _root, result = self._stamp(FORM, "form")
        notebook = next(n for n in result.nodes.values() if n["tag"] == "notebook")
        self.assertEqual(notebook["accepts"], list(canvas_stamp.ACCEPTS["notebook"]))
        field = result.nodes[_by_name(result, "name")]
        self.assertEqual(field["accepts"], [])
        self.assertFalse(field["container"])

    def test_scaffolding_is_not_movable_but_a_notebook_is_removable(self):
        _root, result = self._stamp(FORM, "form")
        by_kind = {n["kind"]: n for n in result.nodes.values()}
        for kind in ("root", "sheet", "header", "button_box", "notebook"):
            self.assertFalse(by_kind[kind]["movable"], kind)
        self.assertTrue(by_kind["notebook"]["removable"])
        self.assertFalse(by_kind["sheet"]["removable"])
        self.assertTrue(by_kind["field"]["movable"])
        self.assertTrue(by_kind["page"]["movable"])

    def test_descendants_are_what_the_table_lists(self):
        _root, result = self._stamp(FORM, "form")
        right = _by_name(result, "right")
        self.assertEqual(
            canvas_stamp.descendants(result.nodes, right),
            [_by_name(result, "child_ids")],
            "the subview's rows are not nodes",
        )
        outer = _by_name(result, "outer")
        inside = canvas_stamp.descendants(result.nodes, outer)
        self.assertEqual(
            [result.nodes[t]["name"] for t in inside],
            ["left", "name", "email", "right", "child_ids"],
            "document order, every level",
        )
        self.assertEqual(canvas_stamp.descendants(result.nodes, "nope"), [])

    def test_payload_tags(self):
        self.assertEqual(
            canvas_stamp.payload_tag({"kind": "existing_field", "name": "x"}), "field"
        )
        self.assertEqual(canvas_stamp.payload_tag({"kind": "new_field"}), "field")
        for component, tag in (
            ("columns", "group"),
            ("group", "group"),
            ("page", "page"),
            ("notebook", "notebook"),
            ("separator", "separator"),
            ("label", "label"),
            ("button", "button"),
        ):
            self.assertEqual(
                canvas_stamp.payload_tag({"kind": "component", "component": component}),
                tag,
            )
        self.assertEqual(
            canvas_stamp.payload_tag({"kind": "move"}, moved_tag="group"), "group"
        )
        self.assertIsNone(
            canvas_stamp.payload_tag({"kind": "component", "component": "nope"})
        )

    # -- the canvas rewrites -----------------------------------------------

    def test_invisible_is_rewritten_only_when_asked(self):
        _root, result = self._stamp(FORM, "form")
        meta = canvas_stamp.prepare_for_canvas(result.arch, "form")
        self.assertEqual(meta["rewritten"], [])
        self.assertEqual(
            result.arch.xpath("//field[@name='email']")[0].get("invisible"), "1"
        )

        _root, result = self._stamp(FORM, "form")
        meta = canvas_stamp.prepare_for_canvas(result.arch, "form", show_invisible=True)
        email = result.arch.xpath("//field[@name='email']")[0]
        self.assertEqual(email.get("invisible"), "0")
        self.assertIn(canvas_stamp.INVISIBLE_MARK, email.get("class"))
        self.assertEqual(meta["rewritten"], [_by_name(result, "email")])
        self.assertEqual(
            result.nodes[_by_name(result, "email")]["attrs"]["invisible"],
            "1",
            "the table keeps what the view really says",
        )

    def test_a_conditional_invisible_is_left_alone(self):
        arch = '<form><field name="a" invisible="not b"/><field name="b"/></form>'
        _root, result = self._stamp(arch, "form")
        meta = canvas_stamp.prepare_for_canvas(result.arch, "form", show_invisible=True)
        self.assertEqual(meta["rewritten"], [])
        # `LxmlElement` (`lxml_types.py`) declares no `__getitem__`; real
        # lxml supports positional indexing for a child, out of this file's
        # own scope to add to that Protocol.
        self.assertEqual(cast("Any", result.arch)[0].get("invisible"), "not b")

    def test_js_class_is_taken_off_and_returned(self):
        _root, result = self._stamp(FORM, "form")
        meta = canvas_stamp.prepare_for_canvas(result.arch, "form")
        self.assertEqual(meta["js_class"], "custom_form")
        self.assertIsNone(result.arch.get("js_class"))

    def test_a_list_shows_hidden_optional_columns_and_is_not_editable(self):
        _root, result = self._stamp(LIST, "list")
        canvas_stamp.prepare_for_canvas(result.arch, "list")
        email = result.arch.xpath("//field[@name='email']")[0]
        self.assertEqual(email.get("optional"), "show")
        self.assertIsNone(result.arch.get("editable"))
        self.assertIsNone(result.arch.get("multi_edit"))
        self.assertEqual(
            result.nodes[_by_name(result, "email")]["attrs"]["optional"], "hide"
        )

    def test_a_kanban_is_pinned_and_an_empty_one_gets_sample_rows(self):
        _root, result = self._stamp(KANBAN, "kanban")
        canvas_stamp.prepare_for_canvas(result.arch, "kanban", sample=True)
        self.assertEqual(result.arch.get("records_draggable"), "0")
        self.assertEqual(result.arch.get("groups_draggable"), "0")
        self.assertEqual(result.arch.get("sample"), "1")

    def test_a_classless_sheet_button_keeps_its_default_look(self):
        """The token is a class, and ViewButton only supplies btn-secondary
        when the class list is empty; header and stat buttons have a rank
        of their own."""
        _root, result = self._stamp(FORM, "form")
        canvas_stamp.prepare_for_canvas(result.arch, "form")
        plain = result.arch.xpath("//button[@name='plain']")[0]
        self.assertTrue(plain.get("class").startswith("btn-secondary "))
        header = result.arch.xpath("//button[@name='go']")[0]
        self.assertNotIn("btn-secondary", header.get("class"))
        stat = result.arch.xpath("//button[@name='stats']")[0]
        self.assertNotIn("btn-secondary", stat.get("class"))

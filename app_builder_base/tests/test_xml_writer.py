# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Determinism guarantees of the XML writer."""

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.tests import TransactionCase, tagged

from ..tools import xml_writer


@tagged("post_install", "-at_install")
class TestXmlWriter(TransactionCase):
    def test_attributes_are_reordered(self):
        node = etree.fromstring('<record zzz="1" model="m" id="i" aaa="2"/>')
        xml_writer.canonicalize_attributes(node)
        self.assertEqual(list(node.attrib), ["id", "model", "aaa", "zzz"])

    def test_attribute_order_is_stable_across_input_order(self):
        a = etree.fromstring('<field name="x" ref="y" eval="z"/>')
        b = etree.fromstring('<field eval="z" name="x" ref="y"/>')
        xml_writer.canonicalize_attributes(a)
        xml_writer.canonicalize_attributes(b)
        self.assertEqual(
            etree.tostring(a),
            etree.tostring(b),
            "attribute order in the source must not affect output",
        )

    def test_structural_indent(self):
        node = etree.fromstring("<form><sheet><group/></sheet></form>")
        xml_writer.indent(node)
        self.assertEqual(
            etree.tostring(node, encoding="unicode"),
            "<form>\n    <sheet>\n        <group/>\n    </sheet>\n</form>",
        )

    def test_mixed_content_is_left_alone(self):
        """Reflowing mixed content would change what it renders as."""
        source = "<p>Hello <b>world</b> and <i>others</i></p>"
        node = etree.fromstring(source)
        xml_writer.indent(node)
        self.assertEqual(etree.tostring(node, encoding="unicode"), source)

    def test_nested_mixed_content_preserved(self):
        source = "<div><p>text <b>bold</b></p></div>"
        node = etree.fromstring(source)
        xml_writer.indent(node)
        self.assertIn(
            "<p>text <b>bold</b></p>", etree.tostring(node, encoding="unicode")
        )

    def test_normalize_arch_is_idempotent(self):
        arch = "<form>  <sheet>\n\n<group><field name='a'/></group></sheet></form>"
        once = xml_writer.normalize_arch(arch)
        twice = xml_writer.normalize_arch(once)
        self.assertEqual(once, twice)

    def test_serialize_document_has_declaration_and_newline(self):
        root = xml_writer.build_document([etree.Element("record")])
        out = xml_writer.serialize_document(root)
        self.assertTrue(out.startswith('<?xml version="1.0" encoding="utf-8"?>\n'))
        self.assertTrue(out.endswith("\n"))

    def test_noupdate_block_is_last(self):
        plain = etree.Element("record")
        plain.set("id", "a")
        nou = etree.Element("record")
        nou.set("id", "b")
        root = xml_writer.build_document([plain], [nou])
        children = list(root)
        self.assertEqual(children[-1].tag, "data")
        self.assertEqual(children[-1].get("noupdate"), "1")

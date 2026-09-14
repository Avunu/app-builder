# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The canvas payload: the real view, named, and nothing else changed.

Two things have to hold at once. The canvas must render exactly what Odoo
would -- the same postprocessing, the same fields, the same nodes hidden
for this user -- and it must leave no trace: nothing written, nothing
cached, no token anywhere a token could be read back by somebody else.
"""

from lxml import etree

from odoo import Command
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase

FORM_ARCH = """
<form string="Canvas Demo">
    <sheet>
        <group name="main">
            <field name="x_name"/>
            <field name="x_when" invisible="1"/>
        </group>
        <group name="restricted" groups="base.group_no_one">
            <field name="x_secret"/>
        </group>
        <notebook>
            <page string="Notes" name="notes">
                <field name="x_note"/>
            </page>
        </notebook>
    </sheet>
</form>
"""

KANBAN_ARCH = """
<kanban>
    <templates>
        <t t-name="card">
            <main>
                <field name="x_name"/>
                <div><field name="x_note"/></div>
            </main>
        </t>
    </templates>
</kanban>
"""

LIST_ARCH = """
<list>
    <field name="x_name"/>
    <field name="x_note" optional="hide"/>
</list>
"""

# A core model, a view nobody owns, and an inline subview of another model.
PARTNER_ARCH = """
<form string="Partner">
    <sheet>
        <group name="main">
            <field name="name"/>
            <field name="child_ids">
                <list>
                    <field name="name"/>
                    <field name="email"/>
                </list>
            </field>
        </group>
    </sheet>
</form>
"""

# An inline subview whose comodel is *not* the view's own model.
PARTNER_BANKS_ARCH = """
<form string="Partner">
    <sheet>
        <group name="main">
            <field name="name"/>
            <field name="bank_ids">
                <list>
                    <field name="acc_number"/>
                </list>
            </field>
        </group>
    </sheet>
</form>
"""


def _named(nodes, name):
    return next((t for t, n in nodes.items() if n["name"] == name), None)


@tagged("post_install", "-at_install")
class TestCanvas(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.package = self.make_package(name="x_canvas_pkg")
        self.model = self.env["ir.model"].create(
            {
                "name": "Canvas Demo",
                "model": "x_canvas_demo",
                "field_id": [
                    Command.create(
                        {"name": "x_name", "ttype": "char", "field_description": "Name"}
                    ),
                    Command.create(
                        {"name": "x_when", "ttype": "date", "field_description": "When"}
                    ),
                    Command.create(
                        {"name": "x_note", "ttype": "char", "field_description": "Note"}
                    ),
                    Command.create(
                        {
                            "name": "x_secret",
                            "ttype": "char",
                            "field_description": "Secret",
                        }
                    ),
                ],
            }
        )
        self.env["ir.model.access"].create(
            {
                "name": "x_canvas_demo all",
                "model_id": self.model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            }
        )
        self.view = self._view(FORM_ARCH, "form")
        self.package.studio_capture(self.view)

    def _view(self, arch, view_type, model="x_canvas_demo"):
        return self.env["ir.ui.view"].create(
            {
                "name": "studio.canvas.test.%s" % view_type,
                "model": model,
                "type": view_type,
                "arch": arch,
            }
        )

    def _builder(self):
        """An administrator -- reading `ir.ui.view` needs one -- who is not
        in base.group_no_one, which nothing implies."""
        return self.make_user("canvas_builder", ["base.group_system"])

    # -- purity ------------------------------------------------------------

    def test_canvas_is_pure(self):
        """No write, no cache poisoning, no token anywhere but the answer.

        `get_view` is cached registry-wide on the view and the language; a
        stamped arch reaching that cache would be served to every user of
        the view. So the real view is read before and after, byte for byte.
        """
        Model = self.env["x_canvas_demo"]
        real_before = Model.get_view(self.view.id)["arch"]
        combined_before = self.view.get_combined_arch()
        arch_before = self.view.arch
        history = self.env["studio.view.edit"]
        # The read above filled the cache with the clean arch, and a cache
        # entry is never overwritten by a later miss -- so it has to go, or
        # a stamped arch reaching the cache during `canvas()` would sit
        # behind the clean entry and the read below could not see it.
        self.env.registry.clear_cache()

        first = self.editor.canvas(self.view.id)
        second = self.editor.canvas(self.view.id)

        self.assertEqual(Model.get_view(self.view.id)["arch"], real_before)
        self.assertNotIn("o_studio_", real_before)
        self.view.invalidate_recordset()
        self.assertEqual(self.view.get_combined_arch(), combined_before)
        self.assertEqual(self.view.arch, arch_before)
        self.assertNotIn("o_studio_", self.view.arch)
        self.assertFalse(history.search([("base_view_id", "=", self.view.id)]))
        self.assertEqual(first["arch"], second["arch"])
        self.assertEqual(first["nodes"], second["nodes"])
        self.assertEqual(first["arch_version"], second["arch_version"])
        self.assertEqual(first["arch_version"], self.editor.arch_version(self.view.id))

    # -- identity ----------------------------------------------------------

    def test_every_token_resolves_to_the_node_it_was_minted_from(self):
        canvas = self.editor.canvas(self.view.id)
        root = etree.fromstring(self.view.get_combined_arch().encode())
        self.assertTrue(canvas["nodes"])
        for token, node in canvas["nodes"].items():
            element = self.editor._find_descriptor(
                root, {"kind": "node", "token": token}
            )
            self.assertIsNotNone(element, token)
            self.assertEqual(element.tag, node["tag"])
            self.assertEqual(element.get("name"), node["name"])

    def test_the_stamped_arch_carries_the_tokens_the_table_lists(self):
        canvas = self.editor.canvas(self.view.id)
        arch = etree.fromstring(canvas["arch"].encode())
        classes = " ".join(el.get("class") or "" for el in arch.iter())
        for token, node in canvas["nodes"].items():
            if node["dom"] and not node["hidden"]:
                self.assertIn(token, classes, token)
        self.assertEqual(canvas["root"], "o_studio_n_0")
        self.assertEqual(canvas["nodes"][canvas["root"]]["kind"], "root")

    def test_nothing_under_a_field_is_addressable(self):
        view = self._view(PARTNER_ARCH, "form", model="res.partner")
        canvas = self.editor.canvas(view.id)
        names = [n["name"] for n in canvas["nodes"].values()]
        self.assertEqual(names.count("name"), 1)
        self.assertNotIn("email", names)
        arch = etree.fromstring(canvas["arch"].encode())
        for sub in arch.xpath("//field[@name='child_ids']//*"):
            self.assertNotIn("o_studio_", sub.get("class") or "")

    def test_a_node_hidden_by_groups_is_still_addressable(self):
        builder = self._builder()
        editor = self.editor.with_user(builder)
        canvas = editor.canvas(self.view.id)
        token = _named(canvas["nodes"], "restricted")
        self.assertIsNotNone(token)
        self.assertEqual(canvas["nodes"][token]["hidden"], "groups")
        self.assertEqual(
            canvas["nodes"][_named(canvas["nodes"], "x_secret")]["hidden"],
            "groups",
            "what is inside a hidden group is hidden with it",
        )
        self.assertNotIn(token, canvas["arch"])
        self.assertIsNone(canvas["nodes"][_named(canvas["nodes"], "main")]["hidden"])
        # Addressable: a move aimed at it resolves.
        root = etree.fromstring(self.view.get_combined_arch().encode())
        element = editor._find_descriptor(root, {"kind": "node", "token": token})
        self.assertEqual(element.get("name"), "restricted")

    def test_an_invisible_node_is_reported_and_shown_on_request(self):
        canvas = self.editor.canvas(self.view.id)
        token = _named(canvas["nodes"], "x_when")
        self.assertEqual(canvas["nodes"][token]["hidden"], "invisible")
        self.assertIn('invisible="1"', canvas["arch"])
        combined = self.view.get_combined_arch()

        shown = self.editor.canvas(self.view.id, {"show_invisible": True})
        arch = etree.fromstring(shown["arch"].encode())
        when = arch.xpath("//field[@name='x_when']")[0]
        self.assertEqual(when.get("invisible"), "0")
        self.assertIn("o_studio_invisible", when.get("class"))
        self.assertIn(token, when.get("class"))
        self.assertEqual(
            shown["nodes"][token]["hidden"], "invisible", "still reported as such"
        )
        self.assertEqual(shown["nodes"][token]["attrs"]["invisible"], "1")
        self.view.invalidate_recordset()
        self.assertEqual(self.view.get_combined_arch(), combined)

    def test_a_literal_the_postprocessing_added_reads_as_hidden_by_groups(self):
        """From 19 on `_postprocess_debug` hides a base.group_no_one node
        by writing invisible="1" onto it rather than removing it; the view
        itself never said so, and the node still does not render."""
        canvas = self.editor.canvas(self.view.id)
        token = _named(canvas["nodes"], "x_name")
        arch = etree.fromstring(canvas["arch"].encode())
        arch.xpath("//field[@name='x_name']")[0].set("invisible", "1")
        nodes = {t: dict(n, hidden=None) for t, n in canvas["nodes"].items()}
        self.editor._fill_hidden(nodes, etree.tostring(arch, encoding="unicode"))
        self.assertEqual(nodes[token]["hidden"], "groups")
        self.assertEqual(
            nodes[_named(nodes, "x_when")]["hidden"],
            "invisible",
            "a literal the view itself carries is still `invisible`",
        )
        self.assertIsNone(nodes[_named(nodes, "x_note")]["hidden"])

    # -- other view types --------------------------------------------------

    def test_kanban_card_fields_are_stamped_and_the_board_is_pinned(self):
        view = self._view(KANBAN_ARCH, "kanban")
        canvas = self.editor.canvas(view.id)
        arch = etree.fromstring(canvas["arch"].encode())
        name = arch.xpath("//field[@name='x_name']")[0]
        self.assertIn(_named(canvas["nodes"], "x_name"), name.get("class"))
        self.assertEqual(arch.get("records_draggable"), "0")
        self.assertEqual(arch.get("groups_draggable"), "0")
        self.assertEqual(arch.get("sample"), "1", "no records: sample cards")
        self.assertNotIn("records_draggable", view.get_combined_arch())
        token, card = next(
            (t, n) for t, n in canvas["nodes"].items() if n["kind"] == "card"
        )
        self.assertTrue(card["dom"])
        self.assertIsNone(card["hidden"])
        self.assertIn(token, arch.xpath("//t[@t-name='card']")[0].get("class"))
        main = next(t for t, n in canvas["nodes"].items() if n["tag"] == "main")
        name = canvas["nodes"][_named(canvas["nodes"], "x_name")]
        self.assertEqual(name["parent"], main)

    def test_a_list_shows_its_hidden_optional_columns_on_the_canvas_only(self):
        view = self._view(LIST_ARCH, "list")
        canvas = self.editor.canvas(view.id)
        self.assertIn('optional="show"', canvas["arch"])
        self.assertNotIn('optional="hide"', canvas["arch"])
        self.assertIn('optional="hide"', view.get_combined_arch())
        note = canvas["nodes"][_named(canvas["nodes"], "x_note")]
        self.assertEqual(note["kind"], "column")
        self.assertEqual(note["attrs"]["optional"], "hide")

    def test_models_cover_the_comodel_of_an_inline_subview(self):
        view = self._view(PARTNER_BANKS_ARCH, "form", model="res.partner")
        canvas = self.editor.canvas(view.id)
        self.assertEqual(sorted(canvas["models"]), ["res.partner", "res.partner.bank"])
        fields = canvas["models"]["res.partner"]["fields"]
        self.assertIn("bank_ids", fields)
        self.assertIn("id", fields, "what _get_view_fields adds for a form")
        self.assertEqual(fields["bank_ids"]["relation"], "res.partner.bank")
        self.assertIn("acc_number", canvas["models"]["res.partner.bank"]["fields"])
        self.assertEqual(canvas["view"]["model"], "res.partner")
        self.assertIsNone(canvas["source"], "nobody has written anything yet")

    # -- the rest of the payload ---------------------------------------------

    def test_res_id_is_a_real_record_or_false(self):
        self.assertFalse(self.editor.canvas(self.view.id)["res_id"])
        record = self.env["x_canvas_demo"].create({"x_name": "one"})
        other = self.env["x_canvas_demo"].create({"x_name": "two"})
        canvas = self.editor.canvas(self.view.id)
        self.assertIn(canvas["res_id"], (record.id, other.id))
        self.assertEqual(
            self.editor.canvas(self.view.id, {"res_id": other.id})["res_id"], other.id
        )
        self.assertIn(
            self.editor.canvas(self.view.id, {"res_id": other.id + 1000})["res_id"],
            (record.id, other.id),
            "a record that no longer exists falls back",
        )
        self.assertEqual(canvas["record_count"], 2)

    def test_field_nodes_describe_their_field(self):
        canvas = self.editor.canvas(self.view.id)
        node = canvas["nodes"][_named(canvas["nodes"], "x_name")]
        self.assertEqual(node["field"]["name"], "x_name")
        self.assertEqual(node["field"]["type"], "char")
        self.assertEqual(node["field"]["string"], "Name")
        self.assertEqual(node["field"]["origin"], "manual")
        view = self._view(PARTNER_ARCH, "form", model="res.partner")
        canvas = self.editor.canvas(view.id)
        self.assertEqual(
            canvas["nodes"][_named(canvas["nodes"], "name")]["field"]["origin"], "core"
        )
        self.assertIsNone(canvas["nodes"][_named(canvas["nodes"], "main")]["field"])

    def test_the_comodel_field_list_is_served_on_demand_only(self):
        """Every stored field of res.partner, once per relational field of
        the form, on every drop, is weight the canvas does not need; the
        properties panel asks for the selected node."""
        view = self._view(PARTNER_ARCH, "form", model="res.partner")
        canvas = self.editor.canvas(view.id)
        token = _named(canvas["nodes"], "child_ids")
        self.assertNotIn("comodel_fields", canvas["nodes"][token]["field"])
        described = self.editor.describe_node(view.id, {"kind": "node", "token": token})
        self.assertTrue(described["field"]["comodel_fields"])
        self.assertIn("name", [f["name"] for f in described["field"]["comodel_fields"]])

    def test_the_payload_has_the_shape_the_console_reads(self):
        canvas = self.editor.canvas(self.view.id)
        self.assertEqual(canvas["view"]["id"], self.view.id)
        self.assertEqual(canvas["view"]["type"], "form")
        self.assertIsNone(canvas["view"]["js_class"])
        self.assertEqual(canvas["editable_as"], "canvas")
        self.assertEqual(canvas["pending"], [])
        self.assertFalse(canvas["draft_id"])
        self.assertEqual(canvas["history"]["undo"], [])
        self.assertEqual(canvas["package"]["id"], self.package.id)
        self.assertIn("writable", canvas["package"])
        self.assertEqual(canvas["source"]["view_id"], self.view.id)
        self.assertTrue(canvas["source"]["owned"])
        self.assertIn("x_canvas_demo", canvas["models"])
        self.assertIsInstance(canvas["record_count"], int)

    def test_a_search_view_is_edited_as_lists(self):
        view = self._view('<search><field name="x_name"/></search>', "search")
        canvas = self.editor.canvas(view.id)
        self.assertEqual(canvas["editable_as"], "search_lists")
        self.assertIn("x_canvas_demo", canvas["models"])

    def test_a_report_template_is_previewed_elsewhere(self):
        layout = self.env.ref("web.layout")
        canvas = self.editor.canvas(layout.id)
        self.assertEqual(canvas["editable_as"], "report")
        self.assertIsNone(canvas["arch"])
        self.assertEqual(canvas["nodes"], {})

    def test_editing_context_carries_what_the_console_needs(self):
        self._view(LIST_ARCH, "list")
        context = self.editor.editing_context(self.view.id)
        self.assertEqual(sorted(v["type"] for v in context["views"]), ["form", "list"])
        form = next(v for v in context["views"] if v["type"] == "form")
        self.assertEqual(form["view_id"], self.view.id)
        self.assertTrue(form["owned"])
        self.assertIs(context["python_owned"], False)
        self.assertIs(context["python_owner_id"], False)
        self.assertTrue(context["field_types"])
        self.assertIn("value", context["field_types"][0])
        self.assertIn("enabled", context["field_types"][0])
        self.assertIs(context["draft_id"], False)
        self.assertIn(context["reload_mode"], ("inproc", "restart", "manual"))
        self.assertEqual(context["record_count"], 0)

    def test_an_amount_is_offered_when_the_live_model_has_a_currency(self):
        """The rule is "monetary only with a currency field", and a model no
        package owns in Python still has fields the registry can be asked
        about: res.company has currency_id, the demo model has nothing."""

        def amount(context):
            return next(t for t in context["field_types"] if t["ttype"] == "monetary")

        without = amount(self.editor.editing_context(self.view.id))
        self.assertFalse(without["enabled"])
        self.assertIn("Currency", without["tooltip"])
        company = self.editor.editing_context(model="res.company", view_type="form")
        self.assertTrue(amount(company)["enabled"])

    # -- describe_node -------------------------------------------------------

    def test_describe_node_reads_a_token(self):
        canvas = self.editor.canvas(self.view.id)
        token = _named(canvas["nodes"], "x_name")
        described = self.editor.describe_node(
            self.view.id,
            {"kind": "node", "token": token, "arch_version": canvas["arch_version"]},
        )
        self.assertTrue(described["found"])
        self.assertEqual(described["tag"], "field")
        self.assertEqual(described["attrs"], {"name": "x_name"})
        self.assertEqual(described["field"]["origin"], "manual")
        self.assertEqual(described["definition"]["origin"], "manual")
        self.assertIn("field_description", described["definition"]["editable"])
        self.assertEqual(described["definition"]["values"]["field_description"], "Name")
        self.assertNotIn("xpath", described)

        group = self.editor.describe_node(
            self.view.id, {"kind": "node", "token": _named(canvas["nodes"], "main")}
        )
        self.assertTrue(group["found"])
        self.assertIsNone(group["field"])
        self.assertIsNone(group["definition"])
        self.assertFalse(
            self.editor.describe_node(self.view.id, {"kind": "node", "token": "nope"})[
                "found"
            ]
        )

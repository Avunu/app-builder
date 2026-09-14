# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A field dropped on a Python-owned model lands where it was dropped.

The drop happens before the field exists and Apply happens after a reload,
so the location has to be carried across: an anchor on the draft, a ghost
on the canvas in the meantime, and the real field put at the anchor by the
same operation a live drop uses. What has to hold is that an unchanged view
takes the exact xpath, a changed one finds the neighbour again by name, a
neighbour that is gone falls back to the balanced placement rather than
losing the field, a view the package does not own is patched rather than
rewritten, and the ghost is only ever on the canvas copy.

A neighbour can be another ghost: the gap after one is a place too, and
two fields dropped in a row have to keep that order on the canvas and after
Apply. What holds there is that such an anchor names the other field and
resolves wherever it is, that whatever sits beside a ghost keeps its place
when the ghost is moved or removed, and that anything real dropped beside a
ghost goes beside the nearest real node instead -- on the side of the ghost
the gesture said, on the canvas and after Apply alike.

On a manual model the package has adopted, so the draft can be opened and
its placement run without the reload a real Apply needs; the reload half
is ``probe_console_apply.py``.
"""

import json
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import StudioCase
from odoo.addons.app_builder_base.tools import modelspec

OTHER_FORM = """
<form>
    <sheet>
        <group name="other">
            <field name="x_name"/>
            <field name="x_budget"/>
        </group>
    </sheet>
</form>
"""

LIST_ARCH = """
<list>
    <field name="x_name"/>
    <field name="x_budget"/>
</list>
"""


def _named(nodes, name):
    return next(t for t, n in nodes.items() if n["name"] == name)


@tagged("post_install", "-at_install")
class TestAnchorPlacement(StudioCase):
    def setUp(self):
        super().setUp()
        self.editor = self.env["studio.view.editor"]
        self.package = self.make_package(name="x_anchor_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package.action_adopt(["x_studio_project"])
        self.package_model = self.package.model_ids.filtered(
            lambda m: m.model == "x_studio_project"
        )
        self.form = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )

    # -- helpers ---------------------------------------------------------------

    def _draft(self):
        Draft = self.env["studio.model.draft"]
        return Draft.browse(Draft.open_for_model("x_studio_project")["id"])

    def _added(self, draft, *names):
        """A spec/diff pair claiming ``names`` were just added; the fields
        are ones the registry already has, so the arch validates without
        an Apply in the middle of the test."""
        spec = draft._spec()
        base = spec
        for name in names:
            base = modelspec.without_field(base, name)
        return spec, modelspec.diff_specs(base, spec)

    def _anchor(self, view, neighbour, position="after", **overrides):
        anchor = {
            "view_id": view.id,
            "xpath": "//field[@name='%s']" % neighbour,
            "position": position,
            "arch_version": self.editor.arch_version(view.id),
            "descriptor": {"kind": "field", "name": neighbour},
        }
        anchor.update(overrides)
        return anchor

    @staticmethod
    def _new(label, ttype="char"):
        return {
            "kind": "new_field",
            "values": {"ttype": ttype, "field_description": label},
        }

    def _ghost_order(self, canvas, group=None):
        """What the canvas group holds, top to bottom: field names, and a
        ghost as ``~<name>``."""
        arch = etree.fromstring(canvas["arch"].encode())
        container = arch.find(".//group[@name='%s']" % group) if group else None
        if container is None:
            container = arch.find(".//group") if arch.tag == "form" else arch
        out = []
        for child in container:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "widget":
                out.append(
                    "~" + child.get("class").split("o_studio_n_p_")[1].split()[0]
                )
            else:
                out.append(child.get("name"))
        return out

    def _siblings(self, view, group=None):
        view.invalidate_recordset()
        root = etree.fromstring(view.get_combined_arch().encode())
        container = root.find(".//group[@name='%s']" % group) if group else None
        if container is None:
            container = root.find(".//group") if root.tag == "form" else root
        return [c.get("name") for c in container if isinstance(c.tag, str)]

    def _staged(self, draft, name="colour", neighbour="x_budget", **overrides):
        draft.add_field({"name": name, "ttype": "char", "string": name.title()})
        draft.set_anchor(name, self._anchor(self.form, neighbour, **overrides))
        return draft

    def _unapplied(self, *names):
        """A draft whose class "does not have" ``names`` yet.

        The registry still has the columns, so the fields can be anchored
        and drawn as ghosts like any staged field, and the anchors the
        drops mint can then be run through ``_place_in_views`` and the
        arch after Apply read back -- the whole round trip, without the
        reload a real Apply needs.
        """
        draft = self._draft()
        base = draft._spec()
        for name in names:
            base = modelspec.without_field(base, name)
        draft.base_spec_json = json.dumps(modelspec.spec_to_json(base), sort_keys=True)
        self.assertEqual(sorted(draft._added_names()), sorted(names))
        return draft

    def _apply(self, draft):
        """The order the form has once the draft's anchors were placed."""
        spec = draft._spec()
        diff = modelspec.diff_specs(draft._base_spec(), spec)
        self.assertTrue(draft._place_in_views(spec, diff))
        return self._siblings(self.form)

    # -- the hook --------------------------------------------------------------

    def test_an_unchanged_view_takes_the_xpath_as_it_is(self):
        """The descriptor names another neighbour on purpose: while the
        version matches, the minted xpath is the truth."""
        draft = self._draft()
        anchor = self._anchor(
            self.form, "x_budget", descriptor={"kind": "field", "name": "x_name"}
        )
        self.assertTrue(
            draft._place_anchored(self.form, "x_active_flag", anchor, "boolean_toggle")
        )
        self.assertEqual(
            self._siblings(self.form),
            ["x_name", "x_budget", "x_active_flag", "x_partner_id", "x_stage"],
        )
        placed = etree.fromstring(self.form.arch.encode()).find(
            ".//field[@name='x_active_flag']"
        )
        self.assertEqual(placed.get("widget"), "boolean_toggle")
        history = self.env["studio.view.edit"].stack_for(self.form.id)
        self.assertEqual(history["undo"][0]["summary"], "added x_active_flag")

    def test_a_changed_view_finds_the_neighbour_again(self):
        """Same anchor, stale version: the xpath is not trusted and the
        neighbour is found by what it is."""
        draft = self._draft()
        anchor = self._anchor(
            self.form,
            "x_budget",
            arch_version="older",
            descriptor={"kind": "field", "name": "x_name"},
        )
        self.assertTrue(draft._place_anchored(self.form, "x_active_flag", anchor, ""))
        self.assertEqual(
            self._siblings(self.form),
            ["x_name", "x_active_flag", "x_budget", "x_partner_id", "x_stage"],
        )

    def test_a_neighbour_that_is_gone_declines(self):
        draft = self._draft()
        anchor = self._anchor(self.form, "x_gone", arch_version="older")
        before = self.form.arch
        self.assertFalse(draft._place_anchored(self.form, "x_active_flag", anchor, ""))
        self.assertEqual(self.form.arch, before)

    def test_a_declined_anchor_falls_back_to_balanced_placement(self):
        """Through the whole placement: the field still lands, just not at
        the remembered spot, and the anchor is forgotten with it."""
        draft = self._draft()
        Draft = type(draft)
        anchor = self._anchor(self.form, "x_gone", arch_version="older")
        with patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}):
            self.assertTrue(draft._place_in_views(*self._added(draft, "x_active_flag")))
        self.assertIn('<field name="x_active_flag"/>', self.form.arch)
        self.assertEqual(draft._anchors(), {})

    def test_a_locator_core_cannot_apply_declines_rather_than_failing(self):
        """An Apply has already reloaded by the time placement runs; a raise
        here would roll back the database half of it. The refusal is logged
        and the balanced fallback takes over."""
        draft = self._draft()
        Editor = self.env.registry["studio.view.editor"]
        anchor = self._anchor(self.form, "x_budget")
        with (
            patch.object(
                Editor,
                "apply_operation",
                autospec=True,
                side_effect=UserError("comes from another module's extension"),
            ),
            self.assertLogs(
                "odoo.addons.app_builder_view.models.studio_model_draft",
                level="WARNING",
            ),
        ):
            self.assertFalse(
                draft._place_anchored(self.form, "x_active_flag", anchor, "")
            )

    def test_an_xpath_that_finds_nothing_falls_back_to_the_descriptor(self):
        """The version matches and the xpath is trusted first, but a path
        that locates nothing is not an answer; the descriptor still is."""
        draft = self._draft()
        anchor = self._anchor(self.form, "x_budget", xpath="//group[@name='nope']")
        self.assertTrue(draft._place_anchored(self.form, "x_active_flag", anchor, ""))
        self.assertEqual(
            self._siblings(self.form),
            ["x_name", "x_budget", "x_active_flag", "x_partner_id", "x_stage"],
        )

    def test_the_placement_says_what_it_expects_at_the_locator(self):
        """The same guard a live drop gets: the node found on the combined
        arch travels with the locator, so the owned path can refuse a
        positional path that lands on another node of the primary arch."""
        draft = self._draft()
        Editor = self.env.registry["studio.view.editor"]
        anchor = self._anchor(self.form, "x_budget", xpath="/form/sheet/group/field[2]")
        with patch.object(Editor, "apply_operation", autospec=True) as spy:
            draft._place_anchored(self.form, "x_active_flag", anchor, "")
        operation = spy.call_args.args[3]
        self.assertEqual(operation["_expect"]["tag"], "field")
        self.assertEqual(operation["_expect"]["name"], "x_budget")
        self.assertEqual(operation["xpath"], "//field[@name='x_budget']")

    def test_the_hook_writes_nothing_to_disk_by_itself(self):
        draft = self._draft()
        Package = self.env.registry["studio.package"]
        with patch.object(Package, "action_write_files", autospec=True) as spy:
            draft._place_anchored(
                self.form, "x_active_flag", self._anchor(self.form, "x_budget"), ""
            )
        spy.assert_not_called()

    # -- views the package does not own ----------------------------------------

    def _foreign_form(self, arch=OTHER_FORM):
        """A form of the model that another module declares: it has an
        xmlid, since a patch has to name what it inherits, and it is not
        the package's to rewrite."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "x_studio_project.other",
                "model": "x_studio_project",
                "type": "form",
                "arch": arch,
            }
        )
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "x_studio_project_other_form",
                "model": "ir.ui.view",
                "res_id": view.id,
            }
        )
        return view

    def test_a_foreign_view_is_patched_not_rewritten(self):
        other = self._foreign_form()
        draft = self._draft()
        Draft = type(draft)
        anchor = self._anchor(other, "x_name")
        with patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}):
            self.assertTrue(draft._place_in_views(*self._added(draft, "x_active_flag")))
        other.invalidate_recordset()
        self.assertNotIn("x_active_flag", other.arch, "never rewritten in place")
        extension = self.env["ir.ui.view"].search([("inherit_id", "=", other.id)])
        self.assertEqual(len(extension), 1)
        self.assertEqual(extension.studio_package_id, self.package)
        self.assertIn("//field[@name='x_name']", extension.arch)
        self.assertEqual(
            self._siblings(other, "other"), ["x_name", "x_active_flag", "x_budget"]
        )
        self.assertEqual(self.package.state, "synced", "written, once, at the end")
        self.assertIn("x_active_flag", "".join(self.package._render_files().values()))

    def test_a_foreign_view_that_already_shows_the_field_is_left_alone(self):
        other = self._foreign_form(
            OTHER_FORM.replace(
                '<field name="x_budget"/>',
                '<field name="x_budget"/><field name="x_active_flag"/>',
            )
        )
        draft = self._draft()
        Draft = type(draft)
        anchor = self._anchor(other, "x_name")
        with (
            patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}),
            patch.object(Draft, "_place_anchored", autospec=True) as hook,
        ):
            draft._place_in_views(*self._added(draft, "x_active_flag"))
        for call in hook.call_args_list:
            self.assertNotEqual(call.args[1], other, "already there; not asked")

    # -- the ghost on the canvas -----------------------------------------------

    def test_the_canvas_draws_a_ghost_at_the_anchor(self):
        draft = self._staged(self._draft())
        canvas = self.editor.canvas(self.form.id, {"draft_id": draft.id})
        self.assertEqual(canvas["draft_id"], draft.id)
        arch = etree.fromstring(canvas["arch"].encode())
        ghost = arch.find(".//widget[@name='app_builder_pending']")
        self.assertIsNotNone(ghost)
        self.assertEqual(ghost.getprevious().get("name"), "x_budget")
        self.assertIn("o_studio_n_p_colour", ghost.get("class"))
        self.assertIn("'label': 'Colour'", ghost.get("options"))
        node = canvas["nodes"]["p_colour"]
        self.assertEqual(node["kind"], "pending")
        self.assertTrue(node["movable"])
        self.assertTrue(node["dom"])
        self.assertIsNone(node["hidden"])
        self.assertEqual(
            node["pending"],
            {
                "draft_id": draft.id,
                "name": "colour",
                "ttype": "char",
                "string": "Colour",
                "resolved": True,
            },
        )
        parent = canvas["nodes"][node["parent"]]
        children = parent["children"]
        self.assertEqual(
            children[children.index(_named(canvas["nodes"], "x_budget")) + 1],
            "p_colour",
        )
        self.assertEqual(
            canvas["pending"],
            [
                {
                    "name": "colour",
                    "label": "Colour",
                    "ttype": "char",
                    "widget": "",
                    "token": "p_colour",
                    "placed": True,
                    "resolved": True,
                    "view_id": self.form.id,
                }
            ],
        )

    def test_the_ghost_never_reaches_the_view(self):
        draft = self._staged(self._draft())
        self.editor.canvas(self.form.id, {"draft_id": draft.id})
        self.form.invalidate_recordset()
        self.assertNotIn("app_builder_pending", self.form.get_combined_arch())
        self.assertNotIn("app_builder_pending", self.form.arch)
        self.assertNotIn(
            "app_builder_pending", "".join(self.package._render_files().values())
        )

    def test_the_users_own_draft_is_found_without_being_named(self):
        draft = self._staged(self._draft())
        canvas = self.editor.canvas(self.form.id)
        self.assertEqual(canvas["draft_id"], draft.id)
        self.assertIn("p_colour", canvas["nodes"])

    def test_an_anchor_that_no_longer_resolves_is_drawn_where_the_fallback_goes(self):
        """The neighbour is gone, so the exact place is not known; the ghost
        is still on the canvas -- where the balanced placement will put the
        field -- and says so, rather than being counted by the pill and
        shown nowhere."""
        draft = self._staged(self._draft(), neighbour="x_gone", arch_version="older")
        canvas = self.editor.canvas(self.form.id, {"draft_id": draft.id})
        self.assertIn("p_colour", canvas["nodes"])
        self.assertFalse(canvas["nodes"]["p_colour"]["pending"]["resolved"])
        arch = etree.fromstring(canvas["arch"].encode())
        ghost = arch.find(".//widget[@name='app_builder_pending']")
        self.assertIn("'resolved': False", ghost.get("options"))
        # The demo form has no two-column group, so `place_in_form` would
        # open one at the end of the sheet: that is where the ghost goes.
        self.assertEqual(ghost.getparent().tag, "sheet")
        self.assertIsNone(ghost.getnext(), "the last child, as place_in_form does")
        self.assertEqual(len(canvas["pending"]), 1)
        self.assertTrue(canvas["pending"][0]["placed"])
        self.assertFalse(canvas["pending"][0]["resolved"])

    def test_a_field_anchored_on_another_view_is_listed_not_drawn(self):
        other = self._foreign_form()
        draft = self._draft()
        draft.add_field({"name": "colour", "ttype": "char", "string": "Colour"})
        draft.set_anchor("colour", self._anchor(other, "x_name"))
        canvas = self.editor.canvas(self.form.id, {"draft_id": draft.id})
        self.assertNotIn("p_colour", canvas["nodes"])
        self.assertEqual(len(canvas["pending"]), 1)
        self.assertFalse(canvas["pending"][0]["placed"])
        self.assertEqual(canvas["pending"][0]["view_id"], other.id)

    def test_another_users_draft_is_not_spliced_on_request(self):
        """Drafts are per user; naming somebody else's id does not make
        their ghosts show, and the caller gets their own draft instead."""
        draft = self._staged(self._draft())
        builder = self.make_user(
            "anchor_builder", ["base.group_system", "app_builder_base.group_studio_user"]
        )
        canvas = self.editor.with_user(builder).canvas(
            self.form.id, {"draft_id": draft.id}
        )
        self.assertNotEqual(canvas["draft_id"], draft.id)
        self.assertNotIn("p_colour", canvas["nodes"])
        self.assertEqual(canvas["pending"], [])

    def test_a_ghost_on_a_list_is_a_column(self):
        view = self.env["ir.ui.view"].create(
            {
                "name": "x_studio_project.list",
                "model": "x_studio_project",
                "type": "list",
                "arch": LIST_ARCH,
            }
        )
        self.package.studio_capture(view)
        draft = self._draft()
        draft.add_field({"name": "colour", "ttype": "char", "string": "Colour"})
        draft.set_anchor("colour", self._anchor(view, "x_name"))
        canvas = self.editor.canvas(view.id, {"draft_id": draft.id})
        arch = etree.fromstring(canvas["arch"].encode())
        self.assertEqual(
            [(c.tag, c.get("name")) for c in arch],
            [
                ("field", "x_name"),
                ("widget", "app_builder_pending"),
                ("field", "x_budget"),
            ],
        )
        self.assertEqual(canvas["nodes"]["p_colour"]["parent"], canvas["root"])
        self.assertEqual(canvas["nodes"]["p_colour"]["index"], 1)

    def test_two_ghosts_at_one_anchor_keep_their_drop_order(self):
        """Resolved on the original tree, all of them, before any is
        spliced: the first ghost must not shift the second's locator."""
        draft = self._staged(self._draft(), "first")
        draft.add_field({"name": "second", "ttype": "char", "string": "Second"})
        draft.set_anchor(
            "second",
            self._anchor(
                self.form,
                "x_budget",
                xpath="/form/sheet/group/field[2]",
                descriptor=None,
            ),
        )
        canvas = self.editor.canvas(self.form.id, {"draft_id": draft.id})
        arch = etree.fromstring(canvas["arch"].encode())
        group = arch.find(".//group")
        names = [
            c.get("name") if c.tag == "field" else c.get("options")
            for c in group
            if isinstance(c.tag, str)
        ]
        self.assertEqual(names[1], "x_budget")
        self.assertIn("'second'", names[2])
        self.assertIn("'first'", names[3])

    # -- the drop --------------------------------------------------------------

    def _drop(self, view, neighbour, position, payload, options=None):
        canvas = self.editor.canvas(view.id, options)
        return self.editor.drop_at(
            view.id,
            self.package.id,
            {"token": _named(canvas["nodes"], neighbour), "position": position},
            payload,
            expected_arch_version=canvas["arch_version"],
            canvas_options=options,
        )

    def test_a_new_field_on_a_python_model_is_staged_and_anchored(self):
        result = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "priority", "field_description": "Urgency"},
            },
        )
        self.assertFalse(result["stale"])
        self.assertIsNone(result["created"])
        self.assertEqual(result["select"], "p_urgency")
        draft = self.env["studio.model.draft"].browse(result["staged"]["draft_id"])
        self.assertEqual(
            result["staged"],
            {"name": "urgency", "label": "Urgency", "draft_id": draft.id},
        )
        self.assertEqual(result["draft"]["id"], draft.id)
        staged = next(f for f in result["draft"]["fields"] if f["name"] == "urgency")
        self.assertEqual(staged["ttype"], "selection", "the preset is expanded")
        self.assertEqual(len(staged["selection"]), 4)
        self.assertEqual(staged["placement"]["widget"], "priority")
        anchor = draft._anchors()["urgency"]
        self.assertEqual(anchor["view_id"], self.form.id)
        self.assertEqual(anchor["xpath"], "//field[@name='x_budget']")
        self.assertEqual(anchor["position"], "after")
        self.assertEqual(anchor["descriptor"], {"kind": "field", "name": "x_budget"})
        self.assertNotIn(
            "widget", anchor, "the placement says the widget; an anchor would go stale"
        )
        self.assertIsNone(anchor["pending"])
        self.assertEqual(anchor["arch_version"], self.editor.arch_version(self.form.id))
        self.assertIn("p_urgency", result["canvas"]["nodes"])
        self.assertEqual(result["canvas"]["draft_id"], draft.id)
        self.assertFalse(
            self.env["ir.model.fields"].search(
                [("model", "=", "x_studio_project"), ("name", "=", "urgency")]
            ),
            "staged, not written",
        )
        self.assertNotIn("urgency", self.env["x_studio_project"]._fields)

    def test_a_second_drop_reuses_the_same_draft(self):
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        second = self._drop(
            self.form,
            "x_name",
            "before",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "B"},
            },
            options={"draft_id": first["staged"]["draft_id"]},
        )
        self.assertEqual(first["staged"]["draft_id"], second["staged"]["draft_id"])
        self.assertEqual(len(second["canvas"]["pending"]), 2)
        self.assertEqual(second["draft"]["change_count"], 2)

    def test_a_label_the_model_already_uses_gets_a_suffix(self):
        """Two Text tiles dropped before either was renamed are both
        "New Text"; the second is ``new_text_2``, not a refusal."""
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "New Text"},
            },
        )
        second = self._drop(
            self.form,
            "x_name",
            "before",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "New Text"},
            },
            options={"draft_id": first["staged"]["draft_id"]},
        )
        self.assertEqual(first["staged"]["name"], "new_text")
        self.assertEqual(second["staged"]["name"], "new_text_2")

    def test_a_drop_after_a_ghost_is_anchored_on_the_ghost(self):
        """The gap after a ghost is a place: the second field names the
        first as its neighbour, and the canvas keeps the drop order."""
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        options = {"draft_id": first["staged"]["draft_id"]}
        second = self._drop(
            self.form,
            "a",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "B"},
            },
            options=options,
        )
        draft = self.env["studio.model.draft"].browse(options["draft_id"])
        anchor = draft._anchors()["b"]
        self.assertEqual(anchor["pending"], "a")
        self.assertEqual(anchor["position"], "after")
        self.assertIsNone(anchor["xpath"])
        self.assertEqual(second["select"], "p_b")
        self.assertEqual(
            self._ghost_order(second["canvas"]),
            ["x_name", "x_budget", "~a", "~b", "x_partner_id", "x_stage"],
        )
        third = self._drop(
            self.form,
            "a",
            "before",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "C"},
            },
            options=options,
        )
        self.assertEqual(
            self._ghost_order(third["canvas"]),
            ["x_name", "x_budget", "~c", "~a", "~b", "x_partner_id", "x_stage"],
        )
        self.assertTrue(all(p["placed"] for p in third["canvas"]["pending"]))

    def test_a_ghost_cannot_be_dropped_into(self):
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        with self.assertRaises(UserError):
            self._drop(
                self.form,
                "a",
                "inside",
                {
                    "kind": "new_field",
                    "values": {"ttype": "char", "field_description": "B"},
                },
                options={"draft_id": first["staged"]["draft_id"]},
            )

    def test_something_real_dropped_beside_a_ghost_goes_beside_the_nearest_real_node(
        self,
    ):
        """A ghost is not in the arch to be beside; an existing field
        dropped after it lands before the next real node, so the ghost
        stays between the two as the user saw it."""
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        options = {"draft_id": first["staged"]["draft_id"]}
        result = self._drop(
            self.form,
            "a",
            "after",
            {"kind": "existing_field", "name": "x_active_flag"},
            options=options,
        )
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            ["x_name", "x_budget", "~a", "x_active_flag", "x_partner_id", "x_stage"],
        )
        self.assertEqual(
            result["canvas"]["nodes"][result["select"]]["name"], "x_active_flag"
        )

    # -- something real dropped beside a ghost keeps the ghost's side ---------
    #
    # The real node goes beside the nearest real sibling, which is on one
    # side of the ghost or the other; the ghosts of the gap are then
    # re-anchored on it so the canvas shows what the gesture asked for,
    # and Apply -- run here on the anchors the drop minted -- writes the
    # same order.

    def test_a_real_field_dropped_before_a_ghost_lands_before_it(self):
        """Ghost after x_budget, drop before the ghost: the field lands
        after x_budget too, and the ghost is now anchored after the field
        rather than left after x_budget, which would put it first."""
        draft = self._unapplied("x_active_flag")
        draft.set_anchor("x_active_flag", self._anchor(self.form, "x_budget"))
        options = {"draft_id": draft.id}
        result = self._drop(
            self.form,
            "x_active_flag",
            "before",
            {"kind": "existing_field", "name": "x_budget_doubled"},
            options=options,
        )
        expected = [
            "x_name",
            "x_budget",
            "x_budget_doubled",
            "x_active_flag",
            "x_partner_id",
            "x_stage",
        ]
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            [n if n != "x_active_flag" else "~x_active_flag" for n in expected],
        )
        self.assertEqual(
            result["canvas"]["nodes"][result["select"]]["name"], "x_budget_doubled"
        )
        anchor = draft._anchors()["x_active_flag"]
        self.assertEqual(anchor["position"], "after")
        self.assertEqual(
            anchor["descriptor"], {"kind": "field", "name": "x_budget_doubled"}
        )
        self.assertIsNone(anchor["pending"])
        self.assertEqual(self._apply(draft), expected)

    def test_a_real_field_dropped_after_a_ghost_lands_after_it(self):
        """Ghost before x_partner_id, drop after the ghost: the field lands
        before x_partner_id, and the ghost is re-anchored before it."""
        draft = self._unapplied("x_active_flag")
        draft.set_anchor(
            "x_active_flag", self._anchor(self.form, "x_partner_id", "before")
        )
        options = {"draft_id": draft.id}
        result = self._drop(
            self.form,
            "x_active_flag",
            "after",
            {"kind": "existing_field", "name": "x_budget_doubled"},
            options=options,
        )
        expected = [
            "x_name",
            "x_budget",
            "x_active_flag",
            "x_budget_doubled",
            "x_partner_id",
            "x_stage",
        ]
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            [n if n != "x_active_flag" else "~x_active_flag" for n in expected],
        )
        anchor = draft._anchors()["x_active_flag"]
        self.assertEqual(anchor["position"], "before")
        self.assertEqual(
            anchor["descriptor"], {"kind": "field", "name": "x_budget_doubled"}
        )
        self.assertEqual(self._apply(draft), expected)

    def test_a_node_moved_before_a_ghost_lands_before_it(self):
        draft = self._unapplied("x_active_flag")
        draft.set_anchor("x_active_flag", self._anchor(self.form, "x_budget"))
        options = {"draft_id": draft.id}
        canvas = self.editor.canvas(self.form.id, options)
        result = self._drop(
            self.form,
            "x_active_flag",
            "before",
            {"kind": "move", "token": _named(canvas["nodes"], "x_stage")},
            options=options,
        )
        expected = ["x_name", "x_budget", "x_stage", "x_active_flag", "x_partner_id"]
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            [n if n != "x_active_flag" else "~x_active_flag" for n in expected],
        )
        self.assertEqual(self._apply(draft), expected)

    def test_a_node_moved_after_a_ghost_lands_after_it(self):
        """The moved node was the nearest real sibling on the far side:
        the arch does not change at all, and only the re-anchoring puts
        the ghost where the gesture said."""
        draft = self._unapplied("x_active_flag")
        draft.set_anchor("x_active_flag", self._anchor(self.form, "x_budget"))
        options = {"draft_id": draft.id}
        canvas = self.editor.canvas(self.form.id, options)
        result = self._drop(
            self.form,
            "x_active_flag",
            "after",
            {"kind": "move", "token": _named(canvas["nodes"], "x_budget")},
            options=options,
        )
        expected = ["x_name", "x_active_flag", "x_budget", "x_partner_id", "x_stage"]
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            [n if n != "x_active_flag" else "~x_active_flag" for n in expected],
        )
        self.assertEqual(self._apply(draft), expected)

    def test_something_real_can_go_between_two_ghosts(self):
        """Two ghosts in a row, a separator dropped after the first: the
        first is re-anchored before it, the second after it, and the
        second no longer names the first as its neighbour."""
        draft = self._unapplied("x_active_flag", "x_budget_doubled")
        draft.set_anchor("x_active_flag", self._anchor(self.form, "x_budget"))
        draft.set_anchor(
            "x_budget_doubled",
            {"view_id": self.form.id, "position": "after", "pending": "x_active_flag"},
        )
        options = {"draft_id": draft.id}
        self.assertEqual(
            self._ghost_order(self.editor.canvas(self.form.id, options)),
            [
                "x_name",
                "x_budget",
                "~x_active_flag",
                "~x_budget_doubled",
                "x_partner_id",
                "x_stage",
            ],
        )
        result = self._drop(
            self.form,
            "x_active_flag",
            "after",
            {"kind": "component", "component": "separator", "values": {}},
            options=options,
        )
        order = self._ghost_order(result["canvas"])
        separator = order[3]
        self.assertTrue(separator.startswith("studio_separator_"), order)
        self.assertEqual(
            order,
            [
                "x_name",
                "x_budget",
                "~x_active_flag",
                separator,
                "~x_budget_doubled",
                "x_partner_id",
                "x_stage",
            ],
        )
        anchors = draft._anchors()
        self.assertEqual(anchors["x_active_flag"]["position"], "before")
        self.assertIsNone(anchors["x_active_flag"]["pending"])
        self.assertEqual(anchors["x_budget_doubled"]["position"], "after")
        self.assertIsNone(anchors["x_budget_doubled"]["pending"])
        self.assertEqual(
            self._apply(draft),
            [
                "x_name",
                "x_budget",
                "x_active_flag",
                separator,
                "x_budget_doubled",
                "x_partner_id",
                "x_stage",
            ],
        )

    def test_a_chain_of_ghosts_keeps_its_order_around_a_real_drop(self):
        """a <- b <- c, x_partner_id moved after b: a and b end up before
        it as a chain hanging off it, c after it, on the canvas and once
        placed -- whichever order the class lists the three in."""
        self.form.arch = self.form.arch.replace('<field name="x_stage"/>', "")
        draft = self._unapplied("x_active_flag", "x_budget_doubled", "x_stage")
        draft.set_anchor("x_active_flag", self._anchor(self.form, "x_budget"))
        draft.set_anchor(
            "x_budget_doubled",
            {"view_id": self.form.id, "position": "after", "pending": "x_active_flag"},
        )
        draft.set_anchor(
            "x_stage",
            {
                "view_id": self.form.id,
                "position": "after",
                "pending": "x_budget_doubled",
            },
        )
        options = {"draft_id": draft.id}
        canvas = self.editor.canvas(self.form.id, options)
        self.assertEqual(
            self._ghost_order(canvas),
            [
                "x_name",
                "x_budget",
                "~x_active_flag",
                "~x_budget_doubled",
                "~x_stage",
                "x_partner_id",
            ],
        )
        result = self._drop(
            self.form,
            "x_budget_doubled",
            "after",
            {"kind": "move", "token": _named(canvas["nodes"], "x_partner_id")},
            options=options,
        )
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            [
                "x_name",
                "x_budget",
                "~x_active_flag",
                "~x_budget_doubled",
                "x_partner_id",
                "~x_stage",
            ],
        )
        anchors = draft._anchors()
        self.assertEqual(
            (
                anchors["x_budget_doubled"]["position"],
                anchors["x_budget_doubled"]["descriptor"],
            ),
            ("before", {"kind": "field", "name": "x_partner_id"}),
        )
        self.assertEqual(
            (anchors["x_active_flag"]["position"], anchors["x_active_flag"]["pending"]),
            ("before", "x_budget_doubled"),
        )
        self.assertEqual(
            (anchors["x_stage"]["position"], anchors["x_stage"]["descriptor"]),
            ("after", {"kind": "field", "name": "x_partner_id"}),
        )
        self.assertLess(
            anchors["x_budget_doubled"]["seq"], anchors["x_active_flag"]["seq"]
        )
        self.assertEqual(
            self._apply(draft),
            [
                "x_name",
                "x_budget",
                "x_active_flag",
                "x_budget_doubled",
                "x_partner_id",
                "x_stage",
            ],
        )

    def test_ghosts_anchored_alike_on_one_gap_keep_their_order_around_a_drop(self):
        """Two ghosts both dropped "before x_partner_id" -- neither names
        the other -- and x_stage moved after the second: re-anchoring
        only the second would leave the first resolving after x_stage."""
        draft = self._unapplied("x_active_flag", "x_budget_doubled")
        draft.set_anchor(
            "x_active_flag", self._anchor(self.form, "x_partner_id", "before")
        )
        draft.set_anchor(
            "x_budget_doubled", self._anchor(self.form, "x_partner_id", "before")
        )
        options = {"draft_id": draft.id}
        canvas = self.editor.canvas(self.form.id, options)
        self.assertEqual(
            self._ghost_order(canvas)[2:4], ["~x_active_flag", "~x_budget_doubled"]
        )
        result = self._drop(
            self.form,
            "x_budget_doubled",
            "after",
            {"kind": "move", "token": _named(canvas["nodes"], "x_stage")},
            options=options,
        )
        expected = [
            "x_name",
            "x_budget",
            "x_active_flag",
            "x_budget_doubled",
            "x_stage",
            "x_partner_id",
        ]
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            [
                "x_name",
                "x_budget",
                "~x_active_flag",
                "~x_budget_doubled",
                "x_stage",
                "x_partner_id",
            ],
        )
        self.assertEqual(self._apply(draft), expected)

    def test_moving_a_ghost_leaves_what_sat_beside_it_in_place(self):
        """B was dropped after A; dragging A to the end must not take B
        along, nor leave B pointing at a ghost that is now elsewhere."""
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        options = {"draft_id": first["staged"]["draft_id"]}
        self._drop(
            self.form,
            "a",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "B"},
            },
            options=options,
        )
        moved = self._drop(
            self.form,
            "x_stage",
            "after",
            {"kind": "move_pending", "name": "a"},
            options=options,
        )
        self.assertEqual(
            self._ghost_order(moved["canvas"]),
            ["x_name", "x_budget", "~b", "x_partner_id", "x_stage", "~a"],
        )
        anchors = self.env["studio.model.draft"].browse(options["draft_id"])._anchors()
        self.assertIsNone(anchors["b"]["pending"])
        self.assertEqual(
            anchors["b"]["descriptor"], {"kind": "field", "name": "x_budget"}
        )
        self.assertLess(anchors["b"]["seq"], anchors["a"]["seq"])

    def test_a_ghost_can_be_dropped_after_the_one_that_sat_beside_it(self):
        """A after B, where B was after A: B takes A's old place and A
        goes after B -- no circle, and the order the user asked for."""
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        options = {"draft_id": first["staged"]["draft_id"]}
        self._drop(
            self.form,
            "a",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "B"},
            },
            options=options,
        )
        moved = self._drop(
            self.form,
            "b",
            "after",
            {"kind": "move_pending", "name": "a"},
            options=options,
        )
        self.assertEqual(
            self._ghost_order(moved["canvas"]),
            ["x_name", "x_budget", "~b", "~a", "x_partner_id", "x_stage"],
        )

    def test_a_ghost_cannot_be_dropped_beside_itself(self):
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        with self.assertRaises(UserError) as caught:
            self._drop(
                self.form,
                "a",
                "after",
                {"kind": "move_pending", "name": "a"},
                options={"draft_id": first["staged"]["draft_id"]},
            )
        self.assertIn("beside itself", str(caught.exception))

    def test_removing_a_ghost_hands_its_place_to_what_sat_beside_it(self):
        first = self._drop(
            self.form,
            "x_budget",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
        )
        options = {"draft_id": first["staged"]["draft_id"]}
        self._drop(
            self.form,
            "a",
            "after",
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "B"},
            },
            options=options,
        )
        draft = self.env["studio.model.draft"].browse(options["draft_id"])
        draft.remove_field("a")
        self.assertEqual(list(draft._anchors()), ["b"])
        self.assertIsNone(draft._anchors()["b"]["pending"])
        canvas = self.editor.canvas(self.form.id, options)
        self.assertEqual(
            self._ghost_order(canvas),
            ["x_name", "x_budget", "~b", "x_partner_id", "x_stage"],
        )

    def test_a_pending_field_can_be_dragged_to_a_new_anchor(self):
        draft = self._staged(self._draft())
        result = self._drop(
            self.form,
            "x_name",
            "before",
            {"kind": "move_pending", "name": "colour"},
            options={"draft_id": draft.id},
        )
        self.assertEqual(result["select"], "p_colour")
        self.assertEqual(result["staged"]["name"], "colour")
        anchor = draft._anchors()["colour"]
        self.assertEqual(anchor["position"], "before")
        self.assertEqual(anchor["descriptor"], {"kind": "field", "name": "x_name"})
        arch = etree.fromstring(result["canvas"]["arch"].encode())
        ghost = arch.find(".//widget[@name='app_builder_pending']")
        self.assertEqual(ghost.getnext().get("name"), "x_name")

    def test_moving_a_field_that_is_not_pending_is_refused(self):
        draft = self._draft()
        with self.assertRaises(UserError) as caught:
            self._drop(
                self.form,
                "x_name",
                "before",
                {"kind": "move_pending", "name": "x_budget"},
                options={"draft_id": draft.id},
            )
        self.assertIn("no pending field", str(caught.exception))

    def test_a_drop_inside_the_sheet_anchors_on_a_singleton(self):
        """A container with no name is known by its kind alone when there
        is only one of it, which is enough to find it again."""
        canvas = self.editor.canvas(self.form.id)
        sheet = next(t for t, n in canvas["nodes"].items() if n["kind"] == "sheet")
        result = self.editor.drop_at(
            self.form.id,
            self.package.id,
            {"token": sheet, "position": "inside"},
            {
                "kind": "new_field",
                "values": {"ttype": "text", "field_description": "Notes"},
            },
        )
        draft = self.env["studio.model.draft"].browse(result["staged"]["draft_id"])
        self.assertEqual(draft._anchors()["notes"]["descriptor"], {"kind": "sheet"})
        self.assertEqual(draft._anchors()["notes"]["position"], "inside")
        arch = etree.fromstring(result["canvas"]["arch"].encode())
        self.assertEqual(arch.find("sheet")[-1].get("name"), "app_builder_pending")

    def test_a_neighbour_whose_name_the_view_repeats_is_not_described_by_it(self):
        """Two ``x_name`` fields in one form -- a header copy and the one
        in the group, as extensions produce -- and "the field called
        x_name" would be found again as the first, which is not the one
        dropped on. The exact xpath serves while the arch is unchanged;
        the fallback after."""
        root = etree.fromstring(self.form.arch.encode())
        sheet = root.find("sheet")
        sheet.insert(0, etree.fromstring('<field name="x_name" invisible="1"/>'))
        self.form.arch = etree.tostring(root, encoding="unicode")
        canvas = self.editor.canvas(self.form.id)
        in_group = next(
            t
            for t, n in canvas["nodes"].items()
            if n["name"] == "x_name" and canvas["nodes"][n["parent"]]["kind"] == "group"
        )
        result = self.editor.drop_at(
            self.form.id,
            self.package.id,
            {"token": in_group, "position": "after"},
            {
                "kind": "new_field",
                "values": {"ttype": "char", "field_description": "A"},
            },
            expected_arch_version=canvas["arch_version"],
        )
        draft = self.env["studio.model.draft"].browse(result["staged"]["draft_id"])
        anchor = draft._anchors()["a"]
        self.assertIsNone(anchor["descriptor"])
        self.assertEqual(anchor["xpath"], "/form/sheet/group/field[1]")
        self.assertEqual(
            self._ghost_order(result["canvas"]),
            ["x_name", "~a", "x_budget", "x_partner_id", "x_stage"],
        )

    # -- anchors follow their fields -------------------------------------------

    def test_removing_a_pending_field_forgets_its_anchor(self):
        draft = self._staged(self._draft())
        draft.remove_field("colour")
        self.assertEqual(draft._anchors(), {})

    def test_discarding_forgets_every_anchor(self):
        draft = self._staged(self._draft())
        draft.action_discard()
        self.assertEqual(draft._anchors(), {})
        self.assertEqual(draft.load()["anchors"], {})

    def test_an_anchor_needs_a_pending_field(self):
        draft = self._draft()
        with self.assertRaises(UserError):
            draft.set_anchor("x_budget", self._anchor(self.form, "x_name"))

    def test_load_reports_the_anchors(self):
        draft = self._staged(self._draft())
        self.assertEqual(draft.load()["anchors"]["colour"]["view_id"], self.form.id)

    # -- after Apply ---------------------------------------------------------

    def test_a_field_anchored_on_another_is_placed_after_it(self):
        """Whichever order the class lists them in: the field anchored on
        the other has the other placed first, then goes beside the real
        ``<field>`` it became."""
        draft = self._draft()
        Draft = type(draft)
        anchors = {
            "x_budget_doubled": self._anchor(self.form, "x_budget", seq=1),
            "x_active_flag": {
                "view_id": self.form.id,
                "position": "after",
                "pending": "x_budget_doubled",
                "seq": 2,
            },
        }
        spec, diff = self._added(draft, "x_active_flag", "x_budget_doubled")
        self.assertEqual(
            list(diff.added)[:2],
            ["x_active_flag", "x_budget_doubled"],
            "class order puts the dependent first, which is the hard case",
        )
        with patch.object(Draft, "_anchors", return_value=anchors):
            self.assertTrue(draft._place_in_views(spec, diff))
        self.assertEqual(
            self._siblings(self.form),
            [
                "x_name",
                "x_budget",
                "x_budget_doubled",
                "x_active_flag",
                "x_partner_id",
                "x_stage",
            ],
        )
        self.assertEqual(self.form.arch.count('name="x_budget_doubled"'), 1)

    def test_a_field_anchored_on_one_that_cannot_be_placed_falls_back(self):
        draft = self._draft()
        Draft = type(draft)
        anchors = {
            "x_budget_doubled": self._anchor(self.form, "x_gone", arch_version="older"),
            "x_active_flag": {
                "view_id": self.form.id,
                "position": "after",
                "pending": "x_budget_doubled",
                "seq": 2,
            },
        }
        spec, diff = self._added(draft, "x_active_flag", "x_budget_doubled")
        with patch.object(Draft, "_anchors", return_value=anchors):
            self.assertTrue(draft._place_in_views(spec, diff))
        self.assertIn('<field name="x_active_flag"/>', self.form.arch)
        self.assertIn('<field name="x_budget_doubled"/>', self.form.arch)

    def test_placement_uses_the_anchor_once_and_is_idempotent(self):
        draft = self._draft()
        Draft = type(draft)
        anchor = self._anchor(self.form, "x_budget")
        with patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}):
            self.assertTrue(draft._place_in_views(*self._added(draft, "x_active_flag")))
        self.assertEqual(
            self._siblings(self.form),
            ["x_name", "x_budget", "x_active_flag", "x_partner_id", "x_stage"],
        )
        arch_after = self.form.arch
        with patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}):
            self.assertFalse(
                draft._place_in_views(*self._added(draft, "x_active_flag"))
            )
        self.assertEqual(self.form.arch, arch_after)
        self.assertEqual(self.form.arch.count('name="x_active_flag"'), 1)

    # -- after a reload that outran the request ------------------------------

    def test_place_pending_finishes_an_apply_the_registry_already_has(self):
        """The columns exist and the draft still says they are pending:
        the rest of the Apply is the placement and the baseline."""
        draft = self._draft()
        Draft = type(draft)
        spec = draft._spec()
        base = modelspec.without_field(spec, "x_active_flag")
        draft.base_spec_json = json.dumps(modelspec.spec_to_json(base), sort_keys=True)
        self.assertTrue(draft.dirty)
        anchor = self._anchor(self.form, "x_budget")
        with patch.object(Draft, "_anchors", return_value={"x_active_flag": anchor}):
            result = draft.place_pending()
        self.assertTrue(result["placed"])
        self.assertEqual(
            self._siblings(self.form),
            ["x_name", "x_budget", "x_active_flag", "x_partner_id", "x_stage"],
        )
        self.assertFalse(draft.dirty, "the baseline moved with the file")

    def test_place_pending_refuses_while_the_registry_lacks_the_field(self):
        draft = self._staged(self._draft())
        before = self.form.arch
        result = draft.place_pending()
        self.assertFalse(result["placed"])
        self.assertIn("colour", result["reason"])
        self.assertEqual(self.form.arch, before)
        self.assertTrue(draft.dirty)

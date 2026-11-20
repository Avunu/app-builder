# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""An extension is a sequence, and a spec means what it means where it sits.

Every edit of somebody else's view is one more ``<xpath>`` at the end of this
package's extension, and core evaluates them in order -- each on the tree the
ones before it left behind. The editor used to treat the extension as a *set*
keyed on the locator string: a second removal with the same path was "already
there", an attribute edit was folded into whichever block carried the same
path, and a field counted as present because a block for it existed. Each of
those is right exactly until something in between moves the ground, and then
it is a silent no-op or an edit of the wrong node, reported as a success.

These tests are the sequences that moved the ground, plus the guards around
them: what a locator is made of, what happens when another view is applied
after the builder's, what an operation has to carry, and who may edit at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase, raises
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_model import IrModelFields
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.base.models.res_lang import Lang

from ..models.builder_view_edit import BuilderViewEdit
from ..models.builder_view_editor import BuilderViewEditor
from ..models.builder_view_new_field import (
    BuilderViewEditor as BuilderViewEditorNewField,
)

if TYPE_CHECKING:
    from odoo.addons.app_builder_base.models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )

FORM_ARCH = """
<form string="Sequence Demo">
    <sheet>
        <group><field name="x_a"/></group>
        <group><field name="x_b"/></group>
        <group><field name="x_c"/></group>
        <field name="x_x"/>
    </sheet>
</form>
"""

FIELDS = ("x_a", "x_b", "x_c", "x_x", "x_z")


class SequenceCase(BuilderCase):
    """A form of three look-alike groups, owned by another package -- so
    every edit made here is a spec appended to an extension."""

    foreign = True

    def setUp(self):
        super().setUp()
        self.editor = typed.model(self.env, BuilderViewEditor)
        self.history = typed.model(self.env, BuilderViewEdit)
        self.package = self.make_package(name="x_seq_pkg")
        model_vals: dict[str, object] = {
            "name": "Sequence Demo",
            "model": "x_seq_demo",
            "field_id": [
                Command.create(
                    {"name": name, "ttype": "char", "field_description": name[2:]}
                )
                for name in FIELDS
            ],
        }
        self.env["ir.model"].create(model_vals)  # pyright: ignore[reportArgumentType]
        view_vals: dict[str, object] = {
            "name": "builder.sequence.test",
            "model": "x_seq_demo",
            "type": "form",
            "arch": FORM_ARCH,
        }
        self.view = typed.model(self.env, View).create(view_vals)  # pyright: ignore[reportArgumentType]
        owner = self.make_package(name="x_seq_owner") if self.foreign else self.package
        owner.builder_capture(self.view)
        self.view_id = cast("int", self.view.id)
        self.package_id = cast("int", self.package.id)

    def _combined(self):
        return etree.fromstring(
            typed.model(self.env, View)
            .browse(self.view_id)
            .get_combined_arch()
            .encode()
        )

    def _extension(self) -> View:
        return self.editor._find_extension(self.view, self.package)

    def _spec(self):
        return etree.fromstring(cast("str", self._extension().arch).encode())

    def _apply(self, operation: dict[str, object], **kwargs):
        return self.editor.apply_operation(
            self.view_id, self.package_id, operation, **kwargs
        )

    def _fields(self):
        return [f.get("name") for f in self._combined().iter("field")]

    def _group_of(self, name):
        return self._combined().find(".//field[@name='%s']" % name).getparent()

    def _foreign_extension(self, arch: str, priority: int = 16) -> View:
        vals: dict[str, object] = {
            "name": "builder.sequence.test.other_module",
            "model": "x_seq_demo",
            "inherit_id": self.view_id,
            "mode": "extension",
            "priority": priority,
            "arch": arch,
        }
        return typed.model(self.env, View).create(vals)  # pyright: ignore[reportArgumentType]


@tagged("post_install", "-at_install")
class TestRepeatedLocators(SequenceCase):
    # -- removal -------------------------------------------------------------

    def test_a_positional_removal_is_applied_each_time_it_is_asked(self):
        """Once ``group[2]`` is gone the next group *is* ``group[2]``. The
        second removal has the same locator and a different target; treated
        as a duplicate of the first it removed nothing, and said it had."""
        for _turn in range(2):
            self._apply({"type": "remove_node", "xpath": "/form/sheet/group[2]"})
        self.assertEqual(self._fields(), ["x_a", "x_x"])
        self.assertEqual(len(self.history.history_for(self.view_id)), 2)

    def test_two_unnamed_siblings_are_removed_one_after_the_other(self):
        """The same sequence as the console makes it: point at the second
        group, remove it, point at what is now the second group."""
        for _turn in range(2):
            self.editor.remove_at(
                self.view_id, self.package_id, {"kind": "group", "index": 1}, force=True
            )
        self.assertEqual(self._fields(), ["x_a", "x_x"])

    def test_a_label_switched_on_and_off_twice_ends_up_off(self):
        """``//label[@for='x_x']`` removed the first label; the second label
        answers to the same locator and has to be removed as well."""
        for _turn in range(2):
            self.editor.show_label_at(
                self.view_id, self.package_id, {"kind": "field", "name": "x_x"}
            )
            self.assertEqual(len(self._combined().findall(".//label")), 1)
            self._apply({"type": "remove_node", "xpath": "//label[@for='x_x']"})
            self.assertEqual(self._combined().findall(".//label"), [])

    def test_removing_what_the_last_edit_added_takes_the_edit_back(self):
        """No ``replace`` is stacked on an insertion nothing else stands on:
        the spec a developer would write for "added, then removed" is no
        spec at all."""
        self.editor.add_field_at(
            self.view_id,
            self.package_id,
            {"kind": "field", "name": "x_a"},
            "x_z",
            position="after",
        )
        self.editor.remove_at(
            self.view_id, self.package_id, {"kind": "field", "name": "x_z"}
        )
        self.assertNotIn("x_z", self._fields())
        self.assertEqual(self._spec().findall("xpath"), [])

    def test_an_earlier_insertion_is_removed_with_a_replace(self):
        """Only the *last* spec is ever taken back. An earlier one may have
        later specs standing on it, so it stays and a ``replace`` follows."""
        self._apply(
            {
                "type": "add_field",
                "name": "x_z",
                "xpath": "//field[@name='x_a']",
                "position": "after",
            }
        )
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_z']",
                "attrs": {"string": "Zed"},
            }
        )
        self._apply({"type": "remove_node", "xpath": "//field[@name='x_z']"})
        self.assertNotIn("x_z", self._fields())
        self.assertEqual(
            [x.get("position") for x in self._spec().findall("xpath")],
            ["after", "attributes", "replace"],
        )

    def test_a_replayed_removal_changes_nothing(self):
        operation: dict[str, object] = {
            "type": "remove_node",
            "xpath": "//field[@name='x_x']",
        }
        first = self._apply(operation)
        second = self._apply(operation)
        self.assertEqual(first["arch_version"], second["arch_version"])
        self.assertEqual(len(self._spec().findall("xpath")), 1)
        self.assertEqual(len(self.history.history_for(self.view_id)), 1)

    # -- adding --------------------------------------------------------------

    def test_a_removed_field_can_be_dropped_back_in_the_same_place(self):
        """Add, remove, change your mind. The palette offers the field again
        because it reads the view; the add has to read the view too."""
        add: dict[str, object] = {
            "type": "add_field",
            "name": "x_z",
            "xpath": "//field[@name='x_a']",
            "position": "after",
        }
        self._apply(add)
        # Something in between, so the removal is a real `replace`.
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"string": "Ex"},
            }
        )
        self._apply({"type": "remove_node", "xpath": "//field[@name='x_z']"})
        self.assertNotIn("x_z", self._fields())
        self._apply(add)
        self.assertEqual(self._fields().count("x_z"), 1)
        self.assertEqual([f.get("name") for f in self._group_of("x_a")], ["x_a", "x_z"])

    def test_the_same_add_twice_is_still_one_field(self):
        add: dict[str, object] = {
            "type": "add_field",
            "name": "x_z",
            "xpath": "//field[@name='x_a']",
            "position": "after",
        }
        self._apply(add)
        self._apply(add)
        self.assertEqual(self._fields().count("x_z"), 1)
        self.assertEqual(len(self.history.history_for(self.view_id)), 1)

    def test_a_replayed_add_creates_no_empty_extension(self):
        """The field is already where the add would put it -- in the base
        view itself. Nothing changes, so no patch is brought into being."""
        self._apply(
            {
                "type": "add_field",
                "name": "x_x",
                "xpath": "//group[field[@name='x_c']]",
                "position": "after",
            }
        )
        self.assertFalse(self._extension())
        self.assertEqual(self.history.history_for(self.view_id), [])

    def test_a_replace_is_not_mistaken_for_a_replayed_add(self):
        """x_x stands right after x_c's group. A raw add that *replaces*
        that group with x_x asks for the group to go; x_x being beside it
        is no answer to that."""
        self._apply(
            {
                "type": "add_field",
                "name": "x_x",
                "xpath": "//group[field[@name='x_c']]",
                "position": "replace",
            }
        )
        self.assertNotIn("x_c", self._fields())
        self.assertEqual(len(self.history.history_for(self.view_id)), 1)

    def test_a_replayed_add_with_other_attributes_is_refused(self):
        """The field is already there, so inserting it would show it twice;
        dropping the request would claim attributes that were not set."""
        with raises(self, UserError):
            self._apply(
                {
                    "type": "add_field",
                    "name": "x_x",
                    "xpath": "//group[field[@name='x_c']]",
                    "position": "after",
                    "attrs": {"readonly": "1"},
                }
            )
        self.assertFalse(self._extension())
        self.assertNotIn("readonly", self.view.get_combined_arch())

    def test_a_raw_removal_matching_two_nodes_is_not_a_retraction(self):
        """``//field[@name='x_a']`` matches the original x_a first and the
        one the last spec inserted second. Core removes the first; taking
        back the insertion instead removed the other one."""
        self._apply(
            {
                "type": "add_field",
                "name": "x_a",
                "xpath": "//field[@name='x_x']",
                "position": "after",
            }
        )
        self.assertEqual(self._fields().count("x_a"), 2, "fixture")
        self._apply({"type": "remove_node", "xpath": "//field[@name='x_a']"})
        self.assertEqual(self._fields(), ["x_b", "x_c", "x_x", "x_a"])
        self.assertEqual(
            [x.get("position") for x in self._spec().findall("xpath")],
            ["after", "replace"],
        )

    # -- attributes ----------------------------------------------------------

    def test_attributes_follow_the_node_not_the_path(self):
        """An attribute block for ``group[2]``, then a group inserted above:
        the same path now names the group that was first. Folding the second
        edit into the first block put the label on the old target."""
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "/form/sheet/group[2]",
                "attrs": {"invisible": "1"},
            }
        )
        self._apply(
            {
                "type": "add_group",
                "xpath": "/form/sheet/group[1]",
                "position": "before",
                "name": "above",
            }
        )
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "/form/sheet/group[2]",
                "attrs": {"string": "Title"},
            }
        )
        self.assertEqual(self._group_of("x_a").get("string"), "Title")
        self.assertIsNone(self._group_of("x_a").get("invisible"))
        self.assertEqual(self._group_of("x_b").get("invisible"), "1")
        self.assertIsNone(self._group_of("x_b").get("string"))

    def test_attributes_reach_a_node_that_was_removed_and_put_back(self):
        """The earlier block sits before the ``replace``: merged into it, the
        new label would be set on the node that is about to be removed."""
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"string": "One"},
            }
        )
        self._apply({"type": "remove_node", "xpath": "//field[@name='x_x']"})
        self._apply(
            {
                "type": "add_field",
                "name": "x_x",
                "xpath": "//field[@name='x_a']",
                "position": "after",
            }
        )
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"string": "Two"},
            }
        )
        node = self._combined().find(".//field[@name='x_x']")
        self.assertEqual(node.get("string"), "Two")

    def test_attribute_edits_in_a_row_still_share_a_block(self):
        """Other attribute blocks in between change no structure, so the
        earlier block is still the same node and still the one to merge
        into -- typing in the properties panel does not grow the file."""
        for xpath, attrs in (
            ("//field[@name='x_x']", {"string": "One"}),
            ("//field[@name='x_a']", {"readonly": "1"}),
            ("//field[@name='x_x']", {"string": "Two", "required": "1"}),
        ):
            self._apply({"type": "set_attributes", "xpath": xpath, "attrs": attrs})
        blocks = self._spec().findall("xpath")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(
            {a.get("name"): a.text for a in blocks[0].findall("attribute")},
            {"string": "Two", "required": "1"},
        )

    def test_a_renamed_node_ends_the_merge(self):
        """An attribute block that rewrites ``name`` changes what a named
        locator finds, exactly as an insertion changes a positional one."""
        self._apply(
            {
                "type": "add_group",
                "xpath": "//field[@name='x_x']",
                "position": "after",
                "name": "first",
            }
        )
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//group[@name='first']",
                "attrs": {"string": "Old"},
            }
        )
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//group[@name='first']",
                "attrs": {"name": "second"},
            }
        )
        self._apply(
            {
                "type": "add_group",
                "xpath": "//field[@name='x_x']",
                "position": "after",
                "name": "first",
            }
        )
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//group[@name='first']",
                "attrs": {"string": "New"},
            }
        )
        combined = self._combined()
        self.assertEqual(combined.find(".//group[@name='first']").get("string"), "New")
        self.assertEqual(combined.find(".//group[@name='second']").get("string"), "Old")


@tagged("post_install", "-at_install")
class TestLocators(SequenceCase):
    """What a locator is made of when the node has no name of its own."""

    def _locator(self, root, node):
        return self.editor._locator_for(node, self.editor._occurrences(root))

    def _assert_names(self, root, node, expected):
        locator = self._locator(root, node)
        self.assertEqual(locator, expected)
        self.assertEqual(self.editor._resolve_xpath(root, locator), [node])

    def test_an_unnamed_group_is_located_by_a_field_it_holds(self):
        found = self.editor.locate_target(self.view_id, {"kind": "group", "index": 1})
        assert found["found"] is True
        self.assertEqual(found["xpath"], "//group[field[@name='x_b']]")

    def test_that_locator_survives_a_sibling_inserted_above(self):
        """The upstream drift a positional index does not survive: the next
        version of the module that owns the view adds a group at the top."""
        found = self.editor.locate_target(self.view_id, {"kind": "group", "index": 1})
        assert found["found"] is True
        self._apply(
            {
                "type": "set_attributes",
                "xpath": found["xpath"],
                "attrs": {"string": "Bee"},
            }
        )
        self.view.arch = FORM_ARCH.replace(
            "<sheet>", '<sheet><group><field name="x_z"/></group>'
        )
        self.assertEqual(self._group_of("x_b").get("string"), "Bee")
        self.assertIsNone(self._group_of("x_a").get("string"))

    def test_a_node_with_nothing_to_hold_hangs_off_its_named_ancestor(self):
        root = etree.fromstring(
            "<form><sheet><group/><group name='main'><div/><div><span/></div>"
            "</group></sheet></form>"
        )
        second = root.findall(".//div")[1]
        self._assert_names(root, second, "//group[@name='main']/div[2]")
        self._assert_names(root, second[0], "//group[@name='main']/div[2]/span")

    def test_only_a_node_with_no_named_relative_gets_an_absolute_path(self):
        root = etree.fromstring("<form><sheet><group/><group/></sheet></form>")
        self._assert_names(root, root.findall(".//group")[1], "/form/sheet/group[2]")
        self._assert_names(root, root, "/form")

    def test_a_repeated_name_is_not_an_identity(self):
        """An embedded subview repeats the parent's field names: neither the
        node nor a container holding it is unique by that name."""
        root = etree.fromstring(
            "<form><group><field name='a'/></group>"
            "<field name='line_ids'><form><group><field name='a'/></group></form>"
            "</field></form>"
        )
        outer, inner = root.findall(".//group")
        self._assert_names(root, outer, "/form/group")
        self._assert_names(root, inner, "//field[@name='line_ids']/form/group")

    def test_a_value_with_an_apostrophe_is_quoted_the_other_way(self):
        root = etree.fromstring(
            """<t><span t-field="o.with_context(k='v').name"/><span/></t>"""
        )
        self._assert_names(
            root, root[0], """//span[@t-field="o.with_context(k='v').name"]"""
        )

    def test_a_value_with_both_quotes_falls_back_to_position(self):
        root = etree.fromstring("<t><span/><span/></t>")
        root[1].set("t-field", """o.x('a', "b")""")
        self._assert_names(root, root[1], "/t/span[2]")


@tagged("post_install", "-at_install")
class TestViewsAppliedLater(SequenceCase):
    """Priority 99 is late, not last.

    A view with a higher priority, and another package's extension created
    after this one, are applied *after* this package's specs: they are in
    the combined arch a locator is minted on and not in the tree the spec
    is evaluated on.
    """

    LATE = """
        <data>
            <xpath expr="//sheet/group[1]" position="before">
                <group name="late"><field name="x_z"/></group>
                <group/>
            </xpath>
        </data>
    """

    def test_a_node_a_later_view_adds_cannot_be_addressed(self):
        late = self._foreign_extension(self.LATE, priority=150)
        try:
            self.editor.add_field_at(
                self.view_id,
                self.package_id,
                {"kind": "group", "name": "late"},
                "x_x",
                position="inside",
            )
        except UserError as caught:
            self.assertIn("applied after this package's own", str(caught))
            self.assertIn(cast("str", late.name), str(caught))
        else:
            self.fail("the later view's node is not there when our spec runs")
        self.assertFalse(self._extension(), "no patch is left behind by a refusal")

    def test_a_positional_path_shifted_by_a_later_view_is_refused(self):
        """``group[4]`` holds x_b in the combined arch; where the spec is
        evaluated the two late groups are not there yet and there is no
        ``group[4]`` -- and ``group[3]``, x_a's in the combined arch, is
        x_c's. Neither may be edited on the strength of the path."""
        self._foreign_extension(self.LATE, priority=150)
        combined = self._combined()
        for index, holds in ((4, "x_b"), (3, "x_a")):
            pointed_at = combined.findall(".//sheet/group")[index - 1]
            self.assertEqual(pointed_at[0].get("name"), holds, "fixture")
            try:
                self._apply(
                    {
                        "type": "set_attributes",
                        "xpath": "/form/sheet/group[%d]" % index,
                        "attrs": {"string": "Wrong"},
                        "_expect": self.editor._expectation_for(pointed_at),
                    }
                )
            except UserError as caught:
                self.assertIn("applied after this package's own", str(caught))
            else:
                self.fail("group[%d] must not be edited by position" % index)
        self.assertNotIn("Wrong", self.view.get_combined_arch())

    def test_what_the_console_points_at_is_still_edited_correctly(self):
        """The locator the editor mints for an unnamed group names a field
        in it, which means the same group in both trees."""
        self._foreign_extension(self.LATE, priority=150)
        combined = self._combined()
        index = next(
            i
            for i, group in enumerate(combined.iter("group"))
            if len(group) and group[0].get("name") == "x_b"
        )
        self.editor.remove_at(
            self.view_id, self.package_id, {"kind": "group", "index": index}, force=True
        )
        self.assertEqual(self._fields(), ["x_z", "x_a", "x_c", "x_x"])

    def test_another_packages_later_extension_counts_as_later(self):
        """Two packages on one view, both at priority 99: the one created
        second is applied second, and the first cannot stand on it."""
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"string": "Ours"},
            }
        )
        other = self.make_package(name="x_seq_other")
        self.editor.apply_operation(
            self.view_id,
            cast("int", other.id),
            {
                "type": "add_group",
                "xpath": "//field[@name='x_x']",
                "position": "after",
                "name": "theirs",
            },
        )
        with raises(self, UserError):
            self._apply(
                {
                    "type": "add_field",
                    "name": "x_z",
                    "xpath": "//group[@name='theirs']",
                    "position": "inside",
                }
            )
        # The other package's own extension is the last one applied, so for
        # it nothing is later and the same edit goes through.
        self.editor.apply_operation(
            self.view_id,
            cast("int", other.id),
            {
                "type": "add_field",
                "name": "x_z",
                "xpath": "//group[@name='theirs']",
                "position": "inside",
            },
        )
        self.assertIn("x_z", self._fields())

    def test_an_ordinary_extension_applied_before_is_no_obstacle(self):
        self._foreign_extension(self.LATE)
        self.editor.add_field_at(
            self.view_id,
            self.package_id,
            {"kind": "group", "name": "late"},
            "x_x",
            position="inside",
        )
        self.assertEqual(
            [f.get("name") for f in self._combined().find(".//group[@name='late']")],
            ["x_z", "x_x"],
        )

    def test_a_later_sibling_of_an_edited_extension_counts_as_later(self):
        """Editing an extension view: core applies the builder's extension
        of it right after it -- before the extension's own later siblings.
        One of those inserts a group above the others, so ``group[3]`` is
        x_b's in the combined arch and x_c's where the spec runs."""
        middle = self._foreign_extension(
            """
            <data>
                <xpath expr="//field[@name='x_x']" position="attributes">
                    <attribute name="readonly">1</attribute>
                </xpath>
            </data>
            """
        )
        self._foreign_extension(
            """
            <data>
                <xpath expr="//sheet/group[1]" position="before">
                    <group name="late"/>
                </xpath>
            </data>
            """
        )
        combined = etree.fromstring(middle.get_combined_arch().encode())
        pointed_at = combined.findall(".//sheet/group")[2]
        self.assertEqual(pointed_at[0].get("name"), "x_b", "fixture")
        try:
            self.editor.apply_operation(
                cast("int", middle.id),
                self.package_id,
                {
                    "type": "set_attributes",
                    "xpath": "/form/sheet/group[3]",
                    "attrs": {"string": "Wrong"},
                    "_expect": self.editor._expectation_for(pointed_at),
                },
            )
        except UserError as caught:
            self.assertIn("applied after this package's own", str(caught))
        else:
            self.fail("group[3] must not be edited by position")
        self.assertNotIn("Wrong", self.view.get_combined_arch())
        # A locator that means the same node in both trees goes through, into
        # an extension of the edited view.
        result = self.editor.apply_operation(
            cast("int", middle.id),
            self.package_id,
            {
                "type": "set_attributes",
                "xpath": "//group[field[@name='x_b']]",
                "attrs": {"string": "Right"},
            },
        )
        patch = typed.model(self.env, View).browse(result["view_id"])
        self.assertEqual(patch.inherit_id, middle)
        self.assertEqual(self._group_of("x_b").get("string"), "Right")


@tagged("post_install", "-at_install")
class TestOperationInput(SequenceCase):
    """``apply_operation`` is a public RPC: a malformed operation is owed a
    sentence, not a traceback."""

    def _refused(self, operation: object):
        try:
            self._apply(cast("dict[str, object]", operation))
        except UserError:  # pylint: disable=except-pass
            pass
        else:
            self.fail("%r has to be refused" % (operation,))
        self.assertFalse(self._extension(), "and nothing is left behind")

    def test_an_operation_without_a_locator(self):
        for kind in ("add_field", "remove_node", "set_attributes", "add_group"):
            self._refused({"type": kind, "name": "x_z", "attrs": {"string": "S"}})

    def test_an_operation_that_is_not_one(self):
        self._refused("remove_node")
        self._refused({"xpath": "//field[@name='x_x']"})

    def test_a_locator_that_is_not_an_xpath(self):
        self._refused({"type": "remove_node", "xpath": "//field[@name="})
        self._refused({"type": "remove_node", "xpath": 3})

    def test_a_filter_or_a_button_without_a_name(self):
        self._refused({"type": "add_button", "xpath": "//sheet"})
        self._refused({"type": "add_filter", "xpath": "//sheet"})

    def test_an_attribute_name_that_is_not_one(self):
        for attrs in ({"bad key": "1"}, {"": "1"}, {"1st": "1"}, ["string"]):
            self._refused(
                {
                    "type": "set_attributes",
                    "xpath": "//field[@name='x_x']",
                    "attrs": attrs,
                }
            )
        self._refused(
            {
                "type": "add_field",
                "name": "x_z",
                "xpath": "//field[@name='x_x']",
                "attrs": {"<x>": "1"},
            }
        )

    def test_ordinary_attribute_names_pass(self):
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"string": "Ex", "decoration-info": "1"},
            }
        )
        self.assertEqual(
            self._combined().find(".//field[@name='x_x']").get("decoration-info"), "1"
        )


@tagged("post_install", "-at_install")
class TestReadOnlyPackage(SequenceCase):
    """A package whose directory cannot be written is not edited at all.

    The view would be created under the package's xmlids with no data file
    behind it; if the package is an installed module, its next upgrade
    deletes exactly those records. The console says so with a banner. The
    server has to say so too.
    """

    def _freeze(self):
        self.package.root_path = self.unwritable_path()
        self.package.invalidate_recordset()
        self.assertFalse(self.package.writable, "fixture")

    def test_an_edit_is_refused_and_leaves_nothing(self):
        self._freeze()
        with raises(self, UserError):
            self.editor.add_field_at(
                self.view_id,
                self.package_id,
                {"kind": "field", "name": "x_a"},
                "x_z",
            )
        self.assertFalse(self._extension())
        self.assertEqual(self.history.history_for(self.view_id), [])

    def test_a_new_field_is_refused_before_it_exists(self):
        self._freeze()
        with raises(self, UserError):
            typed.model(self.env, BuilderViewEditorNewField).create_field_at(
                self.view_id,
                self.package_id,
                {"kind": "field", "name": "x_a"},
                {"ttype": "char", "field_description": "Nick"},
            )
        self.assertFalse(
            self.env["ir.model.fields"].search(
                [("model", "=", "x_seq_demo"), ("name", "like", "nick")]
            )
        )

    def test_a_manual_field_is_not_redefined(self):
        self._freeze()
        with raises(self, UserError):
            typed.model(self.env, BuilderViewEditorNewField).update_manual_field(
                "x_seq_demo", "x_a", {"field_description": "Changed"}, self.package_id
            )
        field = typed.model(self.env, IrModelFields)._get("x_seq_demo", "x_a")
        self.assertEqual(field.field_description, "a")

    def test_undo_and_redo_are_refused(self):
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"string": "Ex"},
            }
        )
        entry = self.history.browse(self.history.history_for(self.view_id)[0]["id"])
        self._freeze()
        with raises(self, UserError):
            entry.action_undo()
        self.assertTrue(self._extension(), "the patch is still there")
        self.assertFalse(entry.undone)


@tagged("post_install", "-at_install")
class TestOwnedPath(SequenceCase):
    foreign = False

    def test_the_same_add_twice_is_one_field_on_an_owned_view(self):
        """The spec starts empty on every owned edit, so it cannot remember
        the first add. The arch can."""
        add: dict[str, object] = {
            "type": "add_field",
            "name": "x_z",
            "xpath": "//field[@name='x_a']",
            "position": "after",
        }
        self._apply(add)
        self._apply(add)
        self.view.invalidate_recordset()
        self.assertEqual(cast("str", self.view.arch).count('name="x_z"'), 1)
        self.assertEqual(len(self.history.history_for(self.view_id)), 1)

    def test_an_owned_inheriting_primary_view_is_edited_as_a_patch(self):
        """``mode="primary"`` with an ``inherit_id``: the arch is a list of
        specs, so nothing minted on what it renders resolves in it. It is
        edited through an extension of it, like any other patch."""
        child_vals: dict[str, object] = {
            "name": "builder.sequence.test.variant",
            "model": "x_seq_demo",
            "inherit_id": self.view_id,
            "mode": "primary",
            "arch": """
                <data>
                    <xpath expr="//field[@name='x_x']" position="after">
                        <group name="variant"/>
                    </xpath>
                </data>
            """,
        }
        child = typed.model(self.env, View).create(child_vals)  # pyright: ignore[reportArgumentType]
        self.package.builder_capture(child)
        before = child.arch
        result = self.editor.add_field_at(
            cast("int", child.id),
            self.package_id,
            {"kind": "group", "name": "variant"},
            "x_z",
            position="inside",
        )
        child.invalidate_recordset()
        self.assertEqual(child.arch, before, "the variant's own specs are untouched")
        patch = typed.model(self.env, View).browse(result["view_id"])
        self.assertEqual(patch.inherit_id, child)
        self.assertEqual(patch.mode, "extension")
        self.assertEqual(
            cast("BuilderOwnedMixin", patch).builder_package_id, self.package
        )
        combined = etree.fromstring(child.get_combined_arch().encode())
        self.assertEqual(
            [f.get("name") for f in combined.find(".//group[@name='variant']")],
            ["x_z"],
        )
        self.assertNotIn("x_z", self._fields(), "the parent view is not touched")


@tagged("post_install", "-at_install")
class TestSourceLanguage(SequenceCase):
    """An arch is read, changed and written in the source language, whoever
    is editing and whoever is undoing."""

    foreign = False

    def setUp(self):
        super().setUp()
        typed.model(self.env, Lang)._activate_lang("fr_FR")
        self.view.update_field_translations(
            "arch_db", {"fr_FR": {"Sequence Demo": "Démo de suite"}}
        )
        francophone = self.make_user(
            "seq_french_builder", ["base.group_system"], lang="fr_FR"
        )
        self.french = self.editor.with_user(francophone).with_context(lang="fr_FR")

    def _source(self):
        self.view.invalidate_recordset()
        return cast("str", self.view.with_context(lang=None).arch)

    def _french(self):
        self.view.invalidate_recordset()
        return cast("str", self.view.with_context(lang="fr_FR").arch)

    def test_an_edit_made_in_french_leaves_the_source_in_english(self):
        self.assertIn("Démo de suite", self._french(), "fixture")
        self.french.apply_operation(
            self.view_id,
            self.package_id,
            {
                "type": "add_field",
                "name": "x_z",
                "xpath": "//field[@name='x_a']",
                "position": "after",
            },
        )
        self.assertIn('name="x_z"', self._source())
        self.assertIn("Sequence Demo", self._source())
        self.assertNotIn("Démo de suite", self._source())
        self.assertIn("Démo de suite", self._french(), "the translation survives")

    def test_snapshots_are_taken_in_the_source_language(self):
        self.french.apply_operation(
            self.view_id,
            self.package_id,
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"readonly": "1"},
            },
        )
        entry = self.history.sudo().search([("base_view_id", "=", self.view_id)])
        for snapshot in (entry.arch_before, entry.arch_after):
            self.assertIn("Sequence Demo", cast("str", snapshot))
            self.assertNotIn("Démo de suite", cast("str", snapshot))

    def test_an_undo_made_in_french_restores_the_english_source(self):
        self._apply(
            {
                "type": "set_attributes",
                "xpath": "//field[@name='x_x']",
                "attrs": {"readonly": "1"},
            }
        )
        entry = self.history.browse(self.history.history_for(self.view_id)[0]["id"])
        entry.with_user(self.french.env.user).with_context(lang="fr_FR").action_undo()
        self.assertNotIn("readonly", self._source())
        self.assertIn("Sequence Demo", self._source())
        self.assertNotIn("Démo de suite", self._source())
        self.assertIn("Démo de suite", self._french(), "the translation survives")

    def test_an_unnamed_page_is_found_by_its_label_whatever_the_language(self):
        """An owned view another module extends, so the owned path compares
        what the locator finds with what was expected there. A page with no
        name, holding no named child, is known by its label -- and the label
        was read in French while the tree it was compared with was not."""
        self.view.with_context(lang=None).write(
            {
                "arch": """
                    <form string="Sequence Demo">
                        <sheet>
                            <notebook>
                                <page string="Extra">
                                    <group><field name="x_a"/></group>
                                </page>
                            </notebook>
                            <field name="x_x"/>
                        </sheet>
                    </form>
                """
            }
        )
        self.view.update_field_translations(
            "arch_db",
            {"fr_FR": {"Sequence Demo": "Démo de suite", "Extra": "Supplément"}},
        )
        self._foreign_extension(
            """
            <data>
                <xpath expr="//field[@name='x_x']" position="attributes">
                    <attribute name="readonly">1</attribute>
                </xpath>
            </data>
            """
        )
        self.assertIn("Supplément", self._french(), "fixture")
        self.french.apply_at(
            self.view_id,
            self.package_id,
            {"kind": "page", "index": 0},
            {"type": "add_field", "name": "x_z", "position": "inside"},
        )
        self.assertIn('name="x_z"', self._source())
        self.assertIn("Extra", self._source())
        self.assertIn("Supplément", self._french(), "the translation survives")

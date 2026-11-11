# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Regressions for defects found by adversarial review.

Each test here corresponds to a confirmed finding. They are grouped separately
from the feature tests because their value is entirely in *not* regressing --
several of these were silent, and two would have destroyed user data.
"""

from __future__ import annotations

import ast
import os
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import config

from odoo.addons.app_builder_base.models.builder_package_apply import (
    BuilderPackageApply,
)
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.app_builder_view.models.builder_view_editor import BuilderViewEditor
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.base.models.res_lang import Lang

from ..tools import checksum, migrationgen, pycodegen, xml_writer
from .common import BuilderCase, raises

if TYPE_CHECKING:
    # Only for the cast() calls below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every Phase 1c file's own `TYPE_CHECKING` block makes. `BuilderPackageApply`
    # (above) is a real, top-level import -- every use of it is a runtime
    # `typed.model()` call -- but its siblings below never appear outside a
    # `cast("...", ...)` string, so they stay `TYPE_CHECKING`-only, the same
    # split `builder_package_model.py`'s own comment on `BuilderPackage`
    # documents.
    from odoo.sql_db import Cursor

    from odoo.addons.base.models.res_users import Users

    from ..models.builder_owned_mixin import (
        BuilderOwnedMixin,
    )
    from ..models.builder_package import BuilderPackageFile
    from ..models.builder_package_apply import (
        BuilderPackageApplyFile,
    )
    from ..models.builder_package_model import (
        BuilderPackageModel,
    )


@tagged("post_install", "-at_install")
class TestLoadOrder(BuilderCase):
    def test_security_loads_after_the_models_it_references(self):
        """A generated package with an ir.rule was uninstallable.

        Everything we emit under security/ carries a model_id ref, so ranking
        the directory first (as a hand-written addon would) means the rule loads
        before the ir.model record exists.
        """
        package = self.make_package(name="x_order_pkg")
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        rule_vals: dict[str, object] = {
            "name": "order rule",
            "model_id": model.id,
            "domain_force": "[(1, '=', 1)]",
        }
        rule = self.env["ir.rule"].create(rule_vals)  # pyright: ignore[reportArgumentType]
        package._assign(rule)

        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertLess(
            data.index("models/x_builder_project.xml"),
            data.index("security/x_builder_project_security.xml"),
        )
        self.assertLess(
            data.index("models/x_builder_project.xml"),
            data.index("security/ir.model.access.csv"),
        )

    def test_menus_load_after_the_actions_they_reference(self):
        """views/menus.xml would otherwise sort before views/x_*_views.xml."""
        package = self.make_package(name="x_menu_order")
        self.build_demo_content(package)
        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertLess(
            data.index("views/x_builder_project_views.xml"),
            data.index("views/menus.xml"),
        )

    def test_generated_package_installs_into_a_fresh_database(self):
        """The end-to-end consequence of getting load order wrong."""
        package = self.make_package(name="x_installable")
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        installable_rule_vals: dict[str, object] = {
            "name": "installable rule",
            "model_id": model.id,
            "domain_force": "[(1, '=', 1)]",
        }
        package._assign(
            self.env["ir.rule"].create(installable_rule_vals)  # pyright: ignore[reportArgumentType]
        )
        rendered = package._render_files()
        self.wipe_package_records(package)
        # Raises ParseError on an unresolvable ref, which is exactly the bug.
        self.load_rendered(package, rendered)
        self.assertIn("x_builder_project", self.env)


@tagged("post_install", "-at_install")
class TestTranslationNeutrality(BuilderCase):
    def _translate(self, model, french):
        """Give the model a French name, and prove the translation took.

        Without this check the tests below would pass vacuously: if activating
        the language silently failed, there would be no translation to leak and
        every assertion would hold for the wrong reason.
        """
        typed.model(self.env, Lang)._activate_lang("fr_FR")
        model.with_context(lang="fr_FR").name = french
        self.env.flush_all()
        self.assertEqual(model.with_context(lang="fr_FR").name, french)
        self.assertEqual(
            model.with_context(lang="en_US").name,
            "Builder Demo Project",
            "sanity: the two languages must actually differ for this to test anything",
        )

    def test_output_does_not_depend_on_the_users_language(self):
        """Serializing in the user's lang emitted translations as source terms.

        Odoo's importer pins lang=None, so a French admin's save would write the
        French string into the en_US slot on the next load, destroying the
        original and losing the translation.
        """
        package = self.make_package(name="x_lang_pkg")
        model = self.build_demo_content(package)

        self._translate(model, "Projet Demo")

        english = package._render_files()
        french = package.with_context(lang="fr_FR")._render_files()
        self.assertEqual(
            english,
            french,
            "the same package must serialize identically whoever saves it",
        )
        self.assertIn("Builder Demo Project", english["models/x_builder_project.xml"])
        self.assertNotIn("Projet Demo", english["models/x_builder_project.xml"])

    def test_source_term_survives_a_round_trip_under_a_translation(self):
        package = self.make_package(name="x_lang_rt")
        model = self.build_demo_content(package)
        self._translate(model, "Projet Demo")

        rendered = package.with_context(lang="fr_FR")._render_files()
        self.wipe_package_records(package)
        self.load_rendered(package, rendered)

        reloaded = typed.model(self.env, IrModel)._get("x_builder_project")
        self.assertEqual(
            reloaded.with_context(lang="en_US").name,
            "Builder Demo Project",
            "the English source term must not be overwritten by its translation",
        )


@tagged("post_install", "-at_install")
class TestRawIdRefusal(BuilderCase):
    def test_many2one_reference_is_refused_rather_than_emitted(self):
        """Its value is a raw id and would not survive a fresh install."""
        package = self.make_package(name="x_m2oref")
        model = self.build_demo_content(package)
        m2o_ref_vals: dict[str, object] = {
            "name": "x_ref",
            "field_description": "Ref",
            "ttype": "many2one_reference",
            "model_id": model.id,
        }
        field = self.env["ir.model.fields"].create(m2o_ref_vals)  # pyright: ignore[reportArgumentType]
        package._assign(field)
        serializer = typed.serializer(
            self.env["builder.serializer.ir.model.fields"].with_context(
                builder_package=package.name
            )
        )
        record = self.env["res.partner"].search([], limit=1)
        # A record whose many2one_reference actually holds a value.
        with raises(self, UserError):
            serializer._field_node(
                self.env["base.automation"].new(
                    {"trg_field_ref": record.id, "model_id": model.id}
                ),
                "trg_field_ref",
            )


@tagged("post_install", "-at_install")
class TestOwnershipConflicts(BuilderCase):
    def test_assigning_a_record_owned_elsewhere_is_refused(self):
        """Returning silently made 'assign to my package' a no-op."""
        first = self.make_package(name="x_owner_a")
        second = self.make_package(name="x_owner_b")
        shared_model_vals: dict[str, object] = {
            "name": "Shared",
            "model": "x_shared",
            "field_id": [],
        }
        model = self.env["ir.model"].create(shared_model_vals)  # pyright: ignore[reportArgumentType]
        first._assign(model)
        with raises(self, UserError):
            second._assign(model)


@tagged("post_install", "-at_install")
class TestTeardownKeepsFiles(BuilderCase):
    def test_write_after_delete_does_not_erase_the_kept_source(self):
        """The confirm dialog promises the files survive so you can reinstall."""
        package = self.make_package(name="x_keepfiles")
        self.build_demo_content(package)
        package.action_write_files()
        source = os.path.join(package.root_path or "", "models/x_builder_project.xml")
        self.assertTrue(os.path.isfile(source))

        package.action_delete_records()
        package.action_write_files()

        self.assertTrue(
            os.path.isfile(source),
            "the prune pass must not delete files the teardown promised to keep",
        )


@tagged("post_install", "-at_install")
class TestWhitespaceSafety(BuilderCase):
    def test_indent_preserves_non_breaking_space_content(self):
        """str.strip() treats U+00A0 as insignificant; it is content.

        A &nbsp; separating two inline elements in a QWeb template or an HTML
        field was silently deleted on every write.
        """
        nbsp = "\u00a0"
        source = "<div><span>a</span>%s<span>b</span></div>" % nbsp
        node = etree.fromstring(source)
        xml_writer.indent(node)
        self.assertIn(nbsp, etree.tostring(node, encoding="unicode"))

    def test_indent_still_reflows_ordinary_layout_whitespace(self):
        node = etree.fromstring("<form>\n\n  <sheet/>   </form>")
        xml_writer.indent(node)
        self.assertEqual(
            etree.tostring(node, encoding="unicode"), "<form>\n    <sheet/>\n</form>"
        )


@tagged("post_install", "-at_install")
class TestDriftAccounting(BuilderCase):
    def test_freshly_written_files_are_not_reported_as_drifted(self):
        """disk_checksum was left stale, marking every file drifted on write."""
        package = self.make_package(name="x_drift_acct")
        self.build_demo_content(package)
        package.action_write_files()
        self.assertFalse(
            cast("BuilderPackageFile", package.file_ids).filtered("drifted"),
            "nothing can be drifted immediately after we wrote it",
        )
        self.assertEqual(package.state, "synced")


@tagged("post_install", "-at_install")
class TestDeterministicRefs(BuilderCase):
    def test_x2many_refs_are_sorted(self):
        """Recordset order follows the comodel's _order, which for res.groups
        is a translated, non-unique column."""
        package = self.make_package(name="x_refsort")
        self.build_demo_content(package)
        view = typed.model(self.env, View).search(
            [("model", "=", "x_builder_project")], limit=1
        )
        groups = typed.ref(self.env, "base.group_user") + typed.ref(
            self.env, "base.group_system"
        )
        view.groups_id = [(6, 0, groups.ids)]
        rendered = package._render_files()["views/x_builder_project_views.xml"]
        refs = [
            part.split("'")[1] for part in rendered.split("ref(")[1:] if "'" in part
        ]
        self.assertEqual(refs, sorted(refs))


@tagged("post_install", "-at_install")
class TestBuilderAccessControl(BuilderCase):
    """D1 -- every RPC-reachable builder method was callable by any user.

    ``ir.model.access`` cannot protect this: ``builder.view.editor`` is an
    AbstractModel, which ACL rows do not apply to, and ``call_kw`` is
    ``auth="user"`` with no access check of its own. Since these methods write
    Python and XML into a directory on ``addons_path``, an unguarded entry
    point is remote code execution, not a data leak.
    """

    def setUp(self):
        super().setUp()
        outsider_vals: dict[str, object] = {
            "name": "Nosy Employee",
            "login": "builder_outsider",
            "groups_id": [(6, 0, [typed.ref(self.env, "base.group_user").id])],
        }
        self.outsider = self.env["res.users"].create(outsider_vals)  # pyright: ignore[reportArgumentType]

    def test_view_editor_methods_refuse_a_plain_user(self):
        editor = typed.model(self.env, BuilderViewEditor).with_user(self.outsider)
        view = typed.ref(self.env, "base.view_partner_form")
        view_id = cast("int", view.id)
        package = self.make_package(name="x_acl_probe")
        package_id = cast("int", package.id)
        for call in (
            lambda: editor.locate_target(view_id, {"kind": "root"}),
            lambda: editor.editing_context(view_id),
            lambda: editor.search_elements(view_id),
            lambda: editor.addable_view_types("res.partner"),
            lambda: editor.add_view("res.partner", "kanban", package_id),
            lambda: editor.move_node(
                view_id,
                package_id,
                {"kind": "field", "name": "vat"},
                {"kind": "field", "name": "function"},
            ),
            lambda: editor.apply_operation(
                view_id,
                package_id,
                {
                    "type": "add_field",
                    "name": "ref",
                    "xpath": "//field[@name='function']",
                    "position": "after",
                },
            ),
        ):
            with raises(self, AccessError):
                call()

    def test_package_write_methods_refuse_a_plain_user(self):
        package = self.make_package(name="x_acl_pkg")
        # sudo() to dodge the record-level ACL so we are proving the *method*
        # guard fires, not merely that the user cannot read builder.package.
        as_outsider = package.with_user(self.outsider).sudo(False)
        with raises(self, AccessError):
            as_outsider.action_write_files()
        with raises(self, AccessError):
            as_outsider.action_reload()
        with raises(self, AccessError):
            as_outsider.action_delete_records()

    def test_superuser_and_settings_admin_still_pass(self):
        """The guard must not lock out install, data loading, or the admin."""
        package = self.make_package(name="x_acl_ok")
        self.assertTrue(package.action_check_drift())
        admin = cast("Users", typed.ref(self.env, "base.user_admin"))
        self.assertTrue(admin.has_group("app_builder_base.group_builder_manager"))


@tagged("post_install", "-at_install")
class TestLocatorAmbiguity(BuilderCase):
    """D2 -- a bare //tag[@name='x'] is not a locator when it is not unique.

    ``res.partner``'s form carries ``function`` three times: once on the sheet
    and twice inside inline ``child_ids`` subviews grafted in by
    ``_postprocess_tag_field``. ``locate_node`` takes the first match, so the
    picker was handing out one path for three different nodes and an edit
    aimed at a subview column silently patched the sheet.
    """

    def _locators(self):
        """Every node of the partner form, with the locator minted for it.

        Walked here rather than through an RPC: the invariant belongs to
        `_locator_for`, which is what the descriptor resolver calls, and the
        node-list API that used to expose it has been retired along with the
        editor that consumed it.
        """
        editor = typed.model(self.env, BuilderViewEditor)
        view = cast("View", typed.ref(self.env, "base.view_partner_form"))
        root = etree.fromstring(view.get_combined_arch().encode())
        occurrences = editor._occurrences(root)
        return root, [
            (node, editor._locator_for(node, occurrences))
            for node in root.iter()
            if isinstance(node.tag, str)
        ]

    def test_repeated_names_get_distinct_qualified_paths(self):
        _root, pairs = self._locators()
        paths = [
            path
            for node, path in pairs
            if node.tag == "field" and node.get("name") == "function"
        ]
        self.assertGreater(len(paths), 1, "fixture assumes a repeated name")
        self.assertEqual(len(set(paths)), len(paths), "each occurrence needs its own")
        self.assertNotIn("//field[@name='function']", paths)

    def test_unique_names_keep_the_bare_predicate(self):
        """The qualification must be conditional: //field[@name] is preferred
        precisely because it survives a sibling being inserted."""
        _root, pairs = self._locators()
        vat = next(
            path
            for node, path in pairs
            if node.tag == "field" and node.get("name") == "vat"
        )
        self.assertEqual(vat, "//field[@name='vat']")

    def test_every_emitted_locator_resolves_to_exactly_one_node(self):
        """The property that actually matters, asserted over the whole tree."""
        root, pairs = self._locators()
        for _node, path in pairs:
            matches = root.xpath(path)
            self.assertEqual(
                len(matches), 1, "%s matched %d nodes" % (path, len(matches))
            )


@tagged("post_install", "-at_install")
class TestOrphanManualField(BuilderCase):
    """D3 -- autocapture had no else, so a manual field on a core model was
    created live and written to no file at all: the exact drift the project
    exists to prevent, on the models people reach for first."""

    def test_manual_field_on_a_core_model_is_captured_via_context(self):
        package = self.make_package(name="x_orphan_pkg")
        partner_model = typed.model(self.env, IrModel)._get("res.partner")
        loyalty_field_vals: dict[str, object] = {
            "name": "x_builder_loyalty",
            "ttype": "integer",
            "field_description": "Loyalty",
            "model_id": partner_model.id,
        }
        field = (
            self.env["ir.model.fields"]
            .with_context(builder_package_id=package.id)
            .create(loyalty_field_vals)  # pyright: ignore[reportArgumentType]
        )
        self.assertEqual(
            cast("BuilderOwnedMixin", field).builder_package_id,
            package,
            "a manual field on a core model must land in the editing package",
        )
        rendered = package._render_files()
        self.assertTrue(
            any("x_builder_loyalty" in body for body in rendered.values()),
            "the field must reach the source tree, not just the database",
        )

    def test_orphan_field_warns_rather_than_raising(self):
        """A non-builder caller creating a manual field is legitimate and must
        not be forced into a package -- but it must not be silent either."""
        partner_model = typed.model(self.env, IrModel)._get("res.partner")
        unowned_field_vals: dict[str, object] = {
            "name": "x_builder_unowned",
            "ttype": "char",
            "field_description": "Unowned",
            "model_id": partner_model.id,
        }
        with self.assertLogs(
            "odoo.addons.app_builder_base.models.builder_owned_mixin", "WARNING"
        ) as logs:
            field = self.env["ir.model.fields"].create(unowned_field_vals)  # pyright: ignore[reportArgumentType]
        self.assertTrue(field.exists())
        self.assertTrue(any("x_builder_unowned" in line for line in logs.output))


@tagged("post_install", "-at_install")
class TestAddableFieldScope(BuilderCase):
    """D4 -- arch.iter() is recursive, so a field inside an embedded x2many
    subview (a different model entirely) masked the parent's field of the same
    name and the palette came back empty on core models."""

    def test_subview_fields_do_not_mask_parent_model_fields(self):
        editor = typed.model(self.env, BuilderViewEditor)
        view = cast("View", typed.ref(self.env, "base.view_partner_form"))
        root = etree.fromstring(view.get_combined_arch().encode())
        nested_only = {
            el.get("name")
            for el in root.iter("field")
            if el.get("name") and any(a.tag == "field" for a in el.iterancestors())
        } - {
            el.get("name")
            for el in root.iter("field")
            if el.get("name") and not any(a.tag == "field" for a in el.iterancestors())
        }
        addable = {
            f["name"]
            for f in editor.get_addable_fields("res.partner", cast("int", view.id))
        }
        real = {n for n in nested_only if n in self.env["res.partner"]._fields}
        self.assertTrue(real, "fixture assumes the subview introduces a name")
        self.assertTrue(
            real & addable,
            "a field only present inside a subview is still addable to the form",
        )


@tagged("post_install", "-at_install")
class TestAddFieldIdempotence(BuilderCase):
    """D5 -- _op_add_field always appended a new <xpath>, so a double-click put
    the field into the combined arch twice."""

    def test_same_field_twice_is_a_no_op(self):
        package = self.make_package(name="x_idem_pkg")
        package_id = cast("int", package.id)
        editor = typed.model(self.env, BuilderViewEditor)
        view = typed.ref(self.env, "base.view_partner_form")
        view_id = cast("int", view.id)
        operation: dict[str, object] = {
            "type": "add_field",
            "name": "ref",
            "xpath": "//field[@name='function']",
            "position": "after",
        }
        editor.apply_operation(view_id, package_id, operation)
        result = editor.apply_operation(view_id, package_id, operation)
        root = etree.fromstring(
            (typed.model(self.env, View).browse(result["view_id"]).arch or "").encode()
        )
        added = [f for x in root.findall("xpath") for f in x.findall("field")]
        self.assertEqual(
            [f.get("name") for f in added],
            ["ref"],
            "re-applying the same add must not duplicate the field",
        )

    def test_distinct_fields_stay_in_separate_blocks(self):
        """Merging them would silently reverse the order the user added them:
        two position="after" blocks apply in sequence, one block does not."""
        package = self.make_package(name="x_order_pkg")
        package_id = cast("int", package.id)
        editor = typed.model(self.env, BuilderViewEditor)
        view = typed.ref(self.env, "base.view_partner_form")
        view_id = cast("int", view.id)
        for name in ("ref", "lang"):
            add_field_operation: dict[str, object] = {
                "type": "add_field",
                "name": name,
                "xpath": "//field[@name='function']",
                "position": "after",
            }
            editor.apply_operation(view_id, package_id, add_field_operation)
        extension = typed.model(self.env, View).search(
            [("inherit_id", "=", view_id), ("priority", "=", 99)], limit=1
        )
        root = etree.fromstring((extension.arch or "").encode())
        self.assertEqual(len(root.findall("xpath")), 2)


@tagged("post_install", "-at_install")
class TestOwnedViewsAreEditedDirectly(BuilderCase):
    """D6 -- apply_operation always emitted an inheriting view, so a package's
    own generated form shipped alongside a pile of <xpath> patches against
    itself in the same addon: source no developer would have written."""

    def _owned_form(self, package):
        self.build_demo_content(package)
        return typed.model(self.env, View).search(
            [("model", "=", "x_builder_project"), ("type", "=", "form")], limit=1
        )

    def test_a_package_edits_its_own_primary_view_in_place(self):
        package = self.make_package(name="x_owned_pkg")
        form = self._owned_form(package)
        self.assertEqual(
            cast("BuilderOwnedMixin", form).builder_package_id,
            package,
            "fixture must own it",
        )
        before = self.env["ir.ui.view"].search_count([("inherit_id", "=", form.id)])
        own_add_field_operation: dict[str, object] = {
            "type": "add_field",
            "name": "x_budget",
            "xpath": "//field[@name='x_name']",
            "position": "after",
        }
        result = typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", form.id),
            cast("int", package.id),
            own_add_field_operation,
        )
        self.assertEqual(result["view_id"], form.id, "must edit the view itself")
        self.assertIn('name="x_budget"', form.arch or "")
        self.assertNotIn("<xpath", form.arch or "", "no patch against our own view")
        self.assertEqual(
            self.env["ir.ui.view"].search_count([("inherit_id", "=", form.id)]),
            before,
            "no extension view may be created for a view we own",
        )

    def test_a_foreign_view_still_gets_an_inheriting_patch(self):
        """The invariant that makes this project worth using is unchanged."""
        package = self.make_package(name="x_foreign_pkg")
        core_view = cast("View", typed.ref(self.env, "base.view_partner_form"))
        original = core_view.arch
        foreign_add_field_operation: dict[str, object] = {
            "type": "add_field",
            "name": "ref",
            "xpath": "//field[@name='function']",
            "position": "after",
        }
        result = typed.model(self.env, BuilderViewEditor).apply_operation(
            cast("int", core_view.id),
            cast("int", package.id),
            foreign_add_field_operation,
        )
        extension = typed.model(self.env, View).browse(result["view_id"])
        self.assertNotEqual(extension, core_view)
        self.assertEqual(extension.inherit_id, core_view)
        self.assertEqual(extension.mode, "extension")
        self.assertEqual(core_view.arch, original, "core view must be untouched")


@tagged("post_install", "-at_install")
class TestEmitterIsIdempotent(BuilderCase):
    """Phase 2 -- the .py file is the definition, so it is regenerated on every
    write rather than written once. That is only safe because it is also the
    *input*: what the parser can read is reproduced, what it cannot freezes the
    model instead of being overwritten."""

    def _python_package(self):
        package = self.make_package(name="x_emit_pkg")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        return package

    def _source(self, package):
        path = os.path.join(package.root_path, "models/x_builder_project.py")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def _write(self, package, content):
        path = os.path.join(package.root_path, "models/x_builder_project.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_rewriting_an_unchanged_package_is_a_no_op(self):
        """The fixed point, end to end: a save with nothing to say must
        produce an empty diff, or every write shows up as churn in review."""
        package = self._python_package()
        before = self._source(package)
        package.action_write_files()
        self.assertEqual(self._source(package), before)

    def test_a_hand_added_field_is_adopted_not_overwritten(self):
        """The old emitter refused to touch the file at all. Now it reads it
        back, so an edit it understands survives regeneration."""
        package = self._python_package()
        source = self._source(package)
        self.assertNotIn("x_hand_added", source)
        edited = source.replace(
            '    _description = "Builder Demo Project"',
            '    _description = "Builder Demo Project"\n'
            '    x_hand_added = fields.Char(string="Hand Added")',
        )
        self._write(package, edited)

        package.action_write_files()

        rendered = self._source(package)
        self.assertIn("x_hand_added", rendered)
        self.assertIn('string="Hand Added"', rendered)

    def test_code_outside_the_block_never_freezes_the_model(self):
        """The point of the marker convention, and the thing the whole-file
        parser got wrong: a developer adding their own code must not cost them
        access to the builder."""
        package = self._python_package()
        self._write(
            package,
            self._source(package) + "\n"
            "    @property\n"
            "    def shouty(self):\n"
            "        # a comment, which the old parser froze on\n"
            "        return (self.x_name or '').upper()\n",
        )

        package.action_write_files()

        entry = cast("BuilderPackageModel", package.model_ids).filtered(
            lambda m: m.model == "x_builder_project"
        )
        self.assertEqual(entry.source, "python", "must still be builder-owned")
        source = self._source(package)
        self.assertIn("def shouty", source, "the developer's code must survive")
        self.assertIn("old parser froze on", source)

    def test_an_unreadable_block_freezes_the_model_and_keeps_the_file(self):
        """The remaining freeze case is narrow and actionable: our own region
        stopped being readable."""
        package = self._python_package()
        source = self._source(package)
        self._write(
            package,
            source.replace(
                pycodegen.END_MARKER,
                '    _inherits = {"res.partner": "partner_id"}\n'
                + pycodegen.END_MARKER,
            ),
        )

        package.action_write_files()

        entry = cast("BuilderPackageModel", package.model_ids).filtered(
            lambda m: m.model == "x_builder_project"
        )
        self.assertEqual(entry.source, "frozen")
        self.assertTrue(entry.parse_error)
        self.assertIn("_inherits", self._source(package), "the file must be kept")

    def test_a_python_model_is_not_also_emitted_as_xml(self):
        """Two definitions of one model is the unrecoverable state:
        _add_manual_models builds a second class for the same _name and
        _process_end then reaps our own xmlids."""
        package = self._python_package()
        files = package._render_files()
        self.assertIn("models/x_builder_project.py", files)
        self.assertNotIn("models/x_builder_project.xml", files)


@tagged("post_install", "-at_install")
class TestLoadOrderFollowsModelSource(BuilderCase):
    """security/ had to follow models/ only because generated ACLs ref an
    ir.model record that models/*.xml defines. A package whose models are all
    Python has no such file: reflection creates the row during init_models,
    which runs before load_data."""

    def test_xml_models_keep_security_after_models(self):
        package = self.make_package(name="x_order_xml")
        self.build_demo_content(package)
        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertLess(
            data.index("models/x_builder_project.xml"),
            data.index("security/ir.model.access.csv"),
        )

    def test_python_models_get_the_conventional_order_back(self):
        package = self.make_package(name="x_order_py")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertNotIn("models/x_builder_project.xml", data)
        self.assertEqual(
            data[0],
            "security/ir.model.access.csv",
            "with no XML models, security may load first as in any addon",
        )


@tagged("post_install", "-at_install")
class TestDeleteRecordsSpareReflection(BuilderCase):
    """action_delete_records runs with _force_unlink, which makes
    IrModelFields.unlink drop columns. Reflection writes an ir.model.data row
    for every field a Python class declares -- including the magic columns and
    everything mail.thread brings -- so feeding those to unlink would destroy
    data the package never created."""

    def test_reflected_base_fields_are_not_in_the_delete_set(self):
        package = self.make_package(name="x_del_pkg")
        model = self.build_demo_content(package)
        package.action_write_files()

        # Simulate what reflection does for a code-defined model: a base-state
        # metadata row carrying this package's module name.
        reflected_vals: dict[str, object] = {
            "name": "x_reflected",
            "ttype": "char",
            "field_description": "Reflected",
            "model_id": model.id,
            "state": "base",
        }
        reflected = self.env["ir.model.fields"].create(reflected_vals)  # pyright: ignore[reportArgumentType]
        reflected_data_vals: dict[str, object] = {
            "module": package.name,
            "name": "field_x_builder_project__x_reflected",
            "model": "ir.model.fields",
            "res_id": reflected.id,
        }
        self.env["ir.model.data"].create(reflected_data_vals)  # pyright: ignore[reportArgumentType]

        deletable = package._deletable_data()
        self.assertNotIn(
            reflected.id,
            [d.res_id for d in deletable if d.model == "ir.model.fields"],
            "a base-state field is reflection output, not ours to unlink",
        )
        self.assertTrue(deletable, "our own manual records must still be deletable")


@tagged("post_install", "-at_install")
class TestDestructiveApplyGate(BuilderCase):
    """Phase 0 measured that removing a field from the generated .py drops its
    column and its data. The gate makes that a decision rather than a
    side effect, and the pre-migration makes it recoverable."""

    def _python_package(self):
        package = self.make_package(name="x_destr_pkg")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        return package

    def _path(self, package):
        return os.path.join(package.root_path, "models/x_builder_project.py")

    def _drop_a_field(self, package, name="x_active_flag"):
        """Remove one field's declaration, and nothing else.

        Deliberately a field nothing else references. Taking out one a compute
        depends on leaves an orphan ``@api.depends`` and a compute method with
        no field, which the parser rightly refuses -- see the test below.
        """
        with open(self._path(package), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn(name, source, "fixture must have the field to remove")
        kept = "\n".join(
            line
            for line in source.splitlines()
            if not line.strip().startswith("%s = fields." % name)
        )
        with open(self._path(package), "w", encoding="utf-8") as handle:
            handle.write(kept + "\n")

    def test_dropping_a_stored_field_is_detected(self):
        package = self._python_package()
        self._drop_a_field(package)
        dropped = package._destructive_changes(package._render_files())
        self.assertIn("x_builder_project", dropped)
        self.assertIn("x_active_flag", dropped["x_builder_project"])

    def test_removing_a_field_a_compute_depends_on_freezes_instead(self):
        """Better to stop rewriting the file than to report a tidy diff for
        source that no longer makes sense."""
        package = self._python_package()
        with open(self._path(package), encoding="utf-8") as handle:
            source = handle.read()
        mangled = "\n".join(
            line for line in source.splitlines() if "x_budget" not in line
        )
        with open(self._path(package), "w", encoding="utf-8") as handle:
            handle.write(mangled + "\n")

        package._render_files()

        entry = cast("BuilderPackageModel", package.model_ids).filtered(
            lambda m: m.model == "x_builder_project"
        )
        self.assertEqual(entry.source, "frozen")

    def test_an_ordinary_change_is_not_destructive(self):
        package = self._python_package()
        self.assertEqual(package._destructive_changes(package._render_files()), {})

    def test_the_pre_migration_renames_rather_than_drops(self):
        rendered = migrationgen.render_pre_migration(
            "x_builder_project", ["x_budget"], "20260728120000"
        )
        assert rendered is not None, "fixture must produce a pre-migration"
        ast.parse(rendered)  # it has to be importable by Odoo's migration loader
        self.assertIn("RENAME COLUMN", rendered)
        self.assertNotIn("DROP COLUMN", rendered)
        self.assertIn("x_budget_builder_removed_20260728120000", rendered)

    def test_a_long_column_name_stays_within_the_identifier_limit(self):
        target = migrationgen.rename_column_sql(
            "t", "x_" + "a" * 60, migrationgen.suffix_for("20260728120000")
        )
        self.assertLessEqual(len(target), 63)
        self.assertIn("builder_removed", target, "the marker must survive truncation")


@tagged("post_install", "-at_install")
class TestApplyIsRecoverable(BuilderCase):
    """Module operations commit, so a failed apply is not something the ORM
    rolls back. The snapshot is what makes it recoverable."""

    def _python_package(self):
        package = self.make_package(name="x_apply_pkg")
        self.build_demo_content(package)
        package.action_write_files()
        return package

    def test_uncompilable_python_never_reaches_disk(self):
        """The step that keeps a bad apply survivable: once a broken module
        file is written, the next request re-imports it and the database will
        not boot for anybody."""
        package = self._python_package()
        with raises(self, UserError) as caught:
            package._assert_sources_compile(
                {"models/broken.py": "class Nope(:\n    pass\n"}
            )
        self.assertIn("not valid Python", str(caught.exception))

    def test_generated_python_that_cannot_be_reparsed_is_refused(self):
        package = self._python_package()
        package.action_adopt(["x_builder_project"])
        entry = cast("BuilderPackageModel", package.model_ids).filtered(
            lambda m: m.model == "x_builder_project"
        )
        with raises(self, UserError):
            package._assert_specs_reparse(
                {
                    entry.python_path or "": (
                        "from odoo import fields, models\n\n\n"
                        "class X(models.Model):\n"
                        '    _name = "x_builder_project"\n'
                        "    _inherits = {'a': 'b'}\n"
                    )
                }
            )

    def test_snapshot_records_the_bytes_that_were_there(self):
        package = self._python_package()
        files = package._render_files()
        apply = typed.model(self.env, BuilderPackageApply)._snapshot(
            package, files, reason="test", stamp="20260728120000"
        )
        self.assertEqual(apply.state, "pending")
        self.assertTrue(apply.file_ids)
        manifest = cast("BuilderPackageApplyFile", apply.file_ids).filtered(
            lambda f: f.path == "__manifest__.py"
        )
        self.assertTrue(manifest.existed)
        self.assertIn("__manifest__", manifest.path or "")
        self.assertIn('"depends"', manifest.content_before or "")

    def test_restore_puts_the_previous_bytes_back(self):
        package = self._python_package()
        files = package._render_files()
        apply = typed.model(self.env, BuilderPackageApply)._snapshot(
            package, files, reason="test", stamp="20260728120001"
        )
        target = os.path.join(package.root_path or "", "__manifest__.py")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("# clobbered\n")

        apply._restore()

        with open(target, encoding="utf-8") as handle:
            self.assertIn('"depends"', handle.read())

    def test_restore_removes_files_that_did_not_exist_before(self):
        package = self._python_package()
        apply = typed.model(self.env, BuilderPackageApply)._snapshot(
            package, {"views/brand_new.xml": "<odoo/>"}, stamp="20260728120002"
        )
        target = os.path.join(package.root_path or "", "views/brand_new.xml")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("<odoo/>")

        apply._restore()

        self.assertFalse(
            os.path.exists(target),
            "a half-written new file must not be left behind",
        )

    def test_a_pending_apply_from_a_dead_process_is_reaped(self):
        """Step 7 cannot run if the process is gone. A row left pending by
        another process, long enough ago, is the only signal that a rollback
        never completed; one this process started, or one a sibling worker
        started a moment ago, is in progress and is left alone."""
        package = self._python_package()
        Apply = typed.model(self.env, BuilderPackageApply)
        own = Apply._snapshot(
            package, {"__manifest__.py": "{}"}, stamp="20260728120003"
        )
        self.assertFalse(Apply._reap_abandoned(package), "started here: in progress")

        own.write({"boot_id": "someotherprocess"})
        self.assertFalse(Apply._reap_abandoned(package), "too young to be abandoned")

        cast("Cursor", self.env.cr).execute(
            "UPDATE builder_package_apply"
            " SET create_date = now() - interval '10 minutes' WHERE id = %s",
            (own.id,),
        )
        own.invalidate_recordset()
        reaped = Apply._reap_abandoned(package)
        self.assertEqual(reaped, own)
        self.assertEqual(own.state, "failed")
        self.assertIn("stopped", own.error or "")

    def test_multi_worker_deployments_refuse_an_in_process_reload(self):
        """Other workers would rebuild against the Python already in their own
        sys.modules, which is wrong rather than merely slow."""
        package = self._python_package()
        with patch.dict(config.options, {"workers": 4, "dev_mode": []}):
            package.invalidate_recordset(["reload_mode"])
            self.assertEqual(package.reload_mode, "manual")
            with raises(self, UserError) as caught:
                package._reload_now()
        self.assertIn("worker", str(caught.exception))


@tagged("post_install", "-at_install")
class TestPartialWriteDoesNotPrune(BuilderCase):
    """A partial write must not read *absent* as *deleted*.

    ``_write_files`` removes tracked files missing from the dict it is handed,
    which is right only when that dict is the whole rendered package. Handing
    it one model's ``.py`` -- what editing a single model naturally produces --
    deleted every other file the package had generated: the other models, the
    views, the menus, the ACLs. It went unnoticed because the next apply then
    regenerated an *empty* class for the model whose file had vanished, and the
    destructive-change gate refused that, so the symptom was a confusing
    refusal rather than the data loss that caused it.
    """

    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_prune_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()

    def _paths(self):
        return set(cast("BuilderPackageFile", self.package.file_ids).mapped("path"))

    def _on_disk(self, relative):
        return os.path.isfile(os.path.join(self.package.root_path or "", relative))

    def test_a_partial_write_leaves_the_rest_of_the_package_alone(self):
        before = self._paths()
        self.assertGreater(len(before), 1, "fixture should generate several files")
        victim = next(path for path in before if path != "__manifest__.py")

        self.package._write_files({"__manifest__.py": "{'name': 'x'}\n"})

        self.assertTrue(
            self._on_disk(victim),
            "%s was deleted by a write that never mentioned it" % victim,
        )
        for path in before:
            self.assertTrue(self._on_disk(path), "%s went missing" % path)

    def test_a_full_write_still_prunes_what_it_no_longer_generates(self):
        """The pruning itself is wanted -- a file the package stopped
        generating should not linger and get imported."""
        self.package._write_files({"__manifest__.py": "{'name': 'x'}\n"})
        self.package._sync_file_records({"__manifest__.py": "{'name': 'x'}\n"})
        orphan = os.path.join(self.package.root_path or "", "views/leftover.xml")
        os.makedirs(os.path.dirname(orphan), exist_ok=True)
        with open(orphan, "w", encoding="utf-8") as handle:
            handle.write("<odoo/>\n")
        leftover_vals: dict[str, object] = {
            "package_id": self.package.id,
            "path": "views/leftover.xml",
            "generated_checksum": checksum.hash_text("<odoo/>\n"),
        }
        record = self.env["builder.package.file"].create(leftover_vals)  # pyright: ignore[reportArgumentType]
        self.package.invalidate_recordset(["file_ids"])

        self.package._write_files({"__manifest__.py": "{'name': 'x'}\n"}, prune=True)

        self.assertFalse(
            os.path.isfile(orphan), "a full write should still drop what it dropped"
        )
        self.assertTrue(record.exists())

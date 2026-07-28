# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Regressions for defects found by adversarial review.

Each test here corresponds to a confirmed finding. They are grouped separately
from the feature tests because their value is entirely in *not* regressing --
several of these were silent, and two would have destroyed user data.
"""

import ast
import os

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..tools import xml_writer
from .common import StudioCase


@tagged("post_install", "-at_install")
class TestLoadOrder(StudioCase):
    def test_security_loads_after_the_models_it_references(self):
        """A generated package with an ir.rule was uninstallable.

        Everything we emit under security/ carries a model_id ref, so ranking
        the directory first (as a hand-written addon would) means the rule loads
        before the ir.model record exists.
        """
        package = self.make_package(name="x_order_pkg")
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        rule = self.env["ir.rule"].create(
            {
                "name": "order rule",
                "model_id": model.id,
                "domain_force": "[(1, '=', 1)]",
            }
        )
        package._assign(rule)

        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertLess(
            data.index("models/x_studio_project.xml"),
            data.index("security/x_studio_project_security.xml"),
        )
        self.assertLess(
            data.index("models/x_studio_project.xml"),
            data.index("security/ir.model.access.csv"),
        )

    def test_menus_load_after_the_actions_they_reference(self):
        """views/menus.xml would otherwise sort before views/x_*_views.xml."""
        package = self.make_package(name="x_menu_order")
        self.build_demo_content(package)
        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertLess(
            data.index("views/x_studio_project_views.xml"),
            data.index("views/menus.xml"),
        )

    def test_generated_package_installs_into_a_fresh_database(self):
        """The end-to-end consequence of getting load order wrong."""
        package = self.make_package(name="x_installable")
        self.build_demo_content(package)
        model = self.env["ir.model"]._get("x_studio_project")
        package._assign(
            self.env["ir.rule"].create(
                {
                    "name": "installable rule",
                    "model_id": model.id,
                    "domain_force": "[(1, '=', 1)]",
                }
            )
        )
        rendered = package._render_files()
        self.wipe_package_records(package)
        # Raises ParseError on an unresolvable ref, which is exactly the bug.
        self.load_rendered(package, rendered)
        self.assertIn("x_studio_project", self.env)


@tagged("post_install", "-at_install")
class TestTranslationNeutrality(StudioCase):
    def _translate(self, model, french):
        """Give the model a French name, and prove the translation took.

        Without this check the tests below would pass vacuously: if activating
        the language silently failed, there would be no translation to leak and
        every assertion would hold for the wrong reason.
        """
        self.env["res.lang"]._activate_lang("fr_FR")
        model.with_context(lang="fr_FR").name = french
        self.env.flush_all()
        self.assertEqual(model.with_context(lang="fr_FR").name, french)
        self.assertEqual(
            model.with_context(lang="en_US").name,
            "Studio Demo Project",
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
        self.assertIn("Studio Demo Project", english["models/x_studio_project.xml"])
        self.assertNotIn("Projet Demo", english["models/x_studio_project.xml"])

    def test_source_term_survives_a_round_trip_under_a_translation(self):
        package = self.make_package(name="x_lang_rt")
        model = self.build_demo_content(package)
        self._translate(model, "Projet Demo")

        rendered = package.with_context(lang="fr_FR")._render_files()
        self.wipe_package_records(package)
        self.load_rendered(package, rendered)

        reloaded = self.env["ir.model"]._get("x_studio_project")
        self.assertEqual(
            reloaded.with_context(lang="en_US").name,
            "Studio Demo Project",
            "the English source term must not be overwritten by its translation",
        )


@tagged("post_install", "-at_install")
class TestRawIdRefusal(StudioCase):
    def test_many2one_reference_is_refused_rather_than_emitted(self):
        """Its value is a raw id and would not survive a fresh install."""
        package = self.make_package(name="x_m2oref")
        model = self.build_demo_content(package)
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_ref",
                "field_description": "Ref",
                "ttype": "many2one_reference",
                "model_id": model.id,
            }
        )
        package._assign(field)
        serializer = self.env["studio.serializer.ir.model.fields"].with_context(
            studio_package=package.name
        )
        record = self.env["res.partner"].search([], limit=1)
        # A record whose many2one_reference actually holds a value.
        with self.assertRaises(UserError):
            serializer._field_node(
                self.env["base.automation"].new(
                    {"trg_field_ref": record.id, "model_id": model.id}
                ),
                "trg_field_ref",
            )


@tagged("post_install", "-at_install")
class TestOwnershipConflicts(StudioCase):
    def test_assigning_a_record_owned_elsewhere_is_refused(self):
        """Returning silently made 'assign to my package' a no-op."""
        first = self.make_package(name="x_owner_a")
        second = self.make_package(name="x_owner_b")
        model = self.env["ir.model"].create(
            {"name": "Shared", "model": "x_shared", "field_id": []}
        )
        first._assign(model)
        with self.assertRaises(UserError):
            second._assign(model)


@tagged("post_install", "-at_install")
class TestTeardownKeepsFiles(StudioCase):
    def test_write_after_delete_does_not_erase_the_kept_source(self):
        """The confirm dialog promises the files survive so you can reinstall."""
        package = self.make_package(name="x_keepfiles")
        self.build_demo_content(package)
        package.action_write_files()
        source = os.path.join(package.root_path, "models/x_studio_project.xml")
        self.assertTrue(os.path.isfile(source))

        package.action_delete_records()
        package.action_write_files()

        self.assertTrue(
            os.path.isfile(source),
            "the prune pass must not delete files the teardown promised to keep",
        )


@tagged("post_install", "-at_install")
class TestWhitespaceSafety(StudioCase):
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
class TestDriftAccounting(StudioCase):
    def test_freshly_written_files_are_not_reported_as_drifted(self):
        """disk_checksum was left stale, marking every file drifted on write."""
        package = self.make_package(name="x_drift_acct")
        self.build_demo_content(package)
        package.action_write_files()
        self.assertFalse(
            package.file_ids.filtered("drifted"),
            "nothing can be drifted immediately after we wrote it",
        )
        self.assertEqual(package.state, "synced")


@tagged("post_install", "-at_install")
class TestDeterministicRefs(StudioCase):
    def test_x2many_refs_are_sorted(self):
        """Recordset order follows the comodel's _order, which for res.groups
        is a translated, non-unique column."""
        package = self.make_package(name="x_refsort")
        self.build_demo_content(package)
        view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project")], limit=1
        )
        groups = self.env.ref("base.group_user") + self.env.ref("base.group_system")
        view.groups_id = [(6, 0, groups.ids)]
        rendered = package._render_files()["views/x_studio_project_views.xml"]
        refs = [
            part.split("'")[1] for part in rendered.split("ref(")[1:] if "'" in part
        ]
        self.assertEqual(refs, sorted(refs))


@tagged("post_install", "-at_install")
class TestStudioAccessControl(StudioCase):
    """D1 -- every RPC-reachable studio method was callable by any user.

    ``ir.model.access`` cannot protect this: ``studio.view.editor`` is an
    AbstractModel, which ACL rows do not apply to, and ``call_kw`` is
    ``auth="user"`` with no access check of its own. Since these methods write
    Python and XML into a directory on ``addons_path``, an unguarded entry
    point is remote code execution, not a data leak.
    """

    def setUp(self):
        super().setUp()
        self.outsider = self.env["res.users"].create(
            {
                "name": "Nosy Employee",
                "login": "studio_outsider",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    def test_view_editor_methods_refuse_a_plain_user(self):
        editor = self.env["studio.view.editor"].with_user(self.outsider)
        view = self.env.ref("base.view_partner_form")
        package = self.make_package(name="x_acl_probe")
        for call in (
            lambda: editor.get_editable_views("res.partner"),
            lambda: editor.get_view_nodes(view.id),
            lambda: editor.get_addable_fields("res.partner", view.id),
            lambda: editor.apply_operation(
                view.id,
                package.id,
                {
                    "type": "add_field",
                    "name": "ref",
                    "xpath": "//field[@name='function']",
                    "position": "after",
                },
            ),
        ):
            with self.assertRaises(AccessError):
                call()

    def test_package_write_methods_refuse_a_plain_user(self):
        package = self.make_package(name="x_acl_pkg")
        # sudo() to dodge the record-level ACL so we are proving the *method*
        # guard fires, not merely that the user cannot read studio.package.
        as_outsider = package.with_user(self.outsider).sudo(False)
        with self.assertRaises(AccessError):
            as_outsider.action_write_files()
        with self.assertRaises(AccessError):
            as_outsider.action_reload()
        with self.assertRaises(AccessError):
            as_outsider.action_delete_records()

    def test_superuser_and_settings_admin_still_pass(self):
        """The guard must not lock out install, data loading, or the admin."""
        package = self.make_package(name="x_acl_ok")
        self.assertTrue(package.action_check_drift())
        admin = self.env.ref("base.user_admin")
        self.assertTrue(admin.has_group("app_builder_base.group_studio_manager"))


@tagged("post_install", "-at_install")
class TestLocatorAmbiguity(StudioCase):
    """D2 -- a bare //tag[@name='x'] is not a locator when it is not unique.

    ``res.partner``'s form carries ``function`` three times: once on the sheet
    and twice inside inline ``child_ids`` subviews grafted in by
    ``_postprocess_tag_field``. ``locate_node`` takes the first match, so the
    picker was handing out one path for three different nodes and an edit
    aimed at a subview column silently patched the sheet.
    """

    def test_repeated_names_get_distinct_qualified_paths(self):
        editor = self.env["studio.view.editor"]
        view = self.env.ref("base.view_partner_form")
        nodes = editor.get_view_nodes(view.id)
        functions = [n for n in nodes if n["is_field"] and n["label"] == "function"]
        self.assertGreater(len(functions), 1, "fixture assumes a repeated name")
        paths = [n["xpath"] for n in functions]
        self.assertEqual(len(set(paths)), len(paths), "each occurrence needs its own")
        self.assertNotIn("//field[@name='function']", paths)

    def test_unique_names_keep_the_bare_predicate(self):
        """The qualification must be conditional: //field[@name] is preferred
        precisely because it survives a sibling being inserted."""
        editor = self.env["studio.view.editor"]
        view = self.env.ref("base.view_partner_form")
        nodes = editor.get_view_nodes(view.id)
        vat = next(n for n in nodes if n["is_field"] and n["label"] == "vat")
        self.assertEqual(vat["xpath"], "//field[@name='vat']")

    def test_every_emitted_locator_resolves_to_exactly_one_node(self):
        """The property that actually matters, asserted over the whole tree."""
        editor = self.env["studio.view.editor"]
        view = self.env.ref("base.view_partner_form")
        root = etree.fromstring(view.get_combined_arch().encode())
        for node in editor.get_view_nodes(view.id):
            matches = root.xpath(node["xpath"])
            self.assertEqual(
                len(matches),
                1,
                "%s matched %d nodes" % (node["xpath"], len(matches)),
            )


@tagged("post_install", "-at_install")
class TestOrphanManualField(StudioCase):
    """D3 -- autocapture had no else, so a manual field on a core model was
    created live and written to no file at all: the exact drift the project
    exists to prevent, on the models people reach for first."""

    def test_manual_field_on_a_core_model_is_captured_via_context(self):
        package = self.make_package(name="x_orphan_pkg")
        partner_model = self.env["ir.model"]._get("res.partner")
        field = (
            self.env["ir.model.fields"]
            .with_context(studio_package_id=package.id)
            .create(
                {
                    "name": "x_studio_loyalty",
                    "ttype": "integer",
                    "field_description": "Loyalty",
                    "model_id": partner_model.id,
                }
            )
        )
        self.assertEqual(
            field.studio_package_id,
            package,
            "a manual field on a core model must land in the editing package",
        )
        rendered = package._render_files()
        self.assertTrue(
            any("x_studio_loyalty" in body for body in rendered.values()),
            "the field must reach the source tree, not just the database",
        )

    def test_orphan_field_warns_rather_than_raising(self):
        """A non-studio caller creating a manual field is legitimate and must
        not be forced into a package -- but it must not be silent either."""
        partner_model = self.env["ir.model"]._get("res.partner")
        with self.assertLogs(
            "odoo.addons.app_builder_base.models.studio_owned_mixin", "WARNING"
        ) as logs:
            field = self.env["ir.model.fields"].create(
                {
                    "name": "x_studio_unowned",
                    "ttype": "char",
                    "field_description": "Unowned",
                    "model_id": partner_model.id,
                }
            )
        self.assertTrue(field.exists())
        self.assertTrue(any("x_studio_unowned" in line for line in logs.output))


@tagged("post_install", "-at_install")
class TestAddableFieldScope(StudioCase):
    """D4 -- arch.iter() is recursive, so a field inside an embedded x2many
    subview (a different model entirely) masked the parent's field of the same
    name and the palette came back empty on core models."""

    def test_subview_fields_do_not_mask_parent_model_fields(self):
        editor = self.env["studio.view.editor"]
        view = self.env.ref("base.view_partner_form")
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
        addable = {f["name"] for f in editor.get_addable_fields("res.partner", view.id)}
        real = {n for n in nested_only if n in self.env["res.partner"]._fields}
        self.assertTrue(real, "fixture assumes the subview introduces a name")
        self.assertTrue(
            real & addable,
            "a field only present inside a subview is still addable to the form",
        )


@tagged("post_install", "-at_install")
class TestAddFieldIdempotence(StudioCase):
    """D5 -- _op_add_field always appended a new <xpath>, so a double-click put
    the field into the combined arch twice."""

    def test_same_field_twice_is_a_no_op(self):
        package = self.make_package(name="x_idem_pkg")
        editor = self.env["studio.view.editor"]
        view = self.env.ref("base.view_partner_form")
        operation = {
            "type": "add_field",
            "name": "ref",
            "xpath": "//field[@name='function']",
            "position": "after",
        }
        editor.apply_operation(view.id, package.id, operation)
        result = editor.apply_operation(view.id, package.id, operation)
        root = etree.fromstring(
            self.env["ir.ui.view"].browse(result["view_id"]).arch.encode()
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
        editor = self.env["studio.view.editor"]
        view = self.env.ref("base.view_partner_form")
        for name in ("ref", "lang"):
            editor.apply_operation(
                view.id,
                package.id,
                {
                    "type": "add_field",
                    "name": name,
                    "xpath": "//field[@name='function']",
                    "position": "after",
                },
            )
        extension = self.env["ir.ui.view"].search(
            [("inherit_id", "=", view.id), ("priority", "=", 99)], limit=1
        )
        root = etree.fromstring(extension.arch.encode())
        self.assertEqual(len(root.findall("xpath")), 2)


@tagged("post_install", "-at_install")
class TestOwnedViewsAreEditedDirectly(StudioCase):
    """D6 -- apply_operation always emitted an inheriting view, so a package's
    own generated form shipped alongside a pile of <xpath> patches against
    itself in the same addon: source no developer would have written."""

    def _owned_form(self, package):
        self.build_demo_content(package)
        return self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project"), ("type", "=", "form")], limit=1
        )

    def test_a_package_edits_its_own_primary_view_in_place(self):
        package = self.make_package(name="x_owned_pkg")
        form = self._owned_form(package)
        self.assertEqual(form.studio_package_id, package, "fixture must own it")
        before = self.env["ir.ui.view"].search_count([("inherit_id", "=", form.id)])
        result = self.env["studio.view.editor"].apply_operation(
            form.id,
            package.id,
            {
                "type": "add_field",
                "name": "x_budget",
                "xpath": "//field[@name='x_name']",
                "position": "after",
            },
        )
        self.assertEqual(result["view_id"], form.id, "must edit the view itself")
        self.assertIn('name="x_budget"', form.arch)
        self.assertNotIn("<xpath", form.arch, "no patch against our own view")
        self.assertEqual(
            self.env["ir.ui.view"].search_count([("inherit_id", "=", form.id)]),
            before,
            "no extension view may be created for a view we own",
        )

    def test_a_foreign_view_still_gets_an_inheriting_patch(self):
        """The invariant that makes this project worth using is unchanged."""
        package = self.make_package(name="x_foreign_pkg")
        core_view = self.env.ref("base.view_partner_form")
        original = core_view.arch
        result = self.env["studio.view.editor"].apply_operation(
            core_view.id,
            package.id,
            {
                "type": "add_field",
                "name": "ref",
                "xpath": "//field[@name='function']",
                "position": "after",
            },
        )
        extension = self.env["ir.ui.view"].browse(result["view_id"])
        self.assertNotEqual(extension, core_view)
        self.assertEqual(extension.inherit_id, core_view)
        self.assertEqual(extension.mode, "extension")
        self.assertEqual(core_view.arch, original, "core view must be untouched")


@tagged("post_install", "-at_install")
class TestEmitterIsIdempotent(StudioCase):
    """Phase 2 -- the .py file is the definition, so it is regenerated on every
    write rather than written once. That is only safe because it is also the
    *input*: what the parser can read is reproduced, what it cannot freezes the
    model instead of being overwritten."""

    def _python_package(self):
        package = self.make_package(name="x_emit_pkg")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_graduate(["x_studio_project"])
        return package

    def _source(self, package):
        path = os.path.join(package.root_path, "models/x_studio_project.py")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def _write(self, package, content):
        path = os.path.join(package.root_path, "models/x_studio_project.py")
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
            '    _description = "Studio Demo Project"',
            '    _description = "Studio Demo Project"\n'
            '    x_hand_added = fields.Char(string="Hand Added")',
        )
        self._write(package, edited)

        package.action_write_files()

        rendered = self._source(package)
        self.assertIn("x_hand_added", rendered)
        self.assertIn('string="Hand Added"', rendered)

    def test_an_unparseable_file_freezes_the_model_and_is_kept(self):
        package = self._python_package()
        self._write(package, self._source(package) + "\n    _inherits = {'a': 'b'}\n")

        package.action_write_files()

        entry = package.model_ids.filtered(lambda m: m.model == "x_studio_project")
        self.assertEqual(entry.source, "frozen")
        self.assertTrue(entry.parse_error)
        self.assertIn("_inherits", self._source(package), "the file must be kept")

    def test_a_frozen_model_can_be_thawed_once_the_file_parses(self):
        package = self._python_package()
        good = self._source(package)
        self._write(package, good + "\n    _inherits = {'a': 'b'}\n")
        package.action_write_files()
        entry = package.model_ids.filtered(lambda m: m.model == "x_studio_project")
        self.assertEqual(entry.source, "frozen")

        self._write(package, good)
        entry.action_retry_parse()
        self.assertEqual(entry.source, "python")
        self.assertFalse(entry.parse_error)

    def test_a_python_model_is_not_also_emitted_as_xml(self):
        """Two definitions of one model is the unrecoverable state:
        _add_manual_models builds a second class for the same _name and
        _process_end then reaps our own xmlids."""
        package = self._python_package()
        files = package._render_files()
        self.assertIn("models/x_studio_project.py", files)
        self.assertNotIn("models/x_studio_project.xml", files)


@tagged("post_install", "-at_install")
class TestLoadOrderFollowsModelSource(StudioCase):
    """security/ had to follow models/ only because generated ACLs ref an
    ir.model record that models/*.xml defines. A package whose models are all
    Python has no such file: reflection creates the row during init_models,
    which runs before load_data."""

    def test_xml_models_keep_security_after_models(self):
        package = self.make_package(name="x_order_xml")
        self.build_demo_content(package)
        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertLess(
            data.index("models/x_studio_project.xml"),
            data.index("security/ir.model.access.csv"),
        )

    def test_python_models_get_the_conventional_order_back(self):
        package = self.make_package(name="x_order_py")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_graduate(["x_studio_project"])
        data = ast.literal_eval(package._render_files()["__manifest__.py"])["data"]
        self.assertNotIn("models/x_studio_project.xml", data)
        self.assertEqual(
            data[0],
            "security/ir.model.access.csv",
            "with no XML models, security may load first as in any addon",
        )


@tagged("post_install", "-at_install")
class TestDeleteRecordsSpareReflection(StudioCase):
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
        reflected = self.env["ir.model.fields"].create(
            {
                "name": "x_reflected",
                "ttype": "char",
                "field_description": "Reflected",
                "model_id": model.id,
                "state": "base",
            }
        )
        self.env["ir.model.data"].create(
            {
                "module": package.name,
                "name": "field_x_studio_project__x_reflected",
                "model": "ir.model.fields",
                "res_id": reflected.id,
            }
        )

        deletable = package._deletable_data()
        self.assertNotIn(
            reflected.id,
            [d.res_id for d in deletable if d.model == "ir.model.fields"],
            "a base-state field is reflection output, not ours to unlink",
        )
        self.assertTrue(deletable, "our own manual records must still be deletable")

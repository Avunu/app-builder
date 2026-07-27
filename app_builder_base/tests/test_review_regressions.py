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

from odoo.exceptions import UserError
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

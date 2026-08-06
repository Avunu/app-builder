# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The invariant the whole architecture rests on.

Writing the database and the file in the same transaction is only legitimate if
loading the file reproduces the database exactly. If that holds, the DB write is
an optimisation; if it does not, we have two competing sources of truth and the
"files are truth" claim is a lie. So this is the test that decides whether the
design works.
"""

import os

from odoo.tests import tagged

from .common import StudioCase


@tagged("post_install", "-at_install")
class TestRoundTrip(StudioCase):
    def test_render_is_deterministic(self):
        """Rendering twice from unchanged state produces identical bytes."""
        package = self.make_package()
        self.build_demo_content(package)
        first = package._render_files()
        second = package._render_files()
        self.assertEqual(first, second)

    def test_roundtrip_through_odoo_importer(self):
        """serialize -> wipe -> load -> serialize is a fixed point.

        Record ids all change across the wipe/reload, so byte-identical output
        also proves nothing leaks raw ids into the generated files.
        """
        package = self.make_package()
        self.build_demo_content(package)
        before = package._render_files()

        self.assertIn("models/x_studio_project.xml", before)
        self.assertIn("views/x_studio_project_views.xml", before)
        self.assertIn("security/ir.model.access.csv", before)

        original_ids = {
            entry.name: entry.res_id
            for entry in self.env["ir.model.data"].search(
                [("module", "=", package.name)]
            )
        }

        self.wipe_package_records(package)
        self.assertFalse(
            self.env["ir.model.data"].search([("module", "=", package.name)])
        )

        self.load_rendered(package, before)
        after = package._render_files()

        reloaded_ids = {
            entry.name: entry.res_id
            for entry in self.env["ir.model.data"].search(
                [("module", "=", package.name)]
            )
        }
        self.assertEqual(
            set(original_ids), set(reloaded_ids), "xmlid set must survive a reload"
        )

        for path in sorted(set(before) | set(after)):
            self.assertEqual(
                before.get(path),
                after.get(path),
                "round-trip changed %s" % path,
            )

    def test_reloaded_model_is_functional(self):
        """A model rebuilt from files is a real, usable ORM model."""
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        self.wipe_package_records(package)
        self.load_rendered(package, rendered)

        self.assertIn("x_studio_project", self.env)
        record = self.env["x_studio_project"].create(
            {"x_name": "Rebuilt", "x_budget": 21.0}
        )
        self.assertEqual(record.x_name, "Rebuilt")
        # The stored compute survived serialization as data, not code.
        self.assertEqual(record.x_budget_doubled, 42.0)
        # Selection values came back in order.
        field = self.env["ir.model.fields"]._get("x_studio_project", "x_stage")
        self.assertEqual(
            [s.value for s in field.selection_ids.sorted("sequence")],
            ["draft", "done"],
        )

    def test_no_raw_ids_in_output(self):
        """Relations must always be emitted as refs, never integer ids."""
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        menus = rendered["views/menus.xml"]
        self.assertIn('ref="', menus)
        models_xml = rendered["models/x_studio_project.xml"]
        self.assertIn('ref="model_x_studio_project"', models_xml)


@tagged("post_install", "-at_install")
class TestRoundTripKeepsTranslations(StudioCase):
    """The other half of the invariant, and the one that was missing.

    `test_roundtrip_through_odoo_importer` compares the *render* before and
    after, which is `render(load(render(db))) == render(db)` -- the emitter
    measured against itself. A value the emitter never writes is destroyed by
    the wipe, absent from the reload, and absent from both renders, so it passes
    while the data is gone. That is exactly how translations were lost.

    These compare the *records*: `load(render(db)) == db`, which is the
    statement the architecture actually needs.
    """

    def setUp(self):
        super().setUp()
        self.env["res.lang"]._activate_lang("fr_FR")

    def _translate(self, record, fname, value, lang="fr_FR"):
        """`update_field_translations` rather than a write under a lang context.

        Core's own translation tests use it, and it is unambiguous: a write
        with `lang=` in context depends on whether the source value is already
        stored, and for a term-based field it silently rewrites the source when
        it cannot line the terms up. `value` is a string for a whole-value
        field and a `{term_en: term_lang}` map for a term-based one.
        """
        record.update_field_translations(fname, {lang: value})
        self.env.flush_all()

    def test_a_translated_label_survives_the_round_trip(self):
        package = self.make_package()
        self.build_demo_content(package)
        field = self.env["ir.model.fields"].search(
            [("model", "=", "x_studio_project"), ("name", "=", "x_name")], limit=1
        )
        self.assertTrue(field, "demo content must provide the field")
        self._translate(field, "field_description", "Nom de l'affaire")

        english = field.with_context(lang="en_US").field_description
        files = package._render_files()
        self.assertIn("i18n/fr_FR.po", files, "a translation must produce a PO file")
        self.assertIn("Nom de l'affaire", files["i18n/fr_FR.po"])

        # Read the source term before the wipe: the record below is a new row.
        self.wipe_package_records(package)
        self.load_rendered(package, files)
        self.load_translations(package, files)

        restored = self.env["ir.model.fields"].search(
            [("model", "=", "x_studio_project"), ("name", "=", "x_name")], limit=1
        )
        self.assertEqual(
            restored.with_context(lang="fr_FR").field_description,
            "Nom de l'affaire",
            "the translation must come back from source, not just the source term",
        )
        self.assertEqual(restored.with_context(lang="en_US").field_description, english)

    def test_a_model_label_translation_survives(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"].search([("model", "=", "x_studio_project")])
        self._translate(model, "name", "Affaire de démonstration")

        files = package._render_files()
        self.wipe_package_records(package)
        self.load_rendered(package, files)
        self.load_translations(package, files)

        restored = self.env["ir.model"].search([("model", "=", "x_studio_project")])
        self.assertEqual(
            restored.with_context(lang="fr_FR").name, "Affaire de démonstration"
        )

    def test_a_translated_term_inside_a_view_arch_survives(self):
        """`arch_db` is term-translated and sits in _studio_ignored, so the
        generic derivation cannot see it. Odoo references it as
        `model_terms:ir.ui.view,arch_db:...` for the same reason."""
        package = self.make_package()
        self.build_demo_content(package)
        # A view of our own with a term we control, rather than whichever
        # labels the scaffold happened to produce -- an arch without the
        # expected string would make this test skip and read as passing.
        view = self.env["ir.ui.view"].create(
            {
                "name": "x_studio_project.translated",
                "model": "x_studio_project",
                "type": "form",
                "arch": '<form><sheet><separator string="Budget"/></sheet></form>',
            }
        )
        package.studio_capture(view)
        self.assertIn("Budget", view.with_context(lang="en_US").arch_db)
        self._translate(view, "arch_db", {"Budget": "Enveloppe"})

        files = package._render_files()
        self.assertIn("i18n/fr_FR.po", files)
        self.assertIn("model_terms:ir.ui.view,arch_db", files["i18n/fr_FR.po"])

        self.wipe_package_records(package)
        self.load_rendered(package, files)
        self.load_translations(package, files)

        restored = self.env["ir.ui.view"].search(
            [("name", "=", "x_studio_project.translated")], limit=1
        )
        self.assertIn("Enveloppe", restored.with_context(lang="fr_FR").arch_db)

    def test_no_translations_means_no_po_file(self):
        """An addon with nothing to translate should have no i18n directory."""
        package = self.make_package()
        self.build_demo_content(package)
        files = package._render_files()
        self.assertFalse(
            [p for p in files if p.startswith("i18n/")],
            "an empty PO file is a file somebody has to wonder about",
        )

    def _write_po(self, package, lang, body):
        directory = os.path.join(package.root_path, "i18n")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "%s.po" % lang)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def test_an_entry_we_do_not_emit_survives_a_write(self):
        """The PO is the one generated file an external workflow owns."""
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"].search([("model", "=", "x_studio_project")])
        self._translate(model, "name", "Affaire de démonstration")
        package.action_write_files()

        external = (
            "\n#. module: %(pkg)s\n"
            "#: code:addons/%(pkg)s/models/thing.py:0\n"
            'msgid "Something in code"\n'
            'msgstr "Quelque chose"\n' % {"pkg": package.name}
        )
        self._write_po(
            package, "fr_FR", package._render_files()["i18n/fr_FR.po"] + external
        )
        rendered = package._render_files()["i18n/fr_FR.po"]
        self.assertIn("Quelque chose", rendered, "an entry we do not emit must survive")
        self.assertIn("Affaire de démonstration", rendered)

    def test_an_entry_we_do_emit_is_refreshed_from_the_database(self):
        """For a term this package owns, the database is what states it."""
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"].search([("model", "=", "x_studio_project")])
        self._translate(model, "name", "Affaire de démonstration")
        package.action_write_files()

        stale = package._render_files()["i18n/fr_FR.po"].replace(
            "Affaire de démonstration", "Traduction périmée"
        )
        self._write_po(package, "fr_FR", stale)
        rendered = package._render_files()["i18n/fr_FR.po"]
        self.assertIn("Affaire de démonstration", rendered)
        self.assertNotIn("Traduction périmée", rendered)

    def test_merging_is_deterministic(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"].search([("model", "=", "x_studio_project")])
        self._translate(model, "name", "Affaire de démonstration")
        package.action_write_files()
        self.assertEqual(
            package._render_files()["i18n/fr_FR.po"],
            package._render_files()["i18n/fr_FR.po"],
        )

    def test_po_rendering_is_deterministic(self):
        package = self.make_package()
        self.build_demo_content(package)
        model = self.env["ir.model"].search([("model", "=", "x_studio_project")])
        self._translate(model, "name", "Affaire de démonstration")
        self.assertEqual(
            package._render_files()["i18n/fr_FR.po"],
            package._render_files()["i18n/fr_FR.po"],
            "a timestamp in the header would rewrite every PO file on every save",
        )

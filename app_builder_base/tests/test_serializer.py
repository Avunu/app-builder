# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer dispatch, field emission and file placement."""

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import StudioCase


@tagged("post_install", "-at_install")
class TestSerializer(StudioCase):
    def test_dispatch_by_naming_convention(self):
        serializers = self.env["studio.serializer"]
        self.assertEqual(
            serializers._for_model("ir.ui.view")._studio_model, "ir.ui.view"
        )
        self.assertIsNone(serializers._for_model("res.partner"))

    def test_known_models_are_registered(self):
        known = set(self.env["studio.serializer"]._serializable_models())
        for expected in (
            "ir.model",
            "ir.model.fields",
            "ir.model.fields.selection",
            "ir.ui.view",
            "ir.ui.menu",
            "ir.actions.act_window",
            "ir.actions.server",
            "ir.model.access",
            "ir.rule",
        ):
            self.assertIn(expected, known)

    def test_missing_xmlid_raises_rather_than_emitting_an_id(self):
        """A raw id would not survive a fresh install, so refuse to emit one."""
        package = self.make_package()
        model = self.env["ir.model"].create(
            {
                "name": "Orphan",
                "model": "x_studio_orphan",
                "field_id": [],
            }
        )
        # model_id deliberately not assigned an xmlid
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_thing",
                "field_description": "Thing",
                "ttype": "char",
                "model_id": model.id,
            }
        )
        serializer = self.env["studio.serializer.ir.model.fields"].with_context(
            studio_package=package.name
        )
        with self.assertRaises(UserError):
            serializer._serialize(field, "%s.field_x" % package.name)

    def test_same_module_refs_are_shortened(self):
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        models_xml = rendered["models/x_studio_project.xml"]
        # Our own model: bare name. A foreign group: fully qualified.
        self.assertIn('ref="model_x_studio_project"', models_xml)
        self.assertNotIn('ref="%s.model_x_studio_project"' % package.name, models_xml)
        access_csv = rendered["security/ir.model.access.csv"]
        self.assertIn("base.group_user", access_csv)

    def test_boolean_defaults_are_not_dropped_when_default_is_true(self):
        """Skipping a False whose default is True would flip it on reload."""
        package = self.make_package()
        self.build_demo_content(package)
        rule = self.env["ir.rule"].create(
            {
                "name": "demo rule",
                "model_id": self.env["ir.model"]._get("x_studio_project").id,
                "domain_force": "[(1, '=', 1)]",
                "perm_unlink": False,
            }
        )
        package._assign(rule)
        rendered = package._render_files()
        security = rendered["security/x_studio_project_security.xml"]
        self.assertIn('name="perm_unlink"', security)
        self.assertNotIn('name="perm_read"', security)

    def test_manifest_depends_are_derived_from_refs(self):
        """A generated module must declare whatever its refs point at.

        Regression: a menu referencing app_builder_base.menu_studio_root shipped
        with depends=['base'] and could not be installed into a fresh database.
        """
        import ast

        package = self.make_package()
        self.build_demo_content(package)
        # An ACL referencing base.group_user, and a view inheriting a core view.
        ext = self.env["ir.ui.view"].create(
            {
                "name": "res.partner.form.studio.dep",
                "model": "res.partner",
                "inherit_id": self.env.ref("base.view_partner_form").id,
                "priority": 99,
                "arch": "<xpath expr=\"//field[@name='function']\" "
                'position="after"><field name="ref"/></xpath>',
            }
        )
        package._assign(ext)

        rendered = package._render_files()
        depends = ast.literal_eval(rendered["__manifest__.py"])["depends"]
        self.assertIn("base", depends)
        self.assertNotIn(package.name, depends, "a package must never depend on itself")
        self.assertEqual(depends, sorted(depends), "depends must be ordered")

    def test_manifest_depends_include_foreign_parent_menu(self):
        package = self.make_package()
        self.build_demo_content(package)
        action = self.env["ir.actions.act_window"].search(
            [("res_model", "=", "x_studio_project")], limit=1
        )
        menu = self.env["ir.ui.menu"].create(
            {
                "name": "Nested Studio Menu",
                "parent_id": self.env.ref("app_builder_base.menu_studio_root").id,
                "action": "ir.actions.act_window,%d" % action.id,
            }
        )
        package._assign(menu)

        import ast

        manifest = ast.literal_eval(package._render_files()["__manifest__.py"])
        depends = manifest["depends"]
        self.assertIn(
            "app_builder_base",
            depends,
            "referencing a menu from another module must add it to depends",
        )

    def test_default_valued_fields_are_omitted(self):
        """Emitting every default would bury real changes in diff noise."""
        package = self.make_package()
        self.build_demo_content(package)
        models_xml = package._render_files()["models/x_studio_project.xml"]
        for noise in (
            '<field name="domain">[]</field>',
            '<field name="store" eval="True"/>',
            '<field name="selectable" eval="True"/>',
            '<field name="on_delete">set null</field>',
            '<field name="copied" eval="True"/>',
        ):
            self.assertNotIn(noise, models_xml, "%s is a default and is noise" % noise)
        # ...but a genuinely non-default value is still emitted.
        self.assertIn('<field name="required" eval="True"/>', models_xml)

    def test_inherited_docstring_is_not_emitted_as_info(self):
        """_reflect_model_params fills 'info' from the class MRO docstring."""
        package = self.make_package()
        self.build_demo_content(package)
        models_xml = package._render_files()["models/x_studio_project.xml"]
        self.assertNotIn("Main super-class", models_xml)
        self.assertNotIn('<field name="info">', models_xml)

    def test_real_info_is_preserved(self):
        package = self.make_package()
        model = self.build_demo_content(package)
        model.info = "A genuinely documented model."
        models_xml = package._render_files()["models/x_studio_project.xml"]
        self.assertIn("A genuinely documented model.", models_xml)

    def test_magic_columns_are_never_owned(self):
        """model.field_id includes id/create_uid/...; those belong to Odoo.

        Emitting them would produce records a reload cannot reproduce, and Odoo
        refuses to unlink them at all.
        """
        package = self.make_package()
        model = self.build_demo_content(package)
        magic = model.field_id.filtered(lambda f: f.state == "base")
        self.assertTrue(magic, "sanity: the model should have reflected base fields")

        owned = self.env["ir.model.data"].search(
            [
                ("module", "=", package.name),
                ("model", "=", "ir.model.fields"),
                ("res_id", "in", magic.ids),
            ]
        )
        self.assertFalse(owned, "base fields must not receive a package xmlid")

        models_xml = package._render_files()["models/x_studio_project.xml"]
        for name in ("create_uid", "create_date", "write_uid", "__last_update"):
            self.assertNotIn('">%s<' % name, models_xml)

    def test_field_type_specific_noise_is_filtered(self):
        """HTML sanitize flags on a char field would be meaningless output."""
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        models_xml = rendered["models/x_studio_project.xml"]
        self.assertNotIn("sanitize", models_xml)

    def test_file_placement_groups_by_subject_model(self):
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        self.assertIn("models/x_studio_project.xml", rendered)
        self.assertIn("views/x_studio_project_views.xml", rendered)
        self.assertIn("security/ir.model.access.csv", rendered)
        self.assertIn("__manifest__.py", rendered)
        self.assertIn("__init__.py", rendered)

    def test_arch_is_emitted_as_xml_typed_field(self):
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        views = rendered["views/x_studio_project_views.xml"]
        self.assertIn('<field name="arch" type="xml">', views)
        # It must parse, and contain the real form body.
        root = etree.fromstring(views.encode())
        self.assertTrue(root.findall(".//form"))

    def test_view_sort_puts_base_views_before_extensions(self):
        package = self.make_package()
        self.build_demo_content(package)
        base_view = self.env["ir.ui.view"].search(
            [("model", "=", "x_studio_project")], limit=1
        )
        ext = self.env["ir.ui.view"].create(
            {
                "name": "x_studio_project.form.ext",
                "model": "x_studio_project",
                "inherit_id": base_view.id,
                "priority": 99,
                "arch": '<xpath expr="//sheet" position="inside">'
                '<field name="x_active_flag"/></xpath>',
            }
        )
        package._assign(ext)
        views = package._render_files()["views/x_studio_project_views.xml"]
        self.assertLess(
            views.index('model="ir.ui.view"'),
            views.index("inherit_id"),
            "the inherited view must be declared before the view inheriting it",
        )

    def test_manifest_data_order_puts_models_before_views(self):
        package = self.make_package()
        self.build_demo_content(package)
        rendered = package._render_files()
        import ast

        data = ast.literal_eval(rendered["__manifest__.py"])["data"]
        self.assertLess(
            data.index("models/x_studio_project.xml"),
            data.index("views/x_studio_project_views.xml"),
        )
        self.assertLess(
            data.index("models/x_studio_project.xml"),
            data.index("security/ir.model.access.csv"),
            "ACLs reference models, so they must load after them",
        )

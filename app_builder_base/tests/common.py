# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Shared fixtures for the studio test suite."""

import ast
import io
import os
import tempfile

from odoo import Command
from odoo.tests import TransactionCase
from odoo.tools.convert import convert_csv_import, convert_xml_import
from odoo.tools.translate import TranslationImporter

# The one the package itself uses. A second copy here had already drifted:
# it predated base.automation and ir.cron, and a wipe that deletes a server
# action while a cron still references it fails on the foreign key.
from odoo.addons.app_builder_base.models.studio_package import UNLINK_ORDER


# Reverse dependency order for teardown: dependants before their dependencies,
# so no unlink ever hits a restrict/cascade surprise.
class _NamedBytesIO(io.BytesIO):
    """BytesIO with a .name, which convert_xml_import reads for error reports."""

    def __init__(self, content, name):
        super().__init__(content)
        self.name = name


class StudioCase(TransactionCase):
    """Base case for tests that create manual models.

    Test mode is required because ``registry.reset_changes()`` opens its own
    cursor to re-read custom models; without it that cursor would see the
    database as it was before the test started. Copied from Odoo's own
    ``TestIrModel``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry.enter_test_mode(cls.cr)
        cls.addClassCleanup(cls.registry.leave_test_mode)

    def setUp(self):
        # Must be registered before anything else so it runs last.
        self.addCleanup(self.registry.reset_changes)
        super().setUp()

    # -- fixtures ---------------------------------------------------------

    def make_package(self, name="x_studio_demo", installed=True, **overrides):
        tmp = tempfile.mkdtemp(prefix="studio-test-")
        values = {
            "name": name,
            "display_name_": "Studio Demo",
            "root_path": tmp,
            "auto_commit": "off",
        }
        values.update(overrides)
        package = self.env["studio.package"].create(values)
        if installed:
            self.register_module(package.name)
        return package

    def unwritable_path(self):
        """A path nothing can write to, whatever user the suite runs as.

        Deliberately not `chmod 0500`. This suite runs as root in CI, and root
        writes straight through mode bits -- which is how the read-only guard
        came to be covered by an assertion that only held for unprivileged
        developers, and stayed red in CI for days. A parent that is a regular
        file is refused for everybody, root included.
        """
        blocker = os.path.join(tempfile.mkdtemp(prefix="studio-test-ro-"), "blocker")
        with open(blocker, "w"):
            pass
        return os.path.join(blocker, "package")

    def register_module(self, name):
        """Register the package as an installed module.

        Graduation refuses to run otherwise, and rightly so: Odoo only imports
        Python for installed modules, so demoting the metadata without one would
        leave the model with no definition at all. Tests have to satisfy the
        same precondition the UI does.
        """
        Module = self.env["ir.module.module"]
        existing = Module.search([("name", "=", name)], limit=1)
        if existing:
            existing.state = "installed"
            return existing
        return Module.create({"name": name, "state": "installed"})

    def build_demo_content(self, package):
        """Create a representative slice of everything the studio can emit."""
        model = self.env["ir.model"].create(
            {
                "name": "Studio Demo Project",
                "model": "x_studio_project",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_name",
                            "ttype": "char",
                            "field_description": "Name",
                            "required": True,
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_budget",
                            "ttype": "float",
                            "field_description": "Budget",
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_active_flag",
                            "ttype": "boolean",
                            "field_description": "Is Active",
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_partner_id",
                            "ttype": "many2one",
                            "field_description": "Customer",
                            "relation": "res.partner",
                            "on_delete": "set null",
                        }
                    ),
                    Command.create(
                        {
                            "name": "x_stage",
                            "ttype": "selection",
                            "field_description": "Stage",
                        }
                    ),
                ],
            }
        )
        # A stored computed field: proof that "compute" is data, not code.
        self.env["ir.model.fields"].create(
            {
                "name": "x_budget_doubled",
                "field_description": "Budget Doubled",
                "ttype": "float",
                "model_id": model.id,
                "store": True,
                "depends": "x_budget",
                "compute": "for r in self:\n    r['x_budget_doubled'] = r.x_budget * 2",
            }
        )
        stage_field = model.field_id.filtered(lambda f: f.name == "x_stage")
        self.env["ir.model.fields.selection"].create(
            [
                {
                    "field_id": stage_field.id,
                    "value": "draft",
                    "name": "Draft",
                    "sequence": 10,
                },
                {
                    "field_id": stage_field.id,
                    "value": "done",
                    "name": "Done",
                    "sequence": 20,
                },
            ]
        )
        view = self.env["ir.ui.view"].create(
            {
                "name": "x_studio_project.form",
                "model": "x_studio_project",
                "arch": """
                    <form>
                        <sheet>
                            <group>
                                <field name="x_name"/>
                                <field name="x_budget"/>
                                <field name="x_partner_id"/>
                                <field name="x_stage"/>
                            </group>
                        </sheet>
                    </form>
                """,
            }
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "Studio Demo Projects",
                "res_model": "x_studio_project",
                "view_mode": "list,form",
            }
        )
        menu = self.env["ir.ui.menu"].create(
            {
                "name": "Studio Demo Projects",
                "action": "ir.actions.act_window,%d" % action.id,
            }
        )
        access = self.env["ir.model.access"].create(
            {
                "name": "x_studio_project all",
                "model_id": model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": False,
            }
        )

        package._assign(model)
        package._assign(model.field_id)
        package._assign(stage_field.selection_ids)
        package._assign(view)
        package._assign(action)
        package._assign(menu)
        package._assign(access)
        return model

    # -- round-trip helpers ----------------------------------------------

    def wipe_package_records(self, package):
        """Remove every record the package owns, plus its xmlids."""
        data = self.env["ir.model.data"].search([("module", "=", package.name)])
        by_model = {}
        for entry in data:
            by_model.setdefault(entry.model, []).append(entry.res_id)
        # Same flag Odoo's own _module_data_uninstall uses; without it
        # _prepare_update refuses to drop columns that carry module data.
        env = self.env(context=dict(self.env.context, _force_unlink=True))
        for model in UNLINK_ORDER:
            res_ids = by_model.pop(model, [])
            if res_ids and model in env:
                env[model].browse(res_ids).exists().unlink()
        for model, res_ids in by_model.items():
            if model in env:
                env[model].browse(res_ids).exists().unlink()
        data.exists().unlink()
        self.env.flush_all()

    def load_translations(self, package, files):
        """Load the generated PO files the way a module install would.

        `load_rendered` walks the manifest's `data`, and PO files are not in it
        -- Odoo discovers `i18n/*.po` by directory rather than by declaration
        (`ir_module.py:983`). So the round trip has to load them separately or
        it silently proves nothing about translations.
        """
        # `load` rather than `load_file`: the latter goes through `file_open`,
        # which refuses any path outside the addons root -- and swallows the
        # refusal with `suppress(FileNotFoundError)`, so a temp file loads
        # nothing and reports success.
        importer = TranslationImporter(self.env.cr, verbose=False)
        loaded = []
        for relative, content in files.items():
            if not relative.startswith("i18n/") or not relative.endswith(".po"):
                continue
            lang = relative[len("i18n/") : -len(".po")]
            buffer = io.BytesIO(content.encode("utf-8"))
            # PoFileReader reads `.name` to look for a sibling .pot
            # (translate.py:816) and a bare BytesIO has none.
            buffer.name = relative
            importer.load(buffer, "po", lang)
            loaded.append(lang)
        if loaded:
            importer.save(overwrite=True)
            self.env.flush_all()
        return loaded

    def load_rendered(self, package, files):
        """Feed rendered content back through Odoo's own XML/CSV importer.

        Going through ``convert_xml_import`` rather than a bespoke loader is the
        point: it proves the output is consumable by the real install path, not
        merely by our own parser.
        """
        idref = {}
        manifest = ast.literal_eval(files["__manifest__.py"])
        for relative in manifest["data"]:
            content = files[relative].encode("utf-8")
            if relative.endswith(".csv"):
                convert_csv_import(
                    self.env, package.name, relative, content, idref, "init", False
                )
            else:
                convert_xml_import(
                    self.env,
                    package.name,
                    _NamedBytesIO(content, "%s/%s" % (package.name, relative)),
                    idref,
                    "init",
                    False,
                )
        self.env.flush_all()

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Graduate-to-code: the handoff from metadata to owned source."""

from __future__ import annotations

import ast
import os
from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

# Fully-qualified, not the relative `..tools`/`.models...` forms otherwise
# used inside this addon: `make_package()` (`common.py`) returns `BuilderPackage`
# imported via this same `odoo.addons.app_builder_base....` path, so a `ModelSpec`
# built here has to resolve under that identity too, or `_seed_source_for`
# (`builder_package.py`) sees two `ModelSpec`s that print identically but come
# from different resolved module paths -- the exact trap `builder_package.py`'s
# own imports document for the same reason.
from odoo.addons.app_builder_base.models.builder_package_model import (
    BuilderPackageModel,
)
from odoo.addons.app_builder_base.tools import modelspec
from odoo.addons.base.models.ir_model import (
    IrModel,
    IrModelFields,
    IrModelSelection,
    field_xmlid,
    model_xmlid,
    selection_xmlid,
)

from ..tools import typed
from .common import BuilderCase, raises

if TYPE_CHECKING:
    # Only for the cast below; with `from __future__ import annotations`
    # nothing here needs this at runtime, the same `TYPE_CHECKING` bargain
    # `builder_package.py`'s own `env.cr` casts make.
    from odoo.sql_db import Cursor


@tagged("post_install", "-at_install")
class TestAdopt(BuilderCase):
    def _graduated_package(self):
        package = self.make_package(name="x_grad_pkg")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])
        return package

    # -- the xmlid contract that makes graduation safe --------------------

    def test_xmlids_match_odoo_reflection_helpers(self):
        """The whole handoff depends on this.

        When the Python class loads, _reflect_models/_reflect_fields register
        xmlids of their own. If ours differ, _process_end sees the originals as
        stale and deletes the very records we just graduated.
        """
        package = self.make_package(name="x_xmlid_pkg")
        model = self.build_demo_content(package)

        self.assertEqual(
            model.get_external_id()[model.id],
            model_xmlid(package.name, "x_builder_project"),
        )
        field = typed.model(self.env, IrModelFields)._get("x_builder_project", "x_name")
        self.assertEqual(
            field.get_external_id()[field.id],
            field_xmlid(package.name, "x_builder_project", "x_name"),
        )
        stage = typed.model(self.env, IrModelFields)._get(
            "x_builder_project", "x_stage"
        )
        draft = cast("IrModelSelection", stage.selection_ids).filtered(
            lambda s: s.value == "draft"
        )
        self.assertEqual(
            draft.get_external_id()[draft.id],
            selection_xmlid(package.name, "x_builder_project", "x_stage", "draft"),
        )

    # -- graduation -------------------------------------------------------

    def test_graduation_writes_python_and_wires_imports(self):
        package = self._graduated_package()
        # `root_path` is compute-only (`_compute_root_path`, builder_package.py)
        # and declared `str | Literal[False]` like any Char, but a package that
        # just graduated always has one -- same invariant cast as
        # `builder_package.py`'s own real read sites.
        root = cast("str", package.root_path)
        model_file = os.path.join(root, "models/x_builder_project.py")
        self.assertTrue(os.path.isfile(model_file))

        with open(model_file, encoding="utf-8") as handle:
            source = handle.read()
        ast.parse(source)
        self.assertIn("class XBuilderProject(models.Model):", source)

        with open(os.path.join(root, "models/__init__.py"), encoding="utf-8") as h:
            self.assertIn("from . import x_builder_project", h.read())
        with open(os.path.join(root, "__init__.py"), encoding="utf-8") as h:
            self.assertIn("from . import models", h.read())

    def test_graduation_stops_emitting_xml_metadata(self):
        """Emitting both the class and <record model="ir.model"> would double-define."""
        package = self._graduated_package()
        rendered = package._render_files()
        self.assertNotIn("models/x_builder_project.xml", rendered)
        self.assertFalse(
            os.path.isfile(
                os.path.join(
                    cast("str", package.root_path), "models/x_builder_project.xml"
                )
            ),
            "the superseded XML must be pruned from disk",
        )

    def test_graduation_keeps_views_actions_and_acls_as_xml(self):
        """Only the metadata moves; the rest stays as a hand-written addon would."""
        package = self._graduated_package()
        rendered = package._render_files()
        self.assertIn("views/x_builder_project_views.xml", rendered)
        self.assertIn("security/ir.model.access.csv", rendered)

    def test_manifest_still_lists_only_data_files(self):
        package = self._graduated_package()
        manifest = ast.literal_eval(package._render_files()["__manifest__.py"])
        for entry in manifest["data"]:
            self.assertTrue(entry.endswith((".xml", ".csv")), entry)

    def test_adoptd_file_is_never_overwritten(self):
        """Once handed off, the file is the developer's.

        After the class loads, reflection flips the fields to state='base', so
        regenerating would emit an empty class over working code.
        """
        package = self._graduated_package()
        model_file = os.path.join(
            cast("str", package.root_path), "models/x_builder_project.py"
        )
        with open(model_file, "a", encoding="utf-8") as handle:
            handle.write("\n    # hand-written by a developer\n")

        package.action_write_files()

        with open(model_file, encoding="utf-8") as handle:
            self.assertIn("hand-written by a developer", handle.read())

    def test_models_init_preserves_hand_added_imports(self):
        package = self._graduated_package()
        init_path = os.path.join(cast("str", package.root_path), "models/__init__.py")
        with open(init_path, "a", encoding="utf-8") as handle:
            handle.write("from . import my_own_module\n")

        package.action_write_files()

        with open(init_path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("from . import x_builder_project", content)
        self.assertIn("from . import my_own_module", content)

    def test_demotion_reclassifies_metadata_as_base(self):
        """'manual' is what makes _add_manual_models compete with the class.

        Reclassifying rather than deleting is what keeps _add_manual_models and
        _add_manual_fields (which both select on state='manual') from rebuilding
        a custom class that fights the Python one for the same _name.
        """
        package = self.make_package(name="x_demote_pkg")
        self.build_demo_content(package)
        package.action_write_files()
        package.action_adopt(["x_builder_project"])

        model = typed.model(self.env, IrModel).search(
            [("model", "=", "x_builder_project")]
        )
        self.assertTrue(model, "the row must survive; only its state changes")
        self.assertEqual(model.state, "base")
        self.assertFalse(
            self.env["ir.model.fields"].search(
                [("model", "=", "x_builder_project"), ("state", "=", "manual")]
            ),
            "a field left as manual would be added twice at startup",
        )

    def test_demotion_keeps_the_table_and_its_data(self):
        """The most destructive thing this feature could get wrong.

        ir.model.fields.unlink calls _drop_column. If demotion ever deletes
        instead of reclassifying, this test fails and user data is gone.
        """
        package = self.make_package(name="x_demote_data")
        self.build_demo_content(package)
        package.action_write_files()
        vals: dict[str, object] = {"x_name": "Keep me", "x_budget": 7.0}
        record = self.env["x_builder_project"].create(vals)  # pyright: ignore[reportArgumentType]
        record_id = record.id
        self.env.flush_all()

        package.action_adopt(["x_builder_project"])

        cr = cast("Cursor", self.env.cr)
        cr.execute(
            "SELECT x_name, x_budget FROM x_builder_project WHERE id = %s",
            (record_id,),
        )
        self.assertEqual(cr.fetchone(), ("Keep me", 7.0))

    def test_demotion_does_not_cascade_into_dependent_records(self):
        """Every model_id in Odoo is ondelete='cascade'.

        Regression: deleting the ir.model row silently took the access rules,
        record rules and automations with it.
        """
        package = self.make_package(name="x_demote_cascade")
        self.build_demo_content(package)
        model = typed.model(self.env, IrModel)._get("x_builder_project")
        rule_vals: dict[str, object] = {
            "name": "demote rule",
            "model_id": model.id,
            "domain_force": "[(1, '=', 1)]",
        }
        rule = self.env["ir.rule"].create(rule_vals)  # pyright: ignore[reportArgumentType]
        server_action_vals: dict[str, object] = {
            "name": "demote action",
            "model_id": model.id,
            "state": "code",
            "code": "pass",
        }
        server_action = self.env["ir.actions.server"].create(server_action_vals)  # pyright: ignore[reportArgumentType]
        package._assign([rule, server_action])
        package.action_write_files()

        package.action_adopt(["x_builder_project"])

        self.assertTrue(rule.exists(), "record rules must survive graduation")
        self.assertTrue(server_action.exists(), "server actions must survive")
        self.assertTrue(
            self.env["ir.model.access"].search(
                [("model_id.model", "=", "x_builder_project")]
            ),
            "access rules must survive",
        )

    def test_demotion_preserves_the_xmlids_reflection_will_reuse(self):
        """They must stay: reflection re-registers these exact names."""
        package = self.make_package(name="x_demote_xmlid")
        self.build_demo_content(package)
        package.action_write_files()
        before = set(
            self.env["ir.model.data"]
            .search([("module", "=", package.name), ("model", "=", "ir.model")])
            .mapped("name")
        )
        package.action_adopt(["x_builder_project"])
        after = set(
            self.env["ir.model.data"]
            .search([("module", "=", package.name), ("model", "=", "ir.model")])
            .mapped("name")
        )
        self.assertEqual(before, after)
        self.assertIn("model_x_builder_project", after)

    def test_graduating_an_uninstalled_package_is_refused(self):
        """Odoo only imports Python for installed modules.

        Demoting the metadata without a module to load the class would leave
        the model with no definition at all after a restart.
        """
        package = self.make_package(name="x_grad_uninstalled", installed=False)
        self.build_demo_content(package)
        package.action_write_files()
        with raises(self, UserError):
            package.action_adopt(["x_builder_project"])

    def test_graduating_an_unowned_model_is_refused(self):
        package = self.make_package(name="x_grad_guard")
        with raises(self, UserError):
            package.action_adopt(["res.partner"])

    def test_graduating_nothing_is_refused(self):
        package = self.make_package(name="x_grad_empty")
        with raises(self, UserError):
            package.action_adopt([])

    def test_graduation_is_idempotent(self):
        package = self._graduated_package()
        package.action_adopt(["x_builder_project"])
        self.assertEqual(package.python_models, "x_builder_project")


@tagged("post_install", "-at_install")
class TestPackageTeardown(BuilderCase):
    def test_delete_records_removes_everything_but_keeps_files(self):
        package = self.make_package(name="x_teardown")
        self.build_demo_content(package)
        package.action_write_files()
        source = os.path.join(
            cast("str", package.root_path), "models/x_builder_project.xml"
        )
        self.assertTrue(os.path.isfile(source))

        package.action_delete_records()

        self.assertFalse(
            self.env["ir.model.data"].search([("module", "=", package.name)])
        )
        self.assertFalse(
            self.env["ir.model"].search([("model", "=", "x_builder_project")])
        )
        self.assertEqual(package.state, "draft")
        self.assertTrue(
            os.path.isfile(source),
            "source is the durable artifact; deleting records must not touch it",
        )

    def test_records_can_be_rebuilt_from_the_kept_files(self):
        package = self.make_package(name="x_teardown_rebuild")
        self.build_demo_content(package)
        rendered = package._render_files()
        package.action_delete_records()

        self.load_rendered(package, rendered)
        self.assertIn("x_builder_project", self.env)
        self.assertEqual(package._render_files(), rendered)


@tagged("post_install", "-at_install")
class TestExtendingACoreModel(BuilderCase):
    """A package putting a class onto a model somebody else declares.

    This is the capability two other things were waiting on: an automation's
    Python graduating out of a sandboxed string needs somewhere to put the
    method, and approval rules need `tier.validation` added to a core model.
    Both are "a real method, or a mixin, on a model we do not own".
    """

    def test_an_extension_renders_as_inherit_without_name(self):
        package = self.make_package()
        entry = typed.model(self.env, BuilderPackageModel)._adopt(
            package, "res.partner", extends=True
        )
        self.assertTrue(entry.extends)
        spec = modelspec.ModelSpec(
            name="res.partner",
            description="",
            class_name="ResPartner",
            extends=True,
            fields=(modelspec.FieldSpec(name="x_builder_ref", ttype="char"),),
        )
        package._seed_source_for("res.partner", spec)
        # `python_path` is compute-only and declared `str | Literal[False]`
        # like any Char (same invariant cast as `builder_package_model.py`'s
        # own real read sites); `_read_source` returns `str | None` but this
        # source was just seeded above, so it is never `None` here.
        source = cast("str", package._read_source(cast("str", entry.python_path)))
        self.assertIn('_inherit = "res.partner"', source)
        self.assertNotIn("_name =", source)

    def test_an_extension_does_not_claim_the_model_it_extends(self):
        """`_is_python_owned` means declares, not touches.

        Counting an extension would suppress the XML for a manual `x_` field on
        that model, and lose it.
        """
        package = self.make_package()
        typed.model(self.env, BuilderPackageModel)._adopt(
            package, "res.partner", extends=True
        )
        self.assertFalse(
            typed.model(self.env, BuilderPackageModel)._is_python_owned("res.partner")
        )

    def test_a_declaration_still_claims_its_model(self):
        package = self.make_package()
        typed.model(self.env, BuilderPackageModel)._adopt(package, "x_builder_thing")
        self.assertTrue(
            typed.model(self.env, BuilderPackageModel)._is_python_owned(
                "x_builder_thing"
            )
        )

    def test_a_manual_field_on_an_extended_model_still_reaches_xml(self):
        """The regression the extends flag exists to prevent."""
        package = self.make_package()
        typed.model(self.env, BuilderPackageModel)._adopt(
            package, "res.partner", extends=True
        )
        field_vals: dict[str, object] = {
            "name": "x_builder_note",
            "field_description": "Note",
            "ttype": "char",
            "model_id": typed.model(self.env, IrModel)._get("res.partner").id,
        }
        field = self.env["ir.model.fields"].create(field_vals)  # pyright: ignore[reportArgumentType]
        package._assign(field)
        emitted = "".join(package._render_files().values())
        self.assertIn("x_builder_note", emitted)

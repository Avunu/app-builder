# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The record-pane contract, through its first two surfaces.

Access lines and record rules are what every record pane is: rows of a
model a package can own, listed with who owns them, edited through rows the
server declared, created from a template into the chosen package and
written to its file -- and refused, with the honest alternative, when
another module owns them.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.base.models.ir_model import IrModel, IrModelAccess
from odoo.addons.base.models.ir_rule import IrRule

from ..models.builder_security_surfaces import BuilderAccessSurface, BuilderRuleSurface
from ..tools import typed
from .common import BuilderCase, raises

if TYPE_CHECKING:
    # Only for the casts below (`from __future__ import annotations` defers
    # all of them to strings); `BuilderAccessSurface`/`BuilderRuleSurface` are
    # real, top-level imports instead (above), since `typed.model()` reads
    # `cls._name` at *runtime* -- the same split every other Phase 1c/1d
    # file's own `TYPE_CHECKING` block makes.
    from ..models.builder_record_surface import BuilderRecordSurface


@tagged("post_install", "-at_install")
class TestRecordSurface(BuilderCase):
    def setUp(self):
        super().setUp()
        self.package = self.make_package(name="x_surf_pkg")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        # Both surfaces compose `builder.record.surface` only via
        # `_inherit` (registry-level, never a real Python base class), so
        # their own declared class carries none of its methods as far as
        # pyright can see -- the same shape `typed.security()`/`typed
        # .serializer()` (`tools/typed.py`) already fix for the builder's
        # other two mixins, applied here at the call site instead since
        # this file cannot add a helper of its own to `tools/typed.py`.
        self.access = cast(
            "BuilderRecordSurface", typed.model(self.env, BuilderAccessSurface)
        )
        self.rules = cast(
            "BuilderRecordSurface", typed.model(self.env, BuilderRuleSurface)
        )
        self.model = "x_builder_project"
        self.group = typed.ref(self.env, "base.group_user")

    def _file(self, relative):
        # `root_path` is always set by `make_package` before a test ever
        # reaches here (a Char field, `str | Literal[False]` by its own
        # declared type) -- true by construction, the same way
        # `builder_package.py`'s own `root_path` reads already cast it.
        path = os.path.join(cast("str", self.package.root_path), relative)
        if not os.path.isfile(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    # -- catalogue -----------------------------------------------------------------

    def test_the_catalogue_is_data(self):
        catalogue = self.access.catalogue(self.model)
        self.assertEqual(catalogue["model"], self.model)
        sections = {s["id"]: s for s in catalogue["sections"]}
        self.assertIn("line", sections)
        names = [r["name"] for r in sections["line"]["rows"]]
        self.assertEqual(
            names[:5],
            ["group_id", "perm_read", "perm_write", "perm_create", "perm_unlink"],
        )
        group_row = sections["line"]["rows"][0]
        self.assertEqual(group_row["type"], "many2one")
        self.assertEqual(group_row["comodel"], "res.groups")
        self.assertEqual(
            [t["key"] for t in catalogue["templates"]],
            ["read_only", "read_write", "full"],
        )
        for section in catalogue["sections"]:
            for row in section["rows"]:
                for value in row.values():
                    self.assertFalse(callable(value), "rows never carry a function")

    def test_rule_templates_need_the_field_they_use(self):
        keys = [t["key"] for t in self.rules.templates(self.model)]
        self.assertIn("own_records", keys)
        self.assertNotIn("assigned_to_me", keys, "x_builder_project has no user_id")
        self.assertIn(
            "assigned_to_me", [t["key"] for t in self.rules.templates("res.partner")]
        )

    # -- rows ------------------------------------------------------------------------

    def test_rows_say_who_owns_what(self):
        # `self.package` is a real, `.create()`-backed record for the rest
        # of this suite (`setUp`), so `.id` is true by construction a real
        # `int`, never `NewId`/`Literal[False]` -- the same cast `_row`
        # (`builder_record_surface.py`) already makes on `record.id`. Every
        # other `self.package.id`/`<record>.id` argument below is the same
        # cast, for the same reason.
        rows = self.access.rows(self.model, cast("int", self.package.id))
        self.assertTrue(rows)
        owned = [r for r in rows if r["owned"]]
        self.assertTrue(
            owned, "build_demo_content made an access line the package owns"
        )
        self.assertTrue(owned[0]["editable"])
        self.assertEqual(owned[0]["reason"], "")
        self.assertIn("perms", owned[0])

    def test_a_foreign_row_is_shown_but_refused_with_the_alternative(self):
        model_id = typed.model(self.env, IrModel)._get_id(self.model)  # pyright: ignore[reportCallIssue]
        access_vals: dict[str, object] = {
            "name": "from elsewhere",
            "model_id": model_id,
            "group_id": self.group.id,
            "perm_read": True,
        }
        foreign = self.env["ir.model.access"].create(access_vals)  # pyright: ignore[reportArgumentType]
        data_vals: dict[str, object] = {
            "module": "some_other_module",
            "name": "access_elsewhere",
            "model": "ir.model.access",
            "res_id": foreign.id,
        }
        self.env["ir.model.data"].create(data_vals)  # pyright: ignore[reportArgumentType]
        row = next(
            r
            for r in self.access.rows(self.model, cast("int", self.package.id))
            if r["id"] == foreign.id
        )
        self.assertFalse(row["owned"])
        self.assertEqual(row["owner"], "some_other_module")
        self.assertIn("add up", row["reason"])
        self.assertIn(
            {"key": "foreign", "label": "From some_other_module"}, row["badges"]
        )
        with raises(self, UserError) as caught:
            self.access.write_record(
                cast("int", foreign.id),
                {"perm_write": True},
                cast("int", self.package.id),
            )
        self.assertIn("add up", str(caught.exception))
        with raises(self, UserError):
            self.access.remove_record(
                cast("int", foreign.id), cast("int", self.package.id)
            )

    def test_a_row_not_in_source_can_be_added_to_the_package(self):
        model_id = typed.model(self.env, IrModel)._get_id(self.model)  # pyright: ignore[reportCallIssue]
        loose_vals: dict[str, object] = {
            "name": "loose",
            "model_id": model_id,
            "perm_read": True,
        }
        loose = self.env["ir.model.access"].create(loose_vals)  # pyright: ignore[reportArgumentType]
        described = cast(
            "dict[str, Any]",
            self.access.describe(cast("int", loose.id), cast("int", self.package.id)),
        )
        self.assertFalse(described["row"]["in_source"])
        self.assertEqual(described["actions"][0]["key"], "capture")
        with raises(self, UserError):
            self.access.write_record(
                cast("int", loose.id),
                {"perm_write": True},
                cast("int", self.package.id),
            )
        described = cast(
            "dict[str, Any]",
            self.access.run(
                cast("int", loose.id), "capture", cast("int", self.package.id)
            ),
        )
        self.assertTrue(described["row"]["owned"])
        self.assertIn("loose", self._file("security/ir.model.access.csv"))

    # -- describe / write -----------------------------------------------------------

    def test_describe_hands_back_values_in_row_shape(self):
        row = next(
            r
            for r in self.access.rows(self.model, cast("int", self.package.id))
            if r["owned"]
        )
        described = cast(
            "dict[str, Any]",
            self.access.describe(row["id"], cast("int", self.package.id)),
        )
        values = described["values"]
        self.assertIsInstance(values["perm_read"], bool)
        self.assertTrue(
            values["group_id"] is False or "display_name" in values["group_id"]
        )
        self.assertEqual(described["advanced"]["res_model"], "ir.model.access")
        self.assertEqual(
            described["advanced"]["context"]["builder_package_id"], self.package.id
        )

    def test_write_lands_in_the_file(self):
        row = next(
            r
            for r in self.access.rows(self.model, cast("int", self.package.id))
            if r["owned"]
        )
        record = typed.model(self.env, IrModelAccess).browse(row["id"])
        self.access.write_record(
            row["id"],
            {"perm_unlink": True, "group_id": {"id": self.group.id}},
            cast("int", self.package.id),
        )
        self.assertTrue(record.perm_unlink)
        self.assertEqual(record.group_id, self.group)
        csv = self._file("security/ir.model.access.csv")
        self.assertIn("base.group_user", csv)

    def test_write_refuses_what_the_catalogue_did_not_declare(self):
        row = next(
            r
            for r in self.access.rows(self.model, cast("int", self.package.id))
            if r["owned"]
        )
        with raises(self, UserError) as caught:
            self.access.write_record(
                row["id"], {"model_id": 1}, cast("int", self.package.id)
            )
        self.assertIn("Not something the builder sets", str(caught.exception))

    # -- create / duplicate / remove ----------------------------------------------

    def test_create_from_a_template_into_the_package(self):
        row = self.access.create_record(
            self.model,
            cast("int", self.package.id),
            {"group_id": self.group.id},
            template="read_only",
        )
        record = typed.model(self.env, IrModelAccess).browse(row["id"])
        self.assertTrue(row["owned"])
        self.assertTrue(record.perm_read)
        self.assertFalse(record.perm_write)
        self.assertIn("Internal User", cast("str", record.name))
        self.assertIn(record.name, self._file("security/ir.model.access.csv"))
        self.assertIn("read_only", self.access.templates()[0]["key"])

    def test_create_needs_a_writable_package(self):
        # No writable package anywhere: nothing to record into.
        self.package.write({"root_path": self.unwritable_path()})
        other = self.make_package(name="x_surf_other", root_path=self.unwritable_path())
        with raises(self, UserError) as caught:
            self.access.create_record(
                self.model, cast("int", other.id), {"group_id": self.group.id}, "full"
            )
        self.assertIn("Choose a package", str(caught.exception))

    def test_a_rule_is_created_checked_and_written(self):
        with raises(self, UserError) as caught:
            self.rules.create_record(
                self.model,
                cast("int", self.package.id),
                {"name": "bad", "domain_force": "[('nope', '=', 1)]"},
                "blank",
            )
        self.assertIn("does not search", str(caught.exception))
        row = self.rules.create_record(
            self.model,
            cast("int", self.package.id),
            {"name": "Own", "groups": [{"id": self.group.id}]},
            template="own_records",
        )
        rule = typed.model(self.env, IrRule).browse(row["id"])
        self.assertEqual(rule.domain_force, "[('create_uid', '=', user.id)]")
        self.assertIn(
            self.group, rule[cast("BuilderRuleSurface", self.rules)._groups_field()]
        )
        self.assertIn("Own", self._file("security/x_builder_project_security.xml"))
        described = cast(
            "dict[str, Any]",
            self.rules.describe(row["id"], cast("int", self.package.id)),
        )
        self.assertTrue(described["matches"]["valid"])
        self.assertEqual(described["values"]["groups"][0]["id"], self.group.id)
        with raises(self, UserError):
            self.rules.write_record(
                row["id"],
                {
                    "perm_read": False,
                    "perm_write": False,
                    "perm_create": False,
                    "perm_unlink": False,
                },
                cast("int", self.package.id),
            )

    def test_duplicate_makes_an_inactive_copy_in_the_package(self):
        row = self.rules.create_record(
            self.model,
            cast("int", self.package.id),
            {"name": "Original"},
            template="blank",
        )
        copy = self.rules.duplicate_record(row["id"], cast("int", self.package.id))
        record = typed.model(self.env, IrRule).browse(copy["id"])
        self.assertTrue(copy["owned"])
        self.assertFalse(record.active)
        self.assertIn({"key": "inactive", "label": "Inactive"}, copy["badges"])
        self.assertIn(
            record.id,
            [
                r["id"]
                for r in self.rules.rows(self.model, cast("int", self.package.id))
            ],
            "archived rows are listed too",
        )

    def test_remove_takes_the_row_out_of_the_file(self):
        row = self.access.create_record(
            self.model,
            cast("int", self.package.id),
            {"group_id": self.group.id},
            template="full",
        )
        name = typed.model(self.env, IrModelAccess).browse(row["id"]).name
        self.assertIn(name, self._file("security/ir.model.access.csv"))
        self.assertTrue(
            self.access.remove_record(row["id"], cast("int", self.package.id))
        )
        self.assertNotIn(name, self._file("security/ir.model.access.csv"))

    # -- guards ------------------------------------------------------------------------

    def test_writes_need_a_manager(self):
        builder = self.make_user(
            "surf_builder", ["app_builder_base.group_builder_user"]
        )
        as_builder = self.access.with_user(builder)
        self.assertTrue(as_builder.rows(self.model, cast("int", self.package.id)))
        with raises(self, AccessError):
            as_builder.create_record(
                self.model,
                cast("int", self.package.id),
                {"group_id": self.group.id},
                "full",
            )

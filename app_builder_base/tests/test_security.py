# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The guard itself: the server-side switch, ``sudo()``, and file paths.

``test_guard_coverage`` says every method calls the guard. This says what
the guard does once it is called -- and what the read tier, which is let
through, still may not reach.
"""

from __future__ import annotations

import os
import tempfile
from typing import cast

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import config

from odoo.addons.app_builder_base.models.builder_record_surface import (
    BuilderRecordSurface,
)
from odoo.addons.app_builder_base.models.builder_security import (
    WRITE_CONFIG_KEY,
    WRITE_ENV_VAR,
    code_write_enabled,
)
from odoo.addons.app_builder_base.models.builder_workspace import BuilderWorkspace
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_config_parameter import IrConfigParameter
from odoo.addons.base.models.ir_model import IrModelFields

from .common import BuilderCase, raises, set_code_write

SECRET = "admin_passwd = hunter2\n"


@tagged("post_install", "-at_install")
class TestCodeWriteSwitch(BuilderCase):
    def setUp(self):
        super().setUp()
        self.workspace = typed.model(self.env, BuilderWorkspace)

    def _switch(self, env: str | None, conf: object = None):
        """The switch as an operator left it: the environment variable (or
        its absence) and the ``odoo.conf`` key (or its absence)."""
        self.addCleanup(set_code_write(env))
        missing = object()
        before = config.options.get(WRITE_CONFIG_KEY, missing)

        def restore() -> None:
            if before is missing:
                config.options.pop(WRITE_CONFIG_KEY, None)
            else:
                config.options[WRITE_CONFIG_KEY] = before

        self.addCleanup(restore)
        if conf is None:
            config.options.pop(WRITE_CONFIG_KEY, None)
        else:
            config.options[WRITE_CONFIG_KEY] = conf

    def test_it_is_off_unless_somebody_turned_it_on(self):
        self._switch(None)
        self.assertFalse(code_write_enabled())

    def test_the_environment_and_the_config_file_both_turn_it_on(self):
        for env, conf, expected in (
            ("1", None, True),
            ("true", None, True),
            ("YES", None, True),
            ("0", None, False),
            ("no", None, False),
            ("nonsense", None, False),
            (None, True, True),  # `app_builder_enable_write = True`, parsed
            (None, "1", True),
            (None, False, False),
            (None, "0", False),
            ("", True, True),  # an empty variable is not an answer
            ("0", True, False),  # the environment wins over a shared file
            ("1", False, True),
        ):
            with self.subTest(env=env, conf=conf):
                self._switch(env, conf)
                self.assertEqual(code_write_enabled(), expected)

    def test_it_is_not_a_system_parameter(self):
        """A row a Settings administrator can edit must not be the switch."""
        self._switch(None)
        params = typed.model(self.env, IrConfigParameter).sudo()
        params.set_param(WRITE_CONFIG_KEY, "True")
        params.set_param(WRITE_ENV_VAR, "1")
        self.assertFalse(code_write_enabled())

    def test_off_means_read_only_with_a_reason(self):
        package = self.make_package(name="x_sec_off")
        self.assertTrue(package.writable)
        self._switch(None)
        package.invalidate_recordset(["writable"])
        self.assertFalse(package.writable, "a writable directory is not consent")
        with raises(self, UserError) as caught:
            package._assert_writable()
        self.assertIn(WRITE_ENV_VAR, str(caught.exception))
        listed = next(
            p
            for p in self.workspace.packages(include_git=False)
            if p["id"] == package.id
        )
        self.assertFalse(listed["writable"])
        self.assertIn(WRITE_ENV_VAR, listed["read_only_reason"])
        self.assertIn(WRITE_CONFIG_KEY, listed["read_only_reason"])
        self.assertIn("read_only", listed["health"])
        self.assertIn("write_disabled", listed["health"])
        self.assertFalse(any(d["writable"] for d in self.workspace.addons_dirs()))

    def test_on_and_unwritable_gives_the_other_reason(self):
        package = self.make_package(name="x_sec_ro", root_path=self.unwritable_path())
        listed = self.workspace.package(cast("int", package.id))
        self.assertFalse(listed["writable"])
        self.assertTrue(listed["read_only_reason"])
        self.assertNotIn(WRITE_ENV_VAR, listed["read_only_reason"])
        self.assertNotIn("write_disabled", listed["health"])
        writable = self.make_package(name="x_sec_rw")
        self.assertEqual(
            self.workspace.package(cast("int", writable.id))["read_only_reason"], ""
        )

    def test_off_refuses_every_manager_superuser_included(self):
        package = self.make_package(name="x_sec_refuse")
        package_id = cast("int", package.id)
        admin = self.make_user("sec_admin", ["base.group_system"])
        self.assertTrue(admin.has_group("app_builder_base.group_builder_manager"))
        self._switch(None)
        package.invalidate_recordset(["writable"])
        for who in (self.workspace, self.workspace.with_user(admin)):
            for call in (
                lambda who=who: who.write_files(package_id),
                lambda who=who: who.apply(package_id),
                lambda who=who: who.reload(package_id),
                lambda who=who: who.commit(package_id, "m"),
                lambda who=who: who.git_init(package_id),
                lambda who=who: who.create_package({"name": "x_sec_new"}),
                lambda who=who: who.set_auto_commit(package_id, "off"),
            ):
                with raises(self, AccessError) as caught:
                    call()
                self.assertIn(WRITE_ENV_VAR, str(caught.exception))
        with raises(self, AccessError):
            package.action_write_files()
        self.assertFalse(
            os.listdir(cast("str", package.root_path)), "nothing reached the disk"
        )
        # Reading is untouched: the console still opens and says why.
        self.assertTrue(self.workspace.with_user(admin).packages(include_git=False))

    def test_off_tells_a_non_builder_nothing(self):
        """The group is checked first, so the server's configuration is not
        described to somebody who is not a builder at all."""
        nobody = self.make_user("sec_off_nobody", ["base.group_user"])
        self._switch(None)
        with raises(self, AccessError) as caught:
            self.workspace.with_user(nobody).create_package({"name": "x_sec_n"})
        self.assertNotIn(WRITE_ENV_VAR, str(caught.exception))


@tagged("post_install", "-at_install")
class TestSudoIsNotAWayIn(BuilderCase):
    def setUp(self):
        super().setUp()
        self.workspace = typed.model(self.env, BuilderWorkspace)
        self.nobody = self.make_user("sec_nobody", ["base.group_user"])

    def test_the_superuser_itself_passes(self):
        guard = typed.security(self.workspace)
        self.assertTrue(guard._assert_builder_user())
        self.assertTrue(guard._assert_builder_manager())

    def test_sudo_for_a_plain_user_does_not(self):
        deputy = self.workspace.with_user(self.nobody).sudo()
        self.assertTrue(deputy.env.su)
        with raises(self, AccessError):
            typed.security(deputy)._assert_builder_user()
        with raises(self, AccessError):
            typed.security(deputy)._assert_builder_manager()
        with raises(self, AccessError):
            deputy.packages()

    def test_sudo_for_a_builder_keeps_their_own_tier(self):
        builder = self.make_user("sec_builder", ["app_builder_base.group_builder_user"])
        deputy = self.workspace.with_user(builder).sudo()
        self.assertTrue(typed.security(deputy)._assert_builder_user())
        with raises(self, AccessError):
            typed.security(deputy)._assert_builder_manager()

    def test_a_forwarded_context_key_does_not_capture_for_a_non_builder(self):
        """The confused deputy: another addon creates a field under ``sudo()``
        with the client's context, and the context names a package."""
        package = self.make_package(name="x_sec_deputy")
        Fields = (
            typed.model(self.env, IrModelFields)
            .with_user(self.nobody)
            .sudo()
            .with_context(builder_package_id=package.id)
        )
        vals: dict[str, object] = {
            "name": "x_sec_deputy",
            "field_description": "Deputy",
            "ttype": "char",
            "model_id": typed.ref(self.env, "base.model_res_partner").id,
        }
        with raises(self, AccessError):
            Fields.create(vals)  # pyright: ignore[reportArgumentType]
        self.assertFalse(
            os.listdir(cast("str", package.root_path)), "nothing reached the disk"
        )


@tagged("post_install", "-at_install")
class TestDiffPathsStayInThePackage(BuilderCase):
    """``drift_diff`` returned any file the Odoo process could read."""

    def setUp(self):
        super().setUp()
        self.workspace = typed.model(self.env, BuilderWorkspace)
        self.package = self.make_package(name="x_sec_paths")
        self.build_demo_content(self.package)
        self.package.action_write_files()
        self.package_id = cast("int", self.package.id)
        self.root = cast("str", self.package.root_path)
        outside = tempfile.mkdtemp(prefix="builder-test-outside-")
        self.secret = os.path.join(outside, "odoo.conf")
        with open(self.secret, "w", encoding="utf-8") as handle:
            handle.write(SECRET)
        builder = self.make_user("sec_reader", ["app_builder_base.group_builder_user"])
        self.reader = self.workspace.with_user(builder)

    def _escapes(self) -> list[str]:
        link = os.path.join(self.root, "views", "link.xml")
        if not os.path.lexists(link):
            os.symlink(self.secret, link)
        sibling = self.root + "-sibling"
        os.makedirs(sibling, exist_ok=True)
        with open(os.path.join(sibling, "secret"), "w", encoding="utf-8") as handle:
            handle.write(SECRET)
        return [
            self.secret,  # absolute: os.path.join drops the root
            os.path.relpath(self.secret, self.root),  # ../../..
            "views/../../"
            + os.path.basename(os.path.dirname(self.secret))
            + "/odoo.conf",
            "views/link.xml",  # a symlink that leaves
            "../" + os.path.basename(sibling) + "/secret",  # a prefix sibling
            "",
            ".",
            "..",
            "views/\x00",
        ]

    def test_drift_diff_refuses_what_is_not_in_the_package(self):
        for path in self._escapes():
            with self.subTest(path=path), raises(self, UserError):
                self.reader.drift_diff(self.package_id, path)

    def test_git_diff_refuses_what_is_not_in_the_package(self):
        for path in self._escapes():
            if not path:
                continue  # no path is "the whole package", and allowed
            with self.subTest(path=path), raises(self, UserError):
                self.reader.git_diff(self.package_id, path)

    def test_a_path_that_is_not_a_string_is_refused(self):
        with raises(self, UserError):
            self.reader.drift_diff(self.package_id, cast("str", ["views/menus.xml"]))

    def test_a_file_of_the_package_still_diffs(self):
        with open(os.path.join(self.root, "views/menus.xml"), "a") as handle:
            handle.write("<!-- by hand -->\n")
        diff = self.reader.drift_diff(self.package_id, "views/menus.xml")["diff"]
        self.assertIn("by hand", diff)
        # Normalised, not rejected: the same file by a longer name.
        diff = self.reader.drift_diff(self.package_id, "views/../views/menus.xml")
        self.assertIn("by hand", diff["diff"])
        self.assertNotIn("hunter2", diff["diff"])


@tagged("post_install", "-at_install")
class TestDomainCheckIsNotAnOracle(BuilderCase):
    def setUp(self):
        super().setUp()
        self.surface = typed.model(self.env, BuilderRecordSurface)

    def test_it_counts_as_the_caller(self):
        builder = self.make_user("sec_counter", ["app_builder_base.group_builder_user"])
        as_builder = self.surface.with_user(builder)
        # No group but the builder's own: `ir.cron` is not theirs to read.
        self.assertFalse(self.env["ir.cron"].with_user(builder).has_access("read"))
        answer = as_builder._check_domain("ir.cron", "[]")
        self.assertFalse(answer["valid"])
        self.assertNotIn("count", answer)
        self.assertNotIn("ir.cron", answer.get("reason", ""), "no raw exception text")
        self.assertTrue(self.surface._check_domain("ir.cron", "[]")["valid"])

    def test_a_bad_domain_still_says_what_is_wrong(self):
        answer = self.surface._check_domain("res.partner", "[('x_nope', '=', 1)]")
        self.assertFalse(answer["valid"])
        self.assertIn("x_nope", answer.get("reason", ""))

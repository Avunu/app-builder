# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Two record kinds that were owned but never written.

Both were the same shape as the translations gap: a package could take
ownership of the record, the completeness guard reported clean, and the value
existed in this database and nowhere else.
"""

from __future__ import annotations

from odoo.tests import tagged

from odoo.addons.base.models.ir_cron import ir_cron as IrCron
from odoo.addons.base.models.ir_default import IrDefault
from odoo.addons.base.models.ir_model import IrModel
from odoo.addons.app_builder_base.models.serializers.ir_default import (
    IrDefaultSerializer,
)
from odoo.addons.app_builder_base.tools import typed

from .common import StudioCase


@tagged("post_install", "-at_install")
class TestFieldDefaults(StudioCase):
    def _field(self):
        return self.env["ir.model.fields"].search(
            [("model", "=", "x_studio_project"), ("name", "=", "x_budget")], limit=1
        )

    def test_a_default_is_written_to_source(self):
        package = self.make_package()
        self.build_demo_content(package)
        vals = {"field_id": self._field().id, "json_value": "1500.0"}
        default = self.env["ir.default"].create(vals)  # pyright: ignore[reportArgumentType]
        package.studio_capture(default)

        emitted = "".join(package._render_files().values())
        self.assertIn("ir.default", emitted)
        self.assertIn("1500.0", emitted)

    def test_a_default_survives_the_round_trip(self):
        package = self.make_package()
        self.build_demo_content(package)
        vals = {"field_id": self._field().id, "json_value": "1500.0"}
        self.env["ir.default"].create(vals)  # pyright: ignore[reportArgumentType]
        package._assign(self.env["ir.default"].search([]))
        files = package._render_files()

        self.wipe_package_records(package)
        self.load_rendered(package, files)

        restored = typed.model(self.env, IrDefault).search(
            [("field_id.model", "=", "x_studio_project")]
        )
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.json_value, "1500.0")

    def test_a_personal_default_is_not_written(self):
        """A default scoped to one user is that user's preference.

        Writing it into an addon would apply somebody's private setting to
        everyone who installs the package.
        """
        package = self.make_package()
        self.build_demo_content(package)
        vals = {
            "field_id": self._field().id,
            "json_value": "99.0",
            "user_id": self.env.user.id,
        }
        mine = self.env["ir.default"].create(vals)  # pyright: ignore[reportArgumentType]
        serializer = typed.model(self.env, IrDefaultSerializer)
        self.assertFalse(serializer._ownable(mine))

    def test_the_default_lands_beside_the_model_it_belongs_to(self):
        package = self.make_package()
        self.build_demo_content(package)
        vals = {"field_id": self._field().id, "json_value": "1500.0"}
        default = self.env["ir.default"].create(vals)  # pyright: ignore[reportArgumentType]
        package.studio_capture(default)
        self.assertIn(
            "data/x_studio_project_defaults.xml",
            package._render_files(),
        )


@tagged("post_install", "-at_install")
class TestScheduledActions(StudioCase):
    def _make_cron(self, package):
        action_vals = {
            "name": "Nightly tidy",
            "model_id": typed.model(self.env, IrModel)._get("x_studio_project").id,
            "state": "code",
            "code": "pass",
        }
        action = self.env["ir.actions.server"].create(action_vals)  # pyright: ignore[reportArgumentType]
        cron_vals = {
            "ir_actions_server_id": action.id,
            "interval_number": 3,
            "interval_type": "days",
        }
        cron = self.env["ir.cron"].create(cron_vals)  # pyright: ignore[reportArgumentType]
        package.studio_capture([action, cron])
        return action, cron

    def test_the_schedule_is_written_not_just_the_action(self):
        """The half that makes it a cron rather than a server action."""
        package = self.make_package()
        self.build_demo_content(package)
        self._make_cron(package)
        emitted = "".join(package._render_files().values())
        self.assertIn("ir.cron", emitted)
        self.assertIn("interval_number", emitted)
        self.assertIn("days", emitted)

    def test_a_cron_survives_the_round_trip(self):
        package = self.make_package()
        self.build_demo_content(package)
        self._make_cron(package)
        files = package._render_files()

        self.wipe_package_records(package)
        self.load_rendered(package, files)

        restored = typed.model(self.env, IrCron).search(
            [("cron_name", "=", "Nightly tidy")]
        )
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.interval_number, 3)
        self.assertEqual(restored.interval_type, "days")

    def test_the_delegated_half_is_not_written_twice(self):
        """`ir.cron` delegates to `ir.actions.server`, so name/code/model live
        on the parent. Emitting them from both records would let the two
        disagree on reload."""
        package = self.make_package()
        self.build_demo_content(package)
        _action, cron = self._make_cron(package)
        node = typed.serializer(self.env["studio.serializer.ir.cron"])._serialize(
            cron, "pkg.cron_x"
        )
        emitted = {child.get("name") for child in node}
        self.assertNotIn("name", emitted)
        self.assertNotIn("code", emitted)
        self.assertIn("interval_number", emitted)

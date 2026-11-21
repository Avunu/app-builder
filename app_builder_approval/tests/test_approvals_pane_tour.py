# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The Approvals pane's gate, driven from the console.

Turning the gate on reloads the server, which a tour cannot sit through. The
first tour pins what the person sees before pressing it, on a model that is
not gated. The second drives the gate's whole life -- on, changed, off --
through the surface's real ``enable_gate``/``update_gate``/``disable_gate``,
with the one step a test cannot take replaced: the source is written without
Apply (``apply=False``, as ``test_approval.py`` writes it), and whether the
model is gated, and how, is read back from that source instead of from a
reloaded registry. What the reload makes live is ``test_live_gate.py``'s and
``tests/e2e/probe_approval.py``'s to prove.
"""

from __future__ import annotations

import ast
import tempfile
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderHttpCase, join_groups
from odoo.addons.app_builder_base.tools import typed

from ..models.builder_approval import MIXIN, BuilderApproval

if TYPE_CHECKING:
    from odoo.addons.base.models.res_users import Users

    from ..models.builder_approval import GateConfigJSON

PACKAGE = "x_tour_appr_pkg"


@tagged("post_install", "-at_install")
class TestApprovalsPaneTour(BuilderHttpCase):
    def setUp(self):
        super().setUp()
        console = self.env["ir.module.module"].search(
            [("name", "=", "app_builder_view"), ("state", "=", "installed")]
        )
        if not console:
            self.skipTest("app_builder_view is not installed")
        package_vals: dict[str, object] = {
            "name": PACKAGE,
            "display_name_": "Tour Approvals",
            "root_path": tempfile.mkdtemp(prefix="builder-tour-"),
            "auto_commit": "off",
        }
        self.package = self.env["builder.package"].create(package_vals)  # pyright: ignore[reportArgumentType]
        module_vals: dict[str, object] = {"name": PACKAGE, "state": "installed"}
        self.env["ir.module.module"].create(module_vals)  # pyright: ignore[reportArgumentType]
        join_groups(
            cast("Users", typed.ref(self.env, "base.user_admin")),
            ["app_builder_base.group_builder_manager"],
        )
        action_vals: dict[str, object] = {
            "name": "Tour Contacts",
            "res_model": "res.partner",
            "view_mode": "list,form",
        }
        self.action = self.env["ir.actions.act_window"].create(action_vals)  # pyright: ignore[reportArgumentType]

    def assertNotGatedLive(self) -> None:
        self.assertNotIn(
            MIXIN,
            # `_inherit_module`'s own stub gap is the identical one
            # `builder_approval.py`'s own `_empty_state` already documents.
            self.env["res.partner"]._inherit_module,  # pyright: ignore[reportAttributeAccessIssue]
            "the tour must not have switched the live gate on",
        )

    def test_the_gate_comes_before_the_rules(self):
        self.start_tour(
            "/odoo/action-%s" % self.action.id,
            "app_builder_approvals_pane_tour",
            login="admin",
        )
        self.assertNotGatedLive()

    # -- on, changed, off ----------------------------------------------------

    def _source_gate(self, approval: Any, model_name: str) -> GateConfigJSON | None:
        """The gate as the package's source states it: what the registry
        would carry after the reload this test cannot do."""
        package = approval.env["builder.package"].browse(self.package.id)
        entry = approval._gated_entry(package, model_name)
        spec = entry._current_spec() if entry else None
        if spec is None or MIXIN not in spec.inherit:
            return None
        attrs = dict(spec.class_attrs)
        state_field = ast.literal_eval(attrs["_state_field"])
        state_to = ast.literal_eval(attrs["_state_to"])
        values = [
            v for v, _label in approval._selection_values(model_name, state_field)
        ]
        return {
            "state_field": state_field,
            # `_state_from` is written as a rule (STATE_FROM_SOURCE); this is
            # what it evaluates to.
            "state_from": [v for v in values if v not in state_to],
            "state_to": state_to,
            "cancel_state": ast.literal_eval(attrs["_cancel_state"]),
        }

    def test_the_gate_is_turned_on_changed_and_off(self):
        Approval = type(self.env["builder.approval"])
        commit_sources = BuilderApproval._commit_sources
        source_gate = self._source_gate
        package_name = PACKAGE
        written: list[str] = []

        def _commit_sources(self, package, specs, apply, reason, ungating=None):
            written.append(reason)
            return commit_sources(self, package, specs, False, reason, ungating)

        def _gated(self, model_name):
            return bool(model_name) and source_gate(self, model_name) is not None

        def _live_gate_config(self, model_name):
            return source_gate(self, model_name)

        def _gate_module(self, model_name):
            return package_name if source_gate(self, model_name) else ""

        with (
            patch.object(Approval, "_commit_sources", _commit_sources),
            patch.object(Approval, "_gated", _gated),
            patch.object(Approval, "_live_gate_config", _live_gate_config),
            patch.object(Approval, "_gate_module", _gate_module),
        ):
            self.start_tour(
                "/odoo/action-%s" % self.action.id,
                "app_builder_approvals_lifecycle_tour",
                login="admin",
            )
        self.assertEqual(len(written), 3, "enable, change and disable each wrote")
        self.assertIn("enable approvals on res.partner", written[0])
        self.assertIn("change approvals on res.partner", written[1])
        self.assertIn("disable approvals on res.partner", written[2])
        # The last write took the gate back out of the source.
        approval = typed.model(self.env, BuilderApproval)
        self.assertIsNone(self._source_gate(approval, "res.partner"))
        self.assertNotGatedLive()

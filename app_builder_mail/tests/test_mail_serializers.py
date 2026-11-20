# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What ``mail`` adds to a model, a field and an action, kept in source.

The bridge is three ``_emitted_field_names`` overrides and nothing else, so
what there is to get wrong is small and all of it silent: a name left off the
list, or a list that *replaces* the engine's instead of adding to it, and the
generated source simply stops carrying a decision somebody made by hand. The
package still writes, still loads, and comes back with no chatter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import Command
from odoo.tests import tagged

from odoo.addons.app_builder_base.tests.common import BuilderCase
from odoo.addons.app_builder_base.tools import typed
from odoo.addons.base.models.ir_actions import IrActionsServer
from odoo.addons.base.models.ir_model import IrModel, IrModelData

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs this at runtime.
    from odoo.addons.app_builder_base.models.builder_serializer import (
        BuilderSerializer,
    )
    from odoo.addons.base.models.ir_model import IrModelFields

MAIL_NAMES = {
    "ir.model": ("is_mail_thread", "is_mail_activity", "is_mail_blacklist"),
    "ir.model.fields": ("tracking",),
    "ir.actions.server": (
        "template_id",
        "mail_post_method",
        "partner_ids",
        "activity_type_id",
        "activity_summary",
        "activity_user_type",
    ),
}


@tagged("post_install", "-at_install")
class TestMailSerializers(BuilderCase):
    def _serializer(self, model_name: str) -> BuilderSerializer:
        return cast("BuilderSerializer", self.env["builder.serializer.%s" % model_name])

    def test_the_bridge_adds_to_the_engines_names(self):
        """Adds, not replaces: every name the engine emitted on its own is
        still there, in its place, with the mail ones after it."""
        for model_name, added in MAIL_NAMES.items():
            serializer = self._serializer(model_name)
            names = serializer._emitted_field_names()
            for name in added:
                self.assertIn(name, names, "%s lost %s" % (model_name, name))
            own = tuple(serializer._builder_fields)
            self.assertTrue(own, model_name)
            self.assertEqual(names[: len(own)], own, model_name)
            self.assertEqual(len(names), len(set(names)), model_name)

    def test_every_added_name_is_a_real_field_or_knowingly_optional(self):
        """A typo here emits nothing and fails nothing. The two `sms_` names
        are the exception the module documents: present only with `sms`."""
        optional = {"sms_template_id", "sms_method"}
        for model_name in MAIL_NAMES:
            fields = self.env[model_name]._fields
            own = set(self._serializer(model_name)._builder_fields)
            for name in self._serializer(model_name)._emitted_field_names():
                if name in own or name in optional:
                    continue
                self.assertIn(name, fields, "%s has no field %s" % (model_name, name))

    def test_a_model_with_a_chatter_keeps_it_in_source(self):
        package = self.make_package(name="x_mail_pkg")
        model_vals: dict[str, object] = {
            "name": "Mail Ticket",
            "model": "x_mail_ticket",
            "is_mail_thread": True,
            "is_mail_activity": True,
            "field_id": [
                Command.create(
                    {
                        "name": "x_name",
                        "ttype": "char",
                        "field_description": "Name",
                        "tracking": 10,
                    }
                )
            ],
        }
        model = typed.model(self.env, IrModel).create(model_vals)  # pyright: ignore[reportArgumentType]
        fields = cast("IrModelFields", model.field_id).filtered(
            lambda f: f.state == "manual"
        )
        package.builder_capture([model, fields])
        source = "\n".join(package._render_files().values())
        self.assertIn('name="is_mail_thread"', source)
        self.assertIn('name="is_mail_activity"', source)
        self.assertIn('name="tracking"', source)
        # Not switched on, so not written: an emitted False would be noise in
        # every model file the builder produces.
        self.assertNotIn('name="is_mail_blacklist"', source)

    def test_a_send_email_action_keeps_its_template(self):
        """Without `template_id` an action with `state='mail_post'` came back
        from source as a rule that still fired and sent nothing."""
        package = self.make_package(name="x_mail_pkg2")
        partner_model = typed.model(self.env, IrModel)._get("res.partner")
        template_vals: dict[str, object] = {
            "name": "Welcome",
            "model_id": partner_model.id,
            "subject": "Hello",
        }
        template = self.env["mail.template"].create(template_vals)  # pyright: ignore[reportArgumentType]
        xmlid_vals: dict[str, object] = {
            "module": "x_mail_pkg2",
            "name": "welcome_template",
            "model": "mail.template",
            "res_id": template.id,
        }
        typed.model(self.env, IrModelData).create(xmlid_vals)  # pyright: ignore[reportArgumentType]
        action_vals: dict[str, object] = {
            "name": "Send Welcome",
            "model_id": partner_model.id,
            "state": "mail_post",
            "template_id": template.id,
            "mail_post_method": "email",
        }
        action = typed.model(self.env, IrActionsServer).create(action_vals)  # pyright: ignore[reportArgumentType]
        package.builder_capture(action)
        source = "\n".join(package._render_files().values())
        self.assertIn("Send Welcome", source)
        # By reference, to the template's xmlid -- unqualified, because the
        # template lives in the same package the action does.
        self.assertIn('<field name="template_id" ref="welcome_template"/>', source)
        self.assertIn('name="mail_post_method"', source)

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What ``mail`` and ``sms`` add to models the engine already serializes.

The engine depends on ``base`` and nothing else, so it cannot name a field that
``mail`` declares -- but those fields carry real decisions. Ticking *Messaging*
on a custom model, tracking a field in the chatter, or configuring a Send Email
action are all things a person does deliberately and would silently lose on
reload if the generated source did not carry them.

Every extension here goes through ``super()`` rather than by re-declaring
``_builder_fields``. Setting the class attribute from a second module *replaces*
it, so this addon and any other bridge would clobber each other and whichever
loaded last would win. The chain composes instead, which is what lets ``sms``
sit alongside ``mail`` below and any future bridge sit alongside both.

``sms`` fields are listed here rather than in an addon of their own because
``_field_node`` already skips a name the model does not have, and ``sms``
cannot be installed without ``mail``. A separate addon would buy nothing but a
second manifest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs this at runtime. Cross-addon (this addon is not
    # app_builder_base itself), so fully qualified -- same house convention
    # `tier_serializers.py`'s own imports follow.
    from odoo.addons.app_builder_base.models.builder_serializer import (
        BuilderSerializer,
    )


class IrModelSerializer(models.AbstractModel):
    _inherit = "builder.serializer.ir.model"

    @api.model
    def _emitted_field_names(self) -> tuple[str, ...]:
        # Not cosmetic flags: writing one of these makes _add_manual_models
        # give the model the corresponding mixin (ir_model.py:95-97), so a
        # model that loses is_mail_thread on reload comes back with no chatter,
        # no followers and no message history -- and every view that referenced
        # them fails to load.
        #
        # `_inherit`-only composition (never a real Python base class), so
        # `super()` here is invisible to pyright the same way `self
        # ._assert_builder_user()` is on `builder.security.mixin`.
        # `typed.serializer_super()` targets that same gap but does not
        # type-check at any real call site (pyright infers a bare `super()`
        # call's own type as the synthesized concrete base class, not the
        # builtin `super` type that helper declares) -- so this uses the same
        # direct cast `tier_serializers.py`, `ir_model.py` and
        # `base_automation_serializer.py` already use instead.
        return cast("BuilderSerializer", super())._emitted_field_names() + (
            "is_mail_thread",
            "is_mail_activity",
            "is_mail_blacklist",
        )


class IrModelFieldsSerializer(models.AbstractModel):
    _inherit = "builder.serializer.ir.model.fields"

    @api.model
    def _emitted_field_names(self) -> tuple[str, ...]:
        # Whether a change to this field is logged in the chatter, and at what
        # level. Set per field, by hand, and invisible once lost.
        # Same `cast()` as `IrModelSerializer` above, same reason.
        return cast("BuilderSerializer", super())._emitted_field_names() + ("tracking",)


class IrActionsServerSerializer(models.AbstractModel):
    _inherit = "builder.serializer.ir.actions.server"

    @api.model
    def _emitted_field_names(self) -> tuple[str, ...]:
        """The configuration for every action type mail and sms contribute.

        These are the states Odoo Studio's documentation calls Send Email, Send
        SMS, Create Activity and Add/Remove Followers. Without them an action
        serialized with ``state='mail_post'`` came back with no template, and
        one with ``state='next_activity'`` came back with nothing but its name
        -- a rule that still fired, and did the wrong thing quietly.
        """
        # Same `cast()` as `IrModelSerializer` above, same reason.
        return cast("BuilderSerializer", super())._emitted_field_names() + (
            # Send Email
            "template_id",
            "mail_post_method",
            "mail_post_autofollow",
            # Add / Remove Followers
            "partner_ids",
            # Create Activity
            "activity_type_id",
            "activity_summary",
            "activity_date_deadline_range",
            "activity_date_deadline_range_type",
            "activity_user_type",
            "activity_user_id",
            "activity_user_field_name",
            "activity_note",
            # Send SMS -- present only when `sms` is installed, and skipped
            # rather than failing when it is not.
            "sms_template_id",
            "sms_method",
        )

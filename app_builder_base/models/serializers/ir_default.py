# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.default`` -- a field's default value.

The gap this closes was the same shape as the translations one and had the same
consequence: the field editor's *Default value* box writes an ``ir.default``
row, nothing emitted it, and the package reported clean. So the same action was
durable or not depending on which kind of model it landed on -- Python-defined
models carry the default in ``FieldSpec.default`` and survive, XML-defined ones
lost it.

Emitted after the field, because ``field_id`` refs it. Not under
``noupdate="1"``: unlike a sequence, a default carries no state -- it is a
setting, and a module upgrade should bring the current one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo import api, models

from ..builder_serializer import SEQ_DEFAULT

if TYPE_CHECKING:
    # Only used inside annotations/casts below (`from __future__ import
    # annotations` defers all of them to strings), never at runtime -- same
    # bargain every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.models import BaseModel

    # ``ir.default``/``ir.model``/``ir.model.fields`` are core Odoo, reached
    # only through the merged odoo-nix tree -- the fully-qualified
    # ``odoo.addons....`` form is correct here, not same-addon (TYPING.md's
    # "Known traps"/house conventions), the same as ``pycodegen.py``'s own
    # ``IrModel``/``IrModelFields`` imports and ``ir_sequence.py``'s own
    # ``IrSequence`` import.
    from odoo.addons.base.models.ir_default import IrDefault
    from odoo.addons.base.models.ir_model import IrModel, IrModelFields

    # Same-addon cross-file import, so relative (house convention). Only
    # needed for the `super()` cast in `_ownable` -- see its own comment.
    from ..builder_serializer import BuilderSerializer


class IrDefaultSerializer(models.AbstractModel):
    _name = "builder.serializer.ir.default"
    _inherit = "builder.serializer"
    _description = "Builder Serializer for ir.default"

    _builder_model = "ir.default"
    _builder_sequence = SEQ_DEFAULT
    _builder_dir = "data"
    _builder_suffix = "_defaults"
    _builder_fields = (
        "field_id",
        "json_value",
        "condition",
        "user_id",
        "company_id",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        # Beside the field it defaults, not in a file named after the package.
        #
        # `record.field_id`/`.model_id` are both plain, untyped
        # `fields.Many2one(...)` declarations in core (no typed-relation
        # syntax there) -- `_Relational.__get__` carries no return
        # annotation of its own, so each read independently infers a messy,
        # partially-Unknown union regardless of the declaration (Known
        # traps). Cast at each hop, the same `cast()`-at-the-read-site idiom
        # `pycodegen.py`/`builder_package.py` already established for a
        # plain-string-comodel relational field.
        field = cast("IrModelFields", cast("IrDefault", record).field_id)
        model = cast("IrModel", field.model_id)
        return cast("str", model.model) or "misc"

    @api.model
    def _ownable(self, record: BaseModel) -> bool:
        # A default scoped to one user is that user's preference, not a
        # customisation of the database -- writing it into an addon would apply
        # somebody's personal setting to everyone who installs it.
        #
        # `IrDefaultSerializer`'s only real Python base is `models
        # .AbstractModel` -- `BuilderSerializer` is composed in only via
        # Odoo's registry-level `_inherit`, never a literal Python base
        # class, so it is absent from the MRO pyright can see and
        # `super()._ownable` resolves against `object` alone. Same
        # underlying "_inherit-mixin-invisible-to-pyright" gap
        # `typed.security()` exists for, applied to `super()` instead of
        # `self` -- at runtime, Odoo's registry builds the real merged
        # class with `BuilderSerializer` genuinely in the MRO, so `super()`
        # resolves this exactly as it always did (`ir_sequence.py`'s own
        # `_should_skip` establishes the identical pattern).
        return not cast("IrDefault", record).user_id and cast(
            "BuilderSerializer", super()
        )._ownable(record)

    @api.model
    def _suggest_xmlid(self, record: BaseModel) -> str | None:
        field = cast("IrModelFields", cast("IrDefault", record).field_id)
        return "default_%s_%s" % (
            (field.model or "").replace(".", "_"),
            field.name or record.id,
        )

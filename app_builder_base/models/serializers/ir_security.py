# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for access control: ``ir.model.access`` and ``ir.rule``."""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, cast

from odoo import api, models

from ..studio_serializer import SEQ_ACCESS, SEQ_RULE

if TYPE_CHECKING:
    # Only used inside annotations/casts below (`from __future__ import
    # annotations` defers all of them to strings), never at runtime -- same
    # bargain every other Phase 1c model file's `TYPE_CHECKING` block makes.
    from odoo.models import BaseModel

    # Same-addon cross-file import, so relative (house convention). Only
    # needed for the `self`/`super()` casts below -- see their own comments.
    from ..studio_serializer import StudioSerializer

# Odoo's conventional column order for ir.model.access.csv. Annotated (rather
# than left for pyright to infer the precise Literal-tuple type) so that
# `list(ACCESS_COLUMNS)` in `_render_csv` below widens to `list[str]` --
# `csv.DictWriter`'s own `fieldnames` is invariant in its key type, and a
# `list[Literal[...]]` there would reject the plain `dict[str, str]` rows
# `_csv_row` produces.
ACCESS_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "model_id:id",
    "group_id:id",
    "perm_read",
    "perm_write",
    "perm_create",
    "perm_unlink",
)

# Appended only when some row needs it. An archived ACL is rare, but dropping
# the fact would hand back a *granted* permission on reload -- a security
# change, silently, in the direction nobody wants. Emitting the column
# unconditionally would instead put a constant "1" in every package's diff
# forever, so it appears exactly when it carries information.
ACCESS_OPTIONAL_COLUMNS: tuple[str, ...] = ("active",)


class IrModelAccessSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model.access"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model.access"

    _studio_model = "ir.model.access"
    _studio_sequence = SEQ_ACCESS
    _studio_format = "csv"
    _studio_dir = "security"

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        # `record` is genuinely `ir.model.access` at runtime, but the
        # overridden base method declares it `BaseModel` (StudioSerializer's
        # own already-typed contract), which has no `.model_id` of its own --
        # subscript access reads the same field through `BaseModel.__getitem__`
        # instead (`self._fields[key].__get__(self)`, the identical descriptor
        # `.model_id` would call), the same idiom `studio_serializer.py`'s own
        # `_should_skip`/`_field_node` already use for a field name known only
        # at runtime. Recurs at every other literal-attribute read below.
        return record["model_id"].model

    @api.model
    def _target_file(self, record: BaseModel) -> str:
        # Odoo convention is a single CSV for the whole addon, not one per
        # model, so every ACL collapses into the same file.
        return "security/ir.model.access.csv"

    @api.model
    def _emitted_field_names(self) -> tuple[str, ...]:
        """Derived from the CSV columns rather than from ``_studio_fields``.

        A CSV serializer emits by column, so ACCESS_COLUMNS is the allowlist
        here. Deriving it keeps one declaration of what gets written, which is
        why the completeness guard asks this question through a method instead
        of reading the tuple directly.
        """
        return tuple(
            column.partition(":")[0]
            for column in ACCESS_COLUMNS + ACCESS_OPTIONAL_COLUMNS
            if column != "id"
        )

    @api.model
    def _csv_row(self, record: BaseModel, xmlid: str) -> dict[str, str]:
        # Not part of `StudioSerializer`'s own declared contract -- only the
        # one real `_studio_format == "csv"` subclass (this one) needs it, a
        # real, pre-existing design gap `studio_package.py`'s own conversion
        # already flagged and left unfixed. Typed from this method's own real
        # body instead of a base-class signature.
        #
        # `IrModelAccessSerializer`'s only real Python base is `models
        # .AbstractModel` -- `StudioSerializer` is composed in only via
        # Odoo's registry-level `_inherit`, never a literal Python base
        # class, so `_assert_complete`/`_record_id`/`_ref_of` (all declared
        # on `StudioSerializer` alone) are absent from the MRO pyright can
        # see on `self`. Same underlying "_inherit-mixin-invisible-to-pyright"
        # gap `typed.security()` exists for (`studio_security.py`'s own
        # guard methods on `self`), applied here to `StudioSerializer`'s own
        # methods instead -- at runtime, Odoo's registry builds the real
        # merged class with `StudioSerializer` genuinely in the MRO, so every
        # one of these calls resolves exactly as it always did.
        serializer = cast("StudioSerializer", self)
        serializer._assert_complete(record)
        return {
            "active": "1" if record["active"] else "0",
            "id": serializer._record_id(record, xmlid),
            "name": record["name"],
            "model_id:id": serializer._ref_of(
                record["model_id"], source=self._studio_model
            ),
            "group_id:id": (
                serializer._ref_of(record["group_id"], source=self._studio_model)
                if record["group_id"]
                else ""
            ),
            "perm_read": "1" if record["perm_read"] else "0",
            "perm_write": "1" if record["perm_write"] else "0",
            "perm_create": "1" if record["perm_create"] else "0",
            "perm_unlink": "1" if record["perm_unlink"] else "0",
        }

    @api.model
    def _render_csv(self, rows: list[dict[str, str]]) -> str:
        """Render sorted rows with LF endings, so diffs stay platform-stable."""
        columns = list(ACCESS_COLUMNS)
        for column in ACCESS_OPTIONAL_COLUMNS:
            # Present only when some row disagrees with the field's default, so
            # the ordinary file keeps Odoo's conventional shape. The decision
            # reads off the data alone, which is what keeps the output
            # reproducible.
            if any(row.get(column) == "0" for row in rows):
                columns.append(column)
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["id"]):
            writer.writerow(row)
        return buffer.getvalue()


class IrRuleSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.rule"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.rule"

    _studio_model = "ir.rule"
    _studio_sequence = SEQ_RULE
    _studio_dir = "security"
    _studio_suffix = "_security"
    _studio_fields = (
        "name",
        "model_id",
        "domain_force",
        "groups",
        "active",
        "perm_read",
        "perm_write",
        "perm_create",
        "perm_unlink",
    )
    _studio_ignored = (
        # Computed from `groups`: a rule with no group is global. Emitting it
        # would state a conclusion the groups already carry.
        "global",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        # Same `record[...]`-for-a-literal-field idiom as
        # `IrModelAccessSerializer._group_model` above.
        return record["model_id"].model

    @api.model
    def _should_skip(self, record: BaseModel, fname: str) -> bool:
        if fname in ("perm_read", "perm_write", "perm_create", "perm_unlink"):
            # These default to True, so only a False is worth recording.
            return bool(record[fname])
        if fname == "active":
            # Same `record[...]`-for-a-literal-field idiom as
            # `IrModelAccessSerializer._group_model` above.
            return bool(record["active"])
        # `IrRuleSerializer`'s only real Python base is `models.AbstractModel`
        # -- `StudioSerializer` is composed in only via Odoo's registry-level
        # `_inherit`, never a literal Python base class, so it is absent from
        # the MRO pyright can see and `super()._should_skip` resolves against
        # `object` alone. Same underlying "_inherit-mixin-invisible-to-pyright"
        # gap `typed.security()` exists for, applied to `super()` instead of
        # `self` -- at runtime, Odoo's registry builds the real merged class
        # with `StudioSerializer` genuinely in the MRO, so `super()` resolves
        # this exactly as it always did.
        return cast("StudioSerializer", super())._should_skip(record, fname)

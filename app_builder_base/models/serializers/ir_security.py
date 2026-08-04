# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializers for access control: ``ir.model.access`` and ``ir.rule``."""

import csv
import io

from odoo import api, models

from ..studio_serializer import SEQ_ACCESS, SEQ_RULE

# Odoo's conventional column order for ir.model.access.csv.
ACCESS_COLUMNS = (
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
ACCESS_OPTIONAL_COLUMNS = ("active",)


class IrModelAccessSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.model.access"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.model.access"

    _studio_model = "ir.model.access"
    _studio_sequence = SEQ_ACCESS
    _studio_format = "csv"
    _studio_dir = "security"

    @api.model
    def _group_model(self, record):
        return record.model_id.model

    @api.model
    def _target_file(self, record):
        # Odoo convention is a single CSV for the whole addon, not one per
        # model, so every ACL collapses into the same file.
        return "security/ir.model.access.csv"

    @api.model
    def _emitted_field_names(self):
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
    def _csv_row(self, record, xmlid):
        self._assert_complete(record)
        return {
            "active": "1" if record.active else "0",
            "id": self._record_id(record, xmlid),
            "name": record.name,
            "model_id:id": self._ref_of(record.model_id, source=self._studio_model),
            "group_id:id": (
                self._ref_of(record.group_id, source=self._studio_model)
                if record.group_id
                else ""
            ),
            "perm_read": "1" if record.perm_read else "0",
            "perm_write": "1" if record.perm_write else "0",
            "perm_create": "1" if record.perm_create else "0",
            "perm_unlink": "1" if record.perm_unlink else "0",
        }

    @api.model
    def _render_csv(self, rows):
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
    def _group_model(self, record):
        return record.model_id.model

    @api.model
    def _should_skip(self, record, fname):
        if fname in ("perm_read", "perm_write", "perm_create", "perm_unlink"):
            # These default to True, so only a False is worth recording.
            return bool(record[fname])
        if fname == "active":
            return bool(record.active)
        return super()._should_skip(record, fname)

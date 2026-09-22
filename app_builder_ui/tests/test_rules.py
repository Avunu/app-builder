# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Record rules, which the serializer could always write and nothing could make.

A rule is the one thing here whose mistake is invisible. A wrong domain does
not raise: it quietly hides records from the people the rule applies to, and
the person who wrote it is usually an administrator it does not apply to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.app_builder_base.models.studio_domain import StudioDomain
from odoo.addons.app_builder_base.models.studio_security_surfaces import (
    StudioRuleSurface,
)
from odoo.addons.app_builder_base.tests.common import StudioCase, raises
from odoo.addons.app_builder_base.tools import typed

if TYPE_CHECKING:
    # Only for the casts below; with `from __future__ import annotations`
    # nothing here needs these at runtime. `StudioRecordSurface` is
    # `studio.rule.surface`'s sibling mixin (`_inherit = ["studio.record
    # .surface"]`, registry-level, never a real Python base class of the
    # imported `StudioRuleSurface`) -- the identical gap `typed.py`'s own
    # `security()`/`serializer()` document. `_DomainEditableJSON`/
    # `_DomainNotEditableJSON` are `read_domain`'s own two branch variants,
    # named the same way `studio_record_surface.py` itself casts to its own
    # `_RecordCheckDomainInvalidJSON`.
    from odoo.addons.app_builder_base.models.studio_domain import (
        _DomainEditableJSON,
        _DomainNotEditableJSON,
    )
    from odoo.addons.app_builder_base.models.studio_owned_mixin import StudioOwnedMixin
    from odoo.addons.app_builder_base.models.studio_record_surface import (
        RecordCheckDomainJSON,
        StudioRecordSurface,
    )


@tagged("post_install", "-at_install")
class TestRuleBuilder(StudioCase):
    def _make(self, package, **overrides):
        values: dict[str, object] = {
            "name": "Own contacts only",
            "domain_force": "[['user_id', '=', 1]]",
        }
        values.update(overrides)
        surface = cast("StudioRecordSurface", typed.model(self.env, StudioRuleSurface))
        return surface.create_record(
            "res.partner", package.id, values, template="blank"
        )

    def test_a_rule_is_created_and_written_to_source(self):
        package = self.make_package()
        self._make(package)
        rule = self.env["ir.rule"].search([("name", "=", "Own contacts only")], limit=1)
        self.assertTrue(rule)
        self.assertEqual(cast("StudioOwnedMixin", rule).studio_package_id, package)
        self.assertIn("ir.rule", "".join(package._render_files().values()))

    def test_a_condition_that_does_not_search_is_refused(self):
        """Not a style objection: a rule whose domain raises makes every read
        raise, for everyone it applies to."""
        package = self.make_package()
        with raises(self, UserError) as caught:
            self._make(package, domain_force="[['nope', '=', 1]]")
        self.assertIn("does not search", str(caught.exception))

    def test_the_pane_says_what_the_condition_matches(self):
        package = self.make_package()
        row = self._make(package, domain_force="[]")
        surface = cast("StudioRecordSurface", typed.model(self.env, StudioRuleSurface))
        described = surface.describe(row["id"], cast("int", package.id))
        matches = cast("RecordCheckDomainJSON", described["matches"])
        self.assertTrue(matches["valid"])
        self.assertIn("count", matches)
        self.assertIn("total", matches)


@tagged("post_install", "-at_install")
class TestDomainBuilder(StudioCase):
    def test_fields_come_with_operators_that_suit_them(self):
        fields = {
            f["name"]: f
            for f in typed.model(self.env, StudioDomain).fields_for("res.partner")
        }
        self.assertIn("name", fields)
        char_ops = {o["value"] for o in fields["name"]["operators"]}
        self.assertIn("ilike", char_ops)
        # `ilike` on a boolean is accepted by Odoo and meant by nobody.
        bool_ops = {o["value"] for o in fields["active"]["operators"]}
        self.assertNotIn("ilike", bool_ops)
        self.assertNotIn(">", bool_ops)

    def test_a_selection_brings_its_values(self):
        fields = {
            f["name"]: f
            for f in typed.model(self.env, StudioDomain).fields_for("ir.ui.view")
        }
        self.assertTrue(fields["type"].get("values"))

    def test_a_relation_names_what_it_points_at(self):
        fields = {
            f["name"]: f
            for f in typed.model(self.env, StudioDomain).fields_for("res.partner")
        }
        # `comodel` is `NotRequired`, but every relational field sets it
        # (`FieldSpecJSON`'s own docstring) -- `.get()` reads it without
        # pyright's `reportTypedDictNotRequiredAccess` (same idiom as
        # `test_model_draft.py`'s own `destructive`).
        self.assertEqual(fields["parent_id"].get("comodel"), "res.partner")

    def test_a_flat_domain_reads_back_as_rows(self):
        read = typed.model(self.env, StudioDomain).read_domain(
            "['&', ['a', '=', 1], ['b', '=', 2]]"
        )
        self.assertTrue(read["editable"])
        editable = cast("_DomainEditableJSON", read)
        self.assertEqual(editable["joiner"], "all")
        self.assertEqual(len(editable["rows"]), 2)

    def test_a_grouped_domain_refuses_rather_than_flattening_it(self):
        read = typed.model(self.env, StudioDomain).read_domain(
            "['|', '&', ['a','=',1], ['b','=',2], ['c','=',3]]"
        )
        self.assertFalse(read["editable"])
        not_editable = cast("_DomainNotEditableJSON", read)
        self.assertIn("cannot be shown as a flat list", not_editable["reason"])

    def test_rows_become_a_domain_odoo_accepts(self):
        domain = typed.model(self.env, StudioDomain).write_domain(
            [
                {"field": "name", "operator": "ilike", "value": "acme"},
                {"field": "parent_id", "operator": "set"},
            ]
        )
        checked = typed.model(self.env, StudioDomain).check_domain(
            "res.partner", domain
        )
        self.assertTrue(checked["valid"], checked.get("reason"))

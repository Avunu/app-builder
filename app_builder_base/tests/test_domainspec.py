# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The domain <-> conditions round trip, and what it refuses.

Refusing is the half worth testing. A builder that rendered a nested domain as
a flat list would rewrite somebody's rule the moment they touched an unrelated
row, and the rewrite would look like an ordinary edit.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.app_builder_base.tools import domainspec

from .common import raises


@tagged("post_install", "-at_install")
class TestDomainSpec(TransactionCase):
    def test_an_empty_domain_means_no_restriction(self):
        self.assertEqual(domainspec.render([]), "[]")
        self.assertEqual(domainspec.parse("[]"), ([], domainspec.ALL))
        self.assertEqual(domainspec.parse(""), ([], domainspec.ALL))

    def test_one_condition_needs_no_operator(self):
        rendered = domainspec.render([domainspec.Condition("state", "=", "draft")])
        self.assertEqual(rendered, "[['state', '=', 'draft']]")

    def test_several_conditions_are_prefixed(self):
        rendered = domainspec.render(
            [
                domainspec.Condition("state", "=", "draft"),
                domainspec.Condition("amount", ">", 100),
                domainspec.Condition("active", "=", True),
            ]
        )
        self.assertTrue(rendered.startswith("['&', '&',"))

    def test_any_uses_the_or_operator(self):
        rendered = domainspec.render(
            [
                domainspec.Condition("state", "=", "draft"),
                domainspec.Condition("state", "=", "sent"),
            ],
            joiner=domainspec.ANY,
        )
        self.assertTrue(rendered.startswith("['|',"))

    def test_the_round_trip_is_a_fixed_point(self):
        for conditions, joiner in (
            ([domainspec.Condition("state", "=", "draft")], domainspec.ALL),
            (
                [
                    domainspec.Condition("state", "=", "draft"),
                    domainspec.Condition("amount", ">", 100),
                ],
                domainspec.ALL,
            ),
            (
                [
                    domainspec.Condition("a", "=", 1),
                    domainspec.Condition("b", "=", 2),
                    domainspec.Condition("c", "=", 3),
                ],
                domainspec.ANY,
            ),
        ):
            rendered = domainspec.render(conditions, joiner)
            back = domainspec.parse(rendered)
            self.assertIsNotNone(back, rendered)
            # `assertIsNotNone` is a runtime check only; it does not narrow
            # `back` for pyright the way an `if`/`assert` would.
            assert back is not None
            self.assertEqual(
                [c.as_dict() for c in back[0]], [c.as_dict() for c in conditions]
            )
            self.assertEqual(back[1], joiner)
            self.assertEqual(domainspec.render(*back), rendered)

    def test_an_implicit_and_reads_as_all(self):
        """Odoo's own convention: no operator means every leaf must match."""
        parsed = domainspec.parse("[('a', '=', 1), ('b', '=', 2)]")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[1], domainspec.ALL)
        self.assertEqual(len(parsed[0]), 2)

    def test_set_and_not_set_survive_the_round_trip(self):
        """The two spellings of emptiness nobody spells the same way twice."""
        conditions = [
            domainspec.Condition("partner_id", "set"),
            domainspec.Condition("date", "not set"),
        ]
        rendered = domainspec.render(conditions)
        self.assertIn("'!=', False", rendered)
        self.assertIn("'=', False", rendered)
        parsed = domainspec.parse(rendered)
        assert parsed is not None
        back, _joiner = parsed
        self.assertEqual([c.operator for c in back], ["set", "not set"])

    def test_a_mixture_of_and_and_or_is_refused(self):
        self.assertIsNone(
            domainspec.parse("['&', '|', ('a','=',1), ('b','=',2), ('c','=',3)]")
        )

    def test_a_negation_is_refused(self):
        self.assertIsNone(domainspec.parse("['!', ('a', '=', 1)]"))

    def test_a_grouped_domain_is_refused(self):
        """`['&', '|', a, b, c]` binds differently from a flat list, so there
        is no honest flat rendering of it."""
        self.assertIsNone(
            domainspec.parse("['|', '&', ('a','=',1), ('b','=',2), ('c','=',3)]")
        )

    def test_nonsense_is_refused_rather_than_guessed(self):
        for text in ("not a domain", "{'a': 1}", "[('a', '=')]", "[42]"):
            self.assertIsNone(domainspec.parse(text), text)

    def test_an_unknown_joiner_is_a_programming_error(self):
        with raises(self, ValueError):
            domainspec.render([domainspec.Condition("a", "=", 1)], joiner="maybe")

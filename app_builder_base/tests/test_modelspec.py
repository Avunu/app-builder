# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""I1 -- the codegen fixed point, plus spec validation and diffing.

This is the strongest determinism guard the project has, and it replaces
byte-identity-on-a-fixture as the primary one. Two properties, over every spec
the builder can produce:

    parse_model(render_model(spec)) == spec
    render_model(parse_model(source)) == source

The second is what makes the emitter safe to run on every change. The first is
what makes the *parser* safe -- a parser that silently dropped a ``help=``
string would still satisfy the second property forever, on a file that had
quietly lost the developer's text.

Deliberately ``BaseCase`` rather than ``TransactionCase``: nothing here touches
a database, so it runs in milliseconds and can gate the phases that do. (A bare
``unittest.TestCase`` does not work -- Odoo's loader reads ``test_module``, which
only ``MetaCase`` supplies.)
"""

import ast
import itertools

from odoo.tests import BaseCase, tagged

from ..tools import modelspec, pycodegen, pyparse
from ..tools.modelspec import ConstraintSpec, FieldSpec, ModelSpec, SelectionSpec


def spec_with(*fields, **kwargs):
    kwargs.setdefault("name", "probe.model")
    kwargs.setdefault("description", "Probe Model")
    kwargs.setdefault("class_name", "ProbeModel")
    return ModelSpec(fields=tuple(fields), **kwargs)


# One field per supported ttype, each carrying the arguments that type needs.
BY_TTYPE = {
    "char": FieldSpec(name="f_char", ttype="char", string="Char", size=64),
    "text": FieldSpec(name="f_text", ttype="text", string="Text", translate=True),
    "html": FieldSpec(name="f_html", ttype="html", string="Html"),
    "boolean": FieldSpec(name="f_bool", ttype="boolean", string="Bool"),
    "integer": FieldSpec(name="f_int", ttype="integer", string="Int", default="0"),
    "float": FieldSpec(name="f_float", ttype="float", string="Float", digits=(12, 4)),
    "date": FieldSpec(name="f_date", ttype="date", string="Date"),
    "datetime": FieldSpec(name="f_dt", ttype="datetime", string="Datetime"),
    "binary": FieldSpec(name="f_bin", ttype="binary", string="Binary"),
    "monetary": FieldSpec(
        name="f_money", ttype="monetary", string="Money", currency_field="currency_id"
    ),
    "selection": FieldSpec(
        name="f_sel",
        ttype="selection",
        string="Selection",
        selection=(SelectionSpec("a", "A", 10), SelectionSpec("b", "B", 20)),
        default='"a"',
    ),
    "reference": FieldSpec(
        name="f_ref",
        ttype="reference",
        string="Reference",
        selection=(SelectionSpec("res.partner", "Partner", 10),),
    ),
    "many2one": FieldSpec(
        name="f_m2o",
        ttype="many2one",
        string="M2O",
        comodel="res.partner",
        ondelete="cascade",
        domain="[('active', '=', True)]",
    ),
    "one2many": FieldSpec(
        name="f_o2m",
        ttype="one2many",
        string="O2M",
        comodel="probe.line",
        inverse_name="probe_id",
    ),
    "many2many": FieldSpec(
        name="f_m2m",
        ttype="many2many",
        string="M2M",
        comodel="res.partner.category",
        relation_table="probe_tag_rel",
        column1="probe_id",
        column2="tag_id",
    ),
}

# Attributes toggled independently on top of a plain char field.
TOGGLES = (
    {"required": True},
    {"readonly": True},
    {"readonly": False},
    {"index": True},
    {"copy": False},
    {"store": False},
    {"store": True},
    {"help": 'A "quoted" help string'},
    {"tracking": 1},
    {"tracking": True},
    {"default": '"draft"'},
    {"default": 'lambda self: _("New")'},
    {"string": "Unicode — ûñí"},
    {"extra": (("company_dependent", "True"),)},
)


@tagged("standard", "at_install")
class TestCodegenFixedPoint(BaseCase):
    def assert_fixed_point(self, spec):
        source = pycodegen.render_model(spec)
        # The generated file must at minimum be importable Python. A syntax
        # error here would make the whole database unbootable once written,
        # since the next request re-imports the module.
        ast.parse(source)
        parsed = pyparse.parse_model(source)
        self.assertEqual(parsed, spec, "parse(render(spec)) must equal spec")
        self.assertEqual(
            pycodegen.render_model(parsed),
            source,
            "render(parse(source)) must equal source",
        )

    def test_every_supported_ttype_round_trips(self):
        for ttype, spec_field in BY_TTYPE.items():
            with self.subTest(ttype=ttype):
                self.assert_fixed_point(spec_with(spec_field))

    def test_all_ttypes_together_round_trip(self):
        self.assert_fixed_point(spec_with(*BY_TTYPE.values()))

    def test_each_attribute_toggle_round_trips(self):
        for toggle in TOGGLES:
            with self.subTest(toggle=toggle):
                base = {"name": "f_probe", "ttype": "char"}
                base.update(toggle)
                self.assert_fixed_point(spec_with(FieldSpec(**base)))

    def test_attribute_pairs_round_trip(self):
        """Pairs, because an emission-order bug only shows with two kwargs."""
        for first, second in itertools.combinations(TOGGLES, 2):
            if set(first) & set(second):
                continue
            with self.subTest(first=first, second=second):
                base = {"name": "f_probe", "ttype": "char"}
                base.update(first)
                base.update(second)
                self.assert_fixed_point(spec_with(FieldSpec(**base)))

    def test_model_level_attributes_round_trip(self):
        self.assert_fixed_point(
            spec_with(
                FieldSpec(name="name", ttype="char", string="Name"),
                FieldSpec(name="sequence", ttype="integer", string="Sequence"),
                inherit=("mail.thread", "mail.activity.mixin"),
                order="sequence, id",
                rec_name="name",
                sql_constraints=(
                    ConstraintSpec("uniq", "unique(name)", "Must be unique."),
                ),
            )
        )

    def test_transient_model_round_trips(self):
        self.assert_fixed_point(
            spec_with(FieldSpec(name="f_char", ttype="char"), transient=True)
        )

    def test_computed_field_round_trips(self):
        self.assert_fixed_point(
            spec_with(
                FieldSpec(name="base_amount", ttype="float", string="Base"),
                FieldSpec(
                    name="doubled",
                    ttype="float",
                    string="Doubled",
                    store=True,
                    readonly=False,
                    compute="_compute_doubled",
                    compute_body=(
                        "for rec in self:\n    rec.doubled = rec.base_amount * 2"
                    ),
                    depends=("base_amount",),
                ),
            )
        )

    def test_sequence_create_override_round_trips(self):
        self.assert_fixed_point(
            spec_with(
                FieldSpec(name="reference", ttype="char", string="Reference"),
                sequence_code="probe.model",
                sequence_field="reference",
            )
        )

    def test_long_field_lines_wrap_and_still_round_trip(self):
        """The wrapped form must parse back identically to the single-line one."""
        spec = spec_with(
            FieldSpec(
                name="f_m2o",
                ttype="many2one",
                comodel="res.partner",
                string="A rather long label to force the line over the limit",
                domain="[('is_company', '=', True), ('active', '=', True)]",
                ondelete="set null",
                help="And some help text as well, to be sure.",
            )
        )
        source = pycodegen.render_model(spec)
        self.assertIn("\n        ", source, "this fixture should have wrapped")
        self.assert_fixed_point(spec)

    def test_hand_written_method_is_preserved_verbatim(self):
        """The whole point of `preserved`: regenerating must not eat code."""
        method = (
            "    def action_confirm(self):\n"
            "        self.ensure_one()\n"
            "        return True"
        )
        spec = spec_with(FieldSpec(name="f_char", ttype="char"), preserved=(method,))
        source = pycodegen.render_model(spec)
        self.assertIn("def action_confirm", source)
        self.assert_fixed_point(spec)

    def test_extra_import_is_preserved(self):
        spec = spec_with(
            FieldSpec(name="f_char", ttype="char"),
            extra_imports=("from odoo.exceptions import UserError",),
        )
        self.assert_fixed_point(spec)


@tagged("standard", "at_install")
class TestParserIsConservative(BaseCase):
    """A parser that silently discarded what it did not understand would be
    worse than no parser: it would delete working code on the next save, and
    the round-trip property would still hold on the mangled result."""

    def assert_refused(self, source):
        with self.assertRaises(pyparse.UnsupportedConstruct):
            pyparse.parse_model(source)

    def test_unknown_class_attribute_is_refused(self):
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            '    _inherits = {"res.partner": "partner_id"}\n'
        )

    def test_dynamically_generated_fields_are_refused(self):
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    for i in range(3):\n"
            "        pass\n"
        )

    def test_unknown_field_type_is_refused(self):
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    weird = fields.Properties()\n"
        )

    def test_non_literal_kwarg_is_refused(self):
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    a = fields.Char(string=SOME_CONSTANT)\n"
        )

    def test_two_classes_are_refused(self):
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class A(models.Model):\n"
            '    _name = "a"\n\n\n'
            "class B(models.Model):\n"
            '    _name = "b"\n'
        )

    def test_syntax_error_is_refused(self):
        self.assert_refused("class P(models.Model)\n    _name =\n")

    def test_orphan_compute_method_is_refused(self):
        self.assert_refused(
            "from odoo import api, fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    a = fields.Char()\n\n"
            "    def _compute_missing(self):\n"
            "        pass\n"
        )

    def test_a_stray_comment_is_refused(self):
        """ast discards comments, so one in the class body would vanish on the
        next render with nothing to signal it. Freezing is the honest outcome."""
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    a = fields.Char()\n"
            "    # a developer's note that we cannot reproduce\n"
        )

    def test_a_comment_inside_a_preserved_method_is_kept(self):
        spec = pyparse.parse_model(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    a = fields.Char()\n\n"
            "    def action_go(self):\n"
            "        # this one is safe: the whole method is verbatim\n"
            "        return True\n"
        )
        self.assertIn("this one is safe", spec.preserved[0])

    def test_a_hand_written_method_is_kept_not_refused(self):
        """Preserved, not rejected -- this is the common case and must work."""
        spec = pyparse.parse_model(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
            "    a = fields.Char()\n\n"
            "    def action_go(self):\n"
            "        return True\n"
        )
        self.assertEqual(len(spec.preserved), 1)
        self.assertIn("action_go", spec.preserved[0])


@tagged("standard", "at_install")
class TestSpecValidation(BaseCase):
    """Reflection writes ir_model.order through raw SQL, bypassing every
    @api.constrains, and the x_ CHECK constraint only covers manual rows. This
    validator is the only thing left between a typo and a broken model."""

    def test_a_sound_spec_has_no_errors(self):
        spec = spec_with(
            FieldSpec(name="name", ttype="char", string="Name"),
            FieldSpec(name="sequence", ttype="integer", string="Sequence"),
            order="sequence, id",
            rec_name="name",
        )
        self.assertEqual(modelspec.validate_spec(spec), [])

    def test_order_on_an_unknown_field_is_rejected(self):
        spec = spec_with(FieldSpec(name="name", ttype="char"), order="nope desc")
        self.assertTrue(
            any("_order" in e for e in modelspec.validate_spec(spec)),
            "sorting on a field that does not exist raises on every search",
        )

    def test_order_on_an_unstored_field_is_rejected(self):
        spec = spec_with(
            FieldSpec(name="calc", ttype="float", store=False), order="calc"
        )
        self.assertTrue(any("_order" in e for e in modelspec.validate_spec(spec)))

    def test_magic_column_collision_is_rejected(self):
        spec = spec_with(FieldSpec(name="create_date", ttype="datetime"))
        self.assertTrue(modelspec.validate_spec(spec))

    def test_mixin_field_collision_is_rejected(self):
        spec = spec_with(
            FieldSpec(name="activity_ids", ttype="char"),
            inherit=("mail.activity.mixin",),
        )
        self.assertTrue(
            any("already defines" in e for e in modelspec.validate_spec(spec)),
            "shadowing a mixin field breaks something far from where it is set",
        )

    def test_python_keyword_is_rejected(self):
        spec = spec_with(FieldSpec(name="class", ttype="char"))
        self.assertTrue(modelspec.validate_spec(spec))

    def test_unusable_ttypes_are_rejected_with_a_reason(self):
        for ttype in modelspec.UNSUPPORTED_TTYPES:
            with self.subTest(ttype=ttype):
                spec = spec_with(FieldSpec(name="f_probe", ttype=ttype))
                errors = modelspec.validate_spec(spec)
                self.assertTrue(errors, "%s must be refused" % ttype)

    def test_relational_without_comodel_is_rejected(self):
        for ttype in modelspec.RELATIONAL:
            with self.subTest(ttype=ttype):
                spec = spec_with(FieldSpec(name="f_rel", ttype=ttype))
                self.assertTrue(modelspec.validate_spec(spec))

    def test_selection_without_values_is_rejected(self):
        """fields.Selection() with no argument raises at registry build, so
        this would produce a module that cannot be imported at all."""
        spec = spec_with(FieldSpec(name="state", ttype="selection"))
        self.assertTrue(modelspec.validate_spec(spec))

    def test_monetary_without_currency_is_rejected(self):
        spec = spec_with(FieldSpec(name="amount", ttype="monetary"))
        self.assertTrue(modelspec.validate_spec(spec))

    def test_duplicate_model_name_is_rejected(self):
        spec = spec_with(FieldSpec(name="name", ttype="char"))
        self.assertTrue(
            modelspec.validate_spec(spec, taken_model_names={"probe.model"})
        )


@tagged("standard", "at_install")
class TestSpecDiff(BaseCase):
    """The destructive flag gates the pre-migration. Getting it wrong in the
    permissive direction drops a column and its data."""

    def _base(self):
        return spec_with(
            FieldSpec(name="name", ttype="char"),
            FieldSpec(name="note", ttype="text"),
        )

    def test_adding_a_field_is_not_destructive(self):
        after = modelspec.with_field(
            self._base(), FieldSpec(name="extra", ttype="char")
        )
        diff = modelspec.diff_specs(self._base(), after)
        self.assertEqual(diff.added, ("extra",))
        self.assertFalse(diff.destructive)

    def test_removing_a_stored_field_is_destructive(self):
        diff = modelspec.diff_specs(
            self._base(), modelspec.without_field(self._base(), "note")
        )
        self.assertEqual(diff.removed, ("note",))
        self.assertEqual(diff.dropped_columns, ("note",))
        self.assertTrue(diff.destructive)

    def test_removing_an_unstored_computed_field_is_not_destructive(self):
        before = modelspec.with_field(
            self._base(),
            FieldSpec(
                name="calc",
                ttype="float",
                store=False,
                compute="_compute_calc",
                compute_body="pass",
            ),
        )
        diff = modelspec.diff_specs(before, self._base())
        self.assertEqual(diff.removed, ("calc",))
        self.assertFalse(diff.destructive, "an unstored field has no column to drop")

    def test_making_a_stored_field_unstored_is_destructive(self):
        """It drops the column just as surely as deleting the field does."""
        before = self._base()
        after = modelspec.with_field(
            before,
            FieldSpec(
                name="note",
                ttype="text",
                store=False,
                compute="_compute_note",
                compute_body="pass",
            ),
        )
        diff = modelspec.diff_specs(before, after)
        self.assertIn("note", diff.dropped_columns)
        self.assertTrue(diff.destructive)

    def test_no_change_is_empty(self):
        self.assertTrue(modelspec.diff_specs(self._base(), self._base()).empty)

    def test_json_round_trip_preserves_the_spec(self):
        """The edit buffer holds specs as json; it must not quietly lose one."""
        spec = spec_with(*BY_TTYPE.values(), inherit=("mail.thread",), order="id")
        self.assertEqual(modelspec.spec_from_json(modelspec.spec_to_json(spec)), spec)

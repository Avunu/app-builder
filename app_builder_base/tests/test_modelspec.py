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

from ..tools import catalogue, modelspec, pycodegen, pyparse
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

    def test_an_extension_round_trips(self):
        """`_inherit` with no `_name` is Odoo's spelling for extending a model.

        The presence of `_name` is the whole discriminator, which is what keeps
        this unambiguous against a new model that happens to have mixins.
        """
        self.assert_fixed_point(
            ModelSpec(
                name="sale.order",
                description="",
                class_name="SaleOrder",
                extends=True,
                fields=(FieldSpec(name="x_ref", ttype="char", string="Ref"),),
            )
        )

    def test_an_extension_can_add_a_mixin(self):
        """The case approval rules need: `tier.validation` onto a core model."""
        self.assert_fixed_point(
            ModelSpec(
                name="sale.order",
                description="",
                class_name="SaleOrder",
                extends=True,
                inherit=("tier.validation",),
                fields=(FieldSpec(name="x_ref", ttype="char"),),
            )
        )

    def test_an_extension_carries_a_compute_method(self):
        """The case an automation's Python needs: a real method on a model
        somebody else declares."""
        self.assert_fixed_point(
            ModelSpec(
                name="sale.order",
                description="",
                class_name="SaleOrder",
                extends=True,
                fields=(
                    FieldSpec(
                        name="x_total",
                        ttype="float",
                        store=True,
                        readonly=False,
                        compute="_compute_x_total",
                        compute_body="for rec in self:\n    rec.x_total = 1",
                        depends=("amount_total",),
                    ),
                ),
            )
        )

    def test_a_new_model_with_mixins_is_not_read_as_an_extension(self):
        spec = spec_with(FieldSpec(name="name", ttype="char"), inherit=("mail.thread",))
        parsed = pyparse.parse_model(pycodegen.render_model(spec))
        self.assertFalse(parsed.extends)
        self.assertEqual(parsed.name, "probe.model")

    def test_an_extension_needs_no_description(self):
        """It inherits `_description`, and stating it again would make
        `ir_model.info` disagree with what reflection writes."""
        spec = ModelSpec(
            name="sale.order",
            description="",
            class_name="SaleOrder",
            extends=True,
            fields=(FieldSpec(name="x_ref", ttype="char"),),
        )
        self.assertFalse(modelspec.validate_spec(spec))

    def test_extending_a_model_that_exists_is_the_point(self):
        spec = ModelSpec(
            name="sale.order",
            description="",
            class_name="SaleOrder",
            extends=True,
            fields=(FieldSpec(name="x_ref", ttype="char"),),
        )
        self.assertFalse(
            modelspec.validate_spec(spec, taken_model_names=("sale.order",))
        )

    def test_declaring_a_model_that_exists_is_still_refused(self):
        spec = spec_with(FieldSpec(name="name", ttype="char"))
        self.assertTrue(
            modelspec.validate_spec(spec, taken_model_names=("probe.model",))
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

    def test_anything_outside_the_block_survives_a_rewrite(self):
        """The whole point of the marker convention.

        The studio never reads outside the block, so none of this needs to be
        modelled, preserved, or even understood -- it simply is not touched.
        """
        spec = spec_with(FieldSpec(name="f_char", ttype="char", string="Char"))
        source = pycodegen.render_model(spec)
        hostile = source.replace(
            "class ProbeModel(models.Model):",
            "import functools\n"
            "from odoo.exceptions import UserError\n\n\n"
            "def _decor(fn):\n"
            "    return functools.wraps(fn)(fn)\n\n\n"
            "class ProbeModel(models.Model, metaclass=type(models.Model)):",
        ) + (
            "\n"
            "    @property\n"
            "    def shouty(self):\n"
            "        # a comment, which the old whole-file parser froze on\n"
            '        return (self.f_char or "").upper()\n\n'
            "    @_decor\n"
            "    def action_go(self):\n"
            '        raise UserError("nope")\n'
        )

        rewritten = pycodegen.splice_block(hostile, pycodegen.render_block(spec), spec)

        ast.parse(rewritten)
        for survivor in (
            "metaclass=type(models.Model)",
            "import functools",
            "def shouty",
            "@_decor",
            "old whole-file parser froze on",
        ):
            self.assertIn(survivor, rewritten, "%s must survive" % survivor)
        self.assertEqual(rewritten.count(pycodegen.BEGIN_MARKER), 1)
        self.assertEqual(pyparse.parse_model(rewritten), spec)

    def test_a_file_with_no_block_gets_one_after_the_class(self):
        spec = spec_with(FieldSpec(name="f_char", ttype="char"))
        bare = (
            "from odoo import fields, models\n\n\n"
            "class ProbeModel(models.Model):\n"
            '    _name = "probe.model"\n\n'
            "    def existing(self):\n"
            "        return 1\n"
        )
        rewritten = pycodegen.splice_block(bare, pycodegen.render_block(spec), spec)
        ast.parse(rewritten)
        self.assertIn("def existing", rewritten)
        self.assertEqual(pyparse.parse_model(rewritten), spec)

    def test_imports_widen_when_the_block_needs_more(self):
        """The one edit outside the block, and it only ever adds."""
        spec = spec_with(
            FieldSpec(
                name="total",
                ttype="float",
                compute="_compute_total",
                compute_body="pass",
            )
        )
        source = (
            "from odoo import fields, models\n\n\n"
            "class ProbeModel(models.Model):\n    pass\n"
        )
        widened = pycodegen.ensure_imports(source, spec)
        self.assertIn("from odoo import api, fields, models", widened)
        self.assertEqual(
            pycodegen.ensure_imports(widened, spec), widened, "must be idempotent"
        )


@tagged("standard", "at_install")
class TestParserIsConservative(BaseCase):
    """Inside the block, anything unmodelled is refused rather than silently
    dropped. Outside it, nothing is even looked at -- which is what stops a
    developer from locking themselves out of their own builder."""

    def assert_refused(self, source):
        """``source`` is a whole file."""
        with self.assertRaises(pyparse.UnsupportedConstruct):
            pyparse.parse_model(source)

    def assert_block_refused(self, body):
        """``body`` is class-body source that will sit inside the markers."""
        # Written out rather than joined from a list: the shape of the file is
        # the point of the fixture, and a reader should be able to see it.
        source = f"""from odoo import api, fields, models


class P(models.Model):
{pycodegen.BEGIN_MARKER}
{body}
{pycodegen.END_MARKER}
"""
        with self.assertRaises(pyparse.UnsupportedConstruct):
            pyparse.parse_model(source)

    def test_unknown_class_attribute_is_refused(self):
        self.assert_block_refused(
            '    _name = "p"\n    _inherits = {"res.partner": "partner_id"}'
        )

    def test_dynamically_generated_fields_are_refused(self):
        self.assert_block_refused(
            '    _name = "p"\n    for i in range(3):\n        pass'
        )

    def test_unknown_field_type_is_refused(self):
        self.assert_block_refused('    _name = "p"\n    weird = fields.Properties()')

    def test_non_literal_kwarg_is_refused(self):
        self.assert_block_refused(
            '    _name = "p"\n    a = fields.Char(string=SOME_CONSTANT)'
        )

    def test_syntax_error_is_refused(self):
        self.assert_block_refused("    _name =")

    def test_orphan_compute_method_is_refused(self):
        self.assert_block_refused(
            '    _name = "p"\n'
            "    a = fields.Char()\n"
            "\n"
            "    def _compute_missing(self):\n"
            "        pass"
        )

    def test_a_file_with_no_block_is_refused(self):
        self.assert_refused(
            "from odoo import fields, models\n\n\n"
            "class P(models.Model):\n"
            '    _name = "p"\n'
        )

    def test_behaviour_inside_the_block_is_refused_with_a_way_out(self):
        """Not a freeze: the message says exactly where the method belongs."""
        spec = spec_with(FieldSpec(name="a", ttype="char"))
        source = pycodegen.render_model(spec).replace(
            pycodegen.END_MARKER,
            "\n    def action_go(self):\n        return True\n" + pycodegen.END_MARKER,
        )
        with self.assertRaises(pyparse.UnsupportedConstruct) as caught:
            pyparse.parse_model(source)
        self.assertIn("below the block", str(caught.exception))


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


@tagged("standard", "at_install")
class TestFieldTypePresets(BaseCase):
    """A picker entry is not an ORM type.

    Odoo's own picker shows 21 entries over 15 types, because several are one
    type dressed differently: Priority is a selection that arrives with four
    values and a star, Image is a binary that arrives showing the image. The
    entry key never reaches the spec -- resolving it early is what keeps the
    code generator ignorant of picker affordances.
    """

    def test_a_preset_expands_to_a_real_type(self):
        values, widget = modelspec.apply_preset({"name": "x_p", "ttype": "priority"})
        self.assertEqual(values["ttype"], "selection")
        self.assertEqual(widget, "priority")
        self.assertEqual(
            [v["value"] for v in values["selection"]],
            ["0", "1", "2", "3"],
            "three stars means four values -- the first is no stars",
        )

    def test_a_preset_never_overrides_what_the_user_said(self):
        values, _widget = modelspec.apply_preset(
            {"ttype": "priority", "selection": [{"value": "a", "label": "A"}]}
        )
        self.assertEqual([v["value"] for v in values["selection"]], ["a"])

    def test_a_plain_type_is_its_own_entry(self):
        values, widget = modelspec.apply_preset({"ttype": "char"})
        self.assertEqual(values["ttype"], "char")
        self.assertEqual(widget, "")

    def test_every_entry_key_is_unique(self):
        keys = [e.picker_key for e in modelspec.FIELD_TYPES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_preset_widget_exists_in_the_catalogue(self):
        """Offering a widget the view editor would refuse is the drift the
        shared catalogue exists to prevent."""
        for entry in modelspec.FIELD_TYPES:
            if not entry.widget:
                continue
            known = {w.value for w in catalogue.widgets_for(entry.ttype)}
            self.assertIn(
                entry.widget,
                known,
                "%s offers '%s', which the catalogue does not list for %s"
                % (entry.picker_key, entry.widget, entry.ttype),
            )

    def test_placement_carries_the_widget(self):
        placement = modelspec.default_placement("image")
        self.assertEqual(placement["widget"], "image")
        self.assertTrue(placement["form"])

    def test_a_date_range_is_not_offered_as_a_column(self):
        self.assertFalse(modelspec.default_placement("daterange")["list"])
        self.assertTrue(modelspec.default_placement("datetime")["list"])

    def test_clean_placement_keeps_an_explicit_widget(self):
        cleaned = modelspec.clean_placement({"widget": "priority"}, "selection")
        self.assertEqual(cleaned["widget"], "priority")

    def test_clean_placement_can_clear_a_widget(self):
        cleaned = modelspec.clean_placement({"widget": ""}, "image")
        self.assertEqual(
            cleaned["widget"], "image", "an absent answer keeps the default"
        )

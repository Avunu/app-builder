# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The single definition of a studio-built model.

A ``ModelSpec`` is what the builder edits and what the code generator renders.
The ``.py`` file on disk is its canonical serialization: ``render_model`` writes
one, ``parse_model`` reads one back, and the two are inverses. That is what lets
the emitter regenerate a file on every change without losing information --
because the information lives in the file, not in the database.

``ir.model`` and ``ir.model.fields`` are therefore *downstream reflection
artefacts* for anything the package owns in Python, never inputs. The one place
that direction reverses is adoption, where ``spec_from_ir_model`` seeds a spec
from metadata that already exists.

Deliberately free of any ``odoo`` import. Everything here is a pure function
over plain data, so the whole layer is testable in milliseconds with no
database -- which matters because the codegen fixed-point property is the
strongest guard the project has against a lossy parser.

**``None`` means "unstated", not "false".** A field attribute is emitted only
when it is not ``None``, so the generated source says exactly what the user
decided and stays silent where Odoo's own default already applies. Collapsing
that to a boolean would make ``parse(render(spec)) == spec`` false for every
field that relies on a default.
"""

import ast
import io
import tokenize
from dataclasses import asdict, dataclass, replace


def canonical_source(text):
    """One spelling per expression, so verbatim source can round-trip.

    Anything that does not parse is left alone: it will be caught by the
    compile-check before it ever reaches disk, and mangling it here would only
    make the error harder to read.
    """
    try:
        return _prefer_double_quotes(ast.unparse(ast.parse(text, mode="eval").body))
    except (SyntaxError, ValueError):
        return text


def _prefer_double_quotes(source):
    """Re-quote string literals the way the rest of the generated file is quoted.

    ``ast.unparse`` always emits single quotes. That is not cosmetic here: the
    project formats generated packages with ruff, so a single-quoted default
    would be rewritten on the next commit and the package would report as
    drifted with nothing actually changed.

    Splices by token position rather than going through ``untokenize``, which
    reconstructs whitespace from scratch and turns ``lambda self: _("New")``
    into ``lambda self :_ ("New")`` -- valid, but the exact churn this exists
    to prevent.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return source

    lines = source.splitlines(keepends=True)
    edits = []
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        text = token.string
        if not (text.startswith("'") and text.endswith("'") and len(text) >= 2):
            continue
        body = text[1:-1]
        if '"' in body or "\\" in body:
            continue
        if token.start[0] != token.end[0]:
            continue  # multi-line string: leave it alone
        edits.append((token.start[0], token.start[1], token.end[1], '"%s"' % body))

    # Apply from the end so earlier columns stay valid.
    for row, col_start, col_end, replacement in sorted(edits, reverse=True):
        line = lines[row - 1]
        lines[row - 1] = line[:col_start] + replacement + line[col_end:]
    return "".join(lines)


# odoo.models.MAGIC_COLUMNS plus display_name. Inlined rather than imported so
# this module stays database-free; pinned by a test that compares it against
# the real thing.
MAGIC_COLUMNS = (
    "id",
    "create_uid",
    "create_date",
    "write_uid",
    "write_date",
    "display_name",
)

# Field attributes that mixins bring with them. A studio field colliding with
# one of these does not fail loudly -- it shadows a mixin field and breaks
# something far away -- so validate_spec refuses it up front.
MIXIN_FIELDS = {
    "mail.thread": (
        "message_ids",
        "message_follower_ids",
        "message_partner_ids",
        "message_is_follower",
        "message_needaction",
        "message_has_error",
        "message_attachment_count",
        "website_message_ids",
        "has_message",
    ),
    "mail.activity.mixin": (
        "activity_ids",
        "activity_state",
        "activity_user_id",
        "activity_type_id",
        "activity_type_icon",
        "activity_date_deadline",
        "my_activity_date_deadline",
        "activity_summary",
        "activity_exception_decoration",
        "activity_exception_icon",
    ),
}

PYTHON_KEYWORDS = frozenset(
    """
    False None True and as assert async await break class continue def del elif
    else except finally for from global if import in is lambda nonlocal not or
    pass raise return try while with yield match case
    """.split()
)

RELATIONAL = ("many2one", "one2many", "many2many")

# ttypes the studio will generate. Deliberately narrower than
# fields.Field.by_type: see validate_spec for why each exclusion exists.
SUPPORTED_TTYPES = (
    "binary",
    "boolean",
    "char",
    "date",
    "datetime",
    "float",
    "html",
    "integer",
    "many2many",
    "many2one",
    "monetary",
    "one2many",
    "reference",
    "selection",
    "text",
)

UNSUPPORTED_TTYPES = {
    "properties": (
        "Properties are defined by a parent record: definition_record and "
        "definition_record_field are class attributes with no ir.model.fields "
        "column, so the field cannot be described here."
    ),
    "properties_definition": (
        "A properties definition only means anything alongside a properties "
        "field on a child model."
    ),
    "many2one_reference": (
        "Its value is a raw database id, which cannot be written to source in "
        "a form that survives a fresh install."
    ),
    "json": "No editor widget. Use a Long text field.",
}


@dataclass(frozen=True, slots=True)
class SelectionSpec:
    value: str
    label: str
    sequence: int = 10


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    name: str
    definition: str
    message: str


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field. ``None`` on an attribute means "leave it to Odoo's default"."""

    name: str
    ttype: str
    string: str | None = None
    help: str | None = None

    # relational
    comodel: str | None = None
    inverse_name: str | None = None
    relation_table: str | None = None
    column1: str | None = None
    column2: str | None = None
    domain: str | None = None
    ondelete: str | None = None

    # typed extras
    selection: tuple[SelectionSpec, ...] = ()
    size: int | None = None
    digits: tuple[int, int] | None = None
    currency_field: str | None = None
    translate: bool | None = None

    # behaviour
    required: bool | None = None
    readonly: bool | None = None
    index: bool | None = None
    copy: bool | None = None
    store: bool | None = None
    tracking: int | None = None
    # A method name for many2one, or True for selection: the two are not
    # interchangeable, and passing a string where Odoo wants the boolean makes
    # it look for a method that does not exist.
    group_expand: str | bool | None = None
    default: str | None = None  # verbatim Python source, e.g. '"draft"'

    # derived
    related: str | None = None
    compute: str | None = None  # method name
    compute_body: str | None = None  # verbatim method body, no decorator
    depends: tuple[str, ...] = ()

    # anything we round-trip but do not model
    extra: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        # `default` and `extra` hold verbatim Python source, because a default
        # may be a lambda we must not try to interpret. Source text has more
        # than one spelling for the same expression, though, and the parser
        # reads it back through ast.unparse -- so `_("New")` returns as
        # `_('New')` and the codegen fixed point fails on quoting alone.
        # Canonicalising here means the invariant holds for any spec anyone
        # constructs, not just for ones that happen to be already normalised.
        for attr in ("default",):
            value = getattr(self, attr)
            if value is not None:
                object.__setattr__(self, attr, canonical_source(value))
        if self.extra:
            object.__setattr__(
                self,
                "extra",
                tuple((k, canonical_source(v)) for k, v in self.extra),
            )

    @property
    def is_stored(self):
        """Whether this field has a column, for destructive-diff purposes."""
        if self.related is not None or self.compute is not None:
            return self.store is True
        return self.store is not False


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    description: str
    class_name: str
    inherit: tuple[str, ...] = ()
    order: str | None = None
    rec_name: str | None = None
    active_name: str | None = None
    transient: bool = False
    fields: tuple[FieldSpec, ...] = ()
    sql_constraints: tuple[ConstraintSpec, ...] = ()
    sequence_code: str | None = None
    sequence_field: str | None = None

    def field(self, name):
        return next((f for f in self.fields if f.name == name), None)

    @property
    def field_names(self):
        return tuple(f.name for f in self.fields)


# -- json ----------------------------------------------------------------


def spec_to_json(spec):
    """Plain-dict form, for the transient edit buffer."""
    return asdict(spec)


def spec_from_json(data):
    data = dict(data)
    data["fields"] = tuple(
        FieldSpec(
            **{
                **f,
                "selection": tuple(SelectionSpec(**s) for s in f.get("selection", ())),
                "depends": tuple(f.get("depends", ())),
                "extra": tuple(tuple(pair) for pair in f.get("extra", ())),
                "digits": tuple(f["digits"]) if f.get("digits") else None,
            }
        )
        for f in data.get("fields", ())
    )
    data["inherit"] = tuple(data.get("inherit", ()))
    data["sql_constraints"] = tuple(
        ConstraintSpec(**c) for c in data.get("sql_constraints", ())
    )
    return ModelSpec(**data)


# -- diff ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpecDiff:
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    # Removals that take a column with them. These are the ones that need a
    # pre-migration: _process_end unlinks the metadata row and _drop_column
    # issues ALTER TABLE ... DROP COLUMN CASCADE, taking the data too.
    dropped_columns: tuple[str, ...] = ()
    model_changed: tuple[str, ...] = ()

    @property
    def destructive(self):
        return bool(self.dropped_columns)

    @property
    def empty(self):
        return not (self.added or self.removed or self.changed or self.model_changed)


MODEL_ATTRS = (
    "name",
    "description",
    "class_name",
    "inherit",
    "order",
    "rec_name",
    "active_name",
    "transient",
    "sql_constraints",
    "sequence_code",
    "sequence_field",
)


def diff_specs(before, after):
    """What changed, and which of it destroys a column."""
    if before is None:
        return SpecDiff(added=after.field_names if after else ())
    if after is None:
        return SpecDiff(
            removed=before.field_names,
            dropped_columns=tuple(f.name for f in before.fields if f.is_stored),
        )

    old = {f.name: f for f in before.fields}
    new = {f.name: f for f in after.fields}
    added = tuple(n for n in after.field_names if n not in old)
    removed = tuple(n for n in before.field_names if n not in new)
    changed = tuple(n for n in after.field_names if n in old and old[n] != new[n])
    dropped = tuple(n for n in removed if old[n].is_stored)
    # A stored field turning unstored drops its column just as surely as a
    # deletion does.
    dropped += tuple(n for n in changed if old[n].is_stored and not new[n].is_stored)
    model_changed = tuple(
        a for a in MODEL_ATTRS if getattr(before, a) != getattr(after, a)
    )
    return SpecDiff(
        added=added,
        removed=removed,
        changed=changed,
        dropped_columns=dropped,
        model_changed=model_changed,
    )


# -- validation ----------------------------------------------------------

_IDENT = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _valid_identifier(name):
    """Postgres-safe and Python-safe: what check_pg_name accepts."""
    if not name or len(name) > 63:
        return False
    if name[0] not in "abcdefghijklmnopqrstuvwxyz_":
        return False
    return all(c in _IDENT for c in name)


def _valid_model_name(name):
    if not name or len(name) > 63:
        return False
    parts = name.split(".")
    return all(_valid_identifier(p) for p in parts)


def validate_spec(spec, taken_model_names=()):
    """Everything Odoo will no longer check for us.

    Reflection writes ``ir_model.order`` through ``upsert_en`` -- raw SQL that
    bypasses every ``@api.constrains`` -- so ``_check_order`` does not protect a
    code-defined model. Nor does the ``x_`` CHECK constraint, which only applies
    to ``state='manual'`` rows. This validator is the only thing standing
    between a typo and a model that raises on every ``search``.
    """
    errors = []

    if not _valid_model_name(spec.name):
        errors.append(
            "'%s' is not a usable model name: lowercase letters, digits, "
            "underscores and dots, 63 characters at most." % spec.name
        )
    if spec.name in taken_model_names:
        errors.append("A model named '%s' already exists." % spec.name)
    if not spec.description:
        errors.append("The model needs a description; it becomes _description.")
    if not spec.class_name or not spec.class_name[0].isupper():
        errors.append("'%s' is not a usable class name." % spec.class_name)

    reserved = set(MAGIC_COLUMNS)
    for mixin in spec.inherit:
        reserved.update(MIXIN_FIELDS.get(mixin, ()))

    seen = set()
    stored = set()
    for spec_field in spec.fields:
        name = spec_field.name
        errors.extend(_validate_field_name(name, reserved, seen))
        seen.add(name)
        errors.extend(_validate_field_type(spec_field))
        if spec_field.is_stored:
            stored.add(name)

    if spec.rec_name and spec.rec_name not in seen:
        errors.append(
            "_rec_name points at '%s', which this model does not define."
            % spec.rec_name
        )
    if spec.sequence_field and spec.sequence_field not in seen:
        errors.append(
            "The sequence fills '%s', which this model does not define."
            % spec.sequence_field
        )

    errors.extend(_validate_order(spec, stored))
    return errors


def _validate_field_name(name, reserved, seen):
    label = "Field '%s'" % name
    errors = []
    if not _valid_identifier(name):
        errors.append(
            "%s is not a usable field name: lowercase letters, digits and "
            "underscores, 63 characters at most." % label
        )
    if name in PYTHON_KEYWORDS:
        errors.append("%s is a Python keyword." % label)
    if name in reserved:
        errors.append(
            "%s collides with a field Odoo already defines on this model." % label
        )
    if name in seen:
        errors.append("%s is defined twice." % label)
    return errors


def _validate_field_type(spec_field):
    """Whatever the chosen type cannot do without."""
    label = "Field '%s'" % spec_field.name
    ttype = spec_field.ttype
    errors = []

    if ttype in UNSUPPORTED_TTYPES:
        errors.append("%s: %s" % (label, UNSUPPORTED_TTYPES[ttype]))
    elif ttype not in SUPPORTED_TTYPES:
        errors.append("%s has an unknown type '%s'." % (label, ttype))

    if ttype in RELATIONAL and not spec_field.comodel:
        errors.append("%s is relational and needs a target model." % label)
    if ttype == "one2many" and not spec_field.inverse_name:
        errors.append(
            "%s is a one2many and needs the field on the other model that "
            "points back." % label
        )
    if ttype == "monetary" and not spec_field.currency_field:
        errors.append(
            "%s is an amount and needs a currency field on this model." % label
        )
    if ttype in ("selection", "reference") and not spec_field.selection:
        errors.append(
            "%s is a selection with no values, which cannot be built at all -- "
            "fields.Selection() raises without one." % label
        )
    if spec_field.compute and not spec_field.compute_body:
        errors.append("%s declares a compute with no body." % label)
    return errors


def _validate_order(spec, stored):
    """_order may only name stored fields, or Odoo raises on every search."""
    if not spec.order:
        return []
    errors = []
    for term in spec.order.split(","):
        parts = term.split()
        if not parts:
            errors.append("_order has an empty term: %r." % spec.order)
            continue
        name = parts[0].strip('"')
        if len(parts) > 2 or (
            len(parts) == 2 and parts[1].lower() not in ("asc", "desc")
        ):
            errors.append("'%s' is not a valid _order term." % term.strip())
            continue
        if name not in stored and name not in MAGIC_COLUMNS:
            errors.append(
                "_order sorts on '%s', which is not a stored field of this "
                "model. Odoo raises on every search when that happens." % name
            )
    return errors


# -- convenience ---------------------------------------------------------


def with_field(spec, spec_field):
    """Add or replace one field, preserving declaration order."""
    names = spec.field_names
    if spec_field.name in names:
        fields_ = tuple(
            spec_field if f.name == spec_field.name else f for f in spec.fields
        )
    else:
        fields_ = spec.fields + (spec_field,)
    return replace(spec, fields=fields_)


def without_field(spec, name):
    return replace(spec, fields=tuple(f for f in spec.fields if f.name != name))

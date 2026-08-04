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
import keyword
import tokenize
from dataclasses import asdict, dataclass, replace

from . import catalogue


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

# Straight from the interpreter rather than transcribed: a hand-copied list
# silently rots when Python gains a keyword, and the failure mode is a generated
# class that will not import.
PYTHON_KEYWORDS = frozenset(keyword.kwlist) | frozenset(keyword.softkwlist)

RELATIONAL = ("many2one", "one2many", "many2many")


@dataclass(frozen=True, slots=True)
class FieldType:
    """One entry in the field picker.

    ``label`` is deliberately an affordance rather than an ORM type -- a site
    manager choosing "Related list" should not have to know it spells
    ``one2many``. ``params`` names the extra spec attributes this type needs,
    so the editor can show exactly the right rows and no others. ``unsupported``
    carries the reason a type is offered but disabled, because a type that
    silently vanishes from the list teaches nobody anything.

    An entry is *not* the same thing as an ORM type. Several are the same type
    dressed differently -- Priority is a selection that arrives with four values
    and a star widget, Image is a binary that arrives showing the image -- which
    is why Odoo's own picker has 21 entries over 15 types. ``key`` identifies
    the entry, ``ttype`` says what it builds, and ``preset`` is what the entry
    fills in so the user does not have to.
    """

    ttype: str
    label: str
    group: str
    params: tuple[str, ...] = ()
    unsupported: str | None = None
    # Defaults to the ttype: an ordinary type is its own entry.
    key: str = ""
    # The view attribute this entry implies. Not part of the field -- a widget
    # is a fact about a screen -- so it travels with placement.
    widget: str = ""
    # Spec attributes the entry supplies up front, as JSON-shaped values.
    preset: tuple[tuple[str, object], ...] = ()

    @property
    def picker_key(self):
        return self.key or self.ttype

    @property
    def supported(self):
        return self.unsupported is None


# The four values Odoo's own priority fields use. Three stars, because the
# first value is "no stars" -- which is the part everybody gets wrong when
# building one by hand.
PRIORITY_VALUES = (
    {"value": "0", "label": "Normal", "sequence": 10},
    {"value": "1", "label": "Low", "sequence": 20},
    {"value": "2", "label": "High", "sequence": 30},
    {"value": "3", "label": "Very High", "sequence": 40},
)


# Ordered: this is the order the picker shows.
FIELD_TYPES = (
    FieldType("char", "Text", "basic", ("size", "translate", "default")),
    FieldType("text", "Long text", "basic", ("translate", "default")),
    FieldType("html", "Rich text", "basic", ("translate",)),
    FieldType("boolean", "Checkbox", "basic", ("default",)),
    FieldType("integer", "Whole number", "basic", ("default",)),
    FieldType("float", "Decimal", "basic", ("digits", "default")),
    FieldType("monetary", "Amount", "basic", ("currency_field",)),
    FieldType("date", "Date", "basic", ("default",)),
    FieldType("datetime", "Date & Time", "basic", ("default",)),
    FieldType("selection", "Selection", "basic", ("selection", "default")),
    FieldType(
        "selection",
        "Priority",
        "basic",
        ("selection", "default"),
        key="priority",
        widget="priority",
        preset=(("selection", PRIORITY_VALUES),),
    ),
    FieldType("binary", "File", "basic", ()),
    FieldType("binary", "Image", "basic", (), key="image", widget="image"),
    FieldType("binary", "Signature", "basic", (), key="sign", widget="signature"),
    FieldType(
        "datetime",
        "Date range",
        "basic",
        ("default",),
        key="daterange",
        widget="daterange",
    ),
    FieldType(
        "many2one",
        "Link to one record",
        "relational",
        ("comodel", "domain", "ondelete", "default"),
    ),
    FieldType(
        "one2many", "Related list", "relational", ("comodel", "inverse_name", "domain")
    ),
    FieldType(
        "many2many",
        "Link to many records",
        "relational",
        ("comodel", "domain", "relation_table", "column1", "column2"),
    ),
    FieldType(
        "many2many",
        "Tags",
        "relational",
        ("comodel", "domain", "relation_table", "column1", "column2"),
        key="tags",
        widget="many2many_tags",
        # The base entry was *called* Tags and never set the widget, so it
        # rendered as a table of rows. The name now belongs to the entry that
        # actually produces tags.
    ),
    FieldType(
        "one2many",
        "Lines",
        "relational",
        ("comodel", "inverse_name", "domain"),
        key="lines",
        # No widget: what makes a Lines field is where it goes. A table of rows
        # inside a two-column group is unreadable at any real row count, which
        # is why placement gives it a page of its own.
    ),
    FieldType("reference", "Reference", "advanced", ("selection",)),
    FieldType(
        # The ttype is a placeholder: a related field has no type of its own,
        # and `resolve_related` replaces this with whatever the chain ends at
        # before the spec is stored. Declaring one here anyway keeps the entry
        # a `FieldType` like every other, rather than a special case the picker
        # has to know about.
        "char",
        "Related field",
        "advanced",
        ("related",),
        key="related",
    ),
    FieldType(
        "properties",
        "Properties",
        "advanced",
        unsupported=(
            "Properties are defined by a parent record: definition_record and "
            "definition_record_field are class attributes with no "
            "ir.model.fields column, so the field cannot be described here."
        ),
    ),
    FieldType(
        "properties_definition",
        "Properties definition",
        "advanced",
        unsupported=(
            "A properties definition only means anything alongside a "
            "properties field on a child model."
        ),
    ),
    FieldType(
        "many2one_reference",
        "Reference by id",
        "advanced",
        unsupported=(
            "It needs a companion field naming the model its id belongs to, "
            "and there is no way to declare one here. An existing one is "
            "written to source without trouble; what is missing is a way to "
            "build a new one."
        ),
    ),
    FieldType(
        "json",
        "JSON",
        "advanced",
        unsupported="No editor widget. Use a Long text field.",
    ),
)

FIELD_TYPES_BY_KEY = {entry.picker_key: entry for entry in FIELD_TYPES}

# First entry wins, which is the plain one: a *field* of type selection is a
# "Selection", even when it was built through the Priority entry. What the entry
# added is a widget and some values, and neither changes what the field is.
FIELD_TYPES_BY_TTYPE = {}
for _entry in FIELD_TYPES:
    FIELD_TYPES_BY_TTYPE.setdefault(_entry.ttype, _entry)

# Deduplicated in declaration order rather than through a set: a set's iteration
# order varies with PYTHONHASHSEED, and this project's whole claim is that
# nothing it produces depends on run-to-run chance. Membership is all anyone
# asks of it today, which is exactly how such a thing goes unnoticed.
SUPPORTED_TTYPES = tuple(dict.fromkeys(e.ttype for e in FIELD_TYPES if e.supported))
UNSUPPORTED_TTYPES = {e.ttype: e.unsupported for e in FIELD_TYPES if not e.supported}


def field_type_for(key):
    """The picker entry for ``key``, falling back to the plain type.

    Both are accepted because a stored draft predates the presets and names a
    ttype where a picker now sends an entry key.
    """
    return FIELD_TYPES_BY_KEY.get(key) or FIELD_TYPES_BY_TTYPE.get(key)


def apply_preset(values):
    """Expand a picker entry into the spec values it stands for.

    The entry key never reaches the spec: a ``FieldSpec`` describes a field, and
    "Priority" is not a field type -- it is a selection that arrives with four
    values and a star. Resolving it here keeps that distinction where it can be
    seen, rather than teaching the code generator about picker affordances.
    """
    values = dict(values or {})
    entry = field_type_for(values.get("ttype"))
    if entry is None:
        return values, ""
    values["ttype"] = entry.ttype
    for name, preset in entry.preset:
        # Only where the user has not already said something. A preset is a
        # starting point, and re-editing a field must not undo their answer.
        if not values.get(name):
            values[name] = preset
    return values, entry.widget


def available_field_types(spec=None, translate=catalogue.identity):
    """The picker's contents, with each entry's availability decided here.

    Shown-but-disabled beats hidden: a manager who wants an amount field and
    cannot find one learns nothing, whereas one who sees *Amount* greyed out
    with "needs a Currency field on this model" knows what to do next.
    """
    currency_present = bool(
        spec
        and any(
            f.ttype == "many2one" and f.comodel == "res.currency" for f in spec.fields
        )
    )
    out = []
    for entry in FIELD_TYPES:
        enabled, tooltip = entry.supported, entry.unsupported or ""
        if enabled and entry.ttype == "monetary" and not currency_present:
            enabled = False
            tooltip = (
                "An amount needs a Currency field on this model. Add a "
                '"Link to one record" pointing at res.currency first.'
            )
        out.append(
            {
                "value": entry.picker_key,
                "ttype": entry.ttype,
                "widget": entry.widget,
                "label": entry.label,
                "group": entry.group,
                "params": list(entry.params),
                "enabled": enabled,
                "tooltip": tooltip,
                "placement": default_placement(entry.picker_key),
                # The same widget table the view editor reads. The point of
                # sharing it is that a type cannot offer a widget here that the
                # view editor would refuse to set, or the other way round --
                # which is what two tables would eventually produce.
                "widgets": [
                    w.to_json(translate) for w in catalogue.widgets_for(entry.ttype)
                ],
            }
        )
    return out


# Where a field of each type goes in the scaffolded views, unless the user says
# otherwise. These are the defaults a developer would pick by hand: a name or a
# link is worth a column and worth searching; a long note is not.
PLACEMENT_SLOTS = ("form", "list", "search", "group_by")

_LIST_BY_DEFAULT = frozenset(
    {
        "char",
        "many2one",
        "date",
        "datetime",
        "selection",
        "integer",
        "float",
        "monetary",
        "boolean",
    }
)
_SEARCH_BY_DEFAULT = frozenset({"char", "text", "many2one"})


def default_placement(key):
    """Which views a newly added field should appear in.

    Takes a picker key or a plain ttype, because a preset can want different
    placement from the type it builds: an Image belongs on the form and nowhere
    near a list column, whatever binary fields do in general.

    ``group_by`` is off even for the types that support it: a group-by the user
    did not ask for is clutter in the search panel, and it is one tick to turn
    on. ``form`` is on for everything, because a field nobody can see is the
    single most confusing thing the builder could produce -- which is exactly
    what it produced before placement existed.
    """
    entry = field_type_for(key)
    ttype = entry.ttype if entry else key
    return {
        "form": True,
        "list": ttype in _LIST_BY_DEFAULT and key not in _NEVER_A_COLUMN,
        "search": ttype in _SEARCH_BY_DEFAULT,
        "group_by": False,
        # The widget the picker entry implies, if any. Placement is where view
        # intent lives, and a widget is exactly that -- it says how a screen
        # shows the field, not what the field is, so it has no business in the
        # spec the code generator renders.
        "widget": entry.widget if entry else "",
    }


# Entries whose type is list-worthy but which are not, as a column.
_NEVER_A_COLUMN = frozenset({"daterange"})


def clean_placement(values, key=None):
    """Coerce whatever the client sent into exactly the known slots."""
    base = default_placement(key) if key else dict.fromkeys(PLACEMENT_SLOTS, False)
    cleaned = {slot: bool(base.get(slot)) for slot in PLACEMENT_SLOTS}
    cleaned["widget"] = base.get("widget", "")
    if not values:
        return cleaned
    for slot in PLACEMENT_SLOTS:
        if slot in values:
            cleaned[slot] = bool(values[slot])
    if values.get("widget"):
        cleaned["widget"] = str(values["widget"])
    return cleaned


@dataclass(frozen=True, slots=True)
class SelectionSpec:
    value: str
    label: str
    sequence: int = 10


# Methods the builder owns carry this prefix. Not decoration: the parser reads
# the block back, and it needs to tell a method the builder wrote from one a
# developer added -- the latter belongs outside the block and is never touched.
STUDIO_METHOD_PREFIX = "_studio_"


@dataclass(frozen=True, slots=True)
class MethodSpec:
    """A method the builder owns, on the class it generates.

    The precedent is a compute body, which is already stored in the block,
    already round-tripped, and already the user's text rather than ours. What
    makes a method the builder's is not that it is schema -- it plainly is not
    -- but that the user wrote it *in the builder*. An automation's Python is
    the case: they typed it into a box in Odoo, so keeping it in the block is
    what lets them keep editing it there instead of it becoming a file they must
    now maintain by hand.
    """

    name: str
    body: str
    doc: str = ""


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
    # Whether this class *extends* ``name`` rather than declaring it. An
    # extension renders `_inherit = "sale.order"` with no `_name`, which is
    # Odoo's own idiom and the difference between adding to a model and
    # declaring a second one with the same name.
    #
    # It is what lets a package put a real method, or a mixin, onto a model
    # somebody else owns -- which is how an automation's Python graduates out
    # of a sandboxed string, and how approval rules reach a core model.
    extends: bool = False
    order: str | None = None
    rec_name: str | None = None
    active_name: str | None = None
    transient: bool = False
    fields: tuple[FieldSpec, ...] = ()
    methods: tuple[MethodSpec, ...] = ()
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


FIELD_ATTRS = frozenset(FieldSpec.__slots__)


def field_spec_from_json(data):
    """A ``FieldSpec`` from whatever the client sent.

    Unknown keys are dropped rather than raising: the editor sends a whole form
    payload, and a stray ``id`` or display value should not be an error.
    """
    values = {k: v for k, v in data.items() if k in FIELD_ATTRS}
    values["selection"] = tuple(
        SelectionSpec(**s) if isinstance(s, dict) else SelectionSpec(*s)
        for s in values.get("selection") or ()
    )
    values["depends"] = tuple(values.get("depends") or ())
    values["extra"] = tuple(tuple(pair) for pair in values.get("extra") or ())
    if values.get("digits"):
        values["digits"] = tuple(values["digits"])
    else:
        values["digits"] = None
    return FieldSpec(**values)


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
    data["methods"] = tuple(MethodSpec(**m) for m in data.get("methods", ()))
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
    "extends",
    "order",
    "rec_name",
    "active_name",
    "transient",
    "methods",
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

    if spec.extends and spec.name in taken_model_names:
        # Extending is the one case where the name existing is the *point*, so
        # the "already exists" check below has to be skipped rather than
        # tripped over.
        taken_model_names = tuple(n for n in taken_model_names if n != spec.name)
    if not _valid_model_name(spec.name):
        errors.append(
            "'%s' is not a usable model name: lowercase letters, digits, "
            "underscores and dots, 63 characters at most." % spec.name
        )
    if spec.name in taken_model_names:
        errors.append("A model named '%s' already exists." % spec.name)
    if not spec.description and not spec.extends:
        # An extension inherits `_description` from what it extends, so
        # requiring one here would force a second answer to a question already
        # answered -- and `_reflect_model_params` would then disagree with it.
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

# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Everything a new model needs to be an app somebody can actually use.

The spec half is pure and lives here. The arch half takes the *live* model,
because a view whose field names do not resolve fails ``_check_xml`` at create
time -- so the views are built after the class has loaded, from what the
registry really has.

Deliberately **not** built on ``Model._get_default_form_view``. That helper
skips only ``field.automatic``, so ``message_ids``, ``message_follower_ids``
and ``activity_ids`` are ordinary fields to it and would render as raw
relations in the middle of the form. Its field order is also whatever
``_fields`` happens to hold, which for our purposes is class-definition order
only by luck.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, cast

# lxml ships no type stubs in this environment (a compiled extension with no
# `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an installed
# dependency here), so pyright cannot resolve `etree` as an exported member of
# `lxml` at all -- confirmed directly, `from lxml import etree` alone reports
# both `reportMissingTypeStubs` (on `lxml`) and `reportAttributeAccessIssue`
# ("etree" is unknown import symbol, on `etree`). Ignored narrowly on each
# name rather than rewriting the import (e.g. `import lxml.etree as etree`),
# which trades this gap for a different one: ruff's own `PLR0402`
# (`fix = true` project-wide) silently auto-fixes that form straight back to
# `from lxml import etree`, reintroducing the failure. Same pattern as
# `xml_writer.py`/`placement.py`.
from lxml import (  # pyright: ignore[reportMissingTypeStubs]
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)

from .modelspec import (
    PRIORITY_VALUES,
    ConstraintSpec,
    FieldSpec,
    ModelSpec,
    SelectionSpec,
)
from .pycodegen import class_name_for

if TYPE_CHECKING:
    # Only for annotations below; with `from __future__ import annotations`
    # (above) nothing here needs these at runtime, and the module stays
    # importable with no Odoo on the path for the pure, spec-building half.
    from collections.abc import Callable, Collection, Iterable

    from odoo.fields import Field

    from .lxml_types import LxmlElement

CHATTER_MIXINS: tuple[str, ...] = ("mail.thread", "mail.activity.mixin")

DEFAULT_STAGES: tuple[tuple[str, str], ...] = (
    ("draft", "Draft"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
)


@dataclass(frozen=True, slots=True)
class Feature:
    """One thing a model can be given, described rather than branched on.

    These were nine booleans and a chain of ``if`` statements, which was fine
    while they were independent. They are not: Picture and Pipeline stages
    together put the image on the kanban card, Monetary value is meaningless
    without a currency, and Date & Calendar means a field *and* a view. Every
    one of those is a sentence about how two features interact, and a boolean
    has nowhere to write one down.

    ``implies`` is that sentence. ``views`` is the other half nobody had a place
    for: a feature can be as much about which screens exist as about which
    columns do.
    """

    key: str
    label: str
    help: str = ""
    implies: tuple[str, ...] = ()
    views: tuple[str, ...] = ()
    default: bool = False
    #: A second model this feature needs, built alongside the first. "tag" and
    #: "line" are the two shapes; see `companion_specs`.
    companion: str | None = None


FEATURES: tuple[Feature, ...] = (
    Feature(
        "chatter",
        "Messaging & activities",
        "A message log and scheduled activities on every record.",
        implies=("activities",),
        default=True,
    ),
    # Not offered separately: activities without a chatter to show them in is a
    # combination nobody asks for, and `implies` is how that is said now rather
    # than by two booleans a caller has to keep consistent.
    Feature("activities", "Activities", "Scheduling, alongside the message log."),
    Feature(
        "ordering",
        "Custom sorting",
        "A drag handle in the list, so records can be put in a deliberate order.",
        default=True,
    ),
    Feature(
        "active",
        "Archiving",
        "Records can be archived instead of deleted, and are hidden by default.",
        default=True,
    ),
    Feature(
        "description",
        "Notes",
        "A rich-text field across the width of the form.",
        default=True,
    ),
    Feature(
        "reference",
        "Reference numbers",
        "A sequence-backed reference, filled in on create.",
    ),
    Feature(
        "stage",
        "Pipeline stages",
        "A status bar, a priority, and a kanban to move records across.",
        views=("kanban",),
    ),
    Feature(
        "user",
        "Responsible",
        "Who is on it, defaulted to whoever creates the record.",
    ),
    Feature(
        "date",
        "Date & calendar",
        "A date, and a calendar to see it on.",
        views=("calendar",),
    ),
    Feature(
        "date_range",
        "Date range",
        "A start and an end, shown as one field.",
    ),
    Feature(
        "contact",
        "Contact details",
        "A customer, with their phone and e-mail alongside.",
    ),
    Feature("picture", "Picture", "An image in the top corner of the form."),
    Feature(
        "monetary",
        "Monetary value",
        "An amount. Brings the currency it is counted in.",
    ),
    Feature("company", "Company", "Which company the record belongs to."),
    # The two that need a second model. `companion` is what says so -- the
    # difference between "add a column" and "build another model, with its own
    # access rule, and point at it" is not something a boolean could carry,
    # which is why these two were the last documented features missing.
    Feature(
        "tags",
        "Tags",
        "Free-form labels, shared across records and coloured.",
        companion="tag",
    ),
    Feature(
        "lines",
        "Lines",
        "A table of child rows on the form, like order lines.",
        companion="line",
    ),
)

FEATURES_BY_KEY: dict[str, Feature] = {feature.key: feature for feature in FEATURES}
DEFAULT_FEATURES: frozenset[str] = frozenset(f.key for f in FEATURES if f.default)

# What a wizard has to offer: everything except what another feature already
# brings. Declared here so the wizard can be checked against it rather than
# drifting quietly when a feature is added.
_IMPLIED: set[str] = {key for f in FEATURES for key in f.implies}
WIZARD_FEATURES: tuple[str, ...] = tuple(
    f.key for f in FEATURES if f.key not in _IMPLIED
)


class FeatureJSON(TypedDict):
    """What ``features_json`` sends: one entry per tile the wizard renders."""

    key: str
    label: str
    help: str
    default: bool
    views: list[str]


def features_json() -> list[FeatureJSON]:
    """The list a wizard renders, in declaration order."""
    return [
        {
            "key": f.key,
            "label": f.label,
            "help": f.help,
            "default": f.default,
            "views": list(f.views),
        }
        for f in FEATURES
    ]


class ScaffoldOptions:
    """What to include beyond the bare model.

    Still attribute-accessed, because every caller and every arch builder reads
    it that way and a feature registry is not a reason to rewrite them. What
    changed underneath is that the set is closed and resolves its own
    implications, so "Monetary value without a currency" stops being a state the
    caller can construct.
    """

    #: Which features are on, closed over `implies`. The only real instance
    #: state; every other attribute read goes through `__getattr__` below.
    enabled: frozenset[str]

    def __init__(self, **flags: bool) -> None:
        unknown = set(flags) - set(FEATURES_BY_KEY)
        if unknown:
            raise ValueError(
                "unknown scaffold features: %s" % ", ".join(sorted(unknown))
            )
        enabled = {key for key in DEFAULT_FEATURES if flags.get(key, True)}
        enabled |= {key for key, value in flags.items() if value}
        self.enabled = frozenset(self._resolve(enabled))

    @staticmethod
    def _resolve(keys: Iterable[str]) -> set[str]:
        """Close over ``implies``, so a feature arrives with what it needs."""
        seen: set[str] = set()
        pending = list(keys)
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            pending.extend(FEATURES_BY_KEY[key].implies)
        return seen

    @classmethod
    def from_keys(cls, keys: Iterable[str] | None) -> ScaffoldOptions:
        """Exactly these features, defaults included only if asked for."""
        chosen = set(keys or ())
        unknown = chosen - set(FEATURES_BY_KEY)
        if unknown:
            raise ValueError(
                "unknown scaffold features: %s" % ", ".join(sorted(unknown))
            )
        options = cls.__new__(cls)
        options.enabled = frozenset(cls._resolve(chosen))
        return options

    def __getattr__(self, name: str) -> bool:
        # Only reached for attributes the instance does not have, so `enabled`
        # itself never comes through here.
        if name in FEATURES_BY_KEY:
            return name in self.enabled
        raise AttributeError(name)

    @property
    def view_types(self) -> tuple[str, ...]:
        """Views these features want, beyond the three every model gets."""
        out: list[str] = []
        for feature in FEATURES:
            if feature.key in self.enabled:
                out.extend(v for v in feature.views if v not in out)
        return tuple(out)


def inverse_name_for(model_name: str) -> str:
    """``studio_demo.workshop_job`` -> ``workshop_job_id``.

    Kept beside the companions because both sides -- the child's many2one and
    the parent's one2many ``inverse_name`` -- have to produce the same string,
    and they are built in different functions.
    """
    return "%s_id" % model_name.rsplit(".", 1)[-1]


def _companion_fields(model_name: str, options: ScaffoldOptions) -> list[FieldSpec]:
    """The parent's side of each companion model."""
    out: list[FieldSpec] = []
    if options.tags:
        out.append(
            FieldSpec(
                name="tag_ids",
                ttype="many2many",
                string="Tags",
                comodel=companion_name(model_name, "tag"),
            )
        )
    if options.lines:
        out.append(
            FieldSpec(
                name="line_ids",
                ttype="one2many",
                string="Lines",
                comodel=companion_name(model_name, "line"),
                inverse_name=inverse_name_for(model_name),
            )
        )
    return out


def companion_name(model_name: str, kind: str) -> str:
    """``x_studio_job`` + ``tag`` -> ``x_studio_job_tag``."""
    return "%s_%s" % (model_name, kind)


def companion_specs(
    model_name: str, label: str, options: ScaffoldOptions | None = None
) -> list[ModelSpec]:
    """The extra models the chosen features need, in load order.

    Tags and Lines are the only two documented features that are not a column:
    a tag is a record shared across many parents, a line is a record owned by
    one. Both need a model of their own, and the parent's field points at it --
    which is why they could not be added to the registry as another boolean.

    Returned before the parent spec is built, because the parent's many2many and
    one2many name these models.
    """
    options = options or ScaffoldOptions()
    specs: list[ModelSpec] = []
    if options.tags:
        specs.append(
            ModelSpec(
                name=companion_name(model_name, "tag"),
                description="%s Tag" % label,
                class_name=class_name_for(companion_name(model_name, "tag")),
                order="name",
                fields=(
                    FieldSpec(
                        name="name",
                        ttype="char",
                        string="Tag",
                        required=True,
                        translate=True,
                    ),
                    # Odoo's many2many_tags widget reads `color` for the pill
                    # colour, and shows a colour picker when it is present.
                    FieldSpec(name="color", ttype="integer", string="Colour"),
                ),
                # A tag's label is the whole record, so two with the same name
                # are a duplicate rather than two things.
                sql_constraints=(
                    ConstraintSpec(
                        name="name_uniq",
                        definition="unique(name)",
                        message="That tag already exists.",
                    ),
                ),
            )
        )
    if options.lines:
        # On the dot, not the underscore. A generated model is named
        # `<package>.<slug>` (`studio_app_builder.technical_name`), so splitting
        # on "_" gives `pkg.job_id` for `alpha_pkg.job` -- a field name with a
        # dot in it, which validate_spec refuses. The composer's
        # `_suggest_inverse_name` already splits this way; the two have to agree
        # or a line model built here cannot be built there.
        parent_field = inverse_name_for(model_name)
        specs.append(
            ModelSpec(
                name=companion_name(model_name, "line"),
                description="%s Line" % label,
                class_name=class_name_for(companion_name(model_name, "line")),
                order="sequence, id",
                fields=(
                    FieldSpec(
                        name=parent_field,
                        ttype="many2one",
                        string=label,
                        comodel=model_name,
                        required=True,
                        # A line without its parent is orphaned data; Odoo's own
                        # line models cascade for the same reason.
                        ondelete="cascade",
                        index=True,
                    ),
                    FieldSpec(
                        name="name", ttype="char", string="Description", required=True
                    ),
                    FieldSpec(name="sequence", ttype="integer", string="Sequence"),
                    FieldSpec(name="quantity", ttype="float", string="Quantity"),
                ),
            )
        )
    return specs


def scaffold_spec(
    model_name: str, label: str, options: ScaffoldOptions | None = None
) -> ModelSpec:
    """The model a site manager gets before they add anything of their own."""
    options = options or ScaffoldOptions()
    fields: list[FieldSpec] = [
        FieldSpec(
            name="name",
            ttype="char",
            string=label,
            required=True,
            # Tracked so the chatter has something to say from day one.
            tracking=1 if options.chatter else None,
        )
    ]

    if options.reference:
        fields.append(
            FieldSpec(
                name="reference",
                ttype="char",
                string="Reference",
                readonly=True,
                copy=False,
                index=True,
                default='lambda self: _("New")',
            )
        )
    if options.ordering:
        fields.append(
            FieldSpec(name="sequence", ttype="integer", string="Sequence", default="10")
        )
    if options.stage:
        fields.append(
            FieldSpec(
                name="state",
                ttype="selection",
                string="Status",
                selection=tuple(
                    SelectionSpec(value=v, label=lbl, sequence=(i + 1) * 10)
                    for i, (v, lbl) in enumerate(DEFAULT_STAGES)
                ),
                default='"draft"',
                required=True,
                tracking=1 if options.chatter else None,
            )
        )
    if options.stage:
        # Priority and kanban state are what make a pipeline a pipeline rather
        # than a status field: one says which card to look at first, the other
        # says whether it is blocked. Odoo's own kanbans have both.
        fields.append(
            FieldSpec(
                name="priority",
                ttype="selection",
                string="Priority",
                # `PRIORITY_VALUES` (`modelspec.py`) is declared
                # `tuple[dict[str, str | int], ...]` -- a heterogeneous
                # per-entry value type pyright cannot narrow per key -- but
                # every real entry's own literal shape is fixed:
                # `value`/`label` always `str`, `sequence` always `int`. Cast
                # back to what each key actually holds, the same
                # known-fixed-shape idiom `pycodegen.py`'s
                # `_field_spec_from_record` already uses.
                selection=tuple(
                    SelectionSpec(
                        value=cast("str", entry["value"]),
                        label=cast("str", entry["label"]),
                        sequence=cast("int", entry["sequence"]),
                    )
                    for entry in PRIORITY_VALUES
                ),
                default='"0"',
            )
        )
        fields.append(
            FieldSpec(
                name="kanban_state",
                ttype="selection",
                string="Kanban state",
                selection=(
                    SelectionSpec(value="normal", label="In Progress", sequence=10),
                    SelectionSpec(value="done", label="Ready", sequence=20),
                    SelectionSpec(value="blocked", label="Blocked", sequence=30),
                ),
                default='"normal"',
            )
        )
        # Odoo colours a kanban column from a field literally called `color`.
        fields.append(FieldSpec(name="color", ttype="integer", string="Colour"))
    if options.user:
        fields.append(
            FieldSpec(
                name="user_id",
                ttype="many2one",
                string="Responsible",
                comodel="res.users",
                ondelete="set null",
                # Internal users only. A portal or public user in a Responsible
                # field is never what anybody meant, and the domain is how Odoo
                # says so everywhere else.
                domain="[('share', '=', False)]",
                default="lambda self: self.env.user",
                tracking=1 if options.chatter else None,
            )
        )
    if options.contact:
        fields.append(
            FieldSpec(
                name="partner_id",
                ttype="many2one",
                string="Customer",
                comodel="res.partner",
                ondelete="set null",
                tracking=1 if options.chatter else None,
            )
        )
        # Related rather than copied: an address that goes stale the moment the
        # contact is corrected is worse than no address.
        fields.append(
            FieldSpec(
                name="partner_phone",
                ttype="char",
                string="Phone",
                related="partner_id.phone",
            )
        )
        fields.append(
            FieldSpec(
                name="partner_email",
                ttype="char",
                string="E-mail",
                related="partner_id.email",
            )
        )
    if options.company:
        fields.append(
            FieldSpec(
                name="company_id",
                ttype="many2one",
                string="Company",
                comodel="res.company",
                ondelete="set null",
                default="lambda self: self.env.company",
            )
        )
    if options.monetary:
        # The currency first: fields.Monetary raises without one, so ordering
        # here is not tidiness -- the class would not import.
        fields.append(
            FieldSpec(
                name="currency_id",
                ttype="many2one",
                string="Currency",
                comodel="res.currency",
                ondelete="set null",
                default="lambda self: self.env.company.currency_id",
            )
        )
        fields.append(
            FieldSpec(
                name="amount",
                ttype="monetary",
                string="Amount",
                currency_field="currency_id",
                tracking=1 if options.chatter else None,
            )
        )
    if options.picture:
        fields.append(FieldSpec(name="image", ttype="binary", string="Picture"))
    if options.date:
        fields.append(FieldSpec(name="date", ttype="date", string="Date"))
    if options.date_range:
        fields.append(FieldSpec(name="date_start", ttype="date", string="From"))
        fields.append(FieldSpec(name="date_stop", ttype="date", string="To"))
    if options.description:
        fields.append(FieldSpec(name="note", ttype="html", string="Notes"))
    if options.active:
        # 'active' is magic to Odoo: it turns on archiving and the default
        # search filter, for free, purely by being named this.
        fields.append(
            FieldSpec(name="active", ttype="boolean", string="Active", default="True")
        )

    inherit = ()
    if options.chatter:
        inherit = CHATTER_MIXINS if options.activities else (CHATTER_MIXINS[0],)

    fields.extend(_companion_fields(model_name, options))

    return ModelSpec(
        name=model_name,
        description=label,
        class_name=class_name_for(model_name),
        inherit=inherit,
        order="sequence, id" if options.ordering else None,
        fields=tuple(fields),
        sequence_code=model_name if options.reference else None,
        sequence_field="reference" if options.reference else None,
    )


# -- views ---------------------------------------------------------------


class ModelLike(Protocol):
    """The live recordset the arch builders below walk.

    Narrower than pulling in the whole ``BaseModel`` surface: every real
    reader in this file only ever touches ``_fields`` -- membership,
    ``.get()``, ``.items()`` -- never ``.env``, ``._name`` or anything else,
    so this names exactly that slice rather than the whole recordset, the
    same "narrow, hand-traced boundary" discipline ``lxml_types.py`` uses for
    lxml's own ``_Element``. A real ``env[model_name]`` (a ``BaseModel``)
    satisfies this structurally: OCB's own ``_fields`` is declared
    ``dict[str, Field]``, the bare unparameterized generic, which pyright
    treats as compatible with the parameterized ``Field[Any]`` below.
    """

    _fields: dict[str, Field[Any]]


# `etree.SubElement`/`etree.Element` are the two constructors this module
# actually calls; grabbing each once, behind a single documented cast, keeps
# the "Unknown member of an unstubbed module" gap to two lines instead of one
# `# pyright: ignore` per call site (there are dozens). Same pattern as
# `placement.py`'s own `_sub_element`/`_element`, adapted to this file's own
# call style, which passes `**attrs` keyword arguments (and sometimes a plain
# `dict` as the second positional argument) rather than a single dict --
# `Callable[..., LxmlElement]` accepts either, since `...` places no
# constraint on the parameter list.
_sub_element_raw = etree.SubElement  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_sub_element: Callable[..., LxmlElement] = cast(
    "Callable[..., LxmlElement]", _sub_element_raw
)
_element_raw = etree.Element  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_element: Callable[..., LxmlElement] = cast("Callable[..., LxmlElement]", _element_raw)

# Fields a scaffolded view never shows directly: they are either plumbing or
# rendered by a dedicated widget.
HIDDEN: tuple[str, ...] = (
    "active",
    "sequence",
    "note",
    "state",
    # Plumbing that a widget or another field renders, so showing it as an
    # ordinary row would show it twice or show it raw.
    "color",
    "currency_id",
    "image",
    "partner_phone",
    "partner_email",
    # The daterange widget draws both ends from the start field, so placing the
    # stop field as well would show the same period twice.
    "date_stop",
    # Lines are a table across the width of the form, placed by the form
    # builder rather than as a row inside a group.
    "line_ids",
)

# Fields the scaffold places with a widget rather than bare. Keeping this beside
# HIDDEN says the same thing from the other side: what a field looks like on a
# screen is a decision, and both lists are where those decisions live.
SCAFFOLD_WIDGETS: dict[str, str] = {
    "tag_ids": "many2many_tags",
    "priority": "priority",
    "kanban_state": "state_selection",
    "user_id": "many2one_avatar_user",
    "image": "image",
    "date_start": "daterange",
}


def _field(parent: LxmlElement, name: str, **attrs: str) -> LxmlElement:
    """A <field> node carrying whatever widget the scaffold has decided on."""
    widget = SCAFFOLD_WIDGETS.get(name)
    if widget and "widget" not in attrs:
        attrs["widget"] = widget
    return _sub_element(parent, "field", name=name, **attrs)


def _visible(model: ModelLike, spec: ModelSpec) -> list[FieldSpec]:
    """Spec fields that exist on the live model, in declaration order."""
    return [f for f in spec.fields if f.name in model._fields]


def scaffold_list_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    options = options or ScaffoldOptions()
    root = _element("list", string=spec.description)
    if options.ordering:
        _sub_element(root, "field", name="sequence", widget="handle")
    for spec_field in _visible(model, spec):
        if spec_field.name in HIDDEN:
            continue
        _field(root, spec_field.name)
    if options.stage and "state" in model._fields:
        _sub_element(root, "field", name="state", widget="badge")
    return root


def _scaffold_notebook(
    sheet: LxmlElement, model: ModelLike, options: ScaffoldOptions
) -> None:
    """Lines and Notes, in that order.

    Lines first because the table is the record's substance and the note is a
    remark about it. One notebook either way -- two would render as two rows of
    tabs.
    """
    notebook: LxmlElement | None = None
    if options.lines and "line_ids" in model._fields:
        notebook = _sub_element(sheet, "notebook")
        page = _sub_element(notebook, "page", string="Lines", name="lines")
        field = _sub_element(page, "field", name="line_ids")
        # An inline list, so a line is edited where it is read. The child model
        # is scaffolded with `sequence`, which is what the handle reorders.
        inner = _sub_element(field, "list", editable="bottom")
        _sub_element(inner, "field", name="sequence", widget="handle")
        _sub_element(inner, "field", name="name")
        _sub_element(inner, "field", name="quantity")

    if "note" in model._fields:
        if notebook is None:
            notebook = _sub_element(sheet, "notebook")
        page = _sub_element(notebook, "page", string="Notes", name="notes")
        _sub_element(page, "field", name="note")


def scaffold_form_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    """A form with a title, two columns, and a chatter -- the shape every core
    Odoo form has, so it looks like the rest of the system rather than a
    generated artefact."""
    options = options or ScaffoldOptions()
    form = _element("form", string=spec.description)
    sheet = _sub_element(form, "sheet")

    if options.stage and "state" in model._fields:
        header = _element("header")
        _sub_element(
            header,
            "field",
            name="state",
            widget="statusbar",
            options="{'clickable': '1'}",
        )
        form.insert(0, header)

    if options.reference and "reference" in model._fields:
        title = _sub_element(sheet, "div", {"class": "oe_title"})
        h1 = _sub_element(title, "h1")
        _sub_element(h1, "field", name="reference", readonly="1")

    if options.picture and "image" in model._fields:
        # Before the title, because it floats right: an image declared after it
        # renders below the heading instead of beside it.
        _field(sheet, "image", **{"class": "oe_avatar"})

    title = _sub_element(sheet, "div", {"class": "oe_title"})
    h1 = _sub_element(title, "h1")
    _sub_element(h1, "field", name="name", placeholder=spec.description)

    if options.active and "active" in model._fields:
        # The archive widget belongs beside the title, not in a column.
        _sub_element(title, "field", name="active", invisible="1")

    outer = _sub_element(sheet, "group")
    left = _sub_element(outer, "group")
    right = _sub_element(outer, "group")
    columns = (left, right)
    index = 0
    for spec_field in _visible(model, spec):
        if spec_field.name in HIDDEN or spec_field.name == "name":
            continue
        if spec_field.name == "reference" and options.reference:
            continue
        _field(columns[index % 2], spec_field.name)
        index += 1
        if spec_field.name == "partner_id":
            # The two related fields belong under the contact they come from,
            # not wherever the column balancer would have put them.
            for related in ("partner_phone", "partner_email"):
                if related in model._fields:
                    _field(columns[(index - 1) % 2], related)
        if spec_field.name == "amount" and "currency_id" in model._fields:
            _field(columns[(index - 1) % 2], "currency_id", invisible="1")
    if index == 0:
        # An empty <group><group/><group/></group> renders as a stray gap.
        sheet.remove(outer)

    _scaffold_notebook(sheet, model, options)

    if options.chatter:
        # Bare <chatter/> is the 18.0 form and has no server-side validator, so
        # it is inert rather than an error on a model without mail.thread.
        _sub_element(form, "chatter")
    return form


def scaffold_kanban_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    """A card with a title, a couple of details, and nothing clever.

    Emits the v18 ``t-name="card"`` template rather than the legacy
    ``kanban-box``: the parser warns on the old name and throws when neither is
    present (``kanban_arch_parser.js:153``).

    Every value goes in as a real ``<field>`` rather than ``t-esc`` on the
    record. Both render the same, but only a field puts its name in the DOM,
    which is what lets the builder select it later. A card written the other way
    is editable only as source, and generating one would be building in a dead
    end on purpose.
    """
    options = options or ScaffoldOptions()
    root = _element("kanban")
    if options.stage and "state" in model._fields:
        root.set("default_group_by", "state")

    templates = _sub_element(root, "templates")
    card = _sub_element(templates, "t", {"t-name": "card"})

    title = _sub_element(card, "div", {"class": "fw-bold fs-5"})
    _sub_element(title, "field", name=spec.rec_name or "name")

    details = _sub_element(card, "div", {"class": "d-flex justify-content-between"})
    shown = 0
    for spec_field in _visible(model, spec):
        if spec_field.name in HIDDEN or spec_field.name == (spec.rec_name or "name"):
            continue
        if spec_field.ttype in ("one2many", "many2many", "html", "text", "binary"):
            continue  # unreadable at card size
        _sub_element(details, "field", name=spec_field.name)
        shown += 1
        if shown == 2:
            break
    if not shown:
        card.remove(details)

    if options.chatter and "activity_ids" in model._fields:
        footer = _sub_element(card, "div", {"class": "d-flex justify-content-end"})
        _sub_element(footer, "field", name="activity_ids", widget="kanban_activity")
    return root


def scaffold_calendar_arch(
    model: ModelLike,
    spec: ModelSpec,
    date_field: str | None,
    options: ScaffoldOptions | None = None,
) -> LxmlElement:
    """A calendar keyed on ``date_field``.

    ``date_start`` is not optional -- the parser raises without it
    (``calendar_arch_parser.js:46``) -- which is why the caller has to say which
    date to use rather than the scaffold guessing and producing a view that
    throws on open.
    """
    options = options or ScaffoldOptions()
    if not date_field or date_field not in model._fields:
        raise ValueError("a calendar needs a date field that exists on the model")
    root = _element("calendar", string=spec.description, date_start=date_field)
    root.set("mode", "month")
    if options.stage and "state" in model._fields:
        root.set("color", "state")
    elif options.user and "user_id" in model._fields:
        root.set("color", "user_id")
    _sub_element(root, "field", name=spec.rec_name or "name")
    for spec_field in _visible(model, spec):
        if spec_field.ttype == "many2one" and spec_field.name != spec.rec_name:
            _sub_element(root, "field", name=spec_field.name)
            break
    return root


def scaffold_search_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    """Search fields plus real group-bys -- a list you cannot filter is not a
    list anybody keeps using."""
    options = options or ScaffoldOptions()
    root = _element("search", string=spec.description)
    for spec_field in _visible(model, spec):
        if spec_field.ttype in ("char", "text", "html"):
            _sub_element(root, "field", name=spec_field.name)
    for spec_field in _visible(model, spec):
        if spec_field.ttype == "many2one":
            _sub_element(root, "field", name=spec_field.name)

    if options.active and "active" in model._fields:
        _sub_element(
            root,
            "filter",
            name="inactive",
            string="Archived",
            domain="[('active', '=', False)]",
        )

    groupable = [
        f for f in _visible(model, spec) if f.ttype in ("selection", "many2one", "date")
    ]
    if groupable:
        group = _sub_element(root, "group", expand="0", string="Group By")
        for spec_field in groupable:
            _sub_element(
                group,
                "filter",
                name="group_by_%s" % spec_field.name,
                string=spec_field.string or spec_field.name,
                context="{'group_by': '%s'}" % spec_field.name,
            )
    return root


def arch_to_string(node: LxmlElement) -> str:
    # `etree.tostring` is itself Unknown (same unstubbed-lxml gap as the
    # `etree` import above), so both the call's own member type and its
    # argument types read as Unknown until the `cast` below names the real
    # return type -- same two-rule ignore `xml_writer.py`'s own
    # `serialize_document`/`normalize_arch` already use for this exact call.
    return cast("str", etree.tostring(node, encoding="unicode", pretty_print=True))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def _measure_fields(model: ModelLike, spec: ModelSpec) -> list[FieldSpec]:
    """Numbers worth aggregating: what a pivot or a graph is *for*."""
    return [
        f
        for f in _visible(model, spec)
        if f.ttype in ("integer", "float", "monetary")
        and f.name not in ("sequence", "color", "priority")
    ]


def _groupable_fields(model: ModelLike, spec: ModelSpec) -> list[FieldSpec]:
    return [
        f
        for f in _visible(model, spec)
        if f.ttype in ("many2one", "selection", "date", "datetime", "boolean")
        and f.name not in HIDDEN
    ]


def scaffold_pivot_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    """A pivot with a row grouping and a measure, rather than an empty grid.

    An empty pivot is valid and useless: it opens on a single Count cell and
    the user has to discover the two menus that make it a report. Choosing the
    obvious pair is the difference between a view and a demonstration of one.
    """
    root = _element("pivot", string=spec.description)
    groupable = _groupable_fields(model, spec)
    if groupable:
        _sub_element(root, "field", name=groupable[0].name, type="row")
    for measure in _measure_fields(model, spec)[:1]:
        _sub_element(root, "field", name=measure.name, type="measure")
    return root


def scaffold_graph_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    root = _element("graph", string=spec.description, type="bar")
    groupable = _groupable_fields(model, spec)
    if groupable:
        _sub_element(root, "field", name=groupable[0].name)
    for measure in _measure_fields(model, spec)[:1]:
        _sub_element(root, "field", name=measure.name, type="measure")
    return root


def scaffold_activity_arch(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions | None = None
) -> LxmlElement:
    """The activity view's card, which is a qweb template rather than a list.

    ``t-name="activity-box"`` is not optional -- the renderer looks that name up
    -- and the fields inside are real ``<field>`` nodes for the same reason the
    kanban card uses them: only a field puts its name in the DOM, so anything
    else cannot be selected by the builder later.
    """
    root = _element("activity", string=spec.description)
    templates = _sub_element(root, "templates")
    box = _sub_element(templates, "div", {"t-name": "activity-box"})
    _sub_element(box, "field", name=spec.rec_name or "name")
    for spec_field in _visible(model, spec):
        if spec_field.ttype == "many2one" and spec_field.name not in HIDDEN:
            _sub_element(box, "field", name=spec_field.name, muted="1")
            break
    return root


def scaffold_timeline_arch(
    model: ModelLike,
    spec: ModelSpec,
    date_field: str | None,
    group_field: str | None,
    options: ScaffoldOptions | None = None,
) -> LxmlElement:
    """A timeline, which is OCA's answer to the enterprise Gantt.

    Both attributes are mandatory in ``web_timeline`` -- ``default_group_by``
    unlike Gantt, where rows are optional -- so the caller has to supply them
    rather than the scaffold guessing and producing a view that throws on open.
    """
    options = options or ScaffoldOptions()
    if not date_field or date_field not in model._fields:
        raise ValueError("a timeline needs a date field that exists on the model")
    if not group_field or group_field not in model._fields:
        raise ValueError("a timeline needs a field to group its rows by")
    root = _element(
        "timeline",
        string=spec.description,
        date_start=date_field,
        default_group_by=group_field,
    )
    stop = "date_stop" if "date_stop" in model._fields else None
    if stop and stop != date_field:
        root.set("date_stop", stop)
    root.set("event_open_popup", "true")
    _sub_element(root, "field", name=spec.rec_name or "name")
    return root


# -- reports -------------------------------------------------------------
#
# What Odoo Studio calls External / Internal / Blank is a choice of *wrapper*:
# the body is the same, and the wrapper decides whether a company header and
# footer are drawn around it. `web.html_container` is not part of that choice --
# it is what makes the output a document at all, and every report has it.


@dataclass(frozen=True)
class ReportLayout:
    key: str
    label: str
    #: The qweb template wrapped around the body, or None for no wrapper.
    template: str | None
    help: str


REPORT_LAYOUTS: tuple[ReportLayout, ...] = (
    ReportLayout(
        "external",
        "External",
        "web.external_layout",
        "Company header and footer, as on a quotation or an invoice. What a "
        "customer should receive.",
    ),
    ReportLayout(
        "internal",
        "Internal",
        "web.internal_layout",
        "Header only, with the company name and the date. For something "
        "printed and used in the building.",
    ),
    ReportLayout(
        "blank",
        "Blank",
        None,
        "Nothing around the body. For a label, a form somebody else's paper "
        "is preprinted for, or a layout drawn from scratch.",
    ),
)

REPORT_LAYOUTS_BY_KEY: dict[str, ReportLayout] = {
    layout.key: layout for layout in REPORT_LAYOUTS
}


class ReportLayoutJSON(TypedDict):
    """What ``report_layouts_json`` sends: one entry per layout choice."""

    key: str
    label: str
    template: str | None
    help: str


def report_layouts_json() -> list[ReportLayoutJSON]:
    return [
        {
            "key": layout.key,
            "label": layout.label,
            "template": layout.template,
            "help": layout.help,
        }
        for layout in REPORT_LAYOUTS
    ]


# Which view types the builder can start from nothing, and how each one is
# built. One registry, because two places need it and they were drifting: the
# view editor offered eight and `create_app` built three, so a feature that
# asked for a kanban got a `state` field and no kanban.
#
# `date_field` and `group_field` are passed to every builder and ignored by the
# ones that do not need them, so a caller never has to know which is which.
#
# Named functions rather than the inline lambdas this registry used to hold:
# a lambda parameter cannot carry an annotation at all (a Python syntax
# limit), and under strict mode pyright does not infer one from the
# dict's own declared value type either -- confirmed by trying it first,
# `reportUnknownLambdaType` on every parameter of every entry, the same
# "give it its own signature" fix `pycodegen.py`'s `_selection_sort_key`
# already applied to an unannotated `.sorted(key=...)` lambda for the same
# underlying reason.
def _build_list(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_list_arch(model, spec, options)


def _build_form(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_form_arch(model, spec, options)


def _build_search(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_search_arch(model, spec, options)


def _build_kanban(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_kanban_arch(model, spec, options)


def _build_pivot(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_pivot_arch(model, spec, options)


def _build_graph(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_graph_arch(model, spec, options)


def _build_activity(
    model: ModelLike, spec: ModelSpec, options: ScaffoldOptions, **_kw: object
) -> LxmlElement:
    return scaffold_activity_arch(model, spec, options)


def _build_calendar(
    model: ModelLike,
    spec: ModelSpec,
    options: ScaffoldOptions,
    date_field: str | None = None,
    **_kw: object,
) -> LxmlElement:
    return scaffold_calendar_arch(model, spec, date_field, options)


def _build_timeline(
    model: ModelLike,
    spec: ModelSpec,
    options: ScaffoldOptions,
    date_field: str | None = None,
    group_field: str | None = None,
) -> LxmlElement:
    return scaffold_timeline_arch(model, spec, date_field, group_field, options)


SCAFFOLD_BUILDERS: dict[str, Callable[..., LxmlElement]] = {
    "list": _build_list,
    "form": _build_form,
    "search": _build_search,
    "kanban": _build_kanban,
    "pivot": _build_pivot,
    "graph": _build_graph,
    "activity": _build_activity,
    "calendar": _build_calendar,
    "timeline": _build_timeline,
}

# What a view of this type needs before it can be built at all.
SCAFFOLD_REQUIRES: dict[str, tuple[str, ...]] = {
    "calendar": ("date_field",),
    # Unlike Gantt, where rows are optional, web_timeline requires
    # default_group_by -- so this is the view refusing to open, not a
    # preference of ours.
    "timeline": ("date_field", "group_field"),
}


def first_field_of(
    model: ModelLike, ttypes: Collection[str], prefer: Iterable[str] = ()
) -> str | None:
    """A field on ``model`` of one of ``ttypes``, preferring ``prefer`` by name.

    Used to answer "which date should this calendar place records on" without
    asking, when the feature that wanted the view is also the feature that
    created the field.
    """
    for name in prefer:
        field = model._fields.get(name)
        if field is not None and field.type in ttypes:
            return name
    for name, field in model._fields.items():
        if field.type in ttypes and field.store and not name.startswith("create_"):
            return name
    return None


def scaffold_report_arch(title: str, layout: str = "external") -> LxmlElement:
    """The starting body of a PDF report.

    Iterates ``docs``, which is what ``_render_qweb_html`` puts in the rendering
    context for the records being printed -- so the template works for one
    record or a hundred without the author thinking about it.

    The visible content is deliberately thin: a heading and the record's name.
    A generated report that already contained a guessed table would be a
    template somebody has to delete before they can start.

    **Every layout must end up with one `div.article` per record.** That div is
    not decoration: `_prepare_html` splits the rendered HTML on it and reads
    `data-oe-model` / `data-oe-id` off it to map each PDF body back to a record
    (`ir_actions_report.py:411-427`). Without one, a hundred records print as a
    single undivided body, and a report with `attachment` set refuses outright
    (`ir_actions_report.py:867-873`). The two wrapped layouts get theirs from
    `web.external_layout` / `web.internal_layout`; Blank has to draw its own.
    """
    if layout not in REPORT_LAYOUTS_BY_KEY:
        raise ValueError("unknown report layout %r" % layout)
    wrapper = REPORT_LAYOUTS_BY_KEY[layout].template

    root = _element("t", {"t-call": "web.html_container"})
    loop = _sub_element(root, "t", {"t-foreach": "docs", "t-as": "doc"})
    # `web.external_layout` reads company/address/logo from the record being
    # printed, so the body has to sit inside the t-call rather than beside it.
    # The loop variable has to be `doc`: both layouts do
    # `<t t-if="not o" t-set="o" t-value="doc"/>` (`report_templates.xml:803`),
    # so any other name leaves `o` unset and the header renders blank.
    if wrapper:
        host = _sub_element(loop, "t", {"t-call": wrapper})
    else:
        # `web.basic_layout` is the obvious thing to call here and cannot be
        # used: it t-calls `web.html_container` itself
        # (`report_templates.xml:862`), so inside a loop it would emit N whole
        # documents. Core's own blank exemplar (hr_employee_badge) dodges that
        # by hoisting basic_layout outside the loop, which is why a badge sheet
        # prints as one undivided PDF. Drawing the same div it draws
        # (`report_templates.xml:864`) keeps the chrome off and the splitting on.
        host = _sub_element(
            loop,
            "div",
            {
                "class": "article",
                "t-att-data-oe-model": "doc and doc._name",
                "t-att-data-oe-id": "doc and doc.id",
                "t-att-data-oe-lang": "doc and doc.env.context.get('lang')",
            },
        )
    page = _sub_element(host, "div", {"class": "page"})
    heading = _sub_element(page, "h2")
    heading.text = title
    line = _sub_element(page, "div", {"class": "mb-3"})
    _sub_element(line, "span", {"t-field": "doc.display_name"})
    return root

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

from dataclasses import dataclass

from lxml import etree

from .modelspec import PRIORITY_VALUES, FieldSpec, ModelSpec, SelectionSpec
from .pycodegen import class_name_for

CHATTER_MIXINS = ("mail.thread", "mail.activity.mixin")

DEFAULT_STAGES = (
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


FEATURES = (
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
)

FEATURES_BY_KEY = {feature.key: feature for feature in FEATURES}
DEFAULT_FEATURES = frozenset(f.key for f in FEATURES if f.default)

# What a wizard has to offer: everything except what another feature already
# brings. Declared here so the wizard can be checked against it rather than
# drifting quietly when a feature is added.
_IMPLIED = {key for f in FEATURES for key in f.implies}
WIZARD_FEATURES = tuple(f.key for f in FEATURES if f.key not in _IMPLIED)


def features_json():
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

    def __init__(self, **flags):
        unknown = set(flags) - set(FEATURES_BY_KEY)
        if unknown:
            raise ValueError(
                "unknown scaffold features: %s" % ", ".join(sorted(unknown))
            )
        enabled = {key for key in DEFAULT_FEATURES if flags.get(key, True)}
        enabled |= {key for key, value in flags.items() if value}
        self.enabled = frozenset(self._resolve(enabled))

    @staticmethod
    def _resolve(keys):
        """Close over ``implies``, so a feature arrives with what it needs."""
        seen = set()
        pending = list(keys)
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            pending.extend(FEATURES_BY_KEY[key].implies)
        return seen

    @classmethod
    def from_keys(cls, keys):
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

    def __getattr__(self, name):
        # Only reached for attributes the instance does not have, so `enabled`
        # itself never comes through here.
        if name in FEATURES_BY_KEY:
            return name in self.enabled
        raise AttributeError(name)

    @property
    def view_types(self):
        """Views these features want, beyond the three every model gets."""
        out = []
        for feature in FEATURES:
            if feature.key in self.enabled:
                out.extend(v for v in feature.views if v not in out)
        return tuple(out)


def scaffold_spec(model_name, label, options=None):
    """The model a site manager gets before they add anything of their own."""
    options = options or ScaffoldOptions()
    fields = [
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
                selection=tuple(
                    SelectionSpec(
                        value=entry["value"],
                        label=entry["label"],
                        sequence=entry["sequence"],
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

# Fields a scaffolded view never shows directly: they are either plumbing or
# rendered by a dedicated widget.
HIDDEN = (
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
)

# Fields the scaffold places with a widget rather than bare. Keeping this beside
# HIDDEN says the same thing from the other side: what a field looks like on a
# screen is a decision, and both lists are where those decisions live.
SCAFFOLD_WIDGETS = {
    "priority": "priority",
    "kanban_state": "state_selection",
    "user_id": "many2one_avatar_user",
    "image": "image",
    "date_start": "daterange",
}


def _field(parent, name, **attrs):
    """A <field> node carrying whatever widget the scaffold has decided on."""
    widget = SCAFFOLD_WIDGETS.get(name)
    if widget and "widget" not in attrs:
        attrs["widget"] = widget
    return etree.SubElement(parent, "field", name=name, **attrs)


def _visible(model, spec):
    """Spec fields that exist on the live model, in declaration order."""
    return [f for f in spec.fields if f.name in model._fields]


def scaffold_list_arch(model, spec, options=None):
    options = options or ScaffoldOptions()
    root = etree.Element("list", string=spec.description)
    if options.ordering:
        etree.SubElement(root, "field", name="sequence", widget="handle")
    for spec_field in _visible(model, spec):
        if spec_field.name in HIDDEN:
            continue
        _field(root, spec_field.name)
    if options.stage and "state" in model._fields:
        etree.SubElement(root, "field", name="state", widget="badge")
    return root


def scaffold_form_arch(model, spec, options=None):
    """A form with a title, two columns, and a chatter -- the shape every core
    Odoo form has, so it looks like the rest of the system rather than a
    generated artefact."""
    options = options or ScaffoldOptions()
    form = etree.Element("form", string=spec.description)
    sheet = etree.SubElement(form, "sheet")

    if options.stage and "state" in model._fields:
        header = etree.Element("header")
        etree.SubElement(
            header,
            "field",
            name="state",
            widget="statusbar",
            options="{'clickable': '1'}",
        )
        form.insert(0, header)

    if options.reference and "reference" in model._fields:
        title = etree.SubElement(sheet, "div", {"class": "oe_title"})
        h1 = etree.SubElement(title, "h1")
        etree.SubElement(h1, "field", name="reference", readonly="1")

    if options.picture and "image" in model._fields:
        # Before the title, because it floats right: an image declared after it
        # renders below the heading instead of beside it.
        _field(sheet, "image", **{"class": "oe_avatar"})

    title = etree.SubElement(sheet, "div", {"class": "oe_title"})
    h1 = etree.SubElement(title, "h1")
    etree.SubElement(h1, "field", name="name", placeholder=spec.description)

    if options.active and "active" in model._fields:
        # The archive widget belongs beside the title, not in a column.
        etree.SubElement(title, "field", name="active", invisible="1")

    outer = etree.SubElement(sheet, "group")
    left = etree.SubElement(outer, "group")
    right = etree.SubElement(outer, "group")
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

    if "note" in model._fields:
        notebook = etree.SubElement(sheet, "notebook")
        page = etree.SubElement(notebook, "page", string="Notes", name="notes")
        etree.SubElement(page, "field", name="note")

    if options.chatter:
        # Bare <chatter/> is the 18.0 form and has no server-side validator, so
        # it is inert rather than an error on a model without mail.thread.
        etree.SubElement(form, "chatter")
    return form


def scaffold_kanban_arch(model, spec, options=None):
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
    root = etree.Element("kanban")
    if options.stage and "state" in model._fields:
        root.set("default_group_by", "state")

    templates = etree.SubElement(root, "templates")
    card = etree.SubElement(templates, "t", {"t-name": "card"})

    title = etree.SubElement(card, "div", {"class": "fw-bold fs-5"})
    etree.SubElement(title, "field", name=spec.rec_name or "name")

    details = etree.SubElement(card, "div", {"class": "d-flex justify-content-between"})
    shown = 0
    for spec_field in _visible(model, spec):
        if spec_field.name in HIDDEN or spec_field.name == (spec.rec_name or "name"):
            continue
        if spec_field.ttype in ("one2many", "many2many", "html", "text", "binary"):
            continue  # unreadable at card size
        etree.SubElement(details, "field", name=spec_field.name)
        shown += 1
        if shown == 2:
            break
    if not shown:
        card.remove(details)

    if options.chatter and "activity_ids" in model._fields:
        footer = etree.SubElement(card, "div", {"class": "d-flex justify-content-end"})
        etree.SubElement(footer, "field", name="activity_ids", widget="kanban_activity")
    return root


def scaffold_calendar_arch(model, spec, date_field, options=None):
    """A calendar keyed on ``date_field``.

    ``date_start`` is not optional -- the parser raises without it
    (``calendar_arch_parser.js:46``) -- which is why the caller has to say which
    date to use rather than the scaffold guessing and producing a view that
    throws on open.
    """
    options = options or ScaffoldOptions()
    if not date_field or date_field not in model._fields:
        raise ValueError("a calendar needs a date field that exists on the model")
    root = etree.Element("calendar", string=spec.description, date_start=date_field)
    root.set("mode", "month")
    if options.stage and "state" in model._fields:
        root.set("color", "state")
    elif options.user and "user_id" in model._fields:
        root.set("color", "user_id")
    etree.SubElement(root, "field", name=spec.rec_name or "name")
    for spec_field in _visible(model, spec):
        if spec_field.ttype == "many2one" and spec_field.name != spec.rec_name:
            etree.SubElement(root, "field", name=spec_field.name)
            break
    return root


def scaffold_search_arch(model, spec, options=None):
    """Search fields plus real group-bys -- a list you cannot filter is not a
    list anybody keeps using."""
    options = options or ScaffoldOptions()
    root = etree.Element("search", string=spec.description)
    for spec_field in _visible(model, spec):
        if spec_field.ttype in ("char", "text", "html"):
            etree.SubElement(root, "field", name=spec_field.name)
    for spec_field in _visible(model, spec):
        if spec_field.ttype == "many2one":
            etree.SubElement(root, "field", name=spec_field.name)

    if options.active and "active" in model._fields:
        etree.SubElement(
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
        group = etree.SubElement(root, "group", expand="0", string="Group By")
        for spec_field in groupable:
            etree.SubElement(
                group,
                "filter",
                name="group_by_%s" % spec_field.name,
                string=spec_field.string or spec_field.name,
                context="{'group_by': '%s'}" % spec_field.name,
            )
    return root


def arch_to_string(node):
    return etree.tostring(node, encoding="unicode", pretty_print=True)

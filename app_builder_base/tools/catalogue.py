# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""One vocabulary for "what can be configured", shared by both builders.

Field types were declared here in Python (``modelspec.FIELD_TYPES``) while
widgets and option rows were declared in JavaScript. Two small tables describing
one product, and after the view editor and the composer both grow they are two
*large* tables describing one product -- at which point the composer offers a
widget the view editor cannot set, or the reverse, and nobody notices because
nothing compares them. This is the one table.

Deliberately free of any ``odoo`` import, like ``modelspec``: it is data plus
pure functions, so it is testable in milliseconds and cannot drift from the
registry by accident.

**The client has the last word on widgets.** Every entry below names a widget
by its registry key, and the browser drops any whose key is not actually
registered, or whose ``supportedTypes`` disagree with the field. Declaring one
that does not apply renders an error where the field should be, so the rule is
that this table *proposes* and the live registry *disposes*. The consequence
worth having: a widget contributed by an installed module appears without this
file knowing about it, and one from an uninstalled module disappears without
breaking anything.

``types`` below is transcribed from core's own ``supportedTypes`` declarations
and is the fallback for a client that cannot ask -- not the authority.
"""

from dataclasses import dataclass
from dataclasses import field as dc_field


def identity(value):
    """The default resolver: leave the value exactly as declared.

    Labels here are lazy translations, which resolve by inspecting the calling
    frame for a language (``translate.py:614``). A pure data module has no
    environment in scope, so resolving one *here* finds nothing and Odoo logs an
    error and gives up. The caller passes ``env._`` instead, from somewhere that
    knows which language was asked for -- which is the idiom ``LazyGettext``'s
    own docstring recommends.
    """
    return value


# How a row's value reaches the arch.
#
# ATTRIBUTE writes ``name="value"`` on the node. OPTION merges into the node's
# ``options="{...}"`` JSON, which is where Odoo puts everything that configures
# a *widget* rather than the field -- an image's size, a status bar's
# clickability, a many2one's create/open permissions. Without this distinction
# every one of those needed its own bespoke handling; with it they are rows.
ATTRIBUTE = "attribute"
OPTION = "option"


@dataclass(frozen=True, slots=True)
class Row:
    """One editable line in the properties panel.

    ``type`` names a renderer the client supplies; everything else is data. A
    row never carries a function, which is the property that let this move off
    the client at all.
    """

    name: str
    label: str
    type: str = "text"  # text | toggle | select | groups | condition | field
    target: str = ATTRIBUTE
    help: str = ""
    # A toggle whose attribute exists to switch something *off*: create="0"
    # means "no creating", so the checkbox reads the other way round and an
    # absent attribute means allowed.
    invert: bool = False
    choices: tuple[tuple[str, str], ...] = ()
    # Choices the client computes: "widgets" from the registry, "fields" from
    # the model, "groups" from res.groups.
    source: str = ""
    # For source="fields": which field types may be offered.
    field_types: tuple[str, ...] = ()
    # The row applies only when the selected field is one of these types.
    only_for: tuple[str, ...] = ()
    placeholder_from: str = ""
    allow_empty: bool = True
    empty_label: str = ""

    def to_json(self, translate=identity):
        # Built by hand rather than with `asdict`, which deep-copies every
        # value: a lazy translation is not an ordinary object -- its `__eq__`
        # raises on purpose -- and there is no reason to copy it when it is
        # about to be resolved to a string anyway.
        return {
            "name": self.name,
            "label": translate(self.label),
            "type": self.type,
            "target": self.target,
            "help": translate(self.help) if self.help else "",
            "invert": self.invert,
            "choices": [[value, translate(label)] for value, label in self.choices],
            "source": self.source,
            "field_types": list(self.field_types),
            "only_for": list(self.only_for),
            "placeholder_from": self.placeholder_from,
            "allow_empty": self.allow_empty,
            "empty_label": translate(self.empty_label) if self.empty_label else "",
        }


@dataclass(frozen=True, slots=True)
class Widget:
    """A widget offered for a field, and whatever configures it."""

    value: str
    label: str
    types: tuple[str, ...]
    rows: tuple[Row, ...] = ()

    def to_json(self, translate=identity):
        return {
            "value": self.value,
            "label": translate(self.label),
            "types": list(self.types),
            "rows": [row.to_json(translate) for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class OptionGroup:
    """The rows shown for one kind of selection in one kind of view."""

    id: str
    title: str
    view_types: tuple[str, ...]
    kinds: tuple[str, ...]
    rows: tuple[Row, ...] = dc_field(default_factory=tuple)

    def to_json(self, translate=identity):
        return {
            "id": self.id,
            "title": translate(self.title),
            "view_types": list(self.view_types),
            "kinds": list(self.kinds),
            "rows": [row.to_json(translate) for row in self.rows],
        }


# -- widgets --------------------------------------------------------------
#
# Curated rather than exhaustive: core registers 58 field widgets and a list of
# 58 is not a choice anybody can make. What is here is what Odoo Studio's own
# documentation offers, plus the handful its docs describe by effect rather
# than by name.

_NO_CREATE = Row(
    name="no_create",
    label="Disable creation",
    type="toggle",
    target=OPTION,
    help="Stops users adding a record to the linked model from here.",
)
_NO_OPEN = Row(
    name="no_open",
    label="Disable opening",
    type="toggle",
    target=OPTION,
    help="Stops the linked record opening in a dialog.",
)

WIDGETS = (
    # -- char
    Widget("email", "Email", ("char",)),
    Widget("phone", "Phone", ("char",)),
    Widget("url", "Link", ("char",)),
    Widget("badge", "Badge", ("selection", "many2one", "char")),
    Widget("CopyClipboardChar", "Copy to clipboard", ("char",)),
    Widget("CopyClipboardURL", "Copy link to clipboard", ("char",)),
    Widget(
        "image_url",
        "Image from a URL",
        ("char",),
        rows=(Row("size", "Size", "select", OPTION, choices=(), source="image_size"),),
    ),
    # -- text / html
    Widget("text", "Plain text", ("html", "text")),
    Widget("text_emojis", "Plain text with emojis", ("text",)),
    Widget("ace", "Source editor", ("text", "html")),
    # -- numbers
    Widget("handle", "Drag handle", ("integer",)),
    Widget("progressbar", "Progress bar", ("integer", "float")),
    Widget("percentpie", "Percentage pie", ("float", "integer")),
    Widget("percentage", "Percentage", ("integer", "float")),
    Widget("float_time", "Duration", ("float",)),
    Widget("monetary", "Amount", ("monetary", "float")),
    Widget("statinfo", "Stat button figure", ("float", "integer", "monetary")),
    # -- boolean
    Widget("boolean_toggle", "Toggle", ("boolean",)),
    Widget("boolean_favorite", "Star", ("boolean",)),
    # -- dates
    Widget("remaining_days", "Relative date", ("date", "datetime")),
    Widget(
        "daterange",
        "Date range",
        ("date", "datetime"),
        rows=(
            Row(
                "start_date_field",
                "Start date field",
                "select",
                OPTION,
                source="fields",
                field_types=("date", "datetime"),
                help="Leave empty when this field is the start of the range.",
            ),
            Row(
                "end_date_field",
                "End date field",
                "select",
                OPTION,
                source="fields",
                field_types=("date", "datetime"),
                help="Leave empty when this field is the end of the range.",
            ),
            Row(
                "always_range",
                "Always a range",
                "toggle",
                OPTION,
                help="Both ends are required rather than optional.",
            ),
        ),
    ),
    # -- selection
    Widget("priority", "Stars", ("selection",)),
    Widget("radio", "Radio buttons", ("many2one", "selection")),
    Widget("selection_badge", "Badges", ("many2one", "selection")),
    Widget("label_selection", "Coloured label", ("selection",)),
    Widget(
        "statusbar",
        "Status bar",
        ("many2one", "selection"),
        rows=(
            Row(
                "clickable",
                "Clickable",
                "toggle",
                OPTION,
                help="Lets a user move the record by clicking the bar.",
            ),
        ),
    ),
    # -- files
    Widget(
        "image",
        "Image",
        ("binary", "many2one"),
        rows=(Row("size", "Size", "select", OPTION, source="image_size"),),
    ),
    Widget("pdf_viewer", "PDF viewer", ("binary",)),
    Widget("signature", "Signature", ("binary",)),
    # -- relations
    Widget("many2one_avatar", "Avatar", ("many2one",)),
    Widget("many2one_avatar_user", "User avatar", ("many2one",)),
    Widget(
        "many2many_tags",
        "Tags",
        ("many2many",),
        rows=(
            Row(
                "color_field",
                "Colour field",
                "select",
                OPTION,
                source="comodel_fields",
                field_types=("integer",),
                help="An integer field on the linked model that picks the tag colour.",
            ),
        ),
    ),
    Widget("many2many_tags_avatar", "Tags with avatars", ("many2many",)),
    Widget("many2many_checkboxes", "Checkboxes", ("many2many",)),
    Widget("many2many_binary", "Attachments", ("many2many",)),
)

WIDGETS_BY_VALUE = {entry.value: entry for entry in WIDGETS}

# Sizes the image widget accepts, as Odoo spells them.
IMAGE_SIZES = (
    ("[0, 90]", "Small"),
    ("[0, 180]", "Medium"),
    ("[0, 270]", "Large"),
)

# Rows every relational field gets regardless of widget: these configure the
# *field* rather than the widget, so they are attributes, not options.
RELATIONAL_ROWS = (
    _NO_CREATE,
    _NO_OPEN,
)


def widgets_for(ttype):
    """Every curated widget that core says applies to ``ttype``.

    Advisory: the client intersects this with the live registry, because a
    widget that is not installed must not be offered and one that is should be
    even if this file has never heard of it.
    """
    return tuple(entry for entry in WIDGETS if ttype in entry.types)


def widget_rows(widget):
    """The extra rows a chosen widget brings with it."""
    entry = WIDGETS_BY_VALUE.get(widget)
    return entry.rows if entry else ()


def catalogue_json(translate=identity):
    """The whole vocabulary, for one round trip."""
    return {
        "widgets": [entry.to_json(translate) for entry in WIDGETS],
        "image_sizes": [[value, translate(label)] for value, label in IMAGE_SIZES],
        "relational_rows": [row.to_json(translate) for row in RELATIONAL_ROWS],
    }

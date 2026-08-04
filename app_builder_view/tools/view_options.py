# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""What you can change about the thing you selected, as data.

These lived in ``static/src/wysiwyg/options.js`` as a registry of objects
carrying functions -- ``choices(target, context)``, ``when(target)``,
``placeholder(target)``. That worked while there were five groups, and it meant
the composer and the view editor described the same product from two files that
could not be compared.

Moving them here cost exactly one thing: a row may no longer carry a function.
Everything a function was doing is now named instead --

* ``source="widgets"`` for choices drawn from the field's type,
* ``source="fields"`` for choices drawn from the model,
* ``only_for=(...)`` for what ``when`` decided,
* ``placeholder_from="field.string"`` for what ``placeholder`` returned,

-- and the client resolves those names against what it already has. It is a
narrower vocabulary than "arbitrary JavaScript", which is the point: a row is
now something both builders can render and something a test can enumerate.

Adding "kanban card options" is still an entry rather than a component. It is
just an entry in Python now, and the same entry can feed the composer.
"""

from odoo.tools.translate import LazyTranslate

from odoo.addons.app_builder_base.tools.catalogue import (
    OPTION,
    OptionGroup,
    Row,
    identity,
)

# Lazy, because these are module-level data: a plain `_()` would resolve at
# import time, before any request has said which language it wants. `Row.to_json`
# is what turns them back into strings, once one has.
_lt = LazyTranslate(__name__)

NUMERIC = ("integer", "float", "monetary")

# Types Odoo can colour or group by: a discrete value per record.
GROUPABLE = ("many2one", "selection", "boolean")
DATE_TYPES = ("date", "datetime")


def _label_row(label, help_=""):
    return Row(
        name="string",
        label=label,
        type="text",
        placeholder_from="field.string",
        help=help_ or "Leave empty to use the field's own label.",
    )


_WIDGET_ROW = Row(
    name="widget",
    label=_lt("Shown as"),
    type="select",
    source="widgets",
    empty_label=_lt("Default"),
)

# Shown for every field, in every view that shows fields. Conditional variants
# take a Python expression rather than a domain: `attrs` was removed in 17.0 and
# these attributes are evaluated against the record.
_VISIBILITY_ROWS = (
    Row(
        name="groups",
        label=_lt("Visible only to"),
        type="groups",
        help=_lt("Leave empty to show it to everyone."),
    ),
    Row(
        name="invisible",
        label=_lt("Hidden"),
        type="toggle",
        help=_lt(
            "Hides the field without removing it, so anything depending on "
            "it keeps working."
        ),
    ),
    Row(
        name="invisible",
        label=_lt("Hidden when"),
        type="condition",
        help=_lt("A condition on the record, e.g. state == 'draft'."),
    ),
)


OPTION_GROUPS = (
    # -- list ---------------------------------------------------------------
    OptionGroup(
        id="list_column",
        title=_lt("This column"),
        view_types=("list",),
        kinds=("column",),
        rows=(
            _label_row("Column heading"),
            _WIDGET_ROW,
            Row(
                name="optional",
                label=_lt("Optional column"),
                type="select",
                choices=(
                    ("", "Always shown"),
                    ("show", "Optional, on by default"),
                    ("hide", "Optional, off by default"),
                ),
                help=_lt(
                    "Optional columns can be turned on and off by each user "
                    "from the toggle at the right of the header row."
                ),
            ),
            Row(
                name="sum",
                label=_lt("Column total"),
                type="text",
                only_for=NUMERIC,
                help=_lt("The label shown beside the total, e.g. “Total”."),
            ),
            Row(
                name="width",
                label=_lt("Column width (px)"),
                type="text",
                help=_lt("Leave empty to let Odoo size the column."),
            ),
            Row(
                name="column_invisible",
                label=_lt("Hide this column"),
                type="toggle",
                help=_lt(
                    "Hides the column without removing it, so nothing that "
                    "depends on the field breaks."
                ),
            ),
            Row(
                name="groups",
                label=_lt("Visible only to"),
                type="groups",
                help=_lt("Leave empty to show it to everyone."),
            ),
            Row(name="readonly", label=_lt("Read-only"), type="toggle"),
            Row(
                name="required",
                label=_lt("Required"),
                type="toggle",
                help=_lt("Required on this list only."),
            ),
        ),
    ),
    OptionGroup(
        id="list_root",
        title=_lt("This list"),
        view_types=("list",),
        kinds=("root",),
        rows=(
            Row(name="string", label=_lt("Title"), type="text"),
            Row(
                name="editable",
                label=_lt("Edit rows inline"),
                type="select",
                choices=(
                    ("", "Open the form"),
                    ("top", "Inline, new rows on top"),
                    ("bottom", "Inline, new rows at the bottom"),
                ),
            ),
            Row(
                name="multi_edit",
                label=_lt("Edit many records at once"),
                type="toggle",
                help=_lt("Lets a user select rows and change a value on all of them."),
            ),
            Row(
                name="default_order",
                label=_lt("Default sort"),
                type="text",
                help=_lt("A field name, optionally followed by desc — e.g. date desc."),
            ),
            Row(
                name="default_group_by",
                label=_lt("Group by"),
                type="select",
                source="fields",
                field_types=GROUPABLE + DATE_TYPES,
            ),
            Row(name="create", label=_lt("Allow creating"), type="toggle", invert=True),
            Row(name="edit", label=_lt("Allow editing"), type="toggle", invert=True),
            Row(name="delete", label=_lt("Allow deleting"), type="toggle", invert=True),
            Row(
                name="duplicate",
                label=_lt("Allow duplicating"),
                type="toggle",
                invert=True,
            ),
        ),
    ),
    # -- form ---------------------------------------------------------------
    OptionGroup(
        id="form_field",
        title=_lt("This field"),
        view_types=("form",),
        kinds=("field",),
        rows=(
            _label_row("Label"),
            _WIDGET_ROW,
            Row(
                name="placeholder",
                label=_lt("Placeholder"),
                type="text",
                help=_lt("Grey hint text shown while the field is empty."),
            ),
            Row(
                name="help",
                label=_lt("Tooltip"),
                type="text",
                help=_lt("Shown when the user hovers the label."),
            ),
            Row(
                name="class",
                label=_lt("CSS classes"),
                type="text",
                help=_lt("Bootstrap or custom classes, separated by spaces."),
            ),
            Row(
                name="required",
                label=_lt("Required"),
                type="toggle",
                help=_lt(
                    "Required on this form only. The field itself stays "
                    "optional, so other screens and imports are unaffected."
                ),
            ),
            Row(
                name="required",
                label=_lt("Required when"),
                type="condition",
                help=_lt("A condition on the record, e.g. state != 'draft'."),
            ),
            Row(name="readonly", label=_lt("Read-only"), type="toggle"),
            Row(
                name="readonly",
                label=_lt("Read-only when"),
                type="condition",
                help=_lt("A condition on the record."),
            ),
        )
        + _VISIBILITY_ROWS,
    ),
    OptionGroup(
        id="form_button",
        title=_lt("This button"),
        view_types=("form", "list"),
        kinds=("button",),
        rows=(
            Row(name="string", label=_lt("Label"), type="text"),
            Row(
                name="class",
                label=_lt("Style"),
                type="select",
                choices=(
                    ("btn-secondary", "Secondary"),
                    ("btn-primary", "Primary"),
                ),
                help=_lt(
                    "Primary is the main action on the screen and is more "
                    "prominent; secondary is everything else."
                ),
            ),
            Row(
                name="groups",
                label=_lt("Visible only to"),
                type="groups",
                help=_lt("Leave empty to show it to everyone."),
            ),
            Row(name="invisible", label=_lt("Hidden"), type="toggle"),
            Row(
                name="invisible",
                label=_lt("Hidden when"),
                type="condition",
                help=_lt("A condition on the record."),
            ),
            Row(
                name="confirm",
                label=_lt("Ask before running"),
                type="text",
                help=_lt("The question to ask. Leave empty to run straight away."),
            ),
        ),
    ),
    OptionGroup(
        id="form_page",
        title=_lt("This tab"),
        view_types=("form",),
        kinds=("page",),
        rows=(
            Row(name="string", label=_lt("Tab name"), type="text"),
            Row(
                name="groups",
                label=_lt("Visible only to"),
                type="groups",
                help=_lt("Leave empty to show it to everyone."),
            ),
            Row(name="invisible", label=_lt("Hidden"), type="toggle"),
        ),
    ),
    OptionGroup(
        id="form_group",
        title=_lt("This group"),
        view_types=("form",),
        kinds=("group",),
        rows=(
            Row(
                name="string",
                label=_lt("Heading"),
                type="text",
                help=_lt("Leave empty for an unlabelled group."),
            ),
            Row(
                name="col",
                label=_lt("Columns"),
                type="select",
                choices=(("", "Default"), ("1", "1"), ("2", "2"), ("4", "4")),
            ),
            Row(
                name="groups",
                label=_lt("Visible only to"),
                type="groups",
                help=_lt("Leave empty to show it to everyone."),
            ),
            Row(name="invisible", label=_lt("Hidden"), type="toggle"),
        ),
    ),
    OptionGroup(
        id="form_root",
        title=_lt("This form"),
        view_types=("form",),
        kinds=("root",),
        rows=(
            Row(name="string", label=_lt("Title"), type="text"),
            Row(name="create", label=_lt("Allow creating"), type="toggle", invert=True),
            Row(name="edit", label=_lt("Allow editing"), type="toggle", invert=True),
            Row(name="delete", label=_lt("Allow deleting"), type="toggle", invert=True),
            Row(
                name="duplicate",
                label=_lt("Allow duplicating"),
                type="toggle",
                invert=True,
            ),
        ),
    ),
    # -- kanban -------------------------------------------------------------
    OptionGroup(
        id="kanban_field",
        title=_lt("This field"),
        view_types=("kanban",),
        kinds=("field",),
        rows=(_WIDGET_ROW,) + _VISIBILITY_ROWS,
    ),
    OptionGroup(
        id="kanban_root",
        title=_lt("This kanban"),
        view_types=("kanban",),
        kinds=("root",),
        rows=(
            Row(
                name="default_group_by",
                label=_lt("Group by"),
                type="select",
                source="fields",
                field_types=GROUPABLE,
                help=_lt("The field whose values become the columns, e.g. state."),
            ),
            Row(
                name="quick_create",
                label=_lt("Quick create"),
                type="toggle",
                invert=True,
                help=_lt("Lets a user add a card from the column without a form."),
            ),
            Row(name="create", label=_lt("Allow creating"), type="toggle", invert=True),
            Row(
                name="records_draggable",
                label=_lt("Cards can be dragged"),
                type="toggle",
                invert=True,
            ),
            Row(
                name="group_create",
                label=_lt("Columns can be added"),
                type="toggle",
                invert=True,
            ),
            Row(
                name="archivable",
                label=_lt("Columns can be archived"),
                type="toggle",
                invert=True,
            ),
            Row(
                name="default_order",
                label=_lt("Default sort"),
                type="text",
                help=_lt("A field name, optionally followed by desc."),
            ),
        ),
    ),
    # -- calendar -----------------------------------------------------------
    #
    # A settings panel rather than click-to-select. A calendar draws events, not
    # fields: there is no per-node DOM that maps back to the arch, so inventing
    # click targets would be pretending. What a calendar *is* lives almost
    # entirely in its root attributes, and that is what this edits.
    OptionGroup(
        id="calendar_root",
        title=_lt("This calendar"),
        view_types=("calendar",),
        kinds=("root",),
        rows=(
            Row(name="string", label=_lt("Title"), type="text"),
            Row(
                name="date_start",
                label=_lt("Starts on"),
                type="select",
                source="fields",
                field_types=DATE_TYPES,
                allow_empty=False,
                help=_lt("Required — the calendar cannot open without it."),
            ),
            Row(
                name="date_stop",
                label=_lt("Ends on"),
                type="select",
                source="fields",
                field_types=DATE_TYPES,
                help=_lt("Leave empty for single-moment events."),
            ),
            Row(
                name="date_delay",
                label=_lt("Duration field"),
                type="select",
                source="fields",
                field_types=("float", "integer"),
                help=("Hours the event lasts. Ignored when an end date is set."),
            ),
            Row(
                name="all_day",
                label=_lt("All-day flag"),
                type="select",
                source="fields",
                field_types=("boolean",),
                help=_lt("A checkbox saying the event lasts the whole day."),
            ),
            Row(
                name="color",
                label=_lt("Colour by"),
                type="select",
                source="fields",
                field_types=GROUPABLE,
                help=_lt("Records sharing a value share a colour."),
            ),
            Row(
                name="mode",
                label=_lt("Opens on"),
                type="select",
                choices=(
                    ("", "Default"),
                    ("day", "Day"),
                    ("week", "Week"),
                    ("month", "Month"),
                    ("year", "Year"),
                ),
            ),
            Row(
                name="quick_create",
                label=_lt("Create by dragging a slot"),
                type="toggle",
                invert=True,
            ),
            Row(
                name="event_open_popup",
                label=_lt("Open events in a popup"),
                type="toggle",
            ),
        ),
    ),
    OptionGroup(
        id="calendar_field",
        title=_lt("This field"),
        view_types=("calendar",),
        kinds=("field",),
        rows=(
            Row(
                name="filters",
                label=_lt("Offer as a side filter"),
                type="toggle",
                help=_lt("Shows the field's values in the panel beside the calendar."),
            ),
            Row(name="invisible", label=_lt("Hidden"), type="toggle"),
        ),
    ),
)


def groups_for(view_type):
    """Every option group that could apply in ``view_type``."""
    return tuple(g for g in OPTION_GROUPS if view_type in g.view_types)


def groups_json(view_type=None, translate=identity):
    source = groups_for(view_type) if view_type else OPTION_GROUPS
    return [group.to_json(translate) for group in source]


__all__ = ["OPTION", "OPTION_GROUPS", "groups_for", "groups_json"]

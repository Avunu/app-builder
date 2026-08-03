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

from lxml import etree

from .modelspec import FieldSpec, ModelSpec, SelectionSpec
from .pycodegen import class_name_for

CHATTER_MIXINS = ("mail.thread", "mail.activity.mixin")

DEFAULT_STAGES = (
    ("draft", "Draft"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
)


class ScaffoldOptions:
    """What to include beyond the bare model."""

    def __init__(
        self,
        chatter=True,
        activities=True,
        ordering=True,
        reference=False,
        active=True,
        stage=False,
        description=True,
        user=False,
        date=False,
    ):
        self.chatter = chatter
        self.activities = activities
        self.ordering = ordering
        self.reference = reference
        self.active = active
        self.stage = stage
        self.description = description
        self.user = user
        self.date = date


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
    if options.user:
        fields.append(
            FieldSpec(
                name="user_id",
                ttype="many2one",
                string="Responsible",
                comodel="res.users",
                ondelete="set null",
                default="lambda self: self.env.user",
                tracking=1 if options.chatter else None,
            )
        )
    if options.date:
        fields.append(FieldSpec(name="date", ttype="date", string="Date"))
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
HIDDEN = ("active", "sequence", "note", "state")


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
        etree.SubElement(root, "field", name=spec_field.name)
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
        etree.SubElement(columns[index % 2], "field", name=spec_field.name)
        index += 1
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

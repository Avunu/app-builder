# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Naming every node of a view so a rendered element can point back at it.

The console renders the *real* view and lets the user drop things on it. The
browser then has to say where the drop landed in the view's definition, and
the DOM alone cannot say: a group has no name, a notebook page carries its
identity on the tab and nothing else, and a kanban card renders once per
record. So the server names the nodes before the arch is compiled -- one
class token per element, ``o_studio_n_<ordinal>`` -- and the browser hands the
token back. The token is minted on the combined arch, the same tree every
edit is applied to, so what the user pointed at and what the server edits
are one node by construction.

Tokens are ordinals in document order and nothing else: a pure function of
the arch, identical for every user, and worthless as soon as the arch
changes -- which is what the arch version is for. A token is never an
xpath. The browser holds a name for a node, and the server decides what that
node's locator is, at the moment it edits.

Pure lxml. Nothing here touches the environment, so the walk can be tested
on a string and re-run by the editor on the tree it is about to edit.
"""

import copy
from dataclasses import dataclass, field

TOKEN_PREFIX = "o_studio_n_"

# The marker an invisible node carries when the canvas has been asked to show
# it anyway: the node renders, and the overlay dims it.
INVISIBLE_MARK = "o_studio_invisible"

# Tags that put nothing of their own in the DOM. They are walked -- what is
# inside them renders -- but not stamped, since there is no element to carry
# the class, and not listed, since there is nothing to point at. `t` is the
# one exception, below: a kanban card template is a `<t>` and *is* a place.
NO_DOM_TAGS = frozenset({"templates", "t", "newline", "control", "create", "attribute"})

# Tags that are listed but never descended into, like a `<field>`: what is
# under them belongs to another model. A list's `<groupby>` is a nested view
# of the comodel (`_postprocess_tag_groupby`), so its fields are not columns
# of the list and a drop next to one would land inside a group header.
NESTED_VIEW_TAGS = frozenset({"groupby"})

# The `<t t-name>`s that are a kanban card. The card is what the user drops
# into, so it is listed either way; whether it carries a token depends on
# the template's generation. A v18 `card` template's `class` is read by the
# arch parser (`kanban_arch_parser.js:161`, `cardClassName`) and put on the
# rendered `.o_kanban_record` (`kanban_record.js:281`) -- the same in 19 and
# master -- so the card is stamped like any other node. The legacy
# `kanban-box` template is the one `<t>` whose class goes nowhere, and it is
# listed with `dom` off so the client takes its rectangle from the record.
CARD_TEMPLATES = frozenset({"card", "kanban-box"})
CARD_TEMPLATES_WITH_DOM = frozenset({"card"})

# The values that hide a node whatever the record says. `view_compiler.js`
# drops a node at compile time for exactly "1" and "True"; `true` is a
# py.js builtin and hides it at render time instead. Anything else is an
# expression evaluated against the record, and stays as it is.
INVISIBLE_LITERALS = frozenset({"1", "True", "true"})

# What each container takes as a direct child, by the container's *key*
# (its tag, or `button_box`/`card` for the two containers known by
# something other than their tag). Served verbatim to the client as
# `accepts`, and checked again on the server when the drop arrives, so the
# two can never disagree. A search view is a container so that its root can
# be selected, and accepts nothing because it is not edited on a canvas.
ACCEPTS = {
    "form": (
        "header",
        "sheet",
        "group",
        "notebook",
        "field",
        "div",
        "separator",
        "label",
        "button",
        "widget",
        "chatter",
    ),
    "sheet": (
        "group",
        "notebook",
        "field",
        "div",
        "separator",
        "label",
        "button",
        "widget",
    ),
    "group": ("field", "group", "separator", "label", "button", "div", "widget"),
    "notebook": ("page",),
    "page": (
        "group",
        "notebook",
        "field",
        "div",
        "separator",
        "label",
        "button",
        "widget",
    ),
    "header": ("button", "field"),
    "button_box": ("button",),
    "div": ("field", "div", "span", "label", "button", "widget", "separator"),
    "list": ("field", "button"),
    "card": ("field", "div", "span", "main", "aside", "footer", "widget", "button"),
    "main": ("field", "div", "span", "widget", "button"),
    "aside": ("field", "div", "span", "widget", "button"),
    "footer": ("field", "div", "span", "widget", "button"),
    "search": (),
}

# Containers whose children sit side by side, so the drop bars between them
# are vertical: an outer group's columns, the buttons of a header, the tabs
# of a notebook, the headings of a list, a card's aside and footer.
ROW_KINDS = frozenset({"header", "button_box", "notebook", "aside", "footer"})

# What stays where it is. The scaffolding of a form is not something to drag
# about -- there is one sheet, one header, one chatter -- and a notebook is
# moved by moving what it holds. A card is the template itself.
NOT_MOVABLE = frozenset(
    {
        "root",
        "sheet",
        "header",
        "button_box",
        "chatter",
        "card",
        "notebook",
        "main",
        "aside",
        "footer",
    }
)

# Kinds that can be taken out of the view without being draggable.
REMOVABLE_KINDS = frozenset({"notebook"})

# Tags with a kind of their own; everything else that renders is `html`.
KIND_BY_TAG = {
    "field": "field",
    "button": "button",
    "page": "page",
    "group": "group",
    "notebook": "notebook",
    "sheet": "sheet",
    "header": "header",
    "footer": "footer",
    "separator": "separator",
    "label": "label",
    "widget": "widget",
    "chatter": "chatter",
    "main": "main",
    "aside": "aside",
}

# The tag a drop will put in the arch, by what the palette calls it. A label
# is emitted as `<div class="o_form_label">` -- a bare `<label>` needs a
# `for` and there is no field to point it at -- but it is *accepted* as a
# label, which every container that takes a div takes too.
COMPONENT_TAGS = {
    "group": "group",
    "columns": "group",
    "page": "page",
    "notebook": "notebook",
    "separator": "separator",
    "label": "label",
    "button": "button",
}


@dataclass
class StampResult:
    """What ``stamp`` hands back.

    ``arch`` is the copy carrying the tokens, for rendering; ``elements``
    maps every token to the node of the *original* tree it was minted on,
    for editing; ``nodes`` is the table the client navigates by.
    """

    arch: object
    root: str
    nodes: dict = field(default_factory=dict)
    elements: dict = field(default_factory=dict)


def token_of(element):
    """The token ``element`` carries in its class, or ``None``."""
    for cls in (element.get("class") or "").split():
        if cls.startswith(TOKEN_PREFIX):
            return cls
    return None


def _is_card(element):
    return element.tag == "t" and element.get("t-name") in CARD_TEMPLATES


def _walk(root):
    """Every listed node in document order, with the entry it hangs from.

    Yields ``(element, parent_index, dom, kind_hint)``: ``parent_index`` is
    the position of the nearest listed ancestor in this same sequence,
    ``dom`` whether the element has a DOM of its own to carry a class, and
    ``kind_hint`` is ``"card"`` for a kanban card template and ``None``
    otherwise.

    The rules are the ones every locator already lives by. Nothing under a
    ``<field>`` is listed: an embedded subview belongs to another model, and
    a token into it would edit the wrong thing (``_find_descriptor`` refuses
    the same nodes); a ``<groupby>`` is such a subview under another name.
    Comments and processing instructions are skipped. A
    tag with no DOM is descended into without being listed, so its children
    hang from the nearest real ancestor -- a `<t t-if>` wrapper around two
    fields in a card is invisible to the table, and the fields are the
    card's children.
    """
    in_kanban = root.tag == "kanban"
    out = [(root, None, True, None)]

    def visit(element, parent_index, in_templates):
        for child in element:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "field":
                # Listed, never descended: what is under a field is a subview.
                # A field declared at a kanban's root renders nothing -- it
                # only loads the value for the template -- so it has no DOM.
                out.append((child, parent_index, not in_kanban or in_templates, None))
                continue
            if child.tag in NESTED_VIEW_TAGS:
                # Listed so it can be described, never descended, and with
                # no DOM of its own to point at: a group header renders once
                # per group, not once per node.
                out.append((child, parent_index, False, None))
                continue
            if child.tag in NO_DOM_TAGS:
                if _is_card(child):
                    has_dom = child.get("t-name") in CARD_TEMPLATES_WITH_DOM
                    out.append((child, parent_index, has_dom, "card"))
                    visit(child, len(out) - 1, True)
                else:
                    visit(child, parent_index, in_templates or child.tag == "templates")
                continue
            out.append((child, parent_index, True, None))
            visit(child, len(out) - 1, in_templates)

    visit(root, 0, False)
    return out


def _is_label_div(element):
    """What ``_op_add_label`` emits: a ``<div>`` that is a label, not a box."""
    return (
        element.tag == "div" and "o_form_label" in (element.get("class") or "").split()
    )


def _container_key(element, kind_hint):
    """What ``ACCEPTS`` knows the element as, or ``None`` for a leaf.

    A ``<div>`` is a container, except the one that is a label: it holds
    text, and a field appended after that text would render glued to it.
    """
    if kind_hint == "card":
        return "card"
    if element.tag == "div":
        if element.get("name") == "button_box":
            return "button_box"
        if _is_label_div(element):
            return None
    tag = "list" if element.tag == "tree" else element.tag
    return tag if tag in ACCEPTS else None


def _kind(element, root_tag, kind_hint, is_root):
    if is_root:
        return "root"
    if kind_hint:
        return kind_hint
    if element.tag == "div":
        if element.get("name") == "button_box":
            return "button_box"
        if _is_label_div(element):
            return "label"
        return "html"
    if element.tag == "field" and root_tag in ("list", "tree"):
        return "column"
    return KIND_BY_TAG.get(element.tag, "html")


def _string(element, kind):
    string = element.get("string")
    if string:
        return string
    if kind in ("label", "separator", "html"):
        text = (element.text or "").strip()
        if text:
            return text
    return element.get("name")


def _orientation(element, kind, key):
    if kind in ROW_KINDS or key == "list":
        return "row"
    if element.tag == "group" and any(
        isinstance(child.tag, str) and child.tag == "group" for child in element
    ):
        # An outer group: its children are columns, laid out side by side.
        return "row"
    return "column"


def stamp(root, view_type=None):
    """Name every node of ``root`` and describe them.

    ``root`` is not touched: the copy in the result carries the tokens, and
    ``elements`` points back into the original so that a token resolves to
    the exact node the caller will edit. ``view_type`` is the view's type,
    which is also ``root.tag`` for everything but a list still spelt
    ``tree``; it is accepted for symmetry with the caller and read only to
    tell a list's fields from a form's.
    """
    root_tag = view_type or root.tag
    if root_tag == "tree":
        root_tag = "list"
    listed = _walk(root)
    arch = copy.deepcopy(root)
    # Same walk, same order: the copy is structurally the original.
    listed_copy = _walk(arch)
    tokens = ["%s%d" % (TOKEN_PREFIX, ordinal) for ordinal in range(len(listed))]

    nodes = {}
    elements = {}
    for ordinal, (element, parent_index, dom, hint) in enumerate(listed):
        token = tokens[ordinal]
        is_root = ordinal == 0
        kind = _kind(element, root_tag, hint, is_root)
        key = _container_key(element, hint)
        container = key is not None
        accepts = list(ACCEPTS[key]) if container else []
        movable = dom and kind not in NOT_MOVABLE
        parent = tokens[parent_index] if parent_index is not None else None
        nodes[token] = {
            "tag": element.tag,
            "name": element.get("name") or element.get("t-name") or None,
            "kind": kind,
            "parent": parent,
            "children": [],
            "index": 0,
            "string": _string(element, kind),
            "container": container,
            "orientation": _orientation(element, kind, key),
            "accepts": accepts,
            "movable": movable,
            "removable": movable or kind in REMOVABLE_KINDS,
            "selectable": dom or kind == "card",
            "hidden": None,
            "attrs": dict(element.attrib),
            "dom": dom,
            "field": None,
            "view_id": None,
        }
        elements[token] = element
        if parent is not None:
            siblings = nodes[parent]["children"]
            nodes[token]["index"] = len(siblings)
            siblings.append(token)
        if dom:
            copied = listed_copy[ordinal][0]
            existing = copied.get("class")
            copied.set("class", "%s %s" % (existing, token) if existing else token)
    return StampResult(arch=arch, root=tokens[0], nodes=nodes, elements=elements)


def descendants(nodes, token):
    """Every token listed under ``token``, in document order.

    What "the nodes in it" means for a container about to be removed: the
    nodes the table lists, so an embedded subview's rows -- which the user
    never sees as nodes -- do not make a one2many field look like a box
    holding three things.
    """
    out = []
    pending = list(nodes[token]["children"]) if token in nodes else []
    while pending:
        child = pending.pop(0)
        out.append(child)
        pending = list(nodes[child]["children"]) + pending
    return out


def _under(element, tags):
    return any(
        isinstance(ancestor.tag, str)
        and (
            ancestor.tag in tags
            or (ancestor.tag == "div" and ancestor.get("name") == "button_box")
        )
        for ancestor in element.iterancestors()
    )


def prepare_for_canvas(arch, view_type, *, show_invisible=False, sample=False):
    """Rewrite the stamped copy so it renders as a canvas, and say what changed.

    Everything here is for the rendering only and never reaches a written
    arch: the copy is thrown away after the view is compiled, and the nodes
    table keeps the original attributes.

    A node the view hides with a literal ``invisible="1"`` is dropped at
    compile time (``view_compiler.js:263``), and there is no switch on the
    View that would render it; so when the user asks to see hidden nodes
    the literal is rewritten to ``"0"`` and the node marked, and the tokens
    rewritten are reported so the client knows which outlines to dim. A
    list column with ``optional="hide"`` is shown for the same reason. The
    root's ``js_class`` is taken off and returned so the console can wrap
    the view's own class in its no-save controller; a list's ``editable``
    and ``multi_edit`` go, since nothing may be edited on the canvas, and a
    kanban's records and columns are pinned. ``sample`` asks the view for
    sample data, which is how an empty list still shows its columns.

    A ``<button>`` with no class of its own gets ``btn-secondary``: the
    token is a class, and ``view_button.js getClassName`` only supplies the
    default look when the class list is empty. Header, list and stat
    buttons carry a default rank of their own and are left alone.
    """
    root_tag = "list" if view_type == "tree" else (view_type or arch.tag)
    rewritten = []
    js_class = arch.attrib.pop("js_class", None)
    if root_tag == "list":
        arch.attrib.pop("editable", None)
        arch.attrib.pop("multi_edit", None)
    if root_tag == "kanban":
        arch.set("records_draggable", "0")
        arch.set("groups_draggable", "0")
    if sample:
        arch.set("sample", "1")
    for element in arch.iter():
        token = token_of(element) if isinstance(element.tag, str) else None
        if token is None:
            continue
        if show_invisible:
            hidden = False
            for attr in ("invisible", "column_invisible"):
                if element.get(attr) in INVISIBLE_LITERALS:
                    element.set(attr, "0")
                    hidden = True
            if hidden:
                element.set("class", "%s %s" % (element.get("class"), INVISIBLE_MARK))
                rewritten.append(token)
        if root_tag == "list" and element.get("optional") == "hide":
            element.set("optional", "show")
        if (
            element.tag == "button"
            and root_tag != "list"
            and not _under(element, ("header",))
        ):
            classes = [c for c in element.get("class").split() if c != token]
            if not classes:
                element.set("class", "btn-secondary %s" % token)
    return {"js_class": js_class, "rewritten": rewritten}


def payload_tag(payload, moved_tag=None):
    """The tag a drop will put in the arch, or ``None`` when it has none.

    A field arrives as a field however it is described -- existing, new, or
    staged; a component maps through ``COMPONENT_TAGS``; a move carries the
    tag of the node being moved, which only the caller holding the tree
    knows and passes as ``moved_tag``.
    """
    kind = payload.get("kind")
    if kind in ("existing_field", "new_field", "move_pending"):
        return "field"
    if kind == "component":
        return COMPONENT_TAGS.get(payload.get("component"))
    if kind == "move":
        return moved_tag
    return None


def accepts(container_key, child_tag):
    """Whether a container known as ``container_key`` takes a ``child_tag``."""
    return bool(child_tag) and child_tag in ACCEPTS.get(container_key, ())

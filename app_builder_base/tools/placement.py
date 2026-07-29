# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Putting a field into the views that show it.

A field the builder adds but never places is invisible: the column exists, the
class has it, and the form does not show it. That is the most confusing thing
the builder can produce, so placement is part of adding a field rather than a
separate chore.

This edits the arch of views the package **owns outright**. Patching our own
primary view with an ``<xpath>`` extension would produce source no developer
would have written; ``studio.view.editor`` exists for the other case, editing
views belonging to somebody else, and stays the tool for that.

Removal matters as much as insertion and is easier to forget: a ``<field>``
naming a column that no longer exists fails view validation, which fails the
reload, which rolls the whole apply back. Dropping a field therefore has to
take its view nodes with it.
"""

from lxml import etree

# Fields that carry meaning to Odoo rather than to the user; the scaffold places
# them deliberately or not at all, so automatic placement must leave them alone.
NEVER_PLACE = frozenset(
    {"active", "sequence", "name", "reference", "company_id", "currency_id"}
)

_NOTEBOOK_TYPES = frozenset({"one2many", "many2many", "html", "text"})


def wants_notebook(ttype):
    """Whether this type belongs on its own page rather than in a column.

    A related list in a two-column group is unreadable at any real row count,
    and it is the layout every hand-written Odoo form avoids.
    """
    return ttype in _NOTEBOOK_TYPES


# -- insertion ------------------------------------------------------------


def place_in_form(root, name, ttype, label=None):
    """Add a field to a form arch, in the slot its type deserves."""
    if _find_field(root, name) is not None:
        return False
    if wants_notebook(ttype):
        return _place_in_notebook(root, name, label)
    return _place_in_group(root, name)


def _place_in_group(root, name):
    sheet = root.find(".//sheet")
    host = sheet if sheet is not None else root
    columns = host.findall("./group/group")
    if not columns:
        outer = etree.SubElement(host, "group")
        columns = [etree.SubElement(outer, "group"), etree.SubElement(outer, "group")]
        # A notebook must stay last, so a group created late moves above it.
        notebook = host.find("./notebook")
        if notebook is not None:
            host.remove(outer)
            host.insert(list(host).index(notebook), outer)
    # Balance the two columns rather than always appending to the first, so a
    # form built one field at a time ends up looking like a designed one.
    target = min(columns, key=lambda column: len(column.findall("field")))
    etree.SubElement(target, "field", name=name)
    return True


def _place_in_notebook(root, name, label=None):
    sheet = root.find(".//sheet")
    host = sheet if sheet is not None else root
    notebook = host.find("./notebook")
    if notebook is None:
        notebook = etree.SubElement(host, "notebook")
    page = etree.SubElement(
        notebook, "page", string=label or name, name="page_%s" % name
    )
    etree.SubElement(page, "field", name=name)
    return True


def place_in_list(root, name):
    if _find_field(root, name) is not None:
        return False
    field = etree.Element("field", name=name)
    # The state badge reads as a status column and belongs at the end.
    badge = next(
        (f for f in root.findall("field") if f.get("widget") == "badge"),
        None,
    )
    if badge is not None:
        root.insert(list(root).index(badge), field)
    else:
        root.append(field)
    return True


def place_in_search(root, name):
    if _find_field(root, name) is not None:
        return False
    field = etree.Element("field", name=name)
    fields = root.findall("field")
    if fields:
        root.insert(list(root).index(fields[-1]) + 1, field)
    else:
        root.insert(0, field)
    return True


def place_group_by(root, name, label=None):
    """Add a group-by filter to a search arch, in the group-by group."""
    filter_name = "group_by_%s" % name
    if root.find(".//filter[@name='%s']" % filter_name) is not None:
        return False
    group = root.find("./group")
    if group is None:
        group = etree.SubElement(root, "group", string="Group By")
    etree.SubElement(
        group,
        "filter",
        name=filter_name,
        string=label or name,
        context="{'group_by': '%s'}" % name,
    )
    return True


# -- removal --------------------------------------------------------------


def remove_field(root, name):
    """Take a field out of an arch, along with anything left empty behind it.

    A page whose only field is gone, or a group-by naming a dropped column, is
    not merely untidy -- the group-by would fail view validation on the next
    load, which is the same crash removal is trying to avoid.
    """
    changed = False
    for node in root.xpath(".//field[@name='%s']" % name):
        parent = node.getparent()
        parent.remove(node)
        changed = True
        # An emptied page is a tab that opens onto nothing.
        if parent.tag == "page" and not len(parent):
            notebook = parent.getparent()
            notebook.remove(parent)
            if not len(notebook):
                notebook.getparent().remove(notebook)
    for node in root.xpath(".//filter[@context]"):
        context = node.get("context") or ""
        if "'group_by': '%s'" % name in context or '"group_by": "%s"' % name in context:
            node.getparent().remove(node)
            changed = True
    return changed


# -- shared ---------------------------------------------------------------


def _find_field(root, name):
    """A field anywhere in this arch, including inside a subview.

    Deliberately recursive: if the name already appears at all, placing it again
    would render it twice, and a duplicated field in one form is a bug the user
    reports as "it saved my value in the wrong box".
    """
    return next(iter(root.xpath(".//field[@name='%s']" % name)), None)

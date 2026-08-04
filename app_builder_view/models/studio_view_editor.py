# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""View editing that never rewrites another module's view.

Odoo Studio rewrites view arch in place, which is why a Studio-customised
database fights every upstream upgrade. Here, editing a view somebody else owns
becomes an ``<xpath>`` inside a single extension view per (base view, package)
at ``priority=99`` -- core's own convention for last-loaded views
(``ir_ui_view.py:658``). The result reads like a patch a developer would have
written, survives upstream changes to the base view, and is reviewable in git.

A view the editing package *owns* is edited directly instead. Emitting a patch
against your own primary view would produce source no developer would write --
a generated form plus a pile of xpaths against it in the same addon.
"""

import logging
from collections import Counter

from lxml import etree

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.template_inheritance import apply_inheritance_specs

from odoo.addons.app_builder_base.tools import (
    catalogue,
    modelspec,
    pycodegen,
    scaffold,
    xml_writer,
)

from ..tools import view_options

_logger = logging.getLogger(__name__)

# Core loads views ordered by priority; 99 keeps studio edits last so they win
# over other extensions without replacing them.
STUDIO_PRIORITY = 99

VALID_POSITIONS = ("after", "before", "inside", "replace", "attributes")


class StudioViewEditor(models.AbstractModel):
    _name = "studio.view.editor"
    _inherit = ["studio.security.mixin"]
    _description = "Studio View Editor"

    # -- extension view lifecycle -----------------------------------------

    @api.model
    def _extension_name(self, base_view):
        return "%s.studio" % (base_view.name or base_view.model)

    @api.model
    def _find_extension(self, base_view, package):
        """This package's extension of ``base_view``, if it already has one."""
        name = self._extension_name(base_view)
        candidates = self.env["ir.ui.view"].search(
            [("inherit_id", "=", base_view.id), ("name", "=", name)]
        )
        for candidate in candidates:
            if candidate.studio_package_id == package:
                return candidate
        return self.env["ir.ui.view"].browse()

    @api.model
    def _describe(self, operation):
        """A one-line account of an edit, for the history list."""
        kind = operation.get("type", "edit")
        if kind == "set_attributes":
            keys = ", ".join(sorted((operation.get("attrs") or {}).keys()))
            return _("changed %s", keys) if keys else _("changed attributes")
        if kind == "add_field":
            return _("added %s", operation.get("name", "a field"))
        if kind == "remove_node":
            return _("removed a node")
        return kind.replace("_", " ")

    @api.model
    def _get_or_create_extension(self, base_view, package):
        """One extension view per (base view, package).

        Collecting every edit into a single inheriting view keeps the generated
        source readable -- one record with a list of xpaths, rather than a new
        view record per click.
        """
        View = self.env["ir.ui.view"]
        name = self._extension_name(base_view)
        candidates = View.search(
            [("inherit_id", "=", base_view.id), ("name", "=", name)]
        )
        for candidate in candidates:
            if candidate.studio_package_id == package:
                return candidate
        view = View.create(
            {
                "name": name,
                "model": base_view.model,
                "inherit_id": base_view.id,
                "mode": "extension",
                "priority": STUDIO_PRIORITY,
                "arch": "<data/>",
            }
        )
        package.studio_capture(view)
        return view

    # -- arch surgery -----------------------------------------------------

    @api.model
    def _parse_data(self, view):
        root = xml_writer.parse_arch(view.arch)
        if root.tag != "data":
            # A hand-written extension may use a bare xpath as its root; wrap it
            # so we always have somewhere to append.
            wrapper = etree.Element("data")
            wrapper.append(root)
            root = wrapper
        return root

    @api.model
    def _find_xpath(self, root, expr, position):
        for node in root.findall("xpath"):
            if node.get("expr") == expr and node.get("position") == position:
                return node
        return None

    @api.model
    def _write_arch(self, view, root):
        """Persist an arch, letting Odoo's own validators reject bad edits."""
        xml_writer.canonicalize_attributes(root)
        xml_writer.indent(root)
        arch = etree.tostring(root, encoding="unicode")
        try:
            view.write({"arch": arch})
        except ValidationError as err:
            # _check_xml combines the whole inheritance chain and validates the
            # result, so this catches an xpath that matches nothing as well as
            # a field that does not exist on the model.
            raise UserError(
                _("This change produces an invalid view:\n\n%s", err)
            ) from err
        return view

    # -- public operations ------------------------------------------------

    @api.model
    def apply_operation(self, view_id, package_id, operation):
        """Apply one edit and write the owning package to source.

        ``operation`` is a dict with at least ``type``, ``xpath`` and
        ``position``; the remaining keys depend on the type.

        Two modes, chosen by ownership. Editing *someone else's* view emits an
        inheriting view -- that is the whole point of the project, and it keeps
        the edit reviewable as a patch that survives upstream changes. But a
        view this package owns is ours to edit outright, and stapling an
        ``.studio`` extension onto our own primary view would produce source no
        developer would have written. Both modes run the same handlers over the
        same ``<xpath>`` spec; the owned path just feeds that spec through
        core's own ``apply_inheritance_specs`` instead of storing it, so the
        two can never drift apart semantically.
        """
        self._assert_studio_manager()
        base_view = self.env["ir.ui.view"].browse(view_id).exists()
        if not base_view:
            raise UserError(_("The view being edited no longer exists."))
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this change in."))

        handler = getattr(self, "_op_%s" % operation.get("type"), None)
        if handler is None:
            raise UserError(_("Unknown studio operation '%s'.", operation.get("type")))

        if self._owns_outright(base_view, package):
            target = base_view
            created = False
            spec = etree.Element("data")
            handler(spec, operation)
            arch = apply_inheritance_specs(xml_writer.parse_arch(base_view.arch), spec)
        else:
            existing = self._find_extension(base_view, package)
            target = existing or self._get_or_create_extension(base_view, package)
            created = not existing
            arch = self._parse_data(target)
            handler(arch, operation)

        # Captured before the write, and including whether the target had to be
        # brought into existence -- undoing an edit that created the patch has
        # to remove it rather than leave an empty one behind.
        arch_before = "" if created else target.arch
        self._write_arch(target, arch)
        self.env["studio.view.edit"].record(
            base_view,
            target,
            package,
            self._describe(operation),
            arch_before,
            created,
        )
        package.studio_capture(target)
        # A view edit is live the moment the arch is written -- views are data,
        # there is no reload to wait for -- so the file has to keep up in the
        # same breath. Leaving it behind would report the package as drifted
        # while nothing was wrong, and the next reload from disk would quietly
        # undo the edit.
        if package.writable:
            package.action_write_files()
        return {
            "view_id": target.id,
            "arch": target.arch,
            "combined_arch": self.env["ir.ui.view"]
            .browse(base_view.id)
            .get_combined_arch(),
        }

    @api.model
    def _owns_outright(self, view, package):
        """Whether ``package`` may edit ``view``'s arch directly.

        Only a *primary* view the package already owns. An extension view is
        itself a patch and is always edited as one, and a view owned by another
        module must never be rewritten in place -- that is the Studio failure
        mode this project exists to avoid.
        """
        return view.mode == "primary" and view.studio_package_id == package

    @api.model
    def _new_xpath(self, root, expr, position):
        if position not in VALID_POSITIONS:
            raise UserError(_("'%s' is not a valid xpath position.", position))
        node = etree.SubElement(root, "xpath")
        node.set("expr", expr)
        node.set("position", position)
        return node

    def _op_add_field(self, root, operation):
        """Insert a field relative to an existing node.

        Adding the *same* field at the same anchor twice -- a double-click, a
        replayed request -- must be idempotent, or the field lands in the
        combined arch twice. Adding a *different* field at the same anchor must
        not be folded into the same block: two separate ``position="after"``
        blocks apply in sequence and read back in the order the user added
        them, whereas merging them into one block silently reverses that.
        """
        name = operation.get("name")
        if not name:
            raise UserError(_("Adding a field requires a field name."))
        position = operation.get("position", "after")
        expr = operation["xpath"]
        node = None
        for candidate in root.findall("xpath"):
            if candidate.get("expr") != expr or candidate.get("position") != position:
                continue
            if any(f.get("name") == name for f in candidate.findall("field")):
                node = candidate
                break
        if node is None:
            node = self._new_xpath(root, expr, position)
        field = next((f for f in node.findall("field") if f.get("name") == name), None)
        if field is None:
            field = etree.SubElement(node, "field")
        field.set("name", name)
        for key, value in (operation.get("attrs") or {}).items():
            field.set(key, str(value))
        return node

    def _op_move_node(self, root, operation):
        """Relocate an existing node, using core's own ``position="move"``.

        Core extracts the named node and re-inserts it at the anchor
        (``template_inheritance.py:45``), so this is a real move rather than a
        delete-and-recreate: attributes contributed by *other* inheriting views
        travel with it, which a recreate would silently drop.
        """
        expr = operation.get("xpath")
        anchor = operation.get("target_xpath")
        position = operation.get("position", "before")
        if not expr or not anchor:
            raise UserError(_("Moving a node needs both what moves and where."))
        if position not in ("before", "after"):
            raise UserError(
                _("A node can move before or after another, not '%s'.", position)
            )
        if expr == anchor:
            raise UserError(_("A node cannot be moved relative to itself."))
        node = self._new_xpath(root, anchor, position)
        moved = etree.SubElement(node, "xpath")
        moved.set("expr", expr)
        moved.set("position", "move")
        return node

    def _op_add_filter(self, root, operation):
        """Add a ``<filter>`` -- a saved condition, or a group-by.

        Group-bys are filters too; what makes one a group-by is a ``group_by``
        context *and* living inside the ``<group>``. Outside it the same node
        renders as an ordinary filter in the Filters menu, which is why the
        group is created here when the view has none rather than left to a
        second operation the user would have to understand.
        """
        node = self._new_xpath(
            root, operation["xpath"], operation.get("position", "inside")
        )
        container = node
        if operation.get("in_new_group"):
            container = etree.SubElement(node, "group")
            container.set("string", operation.get("group_string") or "Group By")
        filter_node = etree.SubElement(container, "filter")
        filter_node.set("name", operation["name"])
        filter_node.set("string", operation.get("string") or operation["name"])
        if operation.get("domain"):
            filter_node.set("domain", operation["domain"])
        if operation.get("context"):
            filter_node.set("context", operation["context"])
        return node

    def _op_remove_node(self, root, operation):
        """Remove a node from the rendered view.

        Emitted as ``position="replace"`` with empty content, which is the
        idiomatic Odoo way to drop a node without touching the base view.
        """
        existing = self._find_xpath(root, operation["xpath"], "replace")
        if existing is not None:
            return existing
        return self._new_xpath(root, operation["xpath"], "replace")

    def _op_set_attributes(self, root, operation):
        """Set attributes on an existing node, merging with prior edits."""
        attrs = operation.get("attrs") or {}
        if not attrs:
            raise UserError(_("No attributes given."))
        node = self._find_xpath(root, operation["xpath"], "attributes")
        if node is None:
            node = self._new_xpath(root, operation["xpath"], "attributes")
        for key, value in attrs.items():
            for existing in node.findall("attribute"):
                if existing.get("name") == key:
                    existing.text = None if value is None else str(value)
                    break
            else:
                child = etree.SubElement(node, "attribute")
                child.set("name", key)
                if value is not None:
                    child.text = str(value)
        return node

    def _op_add_group(self, root, operation):
        node = self._new_xpath(
            root, operation["xpath"], operation.get("position", "inside")
        )
        group = etree.SubElement(node, "group")
        if operation.get("string"):
            group.set("string", operation["string"])
        return node

    def _op_add_page(self, root, operation):
        """Add a notebook tab, creating the notebook when there is none.

        Same reasoning as the group a filter lands in: a tab with nowhere to
        live is not a second operation the user should have to understand.
        """
        node = self._new_xpath(
            root, operation["xpath"], operation.get("position", "inside")
        )
        container = node
        if operation.get("in_new_notebook"):
            container = etree.SubElement(node, "notebook")
        page = etree.SubElement(container, "page")
        page.set("string", operation.get("string") or "New tab")
        if operation.get("name"):
            page.set("name", operation["name"])
        return node

    def _op_add_button(self, root, operation):
        node = self._new_xpath(
            root, operation["xpath"], operation.get("position", "inside")
        )
        button = etree.SubElement(node, "button")
        button.set("name", operation["name"])
        button.set("type", operation.get("button_type", "object"))
        if operation.get("string"):
            button.set("string", operation["string"])
        if operation.get("class"):
            button.set("class", operation["class"])
        return node

    # -- helpers for the client -------------------------------------------

    @api.model
    def _occurrences(self, root):
        """How many nodes answer to each ``(tag, name)`` pair.

        A bare ``//tag[@name='x']`` is only a valid locator when nothing else in
        the arch answers to it. An embedded x2many subview routinely repeats the
        parent's field names, and ``locate_node`` silently takes the first match
        -- so without this count an edit aimed at a sublist column patches the
        sheet instead, for the wrong model.
        """
        return Counter(
            (el.tag, el.get("name"))
            for el in root.iter()
            if isinstance(el.tag, str) and el.get("name")
        )

    @api.model
    def _locator_for(self, node, occurrences):
        """The most durable xpath identifying exactly ``node``.

        Prefer an identifying predicate over a positional index: ``//field[@name]``
        survives a sibling being inserted, ``//div[3]`` does not -- but only
        while exactly one node in the arch answers to it.

        The fallback has to be an *absolute* path, not one relative to a
        hand-built ancestor chain. An inline x2many subview is itself a
        ``<form><sheet>``, so "//form/sheet/..." is ambiguous from its first
        step and everything built on it inherits that. ``getpath()`` is anchored
        at the document root and indexes every step, so it is unique by
        construction -- the same call core's own ``distribute_branding`` uses.
        """
        name = node.get("name")
        if name and occurrences[(node.tag, name)] == 1:
            return "//%s[@name='%s']" % (node.tag, name)
        return node.getroottree().getpath(node)

    @api.model
    def apply_at(self, view_id, package_id, anchor, operation):
        """Apply an operation relative to a node the client picked by descriptor.

        The one entry point for every structural edit -- adding a field, a
        button, a tab, a group, or removing any of them. It exists so the client
        keeps its side of the bargain: it says *what was selected*, and the
        xpath is minted here against the combined arch. A browser that computed
        its own locator would produce one derived from a per-user projection,
        which is right for that user and wrong for the next.

        ``position`` is decided here too, from what kind of thing was selected:
        a container takes a child, a leaf takes a sibling. Letting the caller
        choose would mean the same gesture behaved differently depending on
        which button sent it.
        """
        self._assert_studio_manager()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        node = self._find_descriptor(root, anchor)
        if node is None:
            raise UserError(
                _("That is not a place in the view the builder can address.")
            )
        operation = dict(operation)
        operation["xpath"] = self._locator_for(node, self._occurrences(root))
        operation.setdefault("position", self._insert_position(anchor))
        return self.apply_operation(view_id, package_id, operation)

    @api.model
    def add_field_at(self, view_id, package_id, anchor, field_name):
        """Put an existing field of the model into the view.

        The gap this closes is the largest one the builder had: a field could be
        *created* on any model and then placed only into views the package owned
        outright, which excluded every core screen -- so adding a field to the
        quotation form, the most ordinary Studio gesture there is, had no path
        through the UI at all. The server could always emit the inheriting
        ``<xpath>`` for it; nothing asked.
        """
        self._assert_studio_manager()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        if field_name not in self.env[view.model]._fields:
            raise UserError(
                _(
                    "%(field)s is not a field of %(model)s.",
                    field=field_name,
                    model=view.model,
                )
            )
        operation = {"type": "add_field", "name": field_name}
        if view.type == "list":
            # A list has no containers: every field is a column of the root, so
            # "inside the list" and "after that column" are the only readings
            # and the anchor decides which.
            operation["position"] = self._insert_position(anchor)
        return self.apply_at(view_id, package_id, anchor, operation)

    @api.model
    def remove_at(self, view_id, package_id, anchor):
        """Take the selected node out of the view.

        Emitted as ``position="replace"`` with nothing in it, which is how a
        view drops a node it inherits without touching the view that declares
        it. Distinct from hiding: an invisible field is still there and still
        loads, which is usually what somebody actually wants -- so the UI offers
        both and says which is which.
        """
        return self.apply_at(
            view_id, package_id, anchor, {"type": "remove_node", "position": "replace"}
        )

    @api.model
    def add_button_at(self, view_id, package_id, anchor, values):
        """Add a button that runs a server action.

        Restricted to server actions on purpose. The alternative Odoo Studio
        offers -- name any Python method -- writes a call to something that may
        not exist, and the view happily saves: the failure arrives later, for
        whoever presses it. A server action is a record, so the reference is
        checked when it is chosen and travels with the package.
        """
        self._assert_studio_manager()
        action = (
            self.env["ir.actions.server"].browse(values.get("action_id") or 0).exists()
        )
        if not action:
            raise UserError(_("Choose the server action this button should run."))
        # The xmlid, not the id, and not the `%(xmlid)d` form a data file uses.
        # The validator tries `int(name)` and falls back to resolving an xmlid
        # (`ir_ui_view.py:3089-3096`), so a stored arch takes either -- but only
        # one of them still means the same action in the next database. The
        # `%(...)d` spelling is refused outright here, because convert.py
        # resolves it while *loading* and there is nothing to resolve it in a
        # view being written live.
        xmlid = action.get_external_id().get(action.id)
        if not xmlid:
            raise UserError(
                _(
                    "%(name)s has no external ID, so a button naming it could "
                    "not survive being loaded into another database. Assign the "
                    "action to a studio package first.",
                    name=action.display_name,
                )
            )
        return self.apply_at(
            view_id,
            package_id,
            anchor,
            {
                "type": "add_button",
                "name": xmlid,
                "button_type": "action",
                "string": values.get("string") or action.name,
                "class": values.get("class") or "btn-secondary",
            },
        )

    @api.model
    def add_container_at(self, view_id, package_id, anchor, kind, string=None):
        """Add a tab or a group -- the two structural pieces a form is made of."""
        self._assert_studio_manager()
        if kind == "group":
            return self.apply_at(
                view_id, package_id, anchor, {"type": "add_group", "string": string or ""}
            )
        if kind != "page":
            raise UserError(_("The builder does not add '%s'.", kind))

        # A page is only legal inside a notebook -- `_validate_tag_page` refuses
        # anything else outright -- so "add a tab" has to mean "add a tab to the
        # notebook", and provide the notebook when there is none. Making the
        # user create the notebook first would be asking them to know a rule the
        # builder already knows, and the failure if they did not would arrive as
        # a validation error about ancestors.
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        operation = {"type": "add_page", "string": string or _("New tab")}
        if anchor.get("kind") == "notebook":
            return self.apply_at(view_id, package_id, anchor, operation)
        notebook = next(
            (
                node
                for node in root.iter("notebook")
                if not any(a.tag == "field" for a in node.iterancestors())
            ),
            None,
        )
        if notebook is not None:
            return self.apply_at(
                view_id, package_id, {"kind": "notebook"}, operation
            )
        operation["in_new_notebook"] = True
        return self.apply_at(view_id, package_id, anchor, operation)

    @api.model
    def move_node(self, view_id, package_id, source, target, position="before"):
        """Reorder by descriptor, resolving both ends server-side.

        The client says "this column goes before that one" and never computes a
        locator, for the same reason it never computes one when selecting: the
        arch it can see is a per-user projection.
        """
        self._assert_studio_manager()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        occurrences = self._occurrences(root)
        source_node = self._find_descriptor(root, source)
        target_node = self._find_descriptor(root, target)
        if source_node is None or target_node is None:
            raise UserError(
                _("One end of that move is not a node the builder can address.")
            )
        return self.apply_operation(
            view_id,
            package_id,
            {
                "type": "move_node",
                "xpath": self._locator_for(source_node, occurrences),
                "target_xpath": self._locator_for(target_node, occurrences),
                "position": position,
            },
        )

    # -- search views -------------------------------------------------------
    #
    # The one view type with nothing to click: a search view has no rendering
    # of its own, it furnishes another view's control panel. So it is edited as
    # the three lists it really is -- searchable fields, filters, group-bys --
    # while the preview shows a real list with this search view attached, so the
    # menus being edited are the menus on screen.

    # Conditions offered per field, rather than a domain box. A free-text domain
    # is the most powerful option and the least usable one; these cover what
    # people actually add, and anything else belongs in the source.
    FILTER_CONDITIONS = {
        "set": ("%s is set", "[('%s', '!=', False)]"),
        "not_set": ("%s is not set", "[('%s', '=', False)]"),
        "true": ("%s", "[('%s', '=', True)]"),
        "false": ("Not %s", "[('%s', '=', False)]"),
    }

    @api.model
    def search_elements(self, view_id):
        """What a search view offers, in the three groups the sidebar shows."""
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        fields_, filters, group_bys = [], [], []
        for node in root.iter("field"):
            if not any(a.tag == "field" for a in node.iterancestors()):
                fields_.append(
                    {"name": node.get("name"), "string": node.get("string") or ""}
                )
        for node in root.iter("filter"):
            entry = {
                "name": node.get("name") or "",
                "string": node.get("string") or node.get("name") or "",
                "domain": node.get("domain") or "",
            }
            if "group_by" in (node.get("context") or ""):
                group_bys.append(entry)
            else:
                filters.append(entry)
        return {
            "fields": fields_,
            "filters": filters,
            "group_bys": group_bys,
            # Not computed on the client: "already offered" has to ignore
            # fields belonging to embedded subviews, which are another model's
            # entirely, and that rule lives here with the reason for it.
            "addable": self.get_addable_fields(view.model, view.id),
        }

    @api.model
    def add_search_element(self, view_id, package_id, kind, values):
        """Add a searchable field, a filter, or a group-by."""
        self._assert_studio_manager()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        occurrences = self._occurrences(root)
        field_name = values.get("field")
        if not field_name or field_name not in self.env[view.model]._fields:
            raise UserError(_("Choose a field that exists on %s.", view.model))
        field = self.env[view.model]._fields[field_name]

        if kind == "field":
            anchor, position = self._search_anchor(root, "field")
            operation = {
                "type": "add_field",
                "xpath": self._locator_for(anchor, occurrences),
                "position": position,
                "name": field_name,
            }
        elif kind == "filter":
            condition = values.get("condition", "set")
            if condition not in self.FILTER_CONDITIONS:
                raise UserError(_("Unknown filter condition '%s'.", condition))
            label, domain = self.FILTER_CONDITIONS[condition]
            anchor, position = self._search_anchor(root, "filter")
            operation = {
                "type": "add_filter",
                "xpath": self._locator_for(anchor, occurrences),
                "position": position,
                "name": "filter_%s_%s" % (field_name, condition),
                "string": label % (field.string or field_name),
                "domain": domain % field_name,
            }
        elif kind == "group_by":
            group = next(iter(root.iter("group")), None)
            anchor = group if group is not None else root
            operation = {
                "type": "add_filter",
                "xpath": self._locator_for(anchor, occurrences),
                "position": "inside",
                "in_new_group": group is None,
                "name": "group_by_%s" % field_name,
                "string": field.string or field_name,
                "context": "{'group_by': '%s'}" % field_name,
            }
        else:
            raise UserError(_("A search view has no '%s' to add.", kind))
        return self.apply_operation(view_id, package_id, operation)

    @api.model
    def _search_anchor(self, root, tag):
        """Where a new node of ``tag`` should go, and on which side.

        After the last one of its kind, so additions read in the order they
        were made; inside the view itself when there is no example to follow.
        """
        existing = [
            node
            for node in root.iter(tag)
            if not any(a.tag == "field" for a in node.iterancestors())
            and not any(a.tag == "group" for a in node.iterancestors())
        ]
        if existing:
            return existing[-1], "after"
        return root, "inside"

    @api.model
    def remove_search_element(self, view_id, package_id, kind, name):
        """Take a field, filter or group-by out of a search view."""
        self._assert_studio_manager()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        descriptor = {"kind": "field" if kind == "field" else "filter", "name": name}
        node = self._find_descriptor(root, descriptor)
        if node is None:
            raise UserError(_("There is no '%s' in this search view.", name))
        return self.apply_operation(
            view_id,
            package_id,
            {
                "type": "remove_node",
                "xpath": self._locator_for(node, self._occurrences(root)),
                "position": "replace",
            },
        )

    # -- the WYSIWYG editor ------------------------------------------------

    # What a click in the rendered view can select, and which arch tag it means.
    # Data rather than branching, so supporting a new view type is a line here.
    DESCRIPTOR_TAGS = {
        "field": "field",
        "column": "field",
        "button": "button",
        "page": "page",
        "group": "group",
        "filter": "filter",
        # Containers. These are what an *insertion* aims at -- "put it in this
        # group" -- so they became addressable when the editor learnt to add
        # rather than only to change.
        "notebook": "notebook",
        "sheet": "sheet",
        "header": "header",
        "form": "form",
        "list": "list",
    }

    # Where a new node goes, given what was selected. Insertion is the one
    # gesture with two plausible readings -- "after this" or "inside this" --
    # and guessing differently each time is what makes an editor feel arbitrary.
    # A leaf takes a sibling; a container takes a child.
    INSERT_INSIDE = ("group", "notebook", "sheet", "header", "form", "list", "root")

    @api.model
    def locate_target(self, view_id, descriptor):
        """Resolve what the user clicked to a stable xpath, server-side.

        The browser sends a *descriptor* -- "the column for user_id" -- and
        never an xpath, and that division is the whole point. The arch a client
        receives is a per-user projection: nodes are dropped by group rights and
        whole subviews are grafted in, so a path derived from it can be wrong
        for somebody else looking at the same view. Resolution happens here,
        against the combined arch, using the same uniqueness rule the node list
        already uses.
        """
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        node = self._find_descriptor(root, descriptor)
        if node is None:
            return {
                "found": False,
                "reason": _(
                    "That element is not something the builder can edit: it "
                    "does not correspond to a node in the view's definition."
                ),
            }
        return {
            "found": True,
            "xpath": self._locator_for(node, self._occurrences(root)),
            "tag": node.tag,
            "attrs": dict(node.attrib),
            "field": self._field_info(view.model, node),
        }

    @api.model
    def _find_descriptor(self, root, descriptor):
        """The arch node a descriptor refers to, or ``None``."""
        kind = descriptor.get("kind")
        if kind == "root":
            return root
        tag = self.DESCRIPTOR_TAGS.get(kind)
        if not tag:
            return None
        # A node inside an embedded subview belongs to another model entirely;
        # selecting one here would edit the wrong thing.
        candidates = [
            node
            for node in root.iter(tag)
            if not any(ancestor.tag == "field" for ancestor in node.iterancestors())
        ]
        name = descriptor.get("name")
        if name:
            return next((n for n in candidates if n.get("name") == name), None)
        # Position, for nodes that carry no name at all. Core notebook pages
        # usually do not, and refusing to edit them would put most existing
        # forms out of reach -- so the nth tab means the nth <page>, which is
        # the order they render in.
        index = descriptor.get("index")
        if isinstance(index, int) and 0 <= index < len(candidates):
            return candidates[index]
        # A singleton container -- a form's <sheet>, its <header> -- is named by
        # its tag alone, because there is only one and it has nothing else to be
        # named by. Ambiguity is refused rather than resolved to the first: two
        # <group>s and no name is a question, not an answer.
        if len(candidates) == 1:
            return candidates[0]
        return None

    @api.model
    def _insert_position(self, descriptor):
        """Whether a new node goes inside what was selected or after it."""
        kind = descriptor.get("kind")
        return "inside" if kind in self.INSERT_INSIDE else "after"

    @api.model
    def _field_info(self, model_name, node):
        """What the sidebar needs in order to offer the right options.

        Options are type-aware -- a column sum belongs on a number and nowhere
        else -- so the panel is built from the live field rather than guessed
        from the arch.
        """
        if node.tag != "field" or model_name not in self.env:
            return None
        field = self.env[model_name]._fields.get(node.get("name"))
        if not field:
            return None
        info = {
            "name": field.name,
            "type": field.type,
            "string": field.string or field.name,
            "store": bool(field.store),
            "required": bool(field.required),
            "readonly": bool(field.readonly),
        }
        # A relational field's options can name a field on the *other* model --
        # a tag's colour lives on the tag -- so the panel needs that list too.
        comodel = getattr(field, "comodel_name", None)
        if comodel and comodel in self.env:
            info["comodel_fields"] = self._model_fields(comodel)
        return info

    @api.model
    def editing_context(self, view_id=None, model=None, view_type=None):
        """Everything the editor needs to open on a view.

        ``view_id`` is optional on purpose. An ordinary action rarely pins one
        -- ``view_mode="list,form"`` resolves its views at load time -- so the
        client usually knows only *which model and which kind of view* the user
        is looking at. Asking core's own ``default_view`` for the rest means the
        editor opens the view Odoo would actually render, rather than whichever
        one happened to be first.

        Also reports which package will record the edit. A view the studio owns
        records into its own package; anything else needs one chosen, and when
        exactly one writable package exists that is not worth asking about.
        """
        self._assert_studio_user()
        View = self.env["ir.ui.view"]
        view = View.browse(view_id).exists() if view_id else View.browse()
        if not view and model and view_type:
            view = View.browse(View.default_view(model, view_type))
        if not view:
            raise UserError(
                _(
                    "There is no %(type)s view of %(model)s to edit.",
                    type=view_type or _("such"),
                    model=model or _("that model"),
                )
            )
        packages = self.env["studio.package"].search([])
        writable = packages.filtered("writable")
        owner = view.studio_package_id
        suggested = owner or (writable[:1] if len(writable) == 1 else packages.browse())
        return {
            "view": {
                "id": view.id,
                "name": view.name,
                "type": view.type,
                "model": view.model,
                "mode": view.mode,
            },
            # The model's fields, so options that *name* a field can offer the
            # right ones. A calendar's date_start has to be a date and its
            # colour has to be groupable; a free-text box would let the user
            # type a name that breaks the view on open.
            "fields": self._model_fields(view.model),
            "preview": self._preview_for(view),
            # What can be changed about anything in this view, and the widget
            # vocabulary shared with the model composer. Sent here rather than
            # from an endpoint of its own because the editor already makes this
            # call and the answer never changes mid-session.
            "options": view_options.groups_json(view.type, self.env._),
            "catalogue": catalogue.catalogue_json(self.env._),
            "groups": self._selectable_groups(),
            # Whether an edit rewrites this view or emits a patch against it.
            # The preview shows the combined result either way, so saying which
            # is the difference between understanding the output and not.
            "owned": bool(owner) and self._owns_outright(view, owner),
            "packages": [
                {"id": p.id, "name": p.name, "writable": p.writable} for p in packages
            ],
            "suggested_package_id": suggested.id if suggested else False,
        }

    # Types the builder can create from nothing, and what each one needs first.
    ADDABLE_VIEW_TYPES = {
        "kanban": (),
        "calendar": ("date",),
        "list": (),
        "form": (),
    }

    @api.model
    def addable_view_types(self, model_name):
        """Which views this model could have that it does not already.

        Calendar is reported as unavailable rather than hidden when the model
        has no date field: somebody looking for it learns why, and what to add
        to get it, instead of concluding the builder cannot do calendars.
        """
        self._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        model = self.env[model_name]
        existing = set(
            self.env["ir.ui.view"]
            .search([("model", "=", model_name), ("mode", "=", "primary")])
            .mapped("type")
        )
        # create_date and write_date are dates too, and a calendar of when
        # records happened to be typed in is not a calendar anybody wants. They
        # also mean every model looks like it has a date, which would hide the
        # "add one first" answer the user actually needs.
        date_fields = [
            {"name": name, "string": field.string or name}
            for name, field in sorted(model._fields.items())
            if field.type in ("date", "datetime")
            and field.store
            and name not in modelspec.MAGIC_COLUMNS
        ]
        out = []
        for view_type in self.ADDABLE_VIEW_TYPES:
            enabled, reason = True, ""
            if view_type in existing:
                enabled = False
                reason = _("This model already has a %s view.", view_type)
            elif view_type == "calendar" and not date_fields:
                enabled = False
                reason = _(
                    "A calendar needs a date field to place records on, and "
                    "this model has none. Add one first."
                )
            out.append(
                {
                    "type": view_type,
                    "enabled": enabled,
                    "reason": reason,
                    "date_fields": date_fields if view_type == "calendar" else [],
                }
            )
        return out

    @api.model
    def add_view(self, model_name, view_type, package_id, date_field=None):
        """Create a view of ``view_type`` for ``model_name``, and make it
        reachable.

        Creating the record is the easy half. A view no action offers is a view
        nobody can open, so the window actions this package owns for the model
        gain the type in their ``view_mode`` -- otherwise the builder would
        report success and the user would never find what it built.
        """
        self._assert_studio_manager()
        if view_type not in self.ADDABLE_VIEW_TYPES:
            raise UserError(_("The builder does not create %s views.", view_type))
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this view in."))
        package._assert_writable()

        model = self.env[model_name]
        existing = self.env["ir.ui.view"].search(
            [
                ("model", "=", model_name),
                ("type", "=", view_type),
                ("mode", "=", "primary"),
            ]
        )
        if existing:
            raise UserError(
                _(
                    "%(model)s already has a %(type)s view.",
                    model=model_name,
                    type=view_type,
                )
            )

        if view_type == "calendar" and (
            not date_field or date_field not in model._fields
        ):
            raise UserError(
                _(
                    "A calendar has to know which date to place records on. "
                    "Choose a date field on %s first.",
                    model_name,
                )
            )
        arch = self._scaffold_arch(model, view_type, date_field)
        view = self.env["ir.ui.view"].create(
            {
                "name": "%s.%s" % (model_name, view_type),
                "model": model_name,
                "type": view_type,
                "arch": etree.tostring(arch, encoding="unicode"),
            }
        )
        package.studio_capture(view)
        self._offer_view_in_actions(package, model_name, view_type)
        package.action_write_files()
        return {"view_id": view.id, "type": view_type}

    @api.model
    def _scaffold_arch(self, model, view_type, date_field):
        """The starting arch for a new view, built from the live model."""
        spec = self._spec_for(model)
        options = scaffold.ScaffoldOptions(
            stage="state" in model._fields,
            user="user_id" in model._fields,
            chatter="message_ids" in model._fields,
        )
        if view_type == "kanban":
            return scaffold.scaffold_kanban_arch(model, spec, options)
        if view_type == "calendar":
            return scaffold.scaffold_calendar_arch(model, spec, date_field, options)
        if view_type == "list":
            return scaffold.scaffold_list_arch(model, spec, options)
        return scaffold.scaffold_form_arch(model, spec, options)

    @api.model
    def _spec_for(self, model):
        """A spec describing the live model, for the scaffold to read.

        The scaffolds take a spec because that is what building a *new* model
        produces. Here the model already exists, so one is derived from the
        registry -- the same direction adoption uses.
        """
        entry = self.env["studio.package.model"].search(
            [("model", "=", model._name), ("source", "=", "python")], limit=1
        )
        spec = entry._current_spec() if entry else None
        if spec is not None:
            return spec
        fields_ = [
            modelspec.FieldSpec(name=name, ttype=field.type, string=field.string)
            for name, field in model._fields.items()
            if field.store and name not in modelspec.MAGIC_COLUMNS
        ]
        return modelspec.ModelSpec(
            name=model._name,
            description=model._description or model._name,
            class_name=pycodegen.class_name_for(model._name),
            fields=tuple(fields_),
            rec_name=model._rec_name or "name",
        )

    @api.model
    def _offer_view_in_actions(self, package, model_name, view_type):
        """Add the new view type to the window actions that show this model."""
        actions = self.env["ir.actions.act_window"].search(
            [("res_model", "=", model_name)]
        )
        touched = actions.browse()
        for action in actions:
            if action.studio_package_id != package:
                # Somebody else's action is not ours to change; the studio's
                # whole premise is that it does not rewrite what it does not own.
                continue
            modes = [
                m.strip() for m in (action.view_mode or "").split(",") if m.strip()
            ]
            if view_type in modes:
                continue
            # After list, before form: a form is a detail view and reads last.
            insert_at = len(modes) if "form" not in modes else modes.index("form")
            modes.insert(insert_at, view_type)
            action.view_mode = ",".join(modes)
            touched |= action
        if touched:
            package.studio_capture(touched)
        return touched

    @api.model
    def _preview_for(self, view):
        """How to render the view being edited.

        Every type renders itself, except search: a search view has no
        rendering of its own, it furnishes another view's control panel. So it
        previews as the model's list *with this search view attached*, which
        means the Filters and Group By menus on screen are the ones being
        edited rather than an approximation of them.
        """
        if view.type != "search":
            return {"type": view.type, "view_id": view.id, "search_view_id": False}
        host = self.env["ir.ui.view"].default_view(view.model, "list")
        return {
            "type": "list",
            "view_id": host or False,
            "search_view_id": view.id,
            # Without a list to host it there is nothing to show. Editing still
            # works -- the sidebar is the editor for a search view anyway.
            "unavailable": not host,
        }

    @api.model
    def _selectable_groups(self):
        """Groups a ``groups=""`` attribute can name.

        Only ones with an external id: the attribute takes xmlids, and a group
        without one cannot be referred to from an arch at all -- so offering it
        would produce a view that silently shows the field to everybody.
        """
        groups = self.env["res.groups"].sudo().search([])
        external = groups.get_external_id()
        out = [
            {
                "id": group.id,
                "xmlid": external.get(group.id),
                "name": group.display_name,
            }
            for group in groups
            if external.get(group.id)
        ]
        return sorted(out, key=lambda entry: entry["name"])

    @api.model
    def _model_fields(self, model_name):
        """Every stored field of a model, for option rows that name one."""
        if model_name not in self.env:
            return []
        return [
            {"name": name, "string": field.string or name, "type": field.type}
            for name, field in sorted(self.env[model_name]._fields.items())
            if field.store and name not in modelspec.MAGIC_COLUMNS
        ]

    @api.model
    def get_addable_fields(self, model_name, view_id=None):
        """Fields on the model that are not already in the combined arch."""
        self._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        model = self.env[model_name]
        present = set()
        if view_id:
            view = self.env["ir.ui.view"].browse(view_id).exists()
            if view:
                arch = etree.fromstring(view.get_combined_arch().encode())
                # Only fields at this arch's own level count as placed. iter()
                # is recursive, so an embedded x2many subview -- which belongs
                # to another model entirely -- would otherwise mask the parent's
                # field of the same name, and the palette comes back empty on
                # exactly the core models people reach for first.
                present = {
                    node.get("name")
                    for node in arch.iter("field")
                    if node.get("name")
                    and not any(a.tag == "field" for a in node.iterancestors())
                }
        result = []
        for name, field in sorted(model._fields.items()):
            if name in present or name.startswith("_"):
                continue
            # Non-stored, non-computed fields have no value to show on a form,
            # and adding one produces a view that fails validation.
            if not field.store and not field.compute and not field.related:
                continue
            result.append(
                {
                    "name": name,
                    "string": field.string or name,
                    "type": field.type,
                    "required": bool(field.required),
                    "readonly": bool(field.readonly),
                    "manual": bool(getattr(field, "manual", False)),
                }
            )
        return result

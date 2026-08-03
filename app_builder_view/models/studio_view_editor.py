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

from odoo.addons.app_builder_base.tools import xml_writer

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
            spec = etree.Element("data")
            handler(spec, operation)
            arch = apply_inheritance_specs(xml_writer.parse_arch(base_view.arch), spec)
        else:
            target = self._get_or_create_extension(base_view, package)
            arch = self._parse_data(target)
            handler(arch, operation)

        self._write_arch(target, arch)
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
    def get_editable_views(self, model_name):
        """Views of ``model_name`` the editor can offer as a starting point."""
        self._assert_studio_user()
        views = self.env["ir.ui.view"].search(
            [("model", "=", model_name), ("mode", "=", "primary")],
            order="type, priority, id",
        )
        return [
            {"id": v.id, "name": v.name, "type": v.type, "xml_id": v.xml_id}
            for v in views
        ]

    @api.model
    def get_view_nodes(self, view_id):
        """Return the combined arch as a flat, pickable node list.

        Each entry carries a *stable* xpath the user never has to type. Building
        it server-side from the combined arch (rather than from the DOM) means
        the xpath is expressed against the view definition, which is what
        ``apply_inheritance_specs`` matches on -- a DOM-derived path would drift
        the moment another module extends the same view.
        """
        self._assert_studio_user()
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        nodes = []
        self._walk_nodes(root, nodes, depth=0, occurrences=self._occurrences(root))
        return nodes

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
    def _walk_nodes(self, node, nodes, depth, occurrences):
        """Depth-first walk emitting one entry per element."""
        if not isinstance(node.tag, str):
            return
        name = node.get("name")
        path = self._locator_for(node, occurrences)
        label = name or node.get("string") or node.get("class") or ""
        nodes.append(
            {
                "tag": node.tag,
                "xpath": path,
                "label": label,
                "depth": depth,
                "is_field": node.tag == "field",
                "container": node.tag
                in ("form", "sheet", "group", "notebook", "page", "list", "header"),
            }
        )
        for child in node:
            self._walk_nodes(child, nodes, depth + 1, occurrences)

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
    }

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
        name = descriptor.get("name")
        if not tag or not name:
            return None
        for node in root.iter(tag):
            if node.get("name") != name:
                continue
            # A node inside an embedded subview belongs to another model
            # entirely; selecting it here would edit the wrong thing.
            if any(ancestor.tag == "field" for ancestor in node.iterancestors()):
                continue
            return node
        return None

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
        return {
            "name": field.name,
            "type": field.type,
            "string": field.string or field.name,
            "store": bool(field.store),
            "required": bool(field.required),
            "readonly": bool(field.readonly),
        }

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
            # Whether an edit rewrites this view or emits a patch against it.
            # The preview shows the combined result either way, so saying which
            # is the difference between understanding the output and not.
            "owned": bool(owner) and self._owns_outright(view, owner),
            "packages": [
                {"id": p.id, "name": p.name, "writable": p.writable} for p in packages
            ],
            "suggested_package_id": suggested.id if suggested else False,
        }

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

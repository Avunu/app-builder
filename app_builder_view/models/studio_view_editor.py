# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""View editing that produces inheriting views, never replacements.

Odoo Studio rewrites view arch in place, which is why a Studio-customised
database fights every upstream upgrade. Here, every edit becomes an ``<xpath>``
inside a single extension view per (base view, package) at ``priority=99`` --
core's own convention for last-loaded views (``ir_ui_view.py:658``). The result
reads like a patch a developer would have written, survives upstream changes to
the base view, and is reviewable in git.
"""

import logging

from lxml import etree

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.app_builder_base.tools import xml_writer

_logger = logging.getLogger(__name__)

# Core loads views ordered by priority; 99 keeps studio edits last so they win
# over other extensions without replacing them.
STUDIO_PRIORITY = 99

VALID_POSITIONS = ("after", "before", "inside", "replace", "attributes")


class StudioViewEditor(models.AbstractModel):
    _name = "studio.view.editor"
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
        """
        base_view = self.env["ir.ui.view"].browse(view_id).exists()
        if not base_view:
            raise UserError(_("The view being edited no longer exists."))
        package = self.env["studio.package"].browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this change in."))

        handler = getattr(self, "_op_%s" % operation.get("type"), None)
        if handler is None:
            raise UserError(_("Unknown studio operation '%s'.", operation.get("type")))

        extension = self._get_or_create_extension(base_view, package)
        root = self._parse_data(extension)
        handler(root, operation)
        self._write_arch(extension, root)
        package.studio_capture(extension)
        return {
            "view_id": extension.id,
            "arch": extension.arch,
        }

    @api.model
    def _new_xpath(self, root, expr, position):
        if position not in VALID_POSITIONS:
            raise UserError(_("'%s' is not a valid xpath position.", position))
        node = etree.SubElement(root, "xpath")
        node.set("expr", expr)
        node.set("position", position)
        return node

    def _op_add_field(self, root, operation):
        """Insert a field relative to an existing node."""
        name = operation.get("name")
        if not name:
            raise UserError(_("Adding a field requires a field name."))
        node = self._new_xpath(
            root, operation["xpath"], operation.get("position", "after")
        )
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
        view = self.env["ir.ui.view"].browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = etree.fromstring(view.get_combined_arch().encode())
        nodes = []
        self._walk_nodes(root, "", nodes, depth=0)
        return nodes

    @api.model
    def _walk_nodes(self, node, parent_path, nodes, depth):
        """Depth-first walk emitting one entry per element."""
        if not isinstance(node.tag, str):
            return
        # Prefer an identifying predicate over a positional index: //field[@name]
        # survives a sibling being inserted, //div[3] does not.
        name = node.get("name")
        if name:
            path = "//%s[@name='%s']" % (node.tag, name)
        else:
            siblings = [
                child
                for child in (node.getparent() or [])
                if isinstance(child.tag, str) and child.tag == node.tag
            ]
            if node.getparent() is None:
                path = "//%s" % node.tag
            elif len(siblings) > 1:
                index = siblings.index(node) + 1
                path = "%s/%s[%d]" % (parent_path, node.tag, index)
            else:
                path = "%s/%s" % (parent_path, node.tag)

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
            self._walk_nodes(child, path, nodes, depth + 1)

    @api.model
    def get_addable_fields(self, model_name, view_id=None):
        """Fields on the model that are not already in the combined arch."""
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        model = self.env[model_name]
        present = set()
        if view_id:
            view = self.env["ir.ui.view"].browse(view_id).exists()
            if view:
                arch = etree.fromstring(view.get_combined_arch().encode())
                present = {
                    node.get("name") for node in arch.iter("field") if node.get("name")
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

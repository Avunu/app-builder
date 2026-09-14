# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The package's menus as a record pane: a tree, not a list.

A menu is scoped to the package rather than to a model: an app is a root
menu with an icon, a submenu opens a model's views, and both are written
to ``views/menus.xml``. The rows come back in tree order with a depth,
so the pane indents them; the parents another module defines are shown
greyed above the package's own, since that is where a person looks for
them, and they are not editable here.

An action goes with the menu that opens it when nothing else does: a
submenu made from here is a menu and a list+form action, created and
removed as one.
"""

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.app_builder_base.tools import compat
from odoo.addons.app_builder_base.tools.catalogue import Row, Section

DEFAULT_ICON = "fa fa-cubes,#875A7B,#FFFFFF"


class StudioMenu(models.AbstractModel):
    _name = "studio.menu"
    _inherit = ["studio.record.surface"]
    _description = "Studio Menu Surface"

    _surface_model = "ir.ui.menu"
    _surface_model_field = None
    _surface_virtual = ("groups", "opens_model")
    _surface_sections = (
        Section(
            "menu",
            "Menu",
            (
                Row(name="name", label="Name", type="text", required=True),
                Row(
                    name="parent_id",
                    label="Under",
                    type="many2one",
                    comodel="ir.ui.menu",
                    help="Empty: an app of its own in the apps menu.",
                ),
                Row(
                    name="sequence",
                    label="Position",
                    type="integer",
                    help="Lower comes first among the menus beside it.",
                ),
                Row(
                    name="groups",
                    label="Visible to",
                    type="many2many",
                    comodel="res.groups",
                    help="Empty: everyone who can see the parent.",
                ),
                Row(
                    name="web_icon",
                    label="Icon",
                    type="text",
                    help="For an app: `module,path/to/icon.png` or "
                    "`fa fa-name,#background,#color`.",
                ),
                Row(name="active", label="Active", type="toggle"),
            ),
        ),
        Section(
            "opens",
            "Opens",
            (
                Row(name="action", label="Action", type="readonly"),
                Row(
                    name="opens_model",
                    label="Model",
                    type="many2one",
                    comodel="ir.model",
                    help="Changing it makes a new list+form action for that "
                    "model; the old action stays if another menu opens it.",
                ),
            ),
        ),
    )
    _surface_templates = (
        (
            "submenu",
            "Submenu",
            "Opens a model's list and form under an existing menu.",
            {},
            ("name", "parent_id", "opens_model"),
        ),
        (
            "app",
            "App",
            "A root menu with an icon in the apps menu.",
            {"web_icon": DEFAULT_ICON},
            ("name", "opens_model"),
        ),
    )

    # -- rows ------------------------------------------------------------------

    @api.model
    def _subject_model(self, record):
        return ""

    @api.model
    def _subject_vals(self, model_name):
        return {}

    @api.model
    def _groups_field(self):
        return compat.groups_field(self.env, "ir.ui.menu")

    @api.model
    def rows(self, model_name, package_id=None, **kwargs):
        """The package's menus in tree order, under the foreign parents
        they hang from; ``model_name`` marks the ones that open it."""
        self._assert_studio_user()
        package = self.env["studio.package"]._chosen(package_id)
        Menu = self._menus()
        owned = Menu
        if package:
            data = (
                self.env["ir.model.data"]
                .sudo()
                .search([("module", "=", package.name), ("model", "=", "ir.ui.menu")])
            )
            owned = Menu.browse(data.mapped("res_id")).exists()
        # The package's menus, the parents they hang from, and whatever
        # else sits beside them under those parents -- greyed, so the order
        # a person sees in the menu bar is the order shown here.
        shown = owned
        if owned:
            shown |= Menu.search([("parent_id", "in", owned.ids)])
        for menu in owned:
            parent = menu.parent_id
            while parent and parent not in shown:
                shown |= parent
                parent = parent.parent_id
        by_parent = {}
        for menu in shown:
            key = menu.parent_id.id if menu.parent_id in shown else 0
            by_parent.setdefault(key, []).append(menu)
        rows = []

        def walk(parent_id, depth):
            for menu in sorted(
                by_parent.get(parent_id, []), key=lambda m: (m.sequence, m.id)
            ):
                row = self._row(menu, package)
                row["depth"] = depth
                row["parent_id"] = (
                    menu.parent_id.id if menu.parent_id in shown else False
                )
                row["opens"] = self._opens(menu)
                row["highlight"] = bool(model_name) and row["opens"] == model_name
                rows.append(row)
                walk(menu.id, depth + 1)

        walk(0, 0)
        return rows

    @api.model
    def _row(self, record, package):
        row = super()._row(record, package)
        # display_name is the whole path; the tree shows the path already.
        row["title"] = record.name
        return row

    @api.model
    def _menus(self):
        """Every menu, not only the ones the menu bar would show: a folder
        with no children yet is hidden from an ordinary search."""
        return self._model().with_context(
            active_test=False, **{"ir.ui.menu.full_list": True}
        )

    @api.model
    def _opens(self, menu):
        action = menu.action
        if action and action._name == "ir.actions.act_window":
            return action.res_model
        return ""

    @api.model
    def _sentence(self, record):
        action = record.action
        if not action:
            return _("Opens nothing: a folder for the menus under it.")
        if action._name == "ir.actions.act_window":
            return _(
                "Opens %(model)s · %(views)s",
                model=action.res_model,
                views=action.view_mode,
            )
        return _("Opens %s", action.display_name)

    @api.model
    def _foreign_reason(self, record, module):
        return _(
            "Defined by %s. Shown here so you can see where yours sit; edit "
            "it in that module.",
            module,
        )

    # -- values --------------------------------------------------------------

    @api.model
    def _values(self, record):
        values = super()._values(record)
        values["action"] = (
            "%s (%s)" % (record.action.display_name, record.action._name)
            if record.action
            else ""
        )
        return values

    @api.model
    def _virtual_value(self, record, name):
        if name == "groups":
            return [
                {"id": group.id, "display_name": group.full_name}
                for group in record[self._groups_field()]
            ]
        if name == "opens_model":
            model_name = self._opens(record)
            ir_model = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", model_name)], limit=1)
                if model_name
                else None
            )
            return (
                {"id": ir_model.id, "display_name": ir_model.display_name}
                if ir_model
                else False
            )
        return super()._virtual_value(record, name)

    @api.model
    def _coerce_virtual(self, row, value, model_name):
        if row.name == "groups":
            ids = [v.get("id") if isinstance(v, dict) else v for v in (value or [])]
            ids = [int(i) for i in ids if i]
            self._assert_in_source(row, ids)
            return {self._groups_field(): [(6, 0, ids)]}
        if row.name == "opens_model":
            # Turned into an action after the write / on create (see below).
            if isinstance(value, dict):
                value = value.get("id")
            return {"_opens_model_id": int(value) if value else False}
        return super()._coerce_virtual(row, value, model_name)

    @api.model
    def _coerce(self, model_name, values, creating=False):
        vals = super()._coerce(model_name, values, creating=creating)
        # Not a field: popped by the caller and turned into an action.
        vals["_opens"] = vals.pop("_opens_model_id", None)
        return vals

    # -- the action a menu opens ----------------------------------------------

    @api.model
    def _make_action(self, name, model_id, package):
        ir_model = self.env["ir.model"].sudo().browse(model_id).exists()
        if not ir_model:
            raise UserError(_("Say which model the menu opens."))
        action = (
            self.env["ir.actions.act_window"]
            .sudo()
            .with_context(studio_package_id=package.id)
            .create(
                {
                    "name": name,
                    "res_model": ir_model.model,
                    "view_mode": "list,form",
                }
            )
        )
        package.studio_capture(action, write_files=False)
        return action

    @api.model
    def _point_at(self, menu, model_id, package):
        """Make the menu open a new list+form action on ``model_id``; the old
        action goes when nothing else opens it."""
        old = menu.action
        if (
            old
            and old._name == "ir.actions.act_window"
            and old.res_model == (self.env["ir.model"].sudo().browse(model_id).model)
        ):
            return
        action = self._make_action(menu.name, model_id, package)
        menu.write({"action": "ir.actions.act_window,%d" % action.id})
        self._drop_orphan_action(old, package)

    @api.model
    def _drop_orphan_action(self, action, package):
        if not action or action._name != "ir.actions.act_window":
            return
        others = self._menus().search(
            [("action", "=", "ir.actions.act_window,%d" % action.id)]
        )
        if others:
            return
        owner = self._owner(action)
        if owner["package"] == package:
            action.unlink()

    # -- writing -----------------------------------------------------------------

    @api.model
    def write_record(self, record_id, values, package_id=None):
        self._assert_studio_manager()
        record = self._record(record_id)
        package = self.env["studio.package"]._chosen(package_id)
        owner = self._assert_editable(record, package)
        vals = self._coerce("", values)
        opens = vals.pop("_opens", None)
        if vals:
            record.write(vals)
        if opens:
            self._point_at(record, opens, owner)
        if vals or opens:
            owner.studio_capture(record)
        return self._row(record, owner)

    @api.model
    def create_record(self, model_name, package_id, values, template=None):
        self._assert_studio_manager()
        package = self.env["studio.package"]._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to record this in first."))
        package._assert_writable()
        merged = {}
        if template:
            merged.update(self._template_values(template, model_name, values))
        merged.update(values or {})
        vals = self._coerce("", merged, creating=True)
        opens = vals.pop("_opens", None)
        if template == "submenu" and not vals.get("parent_id"):
            raise UserError(_("Say which menu the submenu goes under."))
        if template == "app" and vals.get("parent_id"):
            vals.pop("parent_id")
        vals.setdefault("active", True)
        if "sequence" not in vals:
            siblings = self._menus().search(
                [("parent_id", "=", vals.get("parent_id") or False)]
            )
            vals["sequence"] = max(siblings.mapped("sequence") or [0]) + 10
        if opens:
            action = self._make_action(vals["name"], opens, package)
            vals["action"] = "ir.actions.act_window,%d" % action.id
        menu = self._model().with_context(studio_package_id=package.id).create(vals)
        package.studio_capture(menu)
        return self._row(menu, package)

    @api.model
    def _before_remove(self, record, package, force=False):
        # The children go with the parent (Odoo cascades), and so does the
        # action when nothing else opens it -- after the menu is gone.
        return

    @api.model
    def remove_record(self, record_id, package_id=None, force=False):
        record = self._record(record_id)
        action = record.action
        package = self.env["studio.package"]._chosen(package_id)
        result = super().remove_record(record_id, package_id, force=force)
        self._drop_orphan_action(action, package)
        if package:
            package.action_write_files()
        return result

    @api.model
    def move(self, menu_id, parent_id=None, before_id=None, package_id=None):
        """Put ``menu_id`` under ``parent_id`` (or at the root) before
        ``before_id``, or last; the owned siblings are renumbered 10/20/30
        and the others keep their numbers."""
        self._assert_studio_manager()
        menu = self._record(menu_id)
        package = self.env["studio.package"]._chosen(package_id)
        owner = self._assert_editable(menu, package)
        parent = (
            self._model().browse(parent_id).exists() if parent_id else self._model()
        )
        if parent and parent.parent_path.startswith(menu.parent_path):
            raise UserError(_("A menu cannot go under itself."))
        if parent:
            self._assert_in_source(self._rows_by_name()["parent_id"], [parent.id])
        if menu.parent_id != parent:
            menu.write({"parent_id": parent.id or False})
        siblings = [
            s
            for s in self._menus().search(
                [("parent_id", "=", parent.id or False)], order="sequence, id"
            )
            if s != menu
        ]
        if before_id:
            index = next(
                (i for i, s in enumerate(siblings) if s.id == before_id), len(siblings)
            )
            siblings.insert(index, menu)
        else:
            siblings.append(menu)
        # Renumber what this package owns; a foreign sibling keeps its number
        # and its place is respected by numbering around it.
        sequence = 0
        touched = self._model()
        for entry in siblings:
            if self._owner(entry)["package"] == owner:
                sequence = sequence // 10 * 10 + 10
                if entry.sequence != sequence:
                    entry.write({"sequence": sequence})
                touched |= entry
            else:
                sequence = max(sequence, entry.sequence)
        owner.studio_capture(touched | menu)
        return [s.id for s in siblings]

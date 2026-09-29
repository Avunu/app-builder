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

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_actions import IrActionsActWindow
from odoo.addons.base.models.ir_model import IrModel, IrModelData
from odoo.addons.app_builder_base.models.studio_package import StudioPackage
from odoo.addons.app_builder_base.models.studio_record_surface import RecordRowJSON
from odoo.addons.app_builder_base.tools import compat, typed
from odoo.addons.app_builder_base.tools.catalogue import Row, Section
from odoo.addons.app_builder_base.tools.i18n import _

if TYPE_CHECKING:
    # Only for annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime -- the same bargain
    # `studio_record_surface.py`'s own `TYPE_CHECKING` block makes.
    # `IrActionsActWindow`/`IrModel`/`IrModelData`/`StudioPackage`/
    # `RecordRowJSON` are real, top-level imports instead (above):
    # `typed.model()` reads `cls._name` at *runtime*, and `RecordRowJSON` is
    # subclassed below (a real class statement, not a bare annotation).
    from odoo.models import BaseModel

    from odoo.addons.base.models.ir_ui_menu import IrUiMenu
    from odoo.addons.app_builder_base.models.studio_record_surface import (
        StudioRecordSurface,
    )

DEFAULT_ICON = "fa fa-cubes,#875A7B,#FFFFFF"


class MenuRowJSON(RecordRowJSON):
    """One row of ``rows()``: the base's eleven keys plus tree position and
    what the menu opens (``rows()``'s own ``walk()``, matching ``wire.ts``'s
    optional ``depth``/``parent_id`` extensions to ``RecordRowJSON``)."""

    depth: int
    parent_id: int | Literal[False]
    opens: str
    highlight: bool


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
    _surface_templates: tuple[
        tuple[str, str, str, dict[str, object], tuple[str, ...]], ...
    ] = (
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
    def _subject_model(self, record: BaseModel) -> str:
        return ""

    @api.model
    def _subject_vals(self, model_name: str) -> dict[str, object]:
        return {}

    @api.model
    def _groups_field(self) -> str:
        return compat.groups_field(self.env, "ir.ui.menu")

    @api.model
    def rows(
        self, model_name: str, package_id: int | None = None, **kwargs: object
    ) -> list[MenuRowJSON]:
        """The package's menus in tree order, under the foreign parents
        they hang from; ``model_name`` marks the ones that open it."""
        typed.security(self)._assert_studio_user()
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        Menu = self._menus()
        owned = Menu
        if package:
            data = (
                typed.model(self.env, IrModelData)
                .sudo()
                .search([("module", "=", package.name), ("model", "=", "ir.ui.menu")])
            )
            owned = Menu.browse(cast("list[int]", data.mapped("res_id"))).exists()
        # The package's menus, the parents they hang from, and whatever
        # else sits beside them under those parents -- greyed, so the order
        # a person sees in the menu bar is the order shown here.
        shown = owned
        if owned:
            shown |= Menu.search([("parent_id", "in", owned.ids)])
        for menu in owned:
            parent = cast("IrUiMenu", menu.parent_id)
            while parent and parent not in shown:
                shown |= parent
                parent = cast("IrUiMenu", parent.parent_id)
        by_parent: dict[int | Literal[False], list[IrUiMenu]] = {}
        for menu in shown:
            # `.id` is `int | NewId | Literal[False]` (`odoo.api.IdType`,
            # plus the field's own `Literal[False]` for an unset many2one);
            # every menu reachable here is a persisted record, so only the
            # `NewId` half of that union is cast away -- `Literal[False]`
            # stays, the same honest fallback `row["parent_id"]` below uses.
            key = (
                cast("int | Literal[False]", cast("IrUiMenu", menu.parent_id).id)
                if menu.parent_id in shown
                else 0
            )
            by_parent.setdefault(key, []).append(menu)
        rows: list[MenuRowJSON] = []

        def walk(parent_id: int | Literal[False], depth: int) -> None:
            siblings: list[IrUiMenu] = by_parent.get(parent_id, [])
            for menu in sorted(siblings, key=lambda m: (m.sequence, m.id)):
                row = cast("MenuRowJSON", self._row(menu, package))
                row["depth"] = depth
                row["parent_id"] = (
                    cast("int | Literal[False]", cast("IrUiMenu", menu.parent_id).id)
                    if menu.parent_id in shown
                    else False
                )
                row["opens"] = self._opens(menu)
                row["highlight"] = bool(model_name) and row["opens"] == model_name
                rows.append(row)
                walk(cast("int | Literal[False]", menu.id), depth + 1)

        walk(0, 0)
        return rows

    @api.model
    def _row(self, record: BaseModel, package: StudioPackage) -> RecordRowJSON:
        row = cast("StudioRecordSurface", super())._row(record, package)
        # display_name is the whole path; the tree shows the path already.
        # `name` is `required=True` on `ir.ui.menu`, the same true-by-
        # construction idiom `_subject_model`'s own `.model` cast uses
        # (`studio_record_surface.py`).
        row["title"] = cast("str", cast("IrUiMenu", record).name)
        return row

    @api.model
    def _menus(self) -> IrUiMenu:
        """Every menu, not only the ones the menu bar would show: a folder
        with no children yet is hidden from an ordinary search."""
        # `_model` lives on `studio.record.surface` (`studio_record_surface
        # .py`, a *different* file's class body for the same `_inherit`-
        # composed model) -- invisible to pyright on plain `self` the same
        # way `_assert_studio_user` is on `studio.security.mixin` (rule 6,
        # `typed.py`'s own docstring).
        return cast(
            "IrUiMenu",
            cast("StudioRecordSurface", self)
            ._model()
            .with_context(active_test=False, **{"ir.ui.menu.full_list": True}),
        )

    @api.model
    def _opens(self, menu: IrUiMenu) -> str:
        action = cast("IrActionsActWindow", menu.action)
        if action and action._name == "ir.actions.act_window":
            # `res_model` is `required=True` on `ir.actions.act_window`, the
            # same true-by-construction idiom as `_row`'s own `.name` cast.
            return cast("str", action.res_model)
        return ""

    @api.model
    def _sentence(self, record: BaseModel) -> str:
        action = cast("IrActionsActWindow", cast("IrUiMenu", record).action)
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
    def _foreign_reason(self, record: BaseModel, module: str) -> str:
        return _(
            "Defined by %s. Shown here so you can see where yours sit; edit "
            "it in that module.",
            module,
        )

    # -- values --------------------------------------------------------------

    @api.model
    def _values(self, record: BaseModel) -> dict[str, object]:
        values = cast("StudioRecordSurface", super())._values(record)
        action = cast("BaseModel", cast("IrUiMenu", record).action)
        values["action"] = (
            "%s (%s)" % (action.display_name, action._name) if action else ""
        )
        return values

    @api.model
    def _virtual_value(self, record: BaseModel, name: str) -> object:
        if name == "groups":
            return [
                {"id": group.id, "display_name": group.full_name}
                for group in record[self._groups_field()]
            ]
        if name == "opens_model":
            model_name = self._opens(cast("IrUiMenu", record))
            ir_model = (
                typed.model(self.env, IrModel)
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
        return cast("StudioRecordSurface", super())._virtual_value(record, name)

    @api.model
    def _coerce_virtual(
        self, row: Row, value: object, model_name: str
    ) -> dict[str, object]:
        if row.name == "groups":
            raw_ids: list[int | None] = [
                v.get("id") if isinstance(v, dict) else v
                for v in cast("list[dict[str, int] | int]", value or [])
            ]
            ids = [int(i) for i in raw_ids if i]
            # `_assert_in_source` lives on `studio.record.surface` -- same
            # rule 6 gap as `_model` above.
            cast("StudioRecordSurface", self)._assert_in_source(row, ids)
            return {self._groups_field(): [(6, 0, ids)]}
        if row.name == "opens_model":
            # Turned into an action after the write / on create (see below).
            if isinstance(value, dict):
                value = cast("dict[str, object]", value).get("id")
            return {"_opens_model_id": int(cast("Any", value)) if value else False}
        return cast("StudioRecordSurface", super())._coerce_virtual(
            row, value, model_name
        )

    @api.model
    def _coerce(
        self, model_name: str, values: dict[str, object], creating: bool = False
    ) -> dict[str, object]:
        vals = cast("StudioRecordSurface", super())._coerce(
            model_name, values, creating=creating
        )
        # Not a field: popped by the caller and turned into an action.
        vals["_opens"] = vals.pop("_opens_model_id", None)
        return vals

    # -- the action a menu opens ----------------------------------------------

    @api.model
    def _make_action(
        self, name: str, model_id: int, package: StudioPackage
    ) -> IrActionsActWindow:
        ir_model = typed.model(self.env, IrModel).sudo().browse(model_id).exists()
        if not ir_model:
            raise UserError(_("Say which model the menu opens."))
        vals: dict[str, object] = {
            "name": name,
            "res_model": ir_model.model,
            "view_mode": "list,form",
        }
        action = (
            typed.model(self.env, IrActionsActWindow)
            .sudo()
            .with_context(studio_package_id=package.id)
            .create(vals)  # pyright: ignore[reportArgumentType] -- see `create_record`'s own comment (`studio_record_surface.py`).
        )
        package.studio_capture(action, write_files=False)
        return action

    @api.model
    def _point_at(self, menu: BaseModel, model_id: int, package: StudioPackage) -> None:
        """Make the menu open a new list+form action on ``model_id``; the old
        action goes when nothing else opens it."""
        old = cast("IrActionsActWindow", cast("IrUiMenu", menu).action)
        if (
            old
            and old._name == "ir.actions.act_window"
            and old.res_model
            == (typed.model(self.env, IrModel).sudo().browse(model_id).model)
        ):
            return
        action = self._make_action(
            cast("str", cast("IrUiMenu", menu).name), model_id, package
        )
        menu.write({"action": "ir.actions.act_window,%d" % action.id})
        self._drop_orphan_action(old, package)

    @api.model
    def _drop_orphan_action(self, action: BaseModel, package: StudioPackage) -> None:
        if not action or action._name != "ir.actions.act_window":
            return
        others = self._menus().search(
            [("action", "=", "ir.actions.act_window,%d" % action.id)]
        )
        if others:
            return
        # `_owner` lives on `studio.record.surface` -- same rule 6 gap as
        # `_model`/`_assert_in_source` above.
        owner = cast("StudioRecordSurface", self)._owner(action)
        if owner["package"] == package:
            action.unlink()

    # -- writing -----------------------------------------------------------------

    @api.model
    def write_record(
        self, record_id: int, values: dict[str, object], package_id: int | None = None
    ) -> RecordRowJSON:
        typed.security(self)._assert_studio_manager()
        # `_record`/`_assert_editable` live on `studio.record.surface` --
        # same rule 6 gap as `_model`/`_assert_in_source`/`_owner` above.
        record = cast("StudioRecordSurface", self)._record(record_id)
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        owner = cast("StudioRecordSurface", self)._assert_editable(record, package)
        vals = self._coerce("", values)
        opens = vals.pop("_opens", None)
        if vals:
            record.write(vals)
        if opens:
            self._point_at(record, cast("int", opens), owner)
        if vals or opens:
            owner.studio_capture(record)
        return self._row(record, owner)

    @api.model
    def create_record(
        self,
        model_name: str,
        package_id: int | None,
        values: dict[str, object] | None,
        template: str | None = None,
    ) -> RecordRowJSON:
        typed.security(self)._assert_studio_manager()
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        if not package:
            raise UserError(_("Choose a package to record this in first."))
        package._assert_writable()
        merged: dict[str, object] = {}
        if template:
            # `_template_values` lives on `studio.record.surface` -- same
            # rule 6 gap as `_model`/`_record`/`_assert_editable` above.
            merged.update(
                cast("StudioRecordSurface", self)._template_values(
                    template, model_name, values
                )
            )
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
            vals["sequence"] = (
                max(cast("list[int]", siblings.mapped("sequence")) or [0]) + 10
            )
        if opens:
            action = self._make_action(
                cast("str", vals["name"]), cast("int", opens), package
            )
            vals["action"] = "ir.actions.act_window,%d" % action.id
        menu = (
            cast("StudioRecordSurface", self)
            ._model()
            .with_context(studio_package_id=package.id)
            .create(vals)  # pyright: ignore[reportArgumentType] -- see `create_record`'s own comment (`studio_record_surface.py`).
        )
        package.studio_capture(menu)
        return self._row(menu, package)

    @api.model
    def _before_remove(
        self, record: BaseModel, package: StudioPackage, force: bool = False
    ) -> None:
        # The children go with the parent (Odoo cascades), and so does the
        # action when nothing else opens it -- after the menu is gone.
        return

    @api.model
    def remove_record(
        self, record_id: int, package_id: int | None = None, force: bool = False
    ) -> bool:
        record = cast("StudioRecordSurface", self)._record(record_id)
        action = cast("BaseModel", cast("IrUiMenu", record).action)
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        result = cast("StudioRecordSurface", super()).remove_record(
            record_id, package_id, force=force
        )
        self._drop_orphan_action(action, package)
        if package:
            package.action_write_files()
        return result

    @api.model
    def move(
        self,
        menu_id: int,
        parent_id: int | None = None,
        before_id: int | None = None,
        package_id: int | None = None,
    ) -> list[int]:
        """Put ``menu_id`` under ``parent_id`` (or at the root) before
        ``before_id``, or last; the owned siblings are renumbered 10/20/30
        and the others keep their numbers."""
        typed.security(self)._assert_studio_manager()
        # `_record`/`_assert_editable` live on `studio.record.surface` --
        # same rule 6 gap as `_model`/`_assert_in_source`/`_owner` above.
        menu = cast("IrUiMenu", cast("StudioRecordSurface", self)._record(menu_id))
        package = typed.model(self.env, StudioPackage)._chosen(package_id)
        owner = cast("StudioRecordSurface", self)._assert_editable(menu, package)
        parent = cast(
            "IrUiMenu",
            cast("StudioRecordSurface", self)._model().browse(parent_id).exists()
            if parent_id
            else cast("StudioRecordSurface", self)._model(),
        )
        # `parent_path` is `_parent_store`-computed, always set on a
        # persisted `ir.ui.menu` -- the same true-by-construction idiom as
        # `_row`'s own `.name` cast above.
        if parent and cast("str", parent.parent_path).startswith(
            cast("str", menu.parent_path)
        ):
            raise UserError(_("A menu cannot go under itself."))
        if parent:
            # `_rows_by_name` lives on `studio.record.surface` -- same rule
            # 6 gap as `_model`/`_record`/`_assert_editable` above.
            cast("StudioRecordSurface", self)._assert_in_source(
                cast("StudioRecordSurface", self)._rows_by_name()["parent_id"],
                [cast("int", parent.id)],
            )
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
        touched = cast("IrUiMenu", cast("StudioRecordSurface", self)._model())
        for entry in siblings:
            if cast("StudioRecordSurface", self)._owner(entry)["package"] == owner:
                sequence = sequence // 10 * 10 + 10
                if entry.sequence != sequence:
                    entry.write({"sequence": sequence})
                touched |= entry
            else:
                sequence = max(sequence, entry.sequence)
        owner.studio_capture(touched | menu)
        return [cast("int", s.id) for s in siblings]

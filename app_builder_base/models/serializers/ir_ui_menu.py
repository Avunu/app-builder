# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Serializer for ``ir.ui.menu``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias, cast

if TYPE_CHECKING:
    # Only used inside annotations (`from __future__ import annotations`
    # defers all of them to strings), never at runtime -- same bargain
    # `studio_serializer.py`'s own `TYPE_CHECKING`-guarded imports make.
    from collections.abc import Callable

    from odoo.models import BaseModel

    from odoo.addons.base.models.ir_ui_menu import IrUiMenu

# lxml ships no type stubs in this environment (a compiled extension with no
# `.pyi`/`py.typed` marker; `lxml-stubs`/`types-lxml` is not an installed
# dependency here), so pyright cannot resolve `etree` as an exported member
# of `lxml` at all -- confirmed directly, `from lxml import etree` alone
# reports both `reportMissingTypeStubs` (on `lxml`) and
# `reportAttributeAccessIssue` ("etree" is unknown import symbol, on
# `etree`). Ignored narrowly on each name rather than rewriting the import
# (e.g. `import lxml.etree as etree`), which trades this gap for a different
# one: ruff's own `PLR0402` auto-fixes that form straight back to `from lxml
# import etree` (`fix = true` project-wide), silently reintroducing the
# failure. Same pattern as `studio_serializer.py`/`xml_writer.py`/
# `placement.py`/`scaffold.py`.
from lxml import (  # pyright: ignore[reportMissingTypeStubs]
    etree,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)

from odoo import api, models

from ...tools.lxml_types import LxmlElement
from ..studio_serializer import SEQ_MENU, StudioSerializer

Element: TypeAlias = LxmlElement

# `etree.Element` is the one constructor this module calls; grabbing it once,
# behind a single documented cast, keeps the "Unknown member of an unstubbed
# module" gap to two lines instead of a `# pyright: ignore` at the one call
# site. Same idiom as `studio_serializer.py`'s own `_element` wrapper.
_element_raw = etree.Element  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
_element: Callable[..., Element] = cast("Callable[..., Element]", _element_raw)


class IrUiMenuSerializer(models.AbstractModel):
    _name = "studio.serializer.ir.ui.menu"
    _inherit = "studio.serializer"
    _description = "Studio Serializer for ir.ui.menu"

    _studio_model = "ir.ui.menu"
    _studio_sequence = SEQ_MENU
    _studio_dir = "views"
    _studio_suffix = "_views"
    _studio_fields = (
        "name",
        "parent_id",
        "action",
        "sequence",
        "groups_id",
        "web_icon",
        "active",
    )
    _studio_ignored = (
        # The other end of parent_id, which each child emits itself.
        "child_id",
        # Internal hierarchy cache, maintained by the ORM from parent_id.
        "parent_path",
        # Decoded from web_icon on write, so it follows the field we do emit.
        "web_icon_data",
    )

    @api.model
    def _group_model(self, record: BaseModel) -> str | None:
        """Group a menu with the model its action opens.

        A menu with no action is a container (an app root or a submenu header)
        and has no model of its own, so it goes to views/menus.xml.
        """
        # `record` is genuinely an `ir.ui.menu` recordset here (this
        # serializer is only ever dispatched for that model), but the
        # overridden method's own declared parameter type is `BaseModel` --
        # see TYPING.md's house convention on not narrowing `record` in a
        # subclass override. Cast at the read site instead, same idiom as
        # `studio_package.py`'s `cast("IrModel", record).model`.
        #
        # `action` is declared `fields.Reference(...)` with no class-body
        # annotation, and `Reference` inherits `Selection`'s own declared
        # read type (`str | Literal[False]`, `odoo/fields.py`) rather than
        # the real recordset `Reference.convert_to_record` actually returns
        # -- a genuine, pre-existing vendor-stub inaccuracy, not introduced
        # by this migration. Cast to `BaseModel` at the read site, the same
        # "declared type too abstract/wrong for what is really there at
        # runtime" fix already established for `Environment.cr`.
        action = cast("BaseModel", cast("IrUiMenu", record).action)
        # `res_model`/`model_id` each exist on only *some* of the several
        # concrete `ir.actions.*` models `action` may resolve to at runtime
        # (`res_model` on `ir.actions.act_window`; `model_id` on, e.g.,
        # `ir.actions.report`) -- there is no common declared base for either
        # attribute to type `action` as here, the same "genuinely
        # dynamically-dispatched, no shared contract" shape already
        # established for `studio_package.py`'s own `cast("Any",
        # serializer)._csv_row(...)`. The `_name` check and the `hasattr`
        # guard below are the real runtime checks; `Any` only stands in for
        # the attribute's own static type once they have passed.
        if action and action._name == "ir.actions.act_window":
            return cast("str | None", cast("Any", action).res_model)
        if action and hasattr(action, "model_id") and cast("Any", action).model_id:
            return cast("str", cast("Any", action).model_id.model)
        return "menus"

    @api.model
    def _target_file(self, record: BaseModel) -> str:
        """All menus in one file.

        `_sort_key` puts parents before children, but that only orders records
        *within* a file. Grouping menus by the model their action opens scatters
        a menu tree across several files, and the manifest then loads a child
        before its parent -- an unresolvable ``parent_id`` ref on a fresh
        install. One file keeps the ordering guarantee meaningful.

        studio.package._order_data_files gives this file a rank just after the
        other views, because a menu refs an action those files define.
        """
        return "views/menus.xml"

    @api.model
    def _field_node(self, record: BaseModel, fname: str) -> Element | None:
        if fname == "action":
            # 'action' is a reference field storing 'model,id'. Emit it as a
            # plain ref to the action's xmlid, which is what convert.py expects
            # and what a hand-written menuitem produces.
            action = cast("BaseModel", cast("IrUiMenu", record).action)
            if not action:
                return None
            node = _element("field")
            node.set("name", "action")
            # `_ref_of` lives on `StudioSerializer`, composed onto this class
            # only at the Odoo registry level (`_inherit = "studio.serializer"`
            # above) -- never a real Python base class, so it is invisible to
            # pyright on `self` here. Same "_inherit-mixin-invisible-to-pyright"
            # shape `typed.security()` already fixes for
            # `studio.security.mixin`; no shared helper exists for this mixin,
            # so cast inline instead.
            serializer = cast("StudioSerializer", self)
            node.set("ref", serializer._ref_of(action, source=self._studio_model))
            return node
        # Same mixin-invisibility as `_ref_of` above, on the `super()` proxy
        # this time rather than on `self` -- `cast` only changes what pyright
        # believes the proxy's type is, not the proxy object itself, so the
        # dispatch this performs at runtime (up through the *real*,
        # registry-composed MRO, landing on `StudioSerializer._field_node`)
        # is exactly what the original, untyped call already did.
        return cast("StudioSerializer", super())._field_node(record, fname)

    @api.model
    def _sort_key(self, record: BaseModel, xmlid: str) -> tuple[int, int, int, str]:
        # Parents before children: a child's parent_id ref must already resolve.
        depth = 0
        # `parent_id` is a typed relational field (`Many2one`, comodel
        # `ir.ui.menu`): per TYPING.md's house convention, its *declaration*
        # keeps no LHS annotation and each *read* is cast instead, since
        # `_Relational.__get__` carries no return annotation of its own.
        node = cast("IrUiMenu | None", cast("IrUiMenu", record).parent_id)
        while node and depth < 32:
            depth += 1
            node = cast("IrUiMenu | None", node.parent_id)
        return (self._studio_sequence, depth, cast("IrUiMenu", record).sequence, xmlid)

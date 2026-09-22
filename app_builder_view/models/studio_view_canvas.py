# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""The canvas: the real view, rendered, with every node named.

The console shows the view as Odoo renders it -- the same compiler, the same
widgets, a real record -- and lets the user drop things onto it. For that
the browser needs two things it cannot make itself: the arch with a token on
every node (``canvas_stamp``), and the field descriptions the view compiler
expects, which ``get_views`` would supply for the *unstamped* view.

So the canvas does what ``get_view`` does, step by step, on our own copy of
the arch: postprocess it as the view's own model, drop what the user's groups
hide, describe the fields -- and skips the one thing ``get_view`` adds, the
registry-wide cache. The stamped arch must never be cached: the cache is
keyed on the view and the language, not on who asked or why, and a token-laden
arch in it would be served to every user of that view until the next write.
Nothing here writes, and ``test_canvas_is_pure`` holds it to that.

The tree stamped is the *combined* arch, not ``_get_view()``'s: some models
patch their arch at read time (``analytic_line.py``, ``account_move.py``),
which would shift every ordinal against the tree the editor edits. What the
canvas cannot show is stated as a known limit rather than worked around.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypedDict, cast

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from typing_extensions import NotRequired

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_model import IrModelFields
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.models.studio_model_draft import StudioModelDraft
from odoo.addons.app_builder_base.models.studio_package import StudioPackage
from odoo.addons.app_builder_base.tools import typed

from ..tools import canvas_stamp, manualfield
from .studio_view_edit import StudioViewEdit
from .studio_view_editor import FieldInfoJSON

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.models import BaseModel

    from odoo.addons.base.models.ir_model import IrModelSelection
    from odoo.addons.base.models.ir_ui_view import Model as IrUiViewModelMixin
    from odoo.addons.app_builder_base.models.studio_owned_mixin import StudioOwnedMixin
    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement

    # `app_builder_view`'s own pure `_inherit` extension of `studio.model
    # .draft` (`studio_model_draft.py`, this same addon), aliased against
    # the real base already imported above (`StudioModelDraft`, from
    # `app_builder_base`) -- same rule-7 collision. `_pending_anchored` is
    # declared only there, now real (this replaces a forward-declared
    # `_DraftWithPendingAnchored` Protocol this file used before that
    # sibling was converted, the same reconciliation `studio_view_editor
    # .py`'s own `_DraftHandle` Protocol got once its real target existed).
    from .studio_model_draft import StudioModelDraft as StudioModelDraftView

    # This file is a pure `_inherit = "studio.view.editor"` extension, the
    # same `_name` `studio_view_editor.py`'s own `StudioViewEditor` declares
    # -- a real, *different* Python class the registry merges with this
    # file's own at runtime, so it is aliased on import rather than
    # colliding with this file's own class of the identical name (rule 7,
    # precedent: `studio_package_model.py`'s own `StudioPackageModelBase`).
    # Cast to it wherever this file calls a method the real base declares
    # (`arch_version`, `_resolve_xpath`, `_find_descriptor`, ...) and this
    # file does not -- invisible to pyright on a bare `self` otherwise.
    from .studio_view_editor import CanvasJSON, NodeExpectationJSON
    from .studio_view_editor import StudioViewEditor as StudioViewEditorBase


# -- wire types -----------------------------------------------------------
#
# Cross-checked against `app_builder_view/static/src/console/wire.ts` and
# `.../console/types.ts`, the same read-only references
# `studio_view_editor.py`'s own wire types are checked against.


class CanvasFieldInfoJSON(FieldInfoJSON):
    """``_field_info``'s own answer (``studio_view_editor.py``) plus where
    the field came from -- ``_canvas_field_info``'s own return, consumed by
    ``canvas``/``describe_node``. A real, non-``TYPE_CHECKING`` import of
    the parent TypedDict (rule 9): ``class X(Y):`` executes at import time."""

    origin: Literal["manual", "core"]


class CanvasSourceJSON(TypedDict):
    """``_canvas_source()``'s own return: the arch the console shows as
    "what the studio wrote", for the View tab."""

    view_id: int
    name: str
    owned: bool
    arch: str


class FieldSelectionOptionJSON(TypedDict):
    """One row of ``_field_definition()``'s own ``values["selection"]``."""

    value: str
    label: str
    sequence: int


class FieldDefinitionValuesJSON(TypedDict):
    """``_field_definition()``'s own ``values`` key: the model-level facts
    of a field the properties panel can show or edit."""

    field_description: str
    help: str
    required: bool
    readonly: bool
    index: bool
    translate: bool
    ttype: str
    relation: str | Literal[False]
    selection: NotRequired[list[FieldSelectionOptionJSON]]


class FieldDefinitionJSON(TypedDict):
    """``_field_definition()``'s whole return, consumed by
    ``describe_node``'s own ``definition`` key."""

    origin: Literal["manual", "core"]
    editable: list[str]
    values: FieldDefinitionValuesJSON


class _DescribeNodeNotFoundJSON(TypedDict):
    found: Literal[False]


class _DescribeNodeFoundJSON(TypedDict):
    found: Literal[True]
    tag: str
    attrs: dict[str, str]
    field: CanvasFieldInfoJSON | None
    definition: FieldDefinitionJSON | None


#: ``describe_node()``'s own answer shape. `wire.ts`'s closest cousin,
#: `types.ts:DescribeNodeAnswer`, differs from `locate_target()`'s own
#: `LocateTargetJSON` (`studio_view_editor.py`) exactly the way that file's
#: own docstring anticipates: ``definition`` here where that one has
#: ``xpath``.
DescribeNodeJSON: TypeAlias = _DescribeNodeNotFoundJSON | _DescribeNodeFoundJSON


class StudioViewEditor(models.AbstractModel):
    _inherit = "studio.view.editor"

    # Types with no rendering of their own to drop onto. A search view is
    # edited as three lists; a report is a document, previewed by
    # `studio.report`.
    EDITABLE_AS = {"qweb": "report", "search": "search_lists"}

    @api.model
    def canvas(
        self, view_id: int, options: dict[str, object] | None = None
    ) -> CanvasJSON:
        """Everything the console needs to render one view and address it.

        ``options`` may carry ``show_invisible`` (render nodes the view
        hides), ``res_id`` (the record the user came from, shown when it
        still exists), ``package_id`` (which package's extension to report
        as the source; the suggested one otherwise) and ``draft_id``, which
        is accepted now so a client can already send it and read once
        pending fields are spliced in.

        Returned: the view, the stamped arch, the field descriptions of the
        model and of every inline subview's comodel, the version the arch
        was stamped from, the node table, and what the console shows around
        the canvas -- history, package, source, record count.
        """
        typed.security(self)._assert_studio_user()
        options = dict(options or {})
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        package = self._canvas_package(view, options.get("package_id"))
        payload: CanvasJSON = {
            "view": {
                "id": cast("int", view.id),
                "name": cast("str", view.name),
                "type": cast("str", view.type),
                "model": view.model,
                "mode": cast("str", view.mode),
                "js_class": None,
            },
            "arch": None,
            "models": {},
            "arch_version": cast("StudioViewEditorBase", self).arch_version(
                cast("int", view.id)
            ),
            "res_id": False,
            "root": None,
            "nodes": {},
            "pending": [],
            "draft_id": False,
            "editable_as": self.EDITABLE_AS.get(cast("str", view.type), "canvas"),
            "source": self._canvas_source(view, package),
            "history": typed.model(self.env, StudioViewEdit).stack_for(
                cast("int", view.id)
            ),
            "package": {
                "id": cast("int", package.id),
                "name": cast("str", package.name),
                "writable": package.writable,
            }
            if package
            else None,
            "record_count": 0,
        }
        if not view.model or view.model not in self.env:
            # A report template: previewed as a document, not as a view.
            return payload

        Model = self.env[cast("str", view.model)]
        # What get_view checks first (`ir_ui_view.py:2824`): a view of a
        # model the user may not read is not theirs to look at either.
        Model.browse().check_access("read")
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        stamped = canvas_stamp.stamp(root, cast("str", view.type))
        record_count = cast("StudioViewEditorBase", self)._record_count(view.model)
        meta = canvas_stamp.prepare_for_canvas(
            stamped.arch,
            cast("str", view.type),
            show_invisible=bool(options.get("show_invisible")),
            # An empty list or kanban renders nothing to drop onto; sample
            # rows give it columns and cards.
            sample=view.type in ("list", "kanban") and record_count == 0,
        )
        draft = self._canvas_draft(view, options.get("draft_id"))
        payload["draft_id"] = cast("int", draft.id) if draft else False
        payload["pending"] = self._splice_pending(
            stamped, root, view, draft, payload["arch_version"]
        )
        arch, models_used = self._postprocess_canvas(view, Model, stamped.arch)
        self._fill_hidden(stamped.nodes, arch)
        for token, node in stamped.nodes.items():
            if node["kind"] in ("field", "column"):
                # `StudioNode.field` stays `dict[str, Any] | None` in
                # `canvas_stamp.py` (out of this file's own scope to edit;
                # that file's own docstring already anticipates narrowing it
                # once this producer converts) -- cast rather than widen it.
                node["field"] = cast(
                    "dict[str, Any] | None",
                    self._canvas_field_info(view.model, stamped.elements[token]),
                )

        payload.update(
            {
                "arch": arch,
                "models": {
                    model: {
                        "fields": self.env[model].fields_get(
                            allfields=names,
                            attributes=cast(
                                "IrUiViewModelMixin", Model
                            )._get_view_field_attributes(),
                        )
                    }
                    for model, names in models_used.items()
                },
                "res_id": self._canvas_res_id(Model, options.get("res_id")),
                "root": stamped.root,
                "nodes": stamped.nodes,
                "record_count": record_count,
            }
        )
        payload["view"]["js_class"] = meta["js_class"]
        return payload

    @api.model
    def _postprocess_canvas(
        self, view: View, Model: BaseModel, arch: LxmlElement
    ) -> tuple[str, dict[str, set[str]]]:
        """``get_view``'s pipeline on our copy: the arch string and the
        fields each model in it uses.

        Postprocessing runs on the view *as sudo*, as ``_get_view`` does --
        it resolves other models' default subviews and needs to see them
        all -- and the access-rights pass runs as the real user, since it
        is their groups that decide what the view hides. ``_postprocess_debug``
        exists from 19 on and is called when it does, so the arch string
        matches what ``get_view`` would hand the same user.
        """
        # `postprocess_and_fields`/`_get_view_fields` are core Odoo methods
        # with no annotations of their own -- the same accepted,
        # pre-existing vendor gap `studio_view_editor.py`'s own
        # `_neutral_combined_arch`/`apply_operation` document -- cast to the
        # real shape each always returns. `_get_view_fields` itself is
        # declared on `ir_ui_view.py`'s own `class Model(models.AbstractModel):
        # _inherit = "base"` -- a mixin composed onto *every* model, not
        # `Model`'s own real Python base, aliased `IrUiViewModelMixin`
        # rather than imported as `Model` to avoid shadowing this file's own
        # use of that name.
        arch_str, models_used = cast(
            "tuple[str, dict[str, set[str]]]",
            view.sudo().postprocess_and_fields(arch, model=Model._name),
        )
        models_used = cast(
            "dict[str, set[str]]",
            cast("IrUiViewModelMixin", Model)._get_view_fields(
                cast("str", view.type), models_used
            ),
        )
        # Named `view_model`, not `View`: a local `View = self.env[...]`
        # would shadow this file's own top-level `View` import for the rest
        # of this function -- the same trap `studio_view_editor.py`'s own
        # `_get_or_create_extension` documents.
        view_model = typed.model(self.env, View)
        node = cast(
            "LxmlElement",
            view_model._postprocess_access_rights(
                cast("LxmlElement", etree.fromstring(arch_str))
            ),
        )
        if hasattr(view_model, "_postprocess_debug"):
            # Not on `View` in every core version this repo targets (this
            # file's own docstring); `hasattr()` guards it at runtime, and
            # the same `cast("Any", ...)` sidesteps the attribute check
            # `ir_ui_menu.py`'s own serializer uses for another
            # version-conditional core method.
            node = cast("LxmlElement", cast("Any", view_model)._postprocess_debug(node))
        return (
            cast("str", etree.tostring(node, encoding="unicode").replace("\t", "")),
            models_used,
        )

    @api.model
    def _fill_hidden(
        self, nodes: dict[canvas_stamp.Token, canvas_stamp.StudioNode], arch: str
    ) -> None:
        """Say why a node the table lists is not on the canvas.

        ``groups``: the node -- or an ancestor -- carries ``groups`` the
        user is not in, so the access-rights pass took it out of the arch
        and nothing renders it. Still in the table, still addressable: a
        manager who cannot see a field can still move it. ``invisible``: a
        literal ``invisible`` the view compiler drops; it renders when the
        canvas is asked to show hidden nodes, and the client dims it.

        From 19 on, ``_postprocess_debug`` hides a ``base.group_no_one``
        node from a non-debug user by writing a literal ``invisible`` onto
        it instead of taking it out; the node is then in the arch and still
        never renders, and "show invisible" cannot help since the rewrite
        ran before it. So a literal the final arch carries and the view's
        own attributes do not is read as ``groups`` too.
        """
        present: dict[canvas_stamp.Token, LxmlElement] = {}
        for element in cast("LxmlElement", etree.fromstring(arch.encode())).iter():
            if isinstance(element.tag, str):
                token = canvas_stamp.token_of(element)
                if token:
                    present[token] = element
        for token, node in nodes.items():
            invisible_attrs = ("invisible", "column_invisible")
            if node["kind"] == "pending":
                # A ghost is ours, spliced after the walk; the arch carries
                # it under a token of its own and nothing hides it.
                continue
            if node["dom"] and token not in present:
                node["hidden"] = "groups"
            elif any(
                node["attrs"].get(attr) in canvas_stamp.INVISIBLE_LITERALS
                for attr in invisible_attrs
            ):
                node["hidden"] = "invisible"
            elif token in present and any(
                present[token].get(attr) in canvas_stamp.INVISIBLE_LITERALS
                for attr in invisible_attrs
            ):
                node["hidden"] = "groups"

    @api.model
    def _canvas_draft(self, view: View, draft_id: object = None) -> BaseModel:
        """The draft whose pending fields this canvas shows, or an empty one.

        The one the client names when it names one, it is this model's and
        it is the user's own; otherwise the newest draft the user has on
        the model, the same one ``editing_context`` reports. Drafts are per
        user -- two people building the same model do not see each other's
        tray -- and a canvas that spliced somebody else's ghosts on request
        would be the one way around that. Never created here: looking is
        not editing, and a draft that exists only because somebody opened
        the console would have to be explained away in the tray.
        """
        Draft = typed.model(self.env, StudioModelDraft)
        if draft_id:
            draft = Draft.browse(cast("int", draft_id)).exists()
            if (
                draft
                and draft.model == view.model
                # `create_uid` is a magic field added to every model at
                # registry setup (`models.py:_add_magic_fields`), never a
                # real class attribute -- invisible to pyright on
                # `draft.create_uid`, the same gap `studio_view_edit.py`'s
                # own `_entry` documents; subscripted instead, which
                # sidesteps the missing-attribute error entirely.
                and draft["create_uid"].id == self.env.uid
            ):
                return draft
        return Draft.browse(
            cast("StudioViewEditorBase", self)._open_draft_id(view.model)
        )

    # The tag a ghost is: the one tag that renders in a form group, as a
    # list column and in a kanban card alike. A `<div>` would not.
    PENDING_TAG = "widget"
    PENDING_WIDGET = "app_builder_pending"
    PENDING_TOKEN_PREFIX = "p_"

    @api.model
    def _splice_pending(
        self,
        stamped: canvas_stamp.StampResult,
        root: LxmlElement,
        view: View,
        draft: BaseModel,
        arch_version: str,
    ) -> object:
        """Fields staged on a draft, drawn where they will land.

        For each field the draft is adding with an anchor on this view, a
        ``<widget name="app_builder_pending">`` goes into the stamped copy
        at the anchor -- beside the neighbour, or as the last child for
        ``inside`` -- and the node table gains an entry for it under
        ``p_<name>``, movable so it can be dragged to a new anchor and
        selectable so its properties can be opened. The copy is ours: the
        real arch is untouched and ``get_combined_arch()`` never sees a
        ghost.

        Every field the draft is adding is listed, spliced or not, so the
        tray can count them; ``placed`` says which ones the canvas shows.
        An anchor that no longer resolves -- its neighbour was removed
        since the drop -- is not guessed at: the field will be placed by
        the balanced fallback on Apply, so its ghost is drawn where that
        fallback puts a field, and says so (``resolved`` off) rather than
        vanishing from the canvas while the pill still counts it. A field
        anchored on another view of the model is listed and not drawn.

        Anchors on real nodes are resolved against the *original* tree,
        all of them, before the first ghost is spliced: a positional xpath
        counts siblings, and a ghost already in the copy would shift the
        count for the next one. An anchor on another ghost is resolved
        against the copy, where that ghost is; the anchors come in drop
        order, and a ghost is only ever anchored on one dropped earlier.
        """
        if not draft:
            return []
        by_token: dict[canvas_stamp.Token, LxmlElement] = {}
        for element in stamped.arch.iter():
            if isinstance(element.tag, str):
                token = canvas_stamp.token_of(element)
                if token:
                    by_token[token] = element
        token_of_element = {id(el): token for token, el in stamped.elements.items()}
        entries = cast("StudioModelDraftView", draft)._pending_anchored()
        # Real neighbours first, on the untouched tree.
        neighbours: dict[str, canvas_stamp.Token | None] = {}
        for entry in entries:
            anchor = cast("dict[str, object] | None", entry["anchor"])
            if (
                anchor
                and anchor.get("view_id") == view.id
                and not anchor.get("pending")
            ):
                found = self._resolve_anchor(root, anchor, arch_version)
                neighbours[cast("str", entry["name"])] = (
                    token_of_element.get(id(found)) if found is not None else None
                )
        pending: list[dict[str, object]] = []
        ghosts: dict[str, canvas_stamp.Token] = {}
        for entry in entries:
            anchor = cast("dict[str, object] | None", entry.pop("anchor"))
            name = cast("str", entry["name"])
            token = self.PENDING_TOKEN_PREFIX + name
            listed: dict[str, object] = {
                **entry,
                "token": token,
                "placed": False,
                "resolved": False,
                "view_id": (anchor or {}).get("view_id") or False,
            }
            pending.append(listed)
            if not anchor or anchor.get("view_id") != view.id:
                continue
            position: str | None = cast("str", anchor.get("position") or "after")
            if anchor.get("pending"):
                neighbour_token = ghosts.get(cast("str", anchor["pending"]))
            else:
                neighbour_token = neighbours.get(name)
            resolved = neighbour_token is not None and neighbour_token in by_token
            if resolved and (
                position != "inside"
                and stamped.nodes[cast("canvas_stamp.Token", neighbour_token)]["parent"]
                is None
            ):
                # Nothing goes beside the view itself; an anchor that says
                # so is not one a drop could have minted.
                resolved = False
            if not resolved:
                neighbour_token, position = self._fallback_spot(stamped, by_token, view)
                if neighbour_token is None:
                    continue
            by_token[token] = self._splice_ghost(
                stamped,
                by_token[cast("canvas_stamp.Token", neighbour_token)],
                cast("canvas_stamp.Token", neighbour_token),
                # Only `_fallback_spot`'s own `(None, None)`/`(token, None)`
                # shapes leave `position` `None`, and both are already
                # excluded by the `neighbour_token is None: continue` above
                # -- a correlation between the two halves of that tuple
                # return a flat `str | None` cannot state to pyright, the
                # same gap `studio_view_editor.py`'s own `_find_node_entry`
                # callers document.
                cast("str", position),
                token,
                {**entry, "draft_id": draft.id, "resolved": resolved},
            )
            ghosts[name] = token
            listed["placed"] = True
            listed["resolved"] = resolved
        return pending

    @api.model
    def _fallback_spot(
        self,
        stamped: canvas_stamp.StampResult,
        by_token: dict[canvas_stamp.Token, LxmlElement],
        view: View,
    ) -> tuple[canvas_stamp.Token | None, str | None]:
        """Where the balanced fallback would put a field of this view, as a
        ``(token, position)`` on the stamped copy, or ``(None, None)``.

        The same slot ``placement.place_in_form`` fills -- the emptiest
        column of the first two-column group in the sheet, else the end of
        the sheet -- and the end of a list; a kanban has no such slot.
        Close enough to say "here, roughly" while the ghost's caption says
        the exact place is not known.
        """
        nodes = stamped.nodes
        if view.type == "list":
            return stamped.root, "inside"
        if view.type != "form":
            return None, None
        host = next((t for t, n in nodes.items() if n["kind"] == "sheet"), stamped.root)
        columns = [
            grandchild
            for child in nodes[host]["children"]
            # `nodes.get(x, {})` is defensive: every token in a `children`
            # list is already a key of `nodes` by `stamp()`'s own
            # invariant, so the empty-dict default here is never real at
            # runtime -- cast so the always-present `"kind"` key still
            # type-checks against that invariant.
            if nodes.get(child, cast("canvas_stamp.StudioNode", {})).get("kind")
            == "group"
            for grandchild in nodes[child]["children"]
            if nodes.get(grandchild, cast("canvas_stamp.StudioNode", {})).get("kind")
            == "group"
        ]
        if columns:
            target = min(
                columns,
                key=lambda t: sum(
                    1 for c in nodes[t]["children"] if nodes[c]["tag"] == "field"
                ),
            )
            return target, "inside"
        return (host, "inside") if host in by_token else (None, None)

    @api.model
    def _splice_ghost(
        self,
        stamped: canvas_stamp.StampResult,
        neighbour: LxmlElement,
        neighbour_token: canvas_stamp.Token,
        position: str,
        token: canvas_stamp.Token,
        info: dict[str, object],
    ) -> LxmlElement:
        """Put one ghost into the stamped copy and the node table."""
        ghost = cast("LxmlElement", etree.Element(self.PENDING_TAG))
        ghost.set("name", self.PENDING_WIDGET)
        ghost.set(
            "class",
            "o_studio_pending %s%s" % (canvas_stamp.TOKEN_PREFIX, token),
        )
        ghost.set("colspan", "2")
        ghost.set(
            "options",
            repr(
                {
                    "name": info["name"],
                    "label": info["label"],
                    "ttype": info["ttype"],
                    "resolved": bool(info.get("resolved", True)),
                }
            ),
        )
        if position == "inside":
            neighbour.append(ghost)
            parent_token: canvas_stamp.Token | None = neighbour_token
        else:
            # A neighbour spliced beside (not inside) another node is never
            # the tree root -- `_splice_pending`'s own guard above refuses
            # a `resolved` anchor there, and `_fallback_spot` only ever
            # hands back `"inside"` for the root -- so `getparent()` is
            # never `None` here in practice; `list(...)` rather than
            # lxml's own `.index()`, which `LxmlElement` (no stub for the
            # real thing) does not declare, the same workaround
            # `placement.py`'s own `_place_in_group`/`place_in_list` use.
            parent = cast("LxmlElement", neighbour.getparent())
            index = list(parent).index(neighbour) + (1 if position == "after" else 0)
            parent.insert(index, ghost)
            parent_token = stamped.nodes[neighbour_token]["parent"]
        parent_node = stamped.nodes[cast("canvas_stamp.Token", parent_token)]
        siblings = parent_node["children"]
        if position == "inside":
            place = len(siblings)
        else:
            place = siblings.index(neighbour_token) + (1 if position == "after" else 0)
        siblings.insert(place, token)
        for index, sibling in enumerate(siblings):
            if sibling in stamped.nodes:
                stamped.nodes[sibling]["index"] = index
        stamped.nodes[token] = {
            "tag": self.PENDING_TAG,
            "name": cast("str", info["name"]),
            "kind": "pending",
            "parent": parent_token,
            "children": [],
            "index": place,
            "string": cast("str", info["label"]),
            "container": False,
            "orientation": "column",
            "accepts": [],
            "movable": True,
            "removable": True,
            "selectable": True,
            "hidden": None,
            "attrs": {},
            "dom": True,
            "field": None,
            "view_id": None,
            "label": None,
            "pending": {
                "draft_id": cast("int", info["draft_id"]),
                "name": cast("str", info["name"]),
                "ttype": cast("str", info["ttype"]),
                "string": cast("str", info["label"]),
                "resolved": bool(info.get("resolved", True)),
            },
        }
        return ghost

    @api.model
    def _resolve_anchor(
        self, root: LxmlElement, anchor: dict[str, object], arch_version: str
    ) -> LxmlElement | None:
        """The node of ``root`` an anchor is beside, or ``None``.

        The xpath as minted while the arch is the one it was minted on --
        and only then: a positional locator on a changed tree resolves to
        *some* node, the wrong one. Otherwise the neighbour is found again
        by what it was -- "the field called email" -- which survives
        anything but its own removal.
        """
        if anchor.get("pending"):
            # Beside another staged field: nothing in this tree to find.
            return None
        if anchor.get("arch_version") == arch_version and anchor.get("xpath"):
            found = cast("StudioViewEditorBase", self)._resolve_xpath(
                root, cast("str", anchor["xpath"])
            )
            if found and len(found) == 1:
                return found[0]
        descriptor = anchor.get("descriptor")
        if not descriptor:
            return None
        return cast("StudioViewEditorBase", self)._find_descriptor(
            root, cast("dict[str, object]", descriptor)
        )

    @api.model
    def _anchor_locator(
        self, view: View, root: LxmlElement, anchor: dict[str, object]
    ) -> tuple[str, NodeExpectationJSON] | None:
        """The locator an anchored placement applies, with what it expects
        to find there: ``(xpath, expectation)``, or ``None`` when the
        neighbour is gone.

        The neighbour is resolved whichever way the anchor allows -- the
        minted xpath while the arch is unchanged, the descriptor after --
        and the locator is minted from the node found, as a live drop's
        is. The expectation travels with it for the same reason a live
        drop's does: a positional path minted on the combined arch may
        name another node in the primary arch an owned view is edited
        through, and ``_assert_owned_locators`` can only refuse that when
        told what the node should be.
        """
        base = cast("StudioViewEditorBase", self)
        version = base._version_of(
            cast("int", view.id), base._neutral_combined_arch(view)
        )
        node = self._resolve_anchor(root, anchor, version)
        if node is None:
            return None
        return (
            base._locator_for(node, base._occurrences(root)),
            base._expectation_for(node),
        )

    @api.model
    def _pending_locator(
        self, root: LxmlElement, name: str
    ) -> tuple[str, NodeExpectationJSON] | None:
        """The locator of the real ``<field name>`` a staged neighbour has
        become, with its expectation, or ``None`` when the view does not
        show it -- or shows it only inside a subview, which is another
        model's field of the same name."""
        found = [
            node
            for node in root.iter("field")
            if node.get("name") == name
            and not any(a.tag == "field" for a in node.iterancestors())
        ]
        if len(found) != 1:
            return None
        base = cast("StudioViewEditorBase", self)
        return (
            base._locator_for(found[0], base._occurrences(root)),
            base._expectation_for(found[0]),
        )

    @api.model
    def _canvas_field_info(
        self,
        model_name: str | Literal[False],
        element: LxmlElement,
        comodel_fields: bool = False,
    ) -> CanvasFieldInfoJSON | None:
        """``_field_info`` plus where the field came from.

        The definition section of the properties panel edits a manual
        field's label in ``ir.model.fields`` and shows a core field's as a
        fact, so it has to know which it is looking at.

        ``comodel_fields`` -- every stored field of a relational field's
        comodel -- is what the panel's options need for the *selected*
        node and nothing else needs for any node, so the canvas leaves it
        out: a partner form has some thirty relational fields, and the
        field list of ``res.users`` once per each of them, on every drop,
        is tens of kilobytes that ``describe_node`` supplies on demand.
        """
        # `_field_info` (the real base) returns `FieldInfoJSON | None`; the
        # extra `"origin"` key this method adds is only true once it is set
        # below, so the value is cast to this file's own subclass (rule 9)
        # rather than declared that shape from the start.
        info = cast(
            "CanvasFieldInfoJSON | None",
            cast("StudioViewEditorBase", self)._field_info(
                cast("str", model_name), element
            ),
        )
        if info is not None:
            info["origin"] = self._field_origin(model_name, info["name"])
            if not comodel_fields:
                info.pop("comodel_fields", None)
        return info

    @api.model
    def _field_origin(
        self, model_name: str | Literal[False], field_name: str
    ) -> Literal["manual", "core"]:
        """``manual`` for a field that lives only in ``ir.model.fields``."""
        record = typed.model(self.env, IrModelFields)._get(model_name, field_name)
        return "manual" if record and record.state == "manual" else "core"

    @api.model
    def _canvas_res_id(self, Model: BaseModel, wanted: object) -> int | Literal[False]:
        """The record to render: the one asked for if it exists, else any.

        A form of no record is a form of placeholders, and a canvas that
        renders the record the user was just looking at is one they
        recognise. The fallback is the first record the user can read,
        archived or not, and ``False`` when there is none -- the form then
        renders empty, which is still a form to drop onto.
        """
        if Model._abstract:
            return False
        if wanted and Model.browse(cast("int", wanted)).exists():
            return cast("int", wanted)
        return (
            cast("int", Model.with_context(active_test=False).search([], limit=1).id)
            or False
        )

    @api.model
    def _canvas_package(
        self, view: View, package_id: object | None = None
    ) -> StudioPackage:
        """The package a drop on this canvas would record into."""
        Package = typed.model(self.env, StudioPackage)
        if package_id:
            chosen = Package.browse(cast("int", package_id)).exists()
            if chosen:
                return chosen
        # Ownership is an xmlid lookup, which only an administrator may
        # make; a builder without that right still gets the right package.
        # `studio_package_id` is a field from `studio.owned.mixin`, composed
        # onto `ir.ui.view` (`_inherit`, never a real Python base class) --
        # invisible to pyright on `view` itself without the first cast, the
        # same idiom `studio_view_editor.py`'s own `_find_extension`
        # documents; the second is the plain-string-comodel cast (rule 5).
        owner = cast(
            "StudioPackage", cast("StudioOwnedMixin", view.sudo()).studio_package_id
        )
        return (
            Package.browse(cast("int", owner.id))
            if owner
            else Package.search([])._suggested()
        )

    @api.model
    def _canvas_source(
        self, view: View, package: StudioPackage
    ) -> CanvasSourceJSON | None:
        """The arch the console shows as "what the studio wrote", or ``None``.

        The view itself when the package owns it outright, else the
        package's extension of it when there is one already. ``None`` says
        nothing has been written yet, which the View tab shows as such.
        """
        if not package:
            return None
        base = cast("StudioViewEditorBase", self)
        # Ownership is an xmlid lookup, which only an administrator may
        # make; the fact itself is not a secret.
        if base._owns_outright(view.sudo(), package):
            source = view
        else:
            source = cast("StudioViewEditorBase", self.sudo())._find_extension(
                view, package
            )
            if not source:
                return None
        return {
            "view_id": cast("int", source.id),
            "name": cast("str", source.name),
            "owned": source == view,
            "arch": cast("str", source.arch),
        }

    @api.model
    def describe_node(
        self, view_id: int, descriptor: dict[str, object]
    ) -> DescribeNodeJSON:
        """What the properties panel shows for one node.

        ``locate_target``'s answer for a token descriptor, without the xpath
        the browser must never hold, and with what the panel needs beyond
        it: where a field came from, and what of its definition can be
        edited here. A manual field's label, help and flags are rows of
        ``ir.model.fields`` and can be written; a core field's are facts
        from Python and are shown read-only.
        """
        typed.security(self)._assert_studio_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        base = cast("StudioViewEditorBase", self)
        base._assert_arch_version(
            view, cast("str | None", descriptor.get("arch_version"))
        )
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        node = base._find_descriptor(root, descriptor)
        if node is None:
            return {"found": False}
        info = (
            self._canvas_field_info(view.model, node, comodel_fields=True)
            if view.model
            else None
        )
        return {
            "found": True,
            "tag": cast("str", node.tag),
            "attrs": dict(node.attrib),
            "field": info,
            "definition": self._field_definition(view.model, info) if info else None,
        }

    # What a manual field's definition lets the panel change.
    MANUAL_FIELD_EDITABLE = (
        "field_description",
        "help",
        "required",
        "readonly",
        "index",
    )

    @api.model
    def _field_definition(
        self, model_name: str | Literal[False], info: CanvasFieldInfoJSON
    ) -> FieldDefinitionJSON | None:
        """The model-level facts of a field, and which of them are editable."""
        record = typed.model(self.env, IrModelFields)._get(model_name, info["name"])
        if not record:
            return None
        editable: list[str] = []
        if info["origin"] == "manual":
            editable = list(self.MANUAL_FIELD_EDITABLE)
            if record.ttype in manualfield.TRANSLATABLE:
                editable.append("translate")
            if record.ttype == "selection":
                editable.append("selection")
        values: FieldDefinitionValuesJSON = {
            "field_description": cast("str", record.field_description),
            "help": record.help or "",
            "required": bool(record.required),
            "readonly": bool(record.readonly),
            "index": bool(record.index),
            "translate": bool(record.translate),
            "ttype": cast("str", record.ttype),
            # `X or False` widens the bare `False` to plain `bool` outside
            # of a directly-annotated context (confirmed directly against
            # pyright); cast to the declared, honest shape rather than
            # left for pyright to over-widen.
            "relation": cast("str | Literal[False]", record.relation or False),
        }
        if record.ttype == "selection":
            values["selection"] = [
                {
                    "value": cast("str", s.value),
                    "label": cast("str", s.name),
                    "sequence": s.sequence,
                }
                for s in cast("IrModelSelection", record.selection_ids)
            ]
        return {"origin": info["origin"], "editable": editable, "values": values}

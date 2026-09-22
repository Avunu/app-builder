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

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import Counter
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias, TypedDict, cast

# lxml ships no type stubs in this environment, the same gap `xml_writer.py`/
# `placement.py`/`studio_serializer.py`/`studio_model_draft.py` already
# document -- `reportMissingTypeStubs` only escalates to `error` under
# `tools/`'s own `executionEnvironments` override (`pyrightconfig.json`), not
# at this (model) level, so the one real hit here (`etree` itself, an
# unresolvable import symbol with no stub) is the only one that needs
# silencing.
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from typing_extensions import NotRequired

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.template_inheritance import apply_inheritance_specs

from odoo.addons.base.models.ir_actions import IrActionsActWindow, IrActionsServer
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.base.models.res_users import Groups
from odoo.addons.app_builder_base.models.studio_domain import StudioDomain
from odoo.addons.app_builder_base.models.studio_model_draft import StudioModelDraft
from odoo.addons.app_builder_base.models.studio_package import StudioPackage
from odoo.addons.app_builder_base.models.studio_package_model import StudioPackageModel
from odoo.addons.app_builder_base.tools import (
    catalogue,
    modelspec,
    pycodegen,
    scaffold,
    typed,
    xml_writer,
)

from ..exceptions import STALE_VIEW_MESSAGE, StudioConfirmRequired, StudioStaleView
from ..tools import canvas_stamp, view_options
from .studio_view_edit import StudioViewEdit

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from collections.abc import Callable

    from odoo.fields import Field
    from odoo.models import BaseModel

    from odoo.addons.app_builder_base.models.studio_domain import DomainRowJSON
    from odoo.addons.app_builder_base.models.studio_owned_mixin import StudioOwnedMixin
    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement
    from odoo.addons.web.models.ir_ui_view import View as WebView

_logger = logging.getLogger(__name__)

# Core loads views ordered by priority; 99 keeps studio edits last so they win
# over other extensions without replacing them.
STUDIO_PRIORITY = 99

VALID_POSITIONS = ("after", "before", "inside", "replace", "attributes")

# The positions a caller may name for something *new*: a sibling on either
# side of the anchor, or the anchor's last child. `replace` and `attributes`
# are operations, not places.
INSERT_POSITIONS = ("before", "after", "inside")

# Keys a caller of ``apply_operation`` may find on the operation that no
# handler reads: what the minting step *expected* to find at the locator, so
# the owned path can check it is editing the node the user pointed at.
EXPECTATION_KEYS = ("_expect", "_expect_target", "_expect_label")

# What makes a node identifiable without counting its siblings. `name` is the
# form and list answer; a report has none -- its spans are `<span t-field=...>`
# -- and a positional path into a document shifts the moment anything is
# inserted above it, which for a report is the ordinary edit. A kanban card
# is a `<t t-name="card">`, named by its template name and nothing else. A
# `<label for>` is named by the field it labels: `//label[@for='x']` means
# the same node however the sheet around it is rearranged.
# Order matters: the first attribute that identifies the node uniquely wins.
IDENTIFYING_ATTRS = ("name", "for", "t-field", "t-name")

# How many records the canvas counts before it stops counting. The number is
# shown, and decides whether an empty list gets sample rows; neither needs
# the exact size of a table of millions, and `COUNT(*)` over one costs
# seconds on every gesture.
RECORD_COUNT_CAP = 1000


# -- wire types ---------------------------------------------------------
#
# Cross-checked against `app_builder_view/static/src/console/wire.ts` and
# `.../console/types.ts` (read-only references, hand-kept in sync with
# these until TYPING.md's Phase 2d generator exists) -- named to match
# their TS cousins where one exists. Discrepancies found against the TS
# side are noted per type, typed honestly to the real Python body rather
# than silently following the TS declaration (the same judgment call
# `studio_record_surface.py`'s own conversion already made once).


class OperationResultJSON(TypedDict):
    """``apply_operation()``'s own return (``wire.ts:OperationResult``),
    reused verbatim by every mutator that funnels through it (``apply_at``,
    ``remove_at``, ``show_label_at``, ``add_container_at``, ``move_node``,
    ``add_search_element``, ``remove_search_element``)."""

    view_id: int
    arch: str
    combined_arch: str
    arch_version: str
    #: `wire.ts` declares this `created_name?: string | null` (optional
    #: *and* nullable); the real ``operation.get("_created_name")`` always
    #: sends the key, `None` when the handler named nothing -- so `str |
    #: None`, never absent, is the honest shape.
    created_name: str | None


class NodeExpectationJSON(TypedDict):
    """What a locator minted for a node should still find where it is
    applied (``_expectation_for``), checked by ``_matches_expectation``.

    Server-internal: travels inside an ``operation`` dict's own
    ``_expect``/``_expect_target``/``_expect_label`` keys (``EXPECTATION_
    KEYS``), never sent as a JSON value of its own, so it has no `wire.ts`
    cousin.
    """

    tag: str
    name: str | None
    string: str | None
    children: tuple[tuple[str, str | None], ...]


class EditingContextFieldEntryJSON(TypedDict):
    """One field entry for options that name one (``_model_fields``,
    ``editing_context``'s own ``fields``; ``wire.ts:
    EditingContextFieldEntry``)."""

    name: str
    string: str
    type: str


class FieldInfoJSON(TypedDict):
    """What the sidebar needs to offer the right options for one node
    (``_field_info``, consumed by ``locate_target``/``describe_node`` --
    the latter in ``studio_view_canvas.py``, not yet converted)."""

    name: str
    type: str
    string: str
    store: bool
    required: bool
    readonly: bool
    #: Only set when the field is relational and its comodel is a real,
    #: installed model (``_field_info``'s own ``if comodel and comodel in
    #: self.env:``).
    comodel_fields: NotRequired[list[EditingContextFieldEntryJSON]]


class _LocateTargetNotFoundJSON(TypedDict):
    found: Literal[False]
    reason: str


class _LocateTargetFoundJSON(TypedDict):
    found: Literal[True]
    xpath: str
    tag: str
    attrs: dict[str, str]
    field: FieldInfoJSON | None


#: ``locate_target()``'s own answer shape -- no `wire.ts` cousin of its
#: own (the closest, `types.ts:DescribeNodeAnswer`, is `describe_node`'s,
#: a different method with a different shape: `definition` where this has
#: `xpath`).
LocateTargetJSON: TypeAlias = _LocateTargetNotFoundJSON | _LocateTargetFoundJSON


class PlaceableFieldEntryJSON(TypedDict):
    """A field the picker offers for a date or a group-by when creating
    another kind of view (``_placeable_fields``; ``wire.ts:
    PlaceableFieldEntry``)."""

    name: str
    string: str


class _ViewPrerequisiteExtraJSON(TypedDict, total=False):
    """``_view_prerequisites``'s own second return value: whichever of
    ``AddableViewTypeEntryJSON``'s two field-picker keys this view type
    needs the caller to choose from, merged into the entry with
    ``dict.update()`` -- a real (``total=False``) subset of that TypedDict
    rather than a plain ``dict[str, list[...]]``, which `TypedDict.update()`
    does not structurally accept."""

    date_fields: list[PlaceableFieldEntryJSON]
    group_fields: list[PlaceableFieldEntryJSON]


class AddableViewTypeEntryJSON(TypedDict):
    """One kind of view ``addable_view_types`` offers, and why not when it
    does not (``wire.ts:AddableViewTypeEntry``)."""

    type: str
    label: str
    icon: str
    enabled: bool
    reason: str
    date_fields: list[PlaceableFieldEntryJSON]
    group_fields: list[PlaceableFieldEntryJSON]


class AddableFieldEntryJSON(TypedDict):
    """One field ``get_addable_fields`` offers: not already in the arch,
    with enough to show and place it (``wire.ts:AddableFieldEntry``)."""

    name: str
    string: str
    type: str
    required: bool
    readonly: bool
    manual: bool


class SearchFilterEntryJSON(TypedDict):
    """One row of ``search_elements()``'s ``filters``/``group_bys``
    (``wire.ts:SearchFilterEntry``)."""

    name: str
    string: str
    domain: str


class _SearchFieldEntryJSON(TypedDict):
    #: `wire.ts:SearchElements.fields` declares `name: string` (never
    #: absent or null); the real body appends ``node.get("name")``
    #: straight from the arch with no fallback, and an lxml `.get()`
    #: returns `None` for an attribute that is not there -- a search
    #: `<field>` with no `name` is unlikely but not refused anywhere
    #: upstream, so this is typed to the real, wider possibility rather
    #: than the narrower one `wire.ts` assumes.
    name: str | None
    string: str


class SearchElementsJSON(TypedDict):
    """``search_elements()``'s whole return: what a search view offers, in
    the three groups the sidebar shows (``wire.ts:SearchElements``)."""

    fields: list[_SearchFieldEntryJSON]
    filters: list[SearchFilterEntryJSON]
    group_bys: list[SearchFilterEntryJSON]
    addable: list[AddableFieldEntryJSON]


class SelectableGroupEntryJSON(TypedDict):
    """One group a ``groups=""`` attribute can name (``_selectable_groups``;
    ``wire.ts:SelectableGroupEntry``)."""

    id: int
    xmlid: str
    name: str


class AddViewJSON(TypedDict):
    """``add_view()``'s own return: the new view, created and made
    reachable."""

    view_id: int
    type: str


class ViewOfEntryJSON(TypedDict):
    """One view of a model, as ``_views_of`` picks it (``wire.ts:
    ViewOfEntry``)."""

    type: str
    view_id: int
    name: str
    owned: bool


class PreviewInfoJSON(TypedDict):
    """``_preview_for()``'s whole return (``wire.ts:PreviewInfo``)."""

    type: str
    view_id: int | Literal[False]
    search_view_id: int | Literal[False]
    unavailable: NotRequired[bool]


class EditingContextViewJSON(TypedDict):
    """``editing_context()``'s own ``view`` key."""

    id: int
    name: str
    type: str
    model: str | Literal[False]
    mode: str


class EditingContextPackageEntryJSON(TypedDict):
    """One entry of ``editing_context()``'s own ``packages`` list.

    `wire.ts:EditingContext.packages` is declared `unknown` -- nothing
    converted so far read it when that interface was written -- but the
    real body always sends this exact shape (``{"id": p.id, "name": p.name,
    "writable": p.writable} for p in packages``), so it is typed to what
    the Python actually, always sends rather than left to match the wider
    TS declaration.
    """

    id: int
    name: str
    writable: bool


class EditingContextJSON(TypedDict):
    """``editing_context()``'s whole return -- everything the editor needs
    to open on a view (``wire.ts:EditingContext``).

    ``options``/``catalogue``/``groups`` are given the real return types of
    the calls that build them (``view_options.groups_json``,
    ``catalogue.catalogue_json``, ``_selectable_groups``) rather than left
    `unknown` the way `wire.ts` leaves the first two -- narrower than the
    wire type, not looser, so still an honest supertype of it.
    """

    view: EditingContextViewJSON
    views: list[ViewOfEntryJSON]
    python_owned: bool
    python_owner_id: int | Literal[False]
    field_types: list[modelspec.FieldTypeJSON]
    draft_id: int | Literal[False]
    reload_mode: str | Literal[False]
    record_count: int
    fields: list[EditingContextFieldEntryJSON]
    preview: PreviewInfoJSON
    options: list[catalogue.OptionGroupJSON]
    catalogue: catalogue.CatalogueJSON
    groups: list[SelectableGroupEntryJSON]
    owned: bool
    packages: list[EditingContextPackageEntryJSON]
    suggested_package_id: int | Literal[False]


class CanvasViewJSON(TypedDict):
    """``canvas()``'s own ``view`` key (``studio_view_canvas.py:canvas``,
    ``wire.ts:CanvasPayload.view``)."""

    id: int
    name: str
    type: str
    model: str | Literal[False]
    mode: str
    js_class: str | None


class CanvasPackageJSON(TypedDict):
    """``canvas()``'s own ``package`` key: who a drop here would record
    into (``wire.ts:CanvasPackageSummary``)."""

    id: int
    name: str
    writable: bool


class CanvasJSON(TypedDict):
    """``canvas()``'s whole return (``studio_view_canvas.py:canvas``,
    composed into this same RPC model via a pure ``_inherit`` -- see
    ``_ComposedViewEditor`` below; ``wire.ts:CanvasPayload``).

    Declared here, not there, because this file's own ``drop_at``/
    ``_reanchor_gap``/``_token_named`` all consume it. ``models``/
    ``source``/``pending``/``history`` stay ``object``, matching
    `wire.ts`'s own `unknown` for `models`/`source` -- nothing in *this*
    file reads any of the four beyond passing them on whole.
    """

    view: CanvasViewJSON
    arch: str | None
    models: object
    arch_version: str
    res_id: int | Literal[False]
    root: str | None
    nodes: dict[canvas_stamp.Token, canvas_stamp.StudioNode]
    pending: object
    draft_id: int | Literal[False]
    editable_as: str
    source: object
    history: object
    package: CanvasPackageJSON | None
    record_count: int


class DropCreatedFieldJSON(TypedDict):
    """What a live-created field's ``created`` names, on a ``drop_at``
    answer (``studio_view_new_field.py:_drop_live_field``; ``wire.ts:
    DropCreatedField``)."""

    name: str
    label: str
    live: Literal[True]


class DropStagedFieldJSON(TypedDict):
    """What a staged field's ``staged`` names, on a ``drop_at`` answer
    (``studio_view_new_field.py:_drop_field_definition``; ``wire.ts:
    DropStagedField``)."""

    name: str
    label: str
    draft_id: int


class DropSuccessJSON(TypedDict):
    """A settled (non-stale) ``drop_at`` answer -- built here or by
    ``studio_view_new_field.py``'s own ``_drop_live_field``/
    ``_drop_field_definition``, composed into this same RPC method via
    ``_inherit`` (``wire.ts:DropSuccessResult``)."""

    stale: Literal[False]
    select: str | None
    created: DropCreatedFieldJSON | None
    staged: DropStagedFieldJSON | None
    canvas: CanvasJSON
    history: object
    draft: object | None


class DropStaleJSON(TypedDict):
    """The stale early return: a token minted before the last write no
    longer means anything, so nothing but a fresh canvas is sent."""

    stale: Literal[True]
    canvas: CanvasJSON


#: ``drop_at()``'s own return: the stale early answer, or a settled one --
#: `wire.ts`'s own `_mutate` peels the stale shape off before anything
#: downstream sees it (`types.ts:DropSuccessResult`'s own docstring), so
#: only `DropSuccessJSON` has a `wire.ts` cousin of its own.
DropAtJSON: TypeAlias = DropStaleJSON | DropSuccessJSON


if TYPE_CHECKING:

    class _ComposedViewEditor(Protocol):
        """The slice of ``studio.view.editor`` this file calls but does not
        itself declare.

        ``studio_view_canvas.py`` and ``studio_view_new_field.py`` extend
        this same ``_name`` with a pure ``_inherit = "studio.view.editor"``
        and no ``_name``/base class of their own -- the registry composes
        all three into one model, but neither is a real Python base of
        this file's own ``StudioViewEditor``, so pyright cannot see
        ``PENDING_TOKEN_PREFIX``/``canvas``/``_canvas_draft``/
        ``_splice_pending``/``_drop_field_definition``/``_mint_anchor``/
        ``_python_owner`` on a bare ``self`` here -- the identical
        ``_inherit``-mixin gap ``typed.security()`` exists for, on a
        different mixin, worked around by hand here since a third
        `typed.py` helper is outside this file's own scope (``Only touch
        app_builder_view/models/studio_view_editor.py``). Neither sibling
        is converted yet (a later batch, once this file's own real
        signatures exist for them to read), so ``self`` is cast to this
        narrow, hand-traced Protocol at each call site below rather than
        to their real (still-untyped) classes -- narrow it further, or
        replace it with a real aliased import, once those two convert.
        """

        PENDING_TOKEN_PREFIX: str

        def canvas(
            self, view_id: int, options: dict[str, object] | None = None
        ) -> CanvasJSON: ...
        def _canvas_draft(self, view: View, draft_id: object = None) -> BaseModel: ...
        def _splice_pending(
            self,
            stamped: canvas_stamp.StampResult,
            root: LxmlElement,
            view: View,
            draft: BaseModel,
            arch_version: str,
        ) -> object: ...
        def _drop_field_definition(
            self,
            view: View,
            package: StudioPackage,
            stamped: canvas_stamp.StampResult,
            root: LxmlElement,
            token: canvas_stamp.Token,
            position: str,
            container: canvas_stamp.StudioNode,
            payload: dict[str, object],
            options: dict[str, object],
        ) -> DropSuccessJSON: ...
        def _mint_anchor(
            self,
            view: View,
            stamped: canvas_stamp.StampResult,
            root: LxmlElement,
            token: canvas_stamp.Token,
            position: str,
        ) -> dict[str, object]: ...
        def _python_owner(self, model_name: str) -> StudioPackage: ...

    class _DraftHandle(Protocol):
        """The one extension method ``_reanchor_gap`` calls on a draft
        recordset: ``set_anchor``, declared only on
        ``app_builder_view/models/studio_model_draft.py``'s own pure
        ``_inherit`` extension of ``studio.model.draft`` (not
        ``app_builder_base``'s own base class, ``typed.model()``'s real
        target for ``_open_draft_id`` elsewhere in this file) -- not yet
        converted, so this is the same narrow composed-elsewhere
        workaround as ``_ComposedViewEditor`` above, for a different,
        sibling model.
        """

        def set_anchor(
            self,
            name: str,
            anchor: dict[str, object],
            release_dependents: bool = True,
        ) -> object: ...


class StudioViewEditor(models.AbstractModel):
    _name = "studio.view.editor"
    _inherit = ["studio.security.mixin"]
    _description = "Studio View Editor"

    # -- extension view lifecycle -----------------------------------------

    @api.model
    def _extension_name(self, base_view: View) -> str:
        return "%s.studio" % (base_view.name or base_view.model)

    @api.model
    def _find_extension(self, base_view: View, package: StudioPackage) -> View:
        """This package's extension of ``base_view``, if it already has one."""
        name = self._extension_name(base_view)
        candidates = typed.model(self.env, View).search(
            [("inherit_id", "=", base_view.id), ("name", "=", name)]
        )
        for candidate in candidates:
            # `studio_package_id` is a field from `studio.owned.mixin`,
            # composed onto `ir.ui.view` in `app_builder_base/models/
            # studio_owned_mixin.py` (`_inherit`, never a real Python base
            # class) -- invisible to pyright on `candidate`/`View` itself
            # without the first cast, same idiom as `typed.security()`'s own
            # docstring. The second cast is the plain-string-comodel one
            # (rule 5, `typed.py`'s own docstring): the field is declared
            # `Many2one("studio.package", ...)`, unsubscripted, so its read
            # type is the bound `BaseModel`, not `StudioPackage`.
            if (
                cast(
                    "StudioPackage",
                    cast("StudioOwnedMixin", candidate).studio_package_id,
                )
                == package
            ):
                return candidate
        return typed.model(self.env, View).browse()

    @api.model
    def _describe(self, operation: dict[str, object]) -> str:
        """A one-line account of an edit, for the history list."""
        kind = cast("str", operation.get("type", "edit"))
        if kind == "set_attributes":
            attrs = cast("dict[str, object]", operation.get("attrs") or {})
            keys = ", ".join(sorted(attrs.keys()))
            return _("changed %s", keys) if keys else _("changed attributes")
        if kind == "add_field":
            return _("added %s", operation.get("name", "a field"))
        if kind == "remove_node":
            return _("removed a node")
        if kind == "show_label":
            return _("gave %s a label", operation.get("name", "a field"))
        if kind == "add_chatter":
            return _("added the chatter")
        return kind.replace("_", " ")

    @api.model
    def _get_or_create_extension(
        self, base_view: View, package: StudioPackage, write_files: bool = True
    ) -> View:
        """One extension view per (base view, package).

        Collecting every edit into a single inheriting view keeps the generated
        source readable -- one record with a list of xpaths, rather than a new
        view record per click.

        ``write_files=False`` captures the new view without writing the
        package: a caller about to fill the extension in the same breath
        writes once, afterwards, rather than putting an empty ``<data/>`` on
        disk first.
        """
        # Named `view_model`, not `View` (the real class this method's own
        # signature is typed against): a local `View = self.env[...]`
        # would shadow that import for the rest of this function -- and,
        # worse, `View = typed.model(self.env, View)` would try to read
        # the not-yet-assigned local `View` on its own right-hand side
        # (Python's own scoping: a name assigned anywhere in a function is
        # local for the whole function), an `UnboundLocalError` this
        # conversion must not introduce.
        view_model = typed.model(self.env, View)
        name = self._extension_name(base_view)
        candidates = view_model.search(
            [("inherit_id", "=", base_view.id), ("name", "=", name)]
        )
        for candidate in candidates:
            # Same `studio.owned.mixin` composed-elsewhere cast as
            # `_find_extension` above.
            if (
                cast(
                    "StudioPackage",
                    cast("StudioOwnedMixin", candidate).studio_package_id,
                )
                == package
            ):
                return candidate
        # `@api.model_create_multi` (`odoo/api.py`) is a bare passthrough
        # decorator that does not widen `create()`'s own declared `list
        # [ValuesType]`-only signature to also cover the single-dict
        # calling form it genuinely accepts at runtime -- the documented
        # stub gap (TYPING.md's own "Known traps"), kept as the exact
        # original single-dict call rather than rewritten to `create([...])`.
        vals = {
            "name": name,
            "model": base_view.model,
            "inherit_id": base_view.id,
            "mode": "extension",
            "priority": STUDIO_PRIORITY,
            "arch": "<data/>",
        }
        view = view_model.create(vals)  # pyright: ignore[reportArgumentType]
        if view.type == "qweb":
            # Odoo mints `gen_key.<uuid>` for a qweb view created without a key
            # (`ir_ui_view.py:519`), and the key is emitted -- so an extension of
            # a report template would put a fresh random string in the generated
            # source every time it is recreated. Odoo's own `<template>` loader
            # sets the key to the xmlid; do the same, before anything is written.
            view.key = package._assign(view)[0]
        package.studio_capture(view, write_files=write_files)
        return view

    # -- arch surgery -----------------------------------------------------

    @api.model
    def _parse_data(self, view: View) -> LxmlElement:
        root = xml_writer.parse_arch(cast("str", view.arch))
        if root.tag != "data":
            # A hand-written extension may use a bare xpath as its root; wrap it
            # so we always have somewhere to append.
            wrapper = cast("LxmlElement", etree.Element("data"))
            wrapper.append(root)
            root = wrapper
        return root

    @api.model
    def _find_xpath(
        self, root: LxmlElement, expr: str, position: str
    ) -> LxmlElement | None:
        for node in root.findall("xpath"):
            if node.get("expr") == expr and node.get("position") == position:
                return node
        return None

    @api.model
    def _write_arch(self, view: View, root: LxmlElement) -> View:
        """Persist an arch, letting Odoo's own validators reject bad edits."""
        xml_writer.canonicalize_attributes(root)
        xml_writer.indent(root)
        arch = cast("str", etree.tostring(root, encoding="unicode"))
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

    # -- the version a client edits against --------------------------------

    @api.model
    def _version_of(self, view_id: int, combined_arch: str) -> str:
        return hashlib.sha1(
            ("%s\n%s" % (view_id, combined_arch)).encode("utf-8")
        ).hexdigest()

    @api.model
    def _neutral_combined_arch(self, view: View) -> str:
        """The combined arch in the source language, whoever is asking.

        ``arch_db`` is a translated field: read under a French user's context
        it comes back with every ``string`` in French, and a version taken
        from that would differ between two people looking at one view. The
        version is a claim about the *structure* of the tree, which no
        translation changes, so it is always taken from the untranslated
        source -- ``lang=None`` reads the ``en_US`` terms whatever the
        session speaks.
        """
        # `get_combined_arch`/`get_view_info` are core Odoo methods with no
        # annotations of their own; `etree.tostring(...)` inside the former
        # makes its inferred return `Unknown` given lxml's own missing
        # stubs (this file's own top-of-file comment) -- a genuine,
        # pre-existing vendor gap, not one this migration introduces, cast
        # to the real `str` it always returns.
        return cast("str", view.with_context(lang=None).get_combined_arch())

    @api.model
    def arch_version(self, view_id: int) -> str:
        """A fingerprint of the view as the editor would edit it right now.

        Taken from the *combined* arch and deliberately not from
        ``_get_view()``. The combined arch is the tree every locator here is
        minted against, and it is the same for everybody: ``get_combined_arch``
        filters inheriting views only on ``active``. ``_get_view`` is a
        per-user projection -- nodes dropped by group rights, subviews grafted
        in, models patching the arch at read time -- so a version taken from
        it would differ between two people looking at one view and report
        "changed" to somebody who merely lacks a group. Language is the one
        per-user thing the combined arch does carry, so it is read in the
        source language (``_neutral_combined_arch``): two builders with two
        languages are still looking at one view.

        The id is folded in so that two views with identical archs -- a
        freshly scaffolded list and its copy -- do not share a version and let
        an edit meant for one be accepted against the other.
        """
        typed.security(self)._assert_studio_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        return self._version_of(cast("int", view.id), self._neutral_combined_arch(view))

    @api.model
    def _assert_arch_version(self, view: View, expected: str | None) -> None:
        """Refuse to edit a view that is not the one the client looked at.

        ``None`` means the caller made no claim -- a script, an older client
        -- and is not checked; a claim is checked exactly, before anything is
        written, so a stale gesture costs nothing to retry.
        """
        if expected is not None and expected != self.arch_version(cast("int", view.id)):
            raise StudioStaleView(self.env._(STALE_VIEW_MESSAGE))

    @api.model
    def _claimed_version(
        self, expected: str | None, *descriptors: dict[str, object] | None
    ) -> str | None:
        """The version an edit is checked against.

        The caller's explicit claim when it made one; otherwise the version
        a token descriptor carries. A token is an ordinal into one tree, and
        the descriptor says which tree by carrying ``arch_version`` -- so a
        caller that hands over such a descriptor and no separate claim has
        still made one, and a stale token must not quietly resolve to
        whatever node now sits at that ordinal.
        """
        if expected is not None:
            return expected
        for descriptor in descriptors:
            version = (descriptor or {}).get("arch_version")
            if version is not None:
                return cast("str", version)
        return None

    # -- public operations ------------------------------------------------

    @api.model
    def apply_operation(
        self,
        view_id: int,
        package_id: int,
        operation: dict[str, object],
        expected_arch_version: str | None = None,
        write_files: bool = True,
    ) -> OperationResultJSON:
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

        Every mutator funnels through here, which makes this the one place two
        guards need to live. ``expected_arch_version`` is the version the
        client's view of the arch was minted from (``arch_version``); when it
        is given and no longer current the edit is refused as stale before
        anything is touched. ``write_files=False`` records the edit and
        captures the view but leaves the disk alone, for a gesture made of
        several operations that wants the directory written once, at the end
        -- the caller then owes the package an ``action_write_files()``.
        """
        typed.security(self)._assert_studio_manager()
        base_view = typed.model(self.env, View).browse(view_id).exists()
        if not base_view:
            raise UserError(_("The view being edited no longer exists."))
        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this change in."))

        # `getattr` with a non-literal name is `Any` by construction (pyright
        # cannot know which `_op_*` method it names); every real handler
        # takes `(LxmlElement, dict[str, object]) -> LxmlElement`, but that
        # contract lives in each handler's own signature below, not here.
        handler = getattr(self, "_op_%s" % operation.get("type"), None)
        if handler is None:
            raise UserError(_("Unknown studio operation '%s'.", operation.get("type")))

        # Checked once, here, before any write -- including the creation of
        # the extension view below, which would otherwise survive a refusal.
        self._assert_arch_version(base_view, expected_arch_version)
        operation = dict(operation)
        expectations = {key: operation.pop(key, None) for key in EXPECTATION_KEYS}
        if operation.get("type") == "move_node":
            self._assert_move_is_sane(base_view, operation)

        if self._owns_outright(base_view, package):
            target = base_view
            created = False
            primary = xml_writer.parse_arch(cast("str", base_view.arch))
            self._assert_owned_locators(
                primary,
                operation,
                expectations,
                # `inherit_children_ids` is a bare (unsubscripted)
                # `One2many("ir.ui.view", ...)` -- core Odoo's own
                # declaration, not this migration's -- whose read type
                # pyright cannot resolve past `Unknown` with no stub
                # narrowing it; cast to the real recordset type, the same
                # plain-string-comodel idiom rule 5 already applies to a
                # `Many2one`.
                extended=bool(
                    cast("View", base_view.inherit_children_ids).filtered("active")
                ),
            )
            spec = cast("LxmlElement", etree.Element("data"))
            # A handler dedupes against the spec it is building, which is
            # enough on the extension path where the spec accumulates every
            # edit. Here the spec is empty every time, so a handler that cares
            # about "is this already there" has to be shown the arch it is
            # about to be merged into.
            operation["_current_arch"] = base_view.arch
            handler(spec, operation)
            # `apply_inheritance_specs` (`odoo/tools/template_inheritance.py`)
            # is a core function with no annotations of its own; its
            # parameters are untyped, so its inferred return is `Unknown` --
            # an accepted, pre-existing vendor gap (this migration's own
            # rule for a less-common core utility), cast to the real
            # `LxmlElement` it always returns.
            arch = cast("LxmlElement", apply_inheritance_specs(primary, spec))
        else:
            existing = self._find_extension(base_view, package)
            target = existing or self._get_or_create_extension(
                base_view, package, write_files=False
            )
            created = not existing
            arch = self._parse_data(target)
            handler(arch, operation)

        # Captured before the write, and including whether the target had to be
        # brought into existence -- undoing an edit that created the patch has
        # to remove it rather than leave an empty one behind.
        arch_before = "" if created else cast("str", target.arch)
        self._write_arch(target, arch)
        typed.model(self.env, StudioViewEdit).record(
            base_view,
            target,
            package,
            self._describe(operation),
            arch_before,
            created,
            arch_after=cast("str", target.arch),
        )
        package.studio_capture(target, write_files=False)
        # A view edit is live the moment the arch is written -- views are data,
        # there is no reload to wait for -- so the file has to keep up in the
        # same breath. Leaving it behind would report the package as drifted
        # while nothing was wrong, and the next reload from disk would quietly
        # undo the edit. Written once, here, after everything the operation
        # captured, so a failure anywhere above leaves nothing on disk.
        if write_files and package.writable:
            package.action_write_files()
        # Re-browsed so the combined arch is read after the write, not from
        # what was cached before it. The arch the client renders is in its
        # own language; the version it will edit against is not, or the
        # next call from a colleague in another language would refuse it.
        base_view = typed.model(self.env, View).browse(cast("int", base_view.id))
        return {
            "view_id": cast("int", target.id),
            "arch": cast("str", target.arch),
            "combined_arch": cast("str", base_view.get_combined_arch()),
            "arch_version": self._version_of(
                cast("int", base_view.id), self._neutral_combined_arch(base_view)
            ),
            # What the handler brought into being, by name, when it named
            # something: the caller that wants to select it next has no
            # other way to find a node it did not name itself.
            "created_name": cast("str | None", operation.get("_created_name")),
        }

    @api.model
    def _resolve_xpath(self, root: LxmlElement, expr: str) -> list[LxmlElement] | None:
        """The elements ``expr`` selects in ``root``; ``None`` if it is not an xpath."""
        try:
            found = etree.ETXPath(expr)(root)
        except etree.XPathError:
            return None
        if not isinstance(found, list):
            return None
        return [node for node in found if etree.iselement(node)]

    @api.model
    def _assert_move_is_sane(
        self, base_view: View, operation: dict[str, object]
    ) -> None:
        """Refuse a move core would turn into a crash rather than an error.

        With ``inside`` allowed, a node can be asked to move into one of its
        own descendants. Core extracts the moved subtree first -- taking the
        target with it -- and then tries to insert the node into that subtree,
        which lxml refuses with a bare exception. Both ends are resolved here
        against the combined arch, the tree the locators were minted from;
        when either does not resolve to exactly one node the guard stands
        aside and lets core's own, clearer error surface.
        """
        root = cast(
            "LxmlElement", etree.fromstring(base_view.get_combined_arch().encode())
        )
        source = self._resolve_xpath(root, cast("str", operation.get("xpath")) or "")
        target = self._resolve_xpath(
            root, cast("str", operation.get("target_xpath")) or ""
        )
        if not source or not target or len(source) != 1 or len(target) != 1:
            return
        if source[0] is target[0]:
            raise UserError(_("A node cannot be moved relative to itself."))
        if any(ancestor is source[0] for ancestor in target[0].iterancestors()):
            raise UserError(_("A node cannot be moved into itself."))

    @api.model
    def _assert_owned_locators(
        self,
        primary: LxmlElement,
        operation: dict[str, object],
        expectations: dict[str, object | None],
        extended: bool = True,
    ) -> None:
        """On the owned path, the locator must mean the same node in both trees.

        A locator is minted against the *combined* arch -- the view as it
        renders, other modules' extensions included -- but a view this package
        owns is edited by applying the spec to its *primary* arch, which has
        none of those extensions. A ``//field[@name]`` locator means the same
        thing in both. A positional one does not: another module inserting a
        sibling above the target shifts every index after it, so the same
        path names a different node in the primary arch, or none, and core's
        ``apply_inheritance_specs`` answers with a raw ``ValueError`` or --
        worse -- edits the wrong node without a word.

        So each locator has to select exactly one node here, and when the
        minting step said what it expected to find there, that node has to be
        it (``_matches_expectation``). Each way of falling short gets its own
        sentence: a path that finds nothing or several nodes is a fact about
        the locator, and only a node that resolved to something *else* is the
        foreign-extension case the sentence about other modules describes.

        ``extended`` says whether any other view inherits this one at all.
        When none does, the combined arch *is* the primary arch and a
        positional locator is exact by construction, so the expectation
        is not consulted -- it could only refuse a node it has no signal
        for, such as a bare group holding only unnamed children.
        """
        for key, expected in (
            ("xpath", expectations.get("_expect")),
            ("target_xpath", expectations.get("_expect_target")),
            ("label_xpath", expectations.get("_expect_label")),
        ):
            expr = cast("str | None", operation.get(key))
            if not expr:
                continue
            found = self._resolve_xpath(primary, expr)
            if found is None:
                raise UserError(_("'%s' is not an xpath the builder can apply.", expr))
            if not found:
                raise UserError(_("'%s' does not locate anything in this view.", expr))
            if len(found) > 1:
                raise UserError(
                    _(
                        "'%(expr)s' locates %(count)d nodes; the builder needs "
                        "exactly one.",
                        expr=expr,
                        count=len(found),
                    )
                )
            if extended and not self._matches_expectation(
                found[0], cast("NodeExpectationJSON | None", expected)
            ):
                raise UserError(
                    _(
                        "That element comes from another module's extension of "
                        "this view, so it cannot be edited in place here."
                    )
                )

    @api.model
    def _named_children(self, node: LxmlElement) -> tuple[tuple[str, str | None], ...]:
        """``(tag, name)`` of each direct child that carries a name.

        The fingerprint of a container that has no name of its own. Two
        unnamed sibling groups look identical by tag and label -- usually
        neither has a label -- but they hold different fields, and fields
        are named.
        """
        return tuple(
            (child.tag, child.get("name"))
            for child in node
            if isinstance(child.tag, str) and child.get("name")
        )

    @api.model
    def _identity(self, node: LxmlElement) -> str | None:
        """The value that names ``node`` -- the first identifying attribute
        it carries -- or ``None`` for a node known only by position."""
        for attr in IDENTIFYING_ATTRS:
            value = node.get(attr)
            if value:
                return value
        return None

    @api.model
    def _expectation_for(self, node: LxmlElement) -> NodeExpectationJSON:
        """What a locator minted for ``node`` should find where it is applied.

        ``name`` is the node's identity in the sense of ``IDENTIFYING_ATTRS``,
        so a kanban card -- ``<t t-name="card">``, with no ``name`` -- is
        expected by its template name rather than refused for having none.
        """
        return {
            "tag": cast("str", node.tag),
            "name": self._identity(node),
            "string": node.get("string"),
            "children": self._named_children(node),
        }

    @api.model
    def _matches_expectation(
        self, node: LxmlElement, expected: NodeExpectationJSON | None
    ) -> bool:
        """Whether ``node`` is the one the locator was minted for.

        Tag and name have to agree, and a name settles it: a named node is
        the node. An unnamed one -- a core notebook page, a bare group -- is
        known by two weaker signals, and *either* is enough. Its named
        children: a foreign ``position="attributes"`` can change the label
        of an owned page, and the page is still ours, with the same fields in
        it. Its label: a page whose children another module rearranged is
        still the page the user pointed at. What neither signal can excuse
        is a positional locator shifted by a foreign insertion, which lands
        on a *sibling*: same tag, no name, and a different set of fields
        under a different label -- or, for two bare groups, no label at all.
        An absent label is not a signal, or those two groups would always
        match each other on it -- and neither is an empty set of named
        children: two pages that each wrap their fields in an unnamed
        group have the same empty fingerprint and are still two pages.
        With no signal at all the node is refused; a view nothing else
        extends never gets this far (see ``_assert_owned_locators``).
        """
        if not expected:
            return True
        if node.tag != expected.get("tag") or self._identity(node) != expected.get(
            "name"
        ):
            return False
        if expected.get("name"):
            return True
        expected_children = tuple(map(tuple, expected.get("children") or ()))
        if expected_children and self._named_children(node) == expected_children:
            return True
        string = expected.get("string")
        return bool(string) and node.get("string") == string

    @api.model
    def _owns_outright(self, view: View, package: StudioPackage) -> bool:
        """Whether ``package`` may edit ``view``'s arch directly.

        Only a *primary* view the package already owns. An extension view is
        itself a patch and is always edited as one, and a view owned by another
        module must never be rewritten in place -- that is the Studio failure
        mode this project exists to avoid.
        """
        # Same `studio.owned.mixin` composed-elsewhere cast as
        # `_find_extension` above.
        return (
            view.mode == "primary"
            and cast("StudioPackage", cast("StudioOwnedMixin", view).studio_package_id)
            == package
        )

    @api.model
    def _new_xpath(self, root: LxmlElement, expr: str, position: str) -> LxmlElement:
        if position not in VALID_POSITIONS:
            raise UserError(_("'%s' is not a valid xpath position.", position))
        node = cast("LxmlElement", etree.SubElement(root, "xpath"))
        node.set("expr", expr)
        node.set("position", position)
        return node

    def _op_add_field(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Insert a field relative to an existing node.

        Adding the *same* field at the same anchor twice -- a double-click, a
        replayed request -- must be idempotent, or the field lands in the
        combined arch twice. Adding a *different* field at the same anchor must
        not be folded into the same block: two separate ``position="after"``
        blocks apply in sequence and read back in the order the user added
        them, whereas merging them into one block silently reverses that.
        """
        name = cast("str | None", operation.get("name"))
        if not name:
            raise UserError(_("Adding a field requires a field name."))
        position = cast("str", operation.get("position", "after"))
        expr = cast("str", operation["xpath"])
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
            if operation.get("label"):
                # Where the form draws no label, one of core's own goes
                # before the field -- in the same block, so the drop is
                # one edit and one undo. `_label_wanted` decides.
                label = cast("LxmlElement", etree.SubElement(node, "label"))
                label.set("for", name)
            field = cast("LxmlElement", etree.SubElement(node, "field"))
        field.set("name", name)
        for key, value in cast(
            "dict[str, object]", operation.get("attrs") or {}
        ).items():
            field.set(key, str(value))
        return node

    def _op_move_node(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Relocate an existing node, using core's own ``position="move"``.

        Core extracts the named node and re-inserts it at the anchor
        (``template_inheritance.py:45``), so this is a real move rather than a
        delete-and-recreate: attributes contributed by *other* inheriting views
        travel with it, which a recreate would silently drop.

        ``inside`` appends the node as the *last* child of the anchor: core
        plants its sentinel at the end of the target and inserts everything
        before it (``template_inheritance.py:302``), the same in 18, 19 and
        master. There is no "inside, at index n" -- a drop between two
        children is expressed as before/after one of them.
        """
        expr = cast("str | None", operation.get("xpath"))
        anchor = cast("str | None", operation.get("target_xpath"))
        position = cast("str", operation.get("position", "before"))
        if not expr or not anchor:
            raise UserError(_("Moving a node needs both what moves and where."))
        if position not in INSERT_POSITIONS:
            raise UserError(
                _(
                    "A node can move before, after or inside another, not '%s'.",
                    position,
                )
            )
        if expr == anchor:
            raise UserError(_("A node cannot be moved relative to itself."))
        node = self._new_xpath(root, anchor, position)
        # A field's label follows the field. Its own `<label for>` goes
        # with it, first, so it still stands just before the field -- core
        # inserts a spec's children in order for every position
        # (`template_inheritance.py`, the sentinel) -- unless the
        # destination is a group, which draws the label itself and would
        # draw it twice; then the label is dropped. A field a group was
        # labelling, moved to where nothing will, is given one.
        if operation.get("label_xpath") and not operation.get("drop_label"):
            label = cast("LxmlElement", etree.SubElement(node, "xpath"))
            label.set("expr", cast("str", operation["label_xpath"]))
            label.set("position", "move")
        elif operation.get("label") and operation.get("name"):
            label = cast("LxmlElement", etree.SubElement(node, "label"))
            label.set("for", cast("str", operation["name"]))
        moved = cast("LxmlElement", etree.SubElement(node, "xpath"))
        moved.set("expr", expr)
        moved.set("position", "move")
        if operation.get("label_xpath") and operation.get("drop_label"):
            self._new_xpath(root, cast("str", operation["label_xpath"]), "replace")
        return node

    def _op_add_filter(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Add a ``<filter>`` -- a saved condition, or a group-by.

        Group-bys are filters too; what makes one a group-by is a ``group_by``
        context *and* living inside the ``<group>``. Outside it the same node
        renders as an ordinary filter in the Filters menu, which is why the
        group is created here when the view has none rather than left to a
        second operation the user would have to understand.
        """
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        container = node
        if operation.get("in_new_group"):
            container = cast("LxmlElement", etree.SubElement(node, "group"))
            container.set(
                "string", cast("str", operation.get("group_string") or "Group By")
            )
        filter_node = cast("LxmlElement", etree.SubElement(container, "filter"))
        filter_node.set("name", cast("str", operation["name"]))
        filter_node.set(
            "string", cast("str", operation.get("string") or operation["name"])
        )
        if operation.get("domain"):
            filter_node.set("domain", cast("str", operation["domain"]))
        if operation.get("context"):
            filter_node.set("context", cast("str", operation["context"]))
        return node

    def _op_remove_node(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Remove a node from the rendered view.

        Emitted as ``position="replace"`` with empty content, which is the
        idiomatic Odoo way to drop a node without touching the base view.
        """
        expr = cast("str", operation["xpath"])
        existing = self._find_xpath(root, expr, "replace")
        if existing is not None:
            return existing
        node = self._new_xpath(root, expr, "replace")
        if operation.get("label_xpath"):
            # A field's own `<label for>` has nothing to label once the
            # field is gone, and would render as an empty label.
            self._new_xpath(root, cast("str", operation["label_xpath"]), "replace")
        return node

    def _op_set_attributes(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Set attributes on an existing node, merging with prior edits."""
        attrs = cast("dict[str, object]", operation.get("attrs") or {})
        if not attrs:
            raise UserError(_("No attributes given."))
        expr = cast("str", operation["xpath"])
        node = self._find_xpath(root, expr, "attributes")
        if node is None:
            node = self._new_xpath(root, expr, "attributes")
        for key, value in attrs.items():
            for existing in node.findall("attribute"):
                if existing.get("name") == key:
                    existing.text = None if value is None else str(value)
                    break
            else:
                child = cast("LxmlElement", etree.SubElement(node, "attribute"))
                child.set("name", key)
                if value is not None:
                    child.text = str(value)
        return node

    def _op_show_label(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Give a field the label the form would not draw for it.

        A field is labelled by the form compiler only as a direct child of
        an inner group; on a sheet, in a page, in a div or in columns it
        renders bare, whatever its ``string`` says. Core's own answer is a
        ``<label for="name"/>`` before it, which the compiler pairs with the
        field and renders with the field's label -- the ``string`` the view
        sets, or the model's. That is what is emitted, and nothing else:
        the label's text stays the field's, so the Label row goes on
        writing one attribute.

        A second label for the same field would render twice, so
        ``show_label_at`` refuses one the combined arch already has. Not
        checked against the spec being built: a label this extension added
        and then removed is still in it, and would wrongly count.
        """
        name = cast("str | None", operation.get("name"))
        if not name:
            raise UserError(_("Giving a field a label requires its name."))
        current = operation.get("_current_arch")
        if current is not None:
            primary = xml_writer.parse_arch(cast("str", current))
            if any(label.get("for") == name for label in primary.iter("label")):
                raise UserError(_("%s already has a label of its own.", name))
        node = self._new_xpath(root, cast("str", operation["xpath"]), "before")
        label = cast("LxmlElement", etree.SubElement(node, "label"))
        label.set("for", name)
        return node

    @api.model
    def _container_name(self, kind: str, given: str | None = None) -> str:
        """A name for a container the studio creates, when the user gave none.

        Every container gets one so that it can be *addressed* later. A
        ``<group>`` with no name is only reachable by position, and a
        positional path is the fragile kind: it shifts the moment anything is
        inserted above it, and it means a different node in the primary arch
        than in the combined one as soon as another module extends the view.
        ``//group[@name='studio_group_a1b2c3']`` means the same thing
        everywhere. Random rather than sequential so two packages extending
        the same view, or two people, never mint the same name.
        """
        return given or "studio_%s_%s" % (kind, secrets.token_hex(3))

    def _op_add_group(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        group = cast("LxmlElement", etree.SubElement(node, "group"))
        group.set(
            "name",
            self._container_name("group", cast("str | None", operation.get("name"))),
        )
        if operation.get("string"):
            group.set("string", cast("str", operation["string"]))
        operation["_created_name"] = group.get("name")
        return node

    def _op_add_page(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Add a notebook tab, creating the notebook when there is none.

        Same reasoning as the group a filter lands in: a tab with nowhere to
        live is not a second operation the user should have to understand.
        """
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        container = node
        if operation.get("in_new_notebook"):
            container = cast("LxmlElement", etree.SubElement(node, "notebook"))
            container.set("name", self._container_name("notebook"))
        page = cast("LxmlElement", etree.SubElement(container, "page"))
        page.set(
            "string", cast("str", operation.get("string") or self.DEFAULT_PAGE_STRING)
        )
        page.set(
            "name",
            self._container_name("page", cast("str | None", operation.get("name"))),
        )
        operation["_created_name"] = page.get("name")
        return node

    def _op_add_button(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        button = cast("LxmlElement", etree.SubElement(node, "button"))
        button.set("name", cast("str", operation["name"]))
        button.set("type", cast("str", operation.get("button_type", "object")))
        if operation.get("string"):
            button.set("string", cast("str", operation["string"]))
        if operation.get("class"):
            button.set("class", cast("str", operation["class"]))
        operation["_created_name"] = button.get("name")
        return node

    def _op_add_columns(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Add two side-by-side columns: an outer group holding two groups.

        That is what "Columns" on the palette means in a form, and it is one
        operation on purpose. Three groups added one at a time would be
        three history entries and three file writes for one gesture, and an
        outer group that exists for a moment with nothing in it renders as
        a stray gap. Every group is named so each column can be pointed at
        again.
        """
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        outer = cast("LxmlElement", etree.SubElement(node, "group"))
        outer.set(
            "name",
            self._container_name("group", cast("str | None", operation.get("name"))),
        )
        if operation.get("string"):
            outer.set("string", cast("str", operation["string"]))
        for _column in range(2):
            inner = cast("LxmlElement", etree.SubElement(outer, "group"))
            inner.set("name", self._container_name("group"))
        operation["_created_name"] = outer.get("name")
        return node

    # The text a component carries when the user gave none. Source-language
    # literals on purpose, never `_()`: they are written into the arch and
    # the file on disk, and the source a gesture produces must not depend on
    # which language the builder happened to be logged in with. Translating
    # a view's strings is the view's own job, once it is source.
    DEFAULT_PAGE_STRING = "New tab"
    DEFAULT_SEPARATOR_STRING = "Separator"
    DEFAULT_LABEL_STRING = "Label"

    def _op_add_notebook(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Add a notebook with one tab in it.

        An empty notebook renders as nothing at all -- no tab strip, no
        outline -- so the user who just dropped one would see no change and
        drop another. The first tab is what makes it visible and gives the
        next drop somewhere to land.
        """
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        notebook = cast("LxmlElement", etree.SubElement(node, "notebook"))
        notebook.set(
            "name",
            self._container_name("notebook", cast("str | None", operation.get("name"))),
        )
        page = cast("LxmlElement", etree.SubElement(notebook, "page"))
        page.set(
            "string", cast("str", operation.get("string") or self.DEFAULT_PAGE_STRING)
        )
        page.set("name", self._container_name("page"))
        operation["_created_name"] = notebook.get("name")
        return node

    def _op_add_separator(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Add a titled rule between two blocks of a form.

        Named, although a separator never needs one for itself: the name
        is how the console selects it after the drop, and how a later edit
        addresses it without counting its siblings.
        """
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        separator = cast("LxmlElement", etree.SubElement(node, "separator"))
        separator.set(
            "string",
            cast("str", operation.get("string") or self.DEFAULT_SEPARATOR_STRING),
        )
        separator.set(
            "name",
            self._container_name(
                "separator", cast("str | None", operation.get("name"))
            ),
        )
        operation["_created_name"] = separator.get("name")
        return node

    def _op_add_chatter(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """A ``<chatter/>`` after the sheet, the way every core form has it."""
        node = self._new_xpath(root, cast("str", operation["xpath"]), "after")
        etree.SubElement(node, "chatter")
        return node

    def _op_add_label(
        self, root: LxmlElement, operation: dict[str, object]
    ) -> LxmlElement:
        """Add a piece of static text styled as a label.

        Not a ``<label>``: core's validator refuses one without a ``for``
        (``_validate_tag_label``), and there is no field for it to point
        at -- the whole point is text that stands on its own. The
        validator's own message names the alternative, a node carrying
        ``class="o_form_label"``, and a ``<div>`` is the smallest one the
        form compiler renders as-is. Named for the same reason a separator
        is.
        """
        node = self._new_xpath(
            root,
            cast("str", operation["xpath"]),
            cast("str", operation.get("position", "inside")),
        )
        label = cast("LxmlElement", etree.SubElement(node, "div"))
        label.set("class", "o_form_label")
        label.set(
            "name",
            self._container_name("label", cast("str | None", operation.get("name"))),
        )
        label.text = cast("str", operation.get("string") or self.DEFAULT_LABEL_STRING)
        operation["_created_name"] = label.get("name")
        return node

    # -- helpers for the client -------------------------------------------

    @api.model
    def _occurrences(self, root: LxmlElement) -> Counter[tuple[str, str, str]]:
        """How many nodes answer to each ``(tag, name)`` pair.

        A bare ``//tag[@name='x']`` is only a valid locator when nothing else in
        the arch answers to it. An embedded x2many subview routinely repeats the
        parent's field names, and ``locate_node`` silently takes the first match
        -- so without this count an edit aimed at a sublist column patches the
        sheet instead, for the wrong model.
        """
        return Counter(
            (cast("str", el.tag), attr, cast("str", el.get(attr)))
            for el in root.iter()
            if isinstance(el.tag, str)
            for attr in IDENTIFYING_ATTRS
            if el.get(attr)
        )

    @api.model
    def _locator_for(
        self, node: LxmlElement, occurrences: Counter[tuple[str, str, str]]
    ) -> str:
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
        for attr in IDENTIFYING_ATTRS:
            value = node.get(attr)
            if value and occurrences[(cast("str", node.tag), attr, value)] == 1:
                return "//%s[@%s='%s']" % (node.tag, attr, value)
        return node.getroottree().getpath(node)

    @api.model
    def apply_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        operation: dict[str, object],
        expected_arch_version: str | None = None,
        write_files: bool = True,
    ) -> OperationResultJSON:
        """Apply an operation relative to a node the client picked by descriptor.

        The one entry point for every structural edit -- adding a field, a
        button, a tab, a group, or removing any of them. It exists so the client
        keeps its side of the bargain: it says *what was selected*, and the
        xpath is minted here against the combined arch. A browser that computed
        its own locator would produce one derived from a per-user projection,
        which is right for that user and wrong for the next.

        ``position`` is decided here too, from what kind of thing was selected,
        unless the operation already names one: a container takes a child, a
        leaf takes a sibling. A click has no better information than that; a
        drop does -- "before this field" is exactly what the pointer said --
        and the drop names it. Left to guess in both cases, the same gesture
        would behave differently depending on which button sent it.

        Along with the locator goes what was found at it -- tag, name, label
        -- so that the owned path can check the primary arch it is about to
        edit has the same node there (see ``_assert_owned_locators``).

        The version is checked before the anchor is resolved: a token is an
        ordinal, and resolving a stale one on the current tree gives back a
        node -- the wrong one -- rather than nothing. ``apply_operation``
        checks it again, which costs a hash and keeps the raw-locator path
        guarded by the same line.
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        expected_arch_version = self._claimed_version(expected_arch_version, anchor)
        self._assert_arch_version(view, expected_arch_version)
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        node, stamped, token = self._find_node_entry(root, anchor)
        if node is None:
            raise UserError(
                _("That is not a place in the view the builder can address.")
            )
        operation = dict(operation)
        occurrences = self._occurrences(root)
        operation["xpath"] = self._locator_for(node, occurrences)
        operation["_expect"] = self._expectation_for(node)
        operation.setdefault(
            "position",
            # `_find_node_entry` only ever returns `stamped`/`token`
            # together, never one without the other (its own docstring) --
            # a correlation a flat 3-tuple return can't state to pyright,
            # so `token` is cast here rather than adding a second `token`
            # check that would (harmlessly, but not byte-for-byte) change
            # what a violated invariant does at runtime.
            self._insert_position(
                anchor,
                stamped and stamped.nodes[cast("canvas_stamp.Token", token)],
            ),
        )
        if operation.get("type") == "add_field":
            operation.setdefault(
                "label",
                self._label_wanted(view, node, cast("str", operation["position"])),
            )
        elif operation.get("type") == "remove_node":
            label = self._own_label(node)
            if label is not None:
                operation["label_xpath"] = self._locator_for(label, occurrences)
                operation["_expect_label"] = self._expectation_for(label)
        return self.apply_operation(
            view_id,
            package_id,
            operation,
            expected_arch_version=expected_arch_version,
            write_files=write_files,
        )

    @api.model
    def _explicit_position(self, position: object) -> str | None:
        """A position the caller named for an insertion, checked, or ``None``.

        Refused rather than ignored when it is not one of the three: an
        editor that quietly puts something somewhere other than where it was
        asked to is the arbitrary kind.
        """
        if position is None:
            return None
        if position not in INSERT_POSITIONS:
            raise UserError(
                _(
                    "Something new goes before, after or inside a node, not '%s'.",
                    position,
                )
            )
        return cast("str", position)

    @api.model
    def add_chatter(
        self, view_id: int, package_id: int, expected_arch_version: str | None = None
    ) -> bool:
        """Give a form the messaging pane, once the model has the mixins.

        After the sheet -- or, on a form without one, at the end -- as
        every core form does it. A form that already has one is left
        alone: a second chatter is not a stronger one.
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view or view.type != "form":
            raise UserError(_("Only a form has a chatter."))
        model = self.env.get(cast("str", view.model))
        if model is None or "message_ids" not in model._fields:
            raise UserError(
                _(
                    "%s does not carry messaging yet; the chatter needs the "
                    "mail mixins on the model first.",
                    view.model,
                )
            )
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        if root.find(".//chatter") is not None:
            return False
        sheet = root.find("./sheet")
        anchor = sheet if sheet is not None else list(root)[-1] if len(root) else None
        if anchor is None:
            raise UserError(_("The form is empty; put something on it first."))
        occurrences = self._occurrences(root)
        self.apply_operation(
            view_id,
            package_id,
            {
                "type": "add_chatter",
                "xpath": self._locator_for(anchor, occurrences),
                "position": "after",
                "_expect": self._expectation_for(anchor),
            },
            expected_arch_version=expected_arch_version,
        )
        return True

    @api.model
    def show_label_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        expected_arch_version: str | None = None,
    ) -> OperationResultJSON:
        """Put a ``<label for>`` before the field the client selected.

        The properties panel's "Show label" switch, for a field the form
        draws no label for. The switch the other way is ``remove_at`` on
        the label's own token -- the canvas table names it (``label.token``)
        -- and for a field in a group, where the compiler draws the label
        itself, both directions are the ``nolabel`` attribute and never
        come here.
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        expected_arch_version = self._claimed_version(expected_arch_version, anchor)
        self._assert_arch_version(view, expected_arch_version)
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        node = self._find_descriptor(root, anchor)
        if node is None or node.tag != "field" or not node.get("name"):
            raise UserError(_("Only a field can be given a label."))
        if view.type != "form":
            raise UserError(_("Only a form draws labels for its fields."))
        name = node.get("name")
        if any(
            label.get("for") == name
            for label in root.iter("label")
            if not any(a.tag == "field" for a in label.iterancestors())
        ):
            raise UserError(_("%s already has a label of its own.", name))
        return self.apply_operation(
            view_id,
            package_id,
            {
                "type": "show_label",
                "name": name,
                "xpath": self._locator_for(node, self._occurrences(root)),
                "position": "before",
                "_expect": self._expectation_for(node),
            },
            expected_arch_version=expected_arch_version,
        )

    @api.model
    def add_field_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        field_name: str,
        position: str | None = None,
        attrs: dict[str, object] | None = None,
        expected_arch_version: str | None = None,
    ) -> OperationResultJSON:
        """Put an existing field of the model into the view.

        The gap this closes is the largest one the builder had: a field could be
        *created* on any model and then placed only into views the package owned
        outright, which excluded every core screen -- so adding a field to the
        quotation form, the most ordinary Studio gesture there is, had no path
        through the UI at all. The server could always emit the inheriting
        ``<xpath>`` for it; nothing asked.

        ``attrs`` land on the new ``<field>`` in the same operation -- a
        preset that comes with its widget is one change to the user and one
        entry in the history, not "added a field" followed by "changed
        widget".
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        if field_name not in self.env[cast("str", view.model)]._fields:
            raise UserError(
                _(
                    "%(field)s is not a field of %(model)s.",
                    field=field_name,
                    model=view.model,
                )
            )
        operation: dict[str, object] = {"type": "add_field", "name": field_name}
        if attrs:
            operation["attrs"] = dict(attrs)
        position = self._explicit_position(position)
        if position:
            operation["position"] = position
        # Otherwise `apply_at` decides from the anchor: a container takes a
        # child, a leaf a sibling -- which for a list, where every field is
        # a column of the root, is the only reading there is.
        return self.apply_at(
            view_id,
            package_id,
            anchor,
            operation,
            expected_arch_version=expected_arch_version,
        )

    @api.model
    def remove_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        expected_arch_version: str | None = None,
        force: bool = False,
    ) -> OperationResultJSON:
        """Take the selected node out of the view.

        Emitted as ``position="replace"`` with nothing in it, which is how a
        view drops a node it inherits without touching the view that declares
        it. Distinct from hiding: an invisible field is still there and still
        loads, which is usually what somebody actually wants -- so the UI offers
        both and says which is which.

        A container with something in it is not removed on the first ask.
        Removing a group removes every field in it, and a click on the wrong
        outline would take a dozen fields with it; so the refusal is a
        ``StudioConfirmRequired`` naming the count, the client asks the user,
        and comes back with ``force`` when they say yes. Undo covers the
        rest. What counts as "in it" is what the node table lists: the rows
        of an embedded subview are not nodes the user can see or select,
        so a one2many field is a leaf and needs no confirmation.

        What the table says stays where it is -- a sheet, a header, the
        root -- is refused whatever ``force`` says: the client hides the
        button for those, and the server keeps the same rule for a caller
        that did not.
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        expected_arch_version = self._claimed_version(expected_arch_version, anchor)
        # Before the node is looked at: a stale token resolves to some node,
        # and the question asked about it would be about the wrong one.
        self._assert_arch_version(view, expected_arch_version)
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        _node, stamped, token = self._find_node_entry(root, anchor, stamp=True)
        if stamped is not None:
            # Same correlated-tuple cast as `apply_at`'s own `stamped and
            # stamped.nodes[...]` -- `_find_node_entry` never returns
            # `stamped` without `token`.
            entry = stamped.nodes[cast("canvas_stamp.Token", token)]
            if not entry["removable"]:
                raise UserError(
                    _(
                        "The %s stays where it is; it is not something to "
                        "remove from the view.",
                        self._describe_kind(entry["kind"]),
                    )
                )
            inside = canvas_stamp.descendants(
                stamped.nodes, cast("canvas_stamp.Token", token)
            )
            if inside and not force:
                fields = [
                    t for t in inside if stamped.nodes[t]["kind"] in ("field", "column")
                ]
                raise StudioConfirmRequired(
                    self._confirm_removal(entry["kind"], len(inside), len(fields)),
                    count=len(inside),
                    fields=len(fields),
                )
        return self.apply_at(
            view_id,
            package_id,
            anchor,
            {"type": "remove_node", "position": "replace"},
            expected_arch_version=expected_arch_version,
        )

    @api.model
    def add_button_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        values: dict[str, object],
        position: str | None = None,
        expected_arch_version: str | None = None,
        write_files: bool = True,
    ) -> OperationResultJSON:
        """Add a button that runs a server action.

        Restricted to server actions on purpose. The alternative Odoo Studio
        offers -- name any Python method -- writes a call to something that may
        not exist, and the view happily saves: the failure arrives later, for
        whoever presses it. A server action is a record, so the reference is
        checked when it is chosen and travels with the package.
        """
        typed.security(self)._assert_studio_manager()
        action = (
            typed.model(self.env, IrActionsServer)
            .browse(cast("int", values.get("action_id") or 0))
            .exists()
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
        xmlid = cast("str", action.get_external_id().get(cast("int", action.id)))
        if not xmlid:
            raise UserError(
                _(
                    "%(name)s has no external ID, so a button naming it could "
                    "not survive being loaded into another database. Assign the "
                    "action to a studio package first.",
                    name=action.display_name,
                )
            )
        operation: dict[str, object] = {
            "type": "add_button",
            "name": xmlid,
            "button_type": "action",
            "string": values.get("string") or action.name,
            "class": values.get("class") or "btn-secondary",
        }
        position = self._explicit_position(position)
        if position:
            operation["position"] = position
        return self.apply_at(
            view_id,
            package_id,
            anchor,
            operation,
            expected_arch_version=expected_arch_version,
            write_files=write_files,
        )

    @api.model
    def add_container_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        kind: str,
        string: str | None = None,
        position: str | None = None,
        expected_arch_version: str | None = None,
    ) -> OperationResultJSON:
        """Add a tab or a group -- the two structural pieces a form is made of."""
        typed.security(self)._assert_studio_manager()
        position = self._explicit_position(position)
        if kind == "group":
            operation: dict[str, object] = {"type": "add_group", "string": string or ""}
            if position:
                operation["position"] = position
            return self.apply_at(
                view_id,
                package_id,
                anchor,
                operation,
                expected_arch_version=expected_arch_version,
            )
        if kind != "page":
            raise UserError(_("The builder does not add '%s'.", kind))

        # A page is only legal inside a notebook -- `_validate_tag_page` refuses
        # anything else outright -- so "add a tab" has to mean "add a tab to the
        # notebook", and provide the notebook when there is none. Making the
        # user create the notebook first would be asking them to know a rule the
        # builder already knows, and the failure if they did not would arrive as
        # a validation error about ancestors.
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        # The claim a token anchor carries is settled here, before the
        # token is resolved: the notebook rule below may re-anchor on the
        # notebook itself, and that second descriptor carries no version
        # of its own to be checked against.
        expected_arch_version = self._claimed_version(expected_arch_version, anchor)
        self._assert_arch_version(view, expected_arch_version)
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        operation: dict[str, object] = {"type": "add_page", "string": string or ""}
        if position:
            operation["position"] = position
        # What the anchor is: said outright by a legacy descriptor, and by
        # the node a token resolves to -- a token pointing at a notebook is
        # "the notebook" as much as `{"kind": "notebook"}` is.
        anchor_kind = anchor.get("kind")
        if anchor_kind == "node":
            node = self._find_descriptor(root, anchor)
            anchor_kind = node.tag if node is not None else None
        # A tab dropped next to another tab is the one case the anchor says
        # exactly where: a page beside a page is inside the same notebook.
        beside_a_page = position and anchor_kind == "page"
        if anchor_kind == "notebook" or beside_a_page:
            return self.apply_at(
                view_id,
                package_id,
                anchor,
                operation,
                expected_arch_version=expected_arch_version,
            )
        notebook = next(
            (
                node
                for node in root.iter("notebook")
                if not any(a.tag == "field" for a in node.iterancestors())
            ),
            None,
        )
        if notebook is not None:
            operation["position"] = "inside"
            return self.apply_at(
                view_id,
                package_id,
                {"kind": "notebook"},
                operation,
                expected_arch_version=expected_arch_version,
            )
        operation["in_new_notebook"] = True
        return self.apply_at(
            view_id,
            package_id,
            anchor,
            operation,
            expected_arch_version=expected_arch_version,
        )

    @api.model
    def move_node(
        self,
        view_id: int,
        package_id: int,
        source: dict[str, object],
        target: dict[str, object],
        position: str = "before",
        expected_arch_version: str | None = None,
        write_files: bool = True,
    ) -> OperationResultJSON:
        """Reorder by descriptor, resolving both ends server-side.

        The client says "this column goes before that one" and never computes a
        locator, for the same reason it never computes one when selecting: the
        arch it can see is a per-user projection.

        A node cannot go into its own subtree: core would extract it -- target
        and all -- and then try to put it inside what it just removed. Refused
        here, where both nodes are in hand, and again in ``apply_operation``
        for a caller that arrives with raw locators.

        Either end may carry the version its token was minted on, and each
        is checked before anything is resolved: two tokens from two
        loadings of the view are two claims, and one stale one is enough.
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        for descriptor in (source, target):
            self._assert_arch_version(
                view, self._claimed_version(expected_arch_version, descriptor)
            )
        expected_arch_version = self._claimed_version(
            expected_arch_version, source, target
        )
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        occurrences = self._occurrences(root)
        source_node = self._find_descriptor(root, source)
        target_node = self._find_descriptor(root, target)
        if source_node is None or target_node is None:
            raise UserError(
                _("One end of that move is not a node the builder can address.")
            )
        if source_node is target_node:
            raise UserError(_("A node cannot be moved relative to itself."))
        if any(ancestor is source_node for ancestor in target_node.iterancestors()):
            raise UserError(_("A node cannot be moved into itself."))
        operation: dict[str, object] = {
            "type": "move_node",
            "xpath": self._locator_for(source_node, occurrences),
            "target_xpath": self._locator_for(target_node, occurrences),
            "position": position,
            "_expect": self._expectation_for(source_node),
            "_expect_target": self._expectation_for(target_node),
        }
        # A field's label follows the field (see `_op_move_node`).
        label = self._own_label(source_node)
        if label is not None and label is not target_node:
            operation["label_xpath"] = self._locator_for(label, occurrences)
            operation["_expect_label"] = self._expectation_for(label)
            operation["drop_label"] = not self._label_wanted(
                view, target_node, position
            )
        elif source_node.tag == "field" and self._labelled_by_group(source_node):
            operation["name"] = source_node.get("name")
            operation["label"] = self._label_wanted(view, target_node, position)
        return self.apply_operation(
            view_id,
            package_id,
            operation,
            expected_arch_version=expected_arch_version,
            write_files=write_files,
        )

    @api.model
    def _label_wanted(self, view: View, node: LxmlElement, position: str) -> bool:
        """Whether a field put at ``position`` of ``node`` needs a label of
        its own to have one at all.

        The form compiler labels a field only as a direct child of an
        inner group (``canvas_stamp.draws_label``). Everywhere else --
        the sheet, a tab, columns, a div -- it renders bare, whatever its
        ``string`` says, and the studio's default is that a field dropped
        there is labelled the way core's own views do it: ``<label for>``
        before it. Two places are bare on purpose and get none: the header,
        whose field is a status bar, and the button box.
        """
        if view.type != "form":
            return False
        parent = node if position == "inside" else node.getparent()
        if parent is None or canvas_stamp.draws_label(parent):
            return False
        bare_on_purpose = parent.tag == "header" or (
            parent.tag == "div" and parent.get("name") == "button_box"
        )
        return not bare_on_purpose

    @api.model
    def _labelled_by_group(self, node: LxmlElement) -> bool:
        """Whether the form draws ``node``'s label because of its group."""
        return (
            bool(node.get("name"))
            and canvas_stamp.draws_label(node.getparent())
            and node.get("nolabel") not in canvas_stamp.INVISIBLE_LITERALS
        )

    @api.model
    def _own_label(self, node: LxmlElement) -> LxmlElement | None:
        """The ``<label for>`` immediately before ``node`` naming it, or ``None``."""
        if node.tag != "field" or not node.get("name"):
            return None
        previous = node.getprevious()
        while previous is not None and not isinstance(previous.tag, str):
            previous = previous.getprevious()
        if (
            previous is not None
            and previous.tag == "label"
            and previous.get("for") == node.get("name")
        ):
            return previous
        return None

    # -- the drop -----------------------------------------------------------

    # The operation each palette component becomes. A button is not here: it
    # goes through `add_button_at`, which checks the server action it names.
    COMPONENT_OPS = {
        "group": "add_group",
        "columns": "add_columns",
        "page": "add_page",
        "notebook": "add_notebook",
        "separator": "add_separator",
        "label": "add_label",
    }

    @api.model
    def drop_at(
        self,
        view_id: int,
        package_id: int,
        target: dict[str, object],
        payload: dict[str, object],
        expected_arch_version: str | None = None,
        canvas_options: dict[str, object] | None = None,
    ) -> DropAtJSON:
        """One drop on the canvas: one call, one transaction, one file write.

        ``target`` is ``{token, position}`` -- the node the pointer was
        over and which side of it -- and ``payload`` says what was dragged:
        a field the model already has, a component from the palette, or a
        node of the view being moved. The token is resolved against the
        combined arch the way every descriptor is, and the drop is checked
        against ``canvas_stamp.ACCEPTS`` before anything is minted, so a
        tab dropped on a group is refused with a sentence rather than with
        a validation error about ancestors after the fact.

        The version is checked once, here, and a stale one is *not* an
        error: the client cannot act on it except by reloading, so the
        answer is the fresh canvas with ``stale`` set and the gesture is
        simply asked for again. Every other mutator keeps raising, since
        their callers hold state a silent reload would lose.

        The operations themselves run with the disk gate closed and the
        package is written once, at the end -- a drop that fails halfway
        leaves nothing on disk. The answer carries the regenerated canvas
        and the token of what was dropped, so the client can select it
        without a second round trip.

        ``new_field`` and ``move_pending`` are a field that does not exist
        yet -- created live, or staged on a draft and anchored here -- and
        go through ``_drop_field_definition`` once the target has passed
        the same checks as every other drop.

        The target can be a ghost -- ``p_<name>``, a field staged on the
        user's draft and drawn on the canvas -- since the gap beside one
        is a place the user can point at. The ghosts are spliced into the
        stamped tree the way the canvas splices them, so the token resolves
        and the container check is the same. What lands there depends on
        what was dropped: another field that does not exist yet is anchored
        on the ghost itself, so two ghosts keep the order they were dropped
        in; anything real goes beside the nearest real sibling, the ghost
        not being in the arch to be beside -- and the ghosts of that gap
        are then re-anchored on what landed (``_reanchor_gap``), so the
        canvas keeps showing the order the gesture asked for and Apply
        writes that same order.
        """
        typed.security(self)._assert_studio_manager()
        composed = cast("_ComposedViewEditor", self)
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this change in."))
        # The canvas handed back reports this package's extension as the
        # source, whichever package happens to own the view.
        canvas_options = dict(canvas_options or {}, package_id=package.id)
        expected_arch_version = self._claimed_version(
            expected_arch_version, target, payload
        )
        if (
            expected_arch_version is not None
            and expected_arch_version != self.arch_version(cast("int", view.id))
        ):
            return {
                "stale": True,
                "canvas": composed.canvas(cast("int", view.id), canvas_options),
            }

        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        stamped = canvas_stamp.stamp(root, cast("str", view.type))
        target = dict(target or {})
        draft: BaseModel | None = None
        if str(target.get("token") or "").startswith(composed.PENDING_TOKEN_PREFIX):
            draft = composed._canvas_draft(view, canvas_options.get("draft_id"))
            composed._splice_pending(
                stamped, root, view, draft, self.arch_version(cast("int", view.id))
            )
        token, position, container = self._drop_target(stamped, target)
        payload = dict(payload or {})
        moved = self._moved_node(stamped, payload)
        gesture: tuple[canvas_stamp.Token, str] | None = None
        if stamped.nodes[token]["kind"] == "pending" and payload.get("kind") not in (
            "new_field",
            "move_pending",
        ):
            # The gesture as made, kept so the ghosts can be re-anchored
            # around what lands; the drop itself goes beside a real node.
            gesture = (token, position)
            token, position = self._beside_ghost(
                stamped,
                token,
                position,
                skip=cast("canvas_stamp.Token | None", payload.get("token"))
                if moved
                else None,
            )
            container = stamped.nodes[
                cast(
                    "canvas_stamp.Token",
                    token if position == "inside" else stamped.nodes[token]["parent"],
                )
            ]
        tag = canvas_stamp.payload_tag(payload, moved_tag=moved and moved["tag"])
        if not tag:
            raise UserError(
                _("'%s' is not something the builder can drop.", payload.get("kind"))
            )
        if not container["container"] or tag not in container["accepts"]:
            raise UserError(self._drop_refusal(tag, container))
        if payload.get("kind") in ("new_field", "move_pending"):
            return composed._drop_field_definition(
                view,
                package,
                stamped,
                root,
                token,
                position,
                container,
                payload,
                canvas_options,
            )

        name, select_tag = self._apply_drop(
            view, package, {"kind": "node", "token": token}, position, payload, moved
        )
        if gesture:
            self._reanchor_gap(
                view, draft, stamped, gesture, name, select_tag, container
            )
        if package.writable:
            package.action_write_files()
        canvas = composed.canvas(cast("int", view.id), canvas_options)
        return {
            "stale": False,
            "select": self._token_named(
                canvas["nodes"],
                name,
                select_tag,
                within=(container["tag"], container["name"]),
            ),
            "created": None,
            "staged": None,
            "canvas": canvas,
            "history": canvas["history"],
            "draft": None,
        }

    @api.model
    def _drop_target(
        self, stamped: canvas_stamp.StampResult, target: dict[str, object]
    ) -> tuple[canvas_stamp.Token, str, canvas_stamp.StudioNode]:
        """Resolve a drop target to ``(token, position, container node)``.

        The container is what the drop is checked against: the target
        itself for ``inside``, its parent for either side of it. The root
        has no side to be dropped on.
        """
        position = self._explicit_position(target.get("position"))
        if not position:
            raise UserError(_("A drop has to say before, after or inside what."))
        token = cast("canvas_stamp.Token", target.get("token"))
        if token not in stamped.nodes:
            raise UserError(
                _("That is not a place in the view the builder can address.")
            )
        if position == "inside":
            return token, position, stamped.nodes[token]
        parent = stamped.nodes[token]["parent"]
        if parent is None:
            raise UserError(_("Nothing goes beside the view itself; drop it inside."))
        return token, position, stamped.nodes[parent]

    @api.model
    def _beside_ghost(
        self,
        stamped: canvas_stamp.StampResult,
        token: canvas_stamp.Token,
        position: str,
        skip: canvas_stamp.Token | None = None,
    ) -> tuple[canvas_stamp.Token, str]:
        """The real place a drop beside a ghost stands for: ``(token,
        position)`` on the nearest real sibling, or inside the parent when
        the ghost has none.

        A drop "after the ghost" is a drop before whatever real node comes
        next, and after the real node before it when nothing real follows;
        "before the ghost" the other way round. Which side of the *ghost*
        the node ends up on is not decided here: the ghosts are re-anchored
        around what landed by ``_reanchor_gap``. ``skip`` is the token of
        the node being moved, when the drop is a move: it is not a sibling
        to go beside, since it is about to leave its place, and a move
        relative to itself is refused.
        """
        node = stamped.nodes[token]
        siblings = stamped.nodes[cast("canvas_stamp.Token", node["parent"])]["children"]
        index = siblings.index(token)

        def real(t: canvas_stamp.Token) -> bool:
            return stamped.nodes[t]["kind"] != "pending" and t != skip

        following = [t for t in siblings[index + 1 :] if real(t)]
        preceding = [t for t in siblings[:index] if real(t)]
        if position == "after":
            if following:
                return following[0], "before"
            if preceding:
                return preceding[-1], "after"
        else:
            if preceding:
                return preceding[-1], "after"
            if following:
                return following[0], "before"
        return cast("canvas_stamp.Token", node["parent"]), "inside"

    @api.model
    def _reanchor_gap(
        self,
        view: View,
        draft: BaseModel | None,
        stamped: canvas_stamp.StampResult,
        gesture: tuple[canvas_stamp.Token, str],
        name: str | None,
        tag: str | None,
        container: canvas_stamp.StudioNode,
    ) -> bool:
        """Hang the ghosts of a gap off the real node that just landed in it.

        ``gesture`` is the drop as made -- ``(ghost token, position)`` on
        the stamped tree the ghosts were spliced into -- and ``name``/``tag``
        what ``_apply_drop`` put beside the nearest real sibling. The gap
        is the run of consecutive ghosts the target belongs to, and the
        gesture point splits it in two: the ghosts before it, and those
        after. The new node sits between the two on the canvas only if
        every anchor on the first side resolves before it and every one
        on the second resolves after it, which nothing about the old
        anchors guarantees: a ghost "after x_budget" and one "before
        x_partner_id" stand at the same gap, and whichever real node the
        drop went beside, one of the two now resolves on the wrong side of
        it. So neither side keeps what it had. Each side becomes a chain
        hanging off the new node in the order the canvas showed -- the
        last ghost before the point "before <new>", the one before it
        "before" that ghost, and so on; the first ghost after the point
        "after <new>", the next "after" that one -- which is correct by
        construction and stays so on Apply, where a field anchored on a
        pending neighbour has the neighbour placed first.

        Re-anchored innermost first, so every pending anchor names a ghost
        given its sequence a moment earlier; dependents are not released,
        since every dependent of a gap ghost is in the gap -- an anchor on
        a ghost places the field right beside it -- and gets its own new
        anchor here. A new node the fresh stamp cannot find by name is
        left alone: the ghosts then keep their old anchors, which is the
        order before this change, and nothing is lost.
        """
        if not draft:
            return False
        ghost_token, position = gesture
        node = stamped.nodes[ghost_token]
        siblings = stamped.nodes[cast("canvas_stamp.Token", node["parent"])]["children"]
        index = siblings.index(ghost_token)

        def ghost(token: canvas_stamp.Token) -> bool:
            return stamped.nodes[token]["kind"] == "pending"

        start = index
        while start > 0 and ghost(siblings[start - 1]):
            start -= 1
        end = index + 1
        while end < len(siblings) and ghost(siblings[end]):
            end += 1
        cut = index + (1 if position == "after" else 0)
        # `"pending"` is `NotRequired` on `StudioNode` in general (real for
        # every node `ghost()` selects here, a `kind: "pending"` ghost --
        # `_splice_ghost`'s own construction always sets it on those, true
        # by construction the direct-subscript form pyright refuses to
        # assume); `.get()` plus a cast says so explicitly.
        before = [
            cast("canvas_stamp.PendingFieldInfo", stamped.nodes[t].get("pending"))[
                "name"
            ]
            for t in siblings[start:cut]
        ]
        after = [
            cast("canvas_stamp.PendingFieldInfo", stamped.nodes[t].get("pending"))[
                "name"
            ]
            for t in siblings[cut:end]
        ]

        fresh_view = typed.model(self.env, View).browse(cast("int", view.id))
        root = cast(
            "LxmlElement", etree.fromstring(fresh_view.get_combined_arch().encode())
        )
        fresh = canvas_stamp.stamp(root, cast("str", view.type))
        landed = self._token_named(
            fresh.nodes, name, tag, within=(container["tag"], container["name"])
        )
        if landed is None:
            return False
        landing = cast("_ComposedViewEditor", self)._mint_anchor(
            fresh_view, fresh, root, landed, "after"
        )
        for side, chain in (("before", reversed(before)), ("after", after)):
            previous = None
            for ghost_name in chain:
                anchor: dict[str, object]
                if previous is None:
                    anchor = dict(landing, position=side)
                else:
                    anchor = {"view_id": view.id, "position": side, "pending": previous}
                cast("_DraftHandle", draft).set_anchor(
                    ghost_name, anchor, release_dependents=False
                )
                previous = ghost_name
        return True

    @api.model
    def _moved_node(
        self, stamped: canvas_stamp.StampResult, payload: dict[str, object]
    ) -> canvas_stamp.StudioNode | None:
        """The node table entry a ``move`` payload names, or ``None``.

        A node under a subview is never in the table, so a move across a
        ``<field>`` boundary -- into or out of an embedded list -- cannot
        even be expressed, which is the refusal it deserves. What the table
        says is not movable -- the sheet, a card's parts, a field a kanban
        declares at its root -- is refused here too: the client does not
        offer the grip for those, and the server keeps the same rule for a
        caller that did not ask the table.
        """
        if payload.get("kind") != "move":
            return None
        moved = stamped.nodes.get(cast("canvas_stamp.Token", payload.get("token")))
        if moved is None:
            raise UserError(
                _("One end of that move is not a node the builder can address.")
            )
        if not moved["movable"]:
            raise UserError(
                _(
                    "The %s stays where it is; it is not something to move.",
                    self._describe_kind(moved["kind"]),
                )
            )
        return moved

    @api.model
    def _apply_drop(
        self,
        view: View,
        package: StudioPackage,
        anchor: dict[str, object],
        position: str,
        payload: dict[str, object],
        moved: canvas_stamp.StudioNode | None,
    ) -> tuple[str | None, str | None]:
        """Run the operation a drop stands for, disk gate closed.

        Returns the name of what landed and the tag to select it by, or
        ``None`` for the tag when the operation minted the node and only
        its name is known.
        """
        kind = payload.get("kind")
        if kind == "existing_field":
            name = cast("str | None", payload.get("name"))
            if not name or name not in self.env[cast("str", view.model)]._fields:
                raise UserError(
                    _(
                        "%(field)s is not a field of %(model)s.",
                        field=name,
                        model=view.model,
                    )
                )
            operation: dict[str, object] = {
                "type": "add_field",
                "name": name,
                "position": position,
            }
            if payload.get("attrs"):
                operation["attrs"] = dict(cast("dict[str, object]", payload["attrs"]))
            self.apply_at(
                cast("int", view.id),
                cast("int", package.id),
                anchor,
                operation,
                write_files=False,
            )
            return name, "field"
        if kind == "component":
            component = cast("str | None", payload.get("component"))
            values = cast("dict[str, object]", payload.get("values") or {})
            if component == "button":
                result = self.add_button_at(
                    cast("int", view.id),
                    cast("int", package.id),
                    anchor,
                    values,
                    position=position,
                    write_files=False,
                )
            else:
                operation = {"type": self.COMPONENT_OPS[cast("str", component)]}
                operation["position"] = position
                if values.get("string"):
                    operation["string"] = values["string"]
                result = self.apply_at(
                    cast("int", view.id),
                    cast("int", package.id),
                    anchor,
                    operation,
                    write_files=False,
                )
            return result.get("created_name"), None
        if kind == "move":
            self.move_node(
                cast("int", view.id),
                cast("int", package.id),
                {"kind": "node", "token": payload["token"]},
                anchor,
                position,
                write_files=False,
            )
            moved_entry = cast("canvas_stamp.StudioNode", moved)
            return moved_entry["name"], moved_entry["tag"]
        raise UserError(_("'%s' is not something the builder can drop.", kind))

    @api.model
    def _drop_refusal(self, tag: str, container: canvas_stamp.StudioNode) -> str:
        """The sentence for a drop the container does not take."""
        if tag == "page":
            return _("A tab can only live in a notebook.")
        what = {
            "field": _("A field"),
            "group": _("A group"),
            "notebook": _("A notebook"),
            "separator": _("A separator"),
            "label": _("A label"),
            "button": _("A button"),
        }.get(tag, _("That"))
        if not container["container"] and container["kind"] != "html":
            return _(
                "%(what)s cannot be dropped into a %(kind)s.",
                what=what,
                kind=self._describe_kind(container["kind"]),
            )
        return _("%s cannot be dropped here.", what)

    @api.model
    def _token_named(
        self,
        nodes: dict[canvas_stamp.Token, canvas_stamp.StudioNode],
        name: str | None,
        tag: str | None = None,
        within: tuple[str, str | None] | None = None,
    ) -> canvas_stamp.Token | None:
        """The token of the node called ``name`` in a fresh canvas, or ``None``.

        The canvas is re-stamped after the drop, so the token of what
        landed is found by name -- and a name is not always unique. The
        best match is the one the drop can have produced: selectable (a
        field a kanban declares at its root has no DOM to outline), of the
        tag the drop put there (a ``<label for>`` shares its field's name),
        and sitting in the container the drop was aimed at, given as the
        container's ``(tag, name)`` since its own token did not survive the
        re-stamp. Earlier in document order breaks the remaining ties.
        Nodes under a subview are never in the table, so a sublist column
        of the same name cannot be picked by mistake.
        """
        if not name:
            return None
        best: canvas_stamp.Token | None = None
        best_score: tuple[bool, bool, bool] | None = None
        for token, node in nodes.items():
            if node["name"] != name:
                continue
            parent = (
                nodes.get(cast("canvas_stamp.Token", node["parent"]))
                if node["parent"]
                else None
            )
            score = (
                bool(node["selectable"]),
                tag is None or node["tag"] == tag,
                within is not None
                and parent is not None
                and (parent["tag"], parent["name"]) == tuple(within),
            )
            if best_score is None or score > best_score:
                best, best_score = token, score
        return best

    # -- search views -------------------------------------------------------
    #
    # The one view type with nothing to click: a search view has no rendering
    # of its own, it furnishes another view's control panel. So it is edited as
    # the three lists it really is -- searchable fields, filters, group-bys --
    # while the preview shows a real list with this search view attached, so the
    # menus being edited are the menus on screen.

    # The four one-click conditions, kept because they are what most filters
    # are and naming one takes no thought. Anything with a value, or more than
    # one term, comes from the condition builder instead -- `condition="built"`
    # with rows, which is the same panel the record-rule wizard uses.
    FILTER_CONDITIONS = {
        "set": ("%s is set", "[('%s', '!=', False)]"),
        "not_set": ("%s is not set", "[('%s', '=', False)]"),
        "true": ("%s", "[('%s', '=', True)]"),
        "false": ("Not %s", "[('%s', '=', False)]"),
    }

    @api.model
    def search_elements(self, view_id: int) -> SearchElementsJSON:
        """What a search view offers, in the three groups the sidebar shows."""
        typed.security(self)._assert_studio_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        fields_: list[_SearchFieldEntryJSON] = []
        filters: list[SearchFilterEntryJSON] = []
        group_bys: list[SearchFilterEntryJSON] = []
        for node in root.iter("field"):
            if not any(a.tag == "field" for a in node.iterancestors()):
                fields_.append(
                    {"name": node.get("name"), "string": node.get("string") or ""}
                )
        for node in root.iter("filter"):
            entry: SearchFilterEntryJSON = {
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
            "addable": self.get_addable_fields(
                cast("str", view.model), cast("int", view.id)
            ),
        }

    @api.model
    def add_search_element(
        self, view_id: int, package_id: int, kind: str, values: dict[str, object]
    ) -> OperationResultJSON:
        """Add a searchable field, a filter, or a group-by."""
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        occurrences = self._occurrences(root)
        field_name = cast("str | None", values.get("field"))
        # A built condition names its fields in its rows, so there is no single
        # field to insist on -- and insisting anyway is how "add a filter for
        # two things" turns into "choose one field first".
        built = kind == "filter" and values.get("condition") == "built"
        if not built and (
            not field_name
            or field_name not in self.env[cast("str", view.model)]._fields
        ):
            raise UserError(_("Choose a field that exists on %s.", view.model))
        # `not built and (... or field_name not in self.env[...]._fields)`
        # above already raised unless `field_name` names a real field, so
        # `field` is never actually `None` in either branch below that
        # reads it (`condition in self.FILTER_CONDITIONS`/`group_by`) --
        # true by construction, the same idiom `_field_info`'s own
        # `self.env[model_name]._fields.get(...)` reads rely on elsewhere
        # in this file, invisible to the type checker across the two
        # separate `.get()` calls.
        field = cast(
            "Field[Any]",
            self.env[cast("str", view.model)]._fields.get(cast("str", field_name)),
        )

        operation: dict[str, object]
        if kind == "field":
            anchor, position = self._search_anchor(root, "field")
            operation = {
                "type": "add_field",
                "xpath": self._locator_for(anchor, occurrences),
                "position": position,
                "name": field_name,
            }
        elif kind == "filter":
            condition = cast("str", values.get("condition", "set"))
            anchor, position = self._search_anchor(root, "filter")
            if condition == "built":
                name, string, domain = self._built_filter(
                    cast("str", view.model), values
                )
            elif condition in self.FILTER_CONDITIONS:
                label, template = self.FILTER_CONDITIONS[condition]
                name = "filter_%s_%s" % (field_name, condition)
                string = label % (field.string or field_name)
                domain = template % field_name
            else:
                raise UserError(_("Unknown filter condition '%s'.", condition))
            operation = {
                "type": "add_filter",
                "xpath": self._locator_for(anchor, occurrences),
                "position": position,
                "name": name,
                "string": string,
                "domain": domain,
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
    def _built_filter(
        self, model_name: str, values: dict[str, object]
    ) -> tuple[str, str, str]:
        """A filter from the condition builder: name, label and domain.

        Checked before it is written, for the same reason a record rule is: a
        filter whose domain does not search raises when somebody clicks it,
        and by then it is in the source file and in the next database too.
        """
        domain = typed.model(self.env, StudioDomain).write_domain(
            cast("list[DomainRowJSON] | None", values.get("rows")) or [],
            cast("str", values.get("joiner") or "all"),
        )
        checked = typed.model(self.env, StudioDomain).check_domain(model_name, domain)
        if not checked["valid"]:
            raise UserError(
                _(
                    "This condition does not search:\n\n%s",
                    cast("dict[str, object]", checked)["reason"],
                )
            )
        label = cast("str", (values.get("string") or "")).strip()
        if not label:
            raise UserError(_("Give the filter a name — it becomes its menu entry."))
        slug = "".join(c if c.isalnum() else "_" for c in label.lower())
        return "filter_%s" % "_".join(p for p in slug.split("_") if p), label, domain

    @api.model
    def _search_anchor(self, root: LxmlElement, tag: str) -> tuple[LxmlElement, str]:
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
    def remove_search_element(
        self, view_id: int, package_id: int, kind: str, name: str
    ) -> OperationResultJSON:
        """Take a field, filter or group-by out of a search view."""
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
        descriptor: dict[str, object] = {
            "kind": "field" if kind == "field" else "filter",
            "name": name,
        }
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
        # What the palette drops besides fields. Both are minted with a name
        # (`_op_add_separator`, `_op_add_label`), so a ghost anchored beside
        # one can find it again once the arch has moved on -- a label being
        # the `<div class="o_form_label">` the operation emits.
        "separator": "separator",
        "label": "div",
    }

    # Where a new node goes, given what was selected. Insertion is the one
    # gesture with two plausible readings -- "after this" or "inside this" --
    # and guessing differently each time is what makes an editor feel arbitrary.
    # A leaf takes a sibling; a container takes a child.
    INSERT_INSIDE = ("group", "notebook", "sheet", "header", "form", "list", "root")

    @api.model
    def locate_target(
        self, view_id: int, descriptor: dict[str, object]
    ) -> LocateTargetJSON:
        """Resolve what the user clicked to a stable xpath, server-side.

        The browser sends a *descriptor* -- "the column for user_id" -- and
        never an xpath, and that division is the whole point. The arch a client
        receives is a per-user projection: nodes are dropped by group rights and
        whole subviews are grafted in, so a path derived from it can be wrong
        for somebody else looking at the same view. Resolution happens here,
        against the combined arch, using the same uniqueness rule the node list
        already uses.
        """
        typed.security(self)._assert_studio_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view no longer exists."))
        # A token is only meaningful on the tree it was minted from, so a
        # descriptor that says which tree that was is checked against the
        # current one -- a locator resolved from the wrong tree would be
        # for the wrong node, and the client is better told to reload.
        self._assert_arch_version(
            view, cast("str | None", descriptor.get("arch_version"))
        )
        root = cast("LxmlElement", etree.fromstring(view.get_combined_arch().encode()))
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
            "tag": cast("str", node.tag),
            "attrs": dict(node.attrib),
            "field": self._field_info(cast("str", view.model), node),
        }

    @api.model
    def _find_descriptor(
        self, root: LxmlElement, descriptor: dict[str, object]
    ) -> LxmlElement | None:
        """The arch node a descriptor refers to, or ``None``.

        Three vocabularies. ``root`` is the view itself. A *token* names a
        node by its ordinal in the stamped walk of this very tree
        (``canvas_stamp``): re-stamping ``root`` gives back the same
        ordinals, so the token resolves to the node it was minted on, or to
        nothing if the tree has changed shape -- which is why a caller
        holding a token also holds the arch version it came with. The
        legacy kinds name a node by tag and name, or by index, and stay
        because the search-view lists and older clients still speak them.
        """
        kind = descriptor.get("kind")
        if kind == "root":
            return root
        if kind == "node":
            stamped = canvas_stamp.stamp(root, root.tag)
            return stamped.elements.get(
                cast("canvas_stamp.Token", descriptor.get("token"))
            )
        tag = self.DESCRIPTOR_TAGS.get(cast("str", kind))
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
    def _find_node_entry(
        self, root: LxmlElement, descriptor: dict[str, object], stamp: bool = False
    ) -> tuple[
        LxmlElement | None, canvas_stamp.StampResult | None, canvas_stamp.Token | None
    ]:
        """The node a descriptor names, with its place in the node table.

        Returns ``(element, stamped, token)``. For a token descriptor the
        stamp the token was resolved on comes along, since the caller that
        needs the element usually needs to know what the table says about
        it -- whether it is a container, whether it may be removed -- and
        stamping twice for that would be waste. A legacy descriptor is
        resolved by tag and name and comes back with ``None`` twice, unless
        ``stamp`` asks for its entry anyway: a ``{"kind": "sheet"}`` still
        names a node the table has a rule for.
        """
        if descriptor.get("kind") == "node":
            stamped = canvas_stamp.stamp(root, root.tag)
            token = cast("canvas_stamp.Token | None", descriptor.get("token"))
            element = stamped.elements.get(cast("canvas_stamp.Token", token))
            return element, (stamped if element is not None else None), token
        element = self._find_descriptor(root, descriptor)
        if element is None or not stamp:
            return element, None, None
        stamped = canvas_stamp.stamp(root, root.tag)
        token = next((t for t, el in stamped.elements.items() if el is element), None)
        return element, (stamped if token else None), token

    @api.model
    def _insert_position(
        self,
        descriptor: dict[str, object],
        entry: canvas_stamp.StudioNode | None = None,
    ) -> str:
        """Whether a new node goes inside what was selected or after it.

        A token descriptor says nothing about what it names, so the answer
        comes from the node table entry it resolved to: a container takes a
        child, a leaf a sibling -- the same rule the legacy kinds encode by
        name.
        """
        if entry is not None:
            return "inside" if entry["container"] else "after"
        kind = descriptor.get("kind")
        return "inside" if kind in self.INSERT_INSIDE else "after"

    @api.model
    def _describe_kind(self, kind: str) -> str:
        """How a sentence to the user names a node of ``kind``.

        Internal kinds -- ``html``, ``button_box``, the kanban parts -- are
        not words the user has seen on the palette, so they get ordinary
        ones rather than leaking into a toast as "into a html".
        """
        return {
            "root": _("view"),
            "field": _("field"),
            "column": _("column"),
            "button": _("button"),
            "page": _("tab"),
            "group": _("group"),
            "notebook": _("notebook"),
            "sheet": _("sheet"),
            "header": _("header"),
            "footer": _("footer"),
            "separator": _("separator"),
            "label": _("label"),
            "widget": _("widget"),
            "pending": _("pending field"),
            "chatter": _("chatter"),
            "button_box": _("button box"),
            "card": _("card"),
            "main": _("card body"),
            "aside": _("card side panel"),
        }.get(kind, _("element"))

    @api.model
    def _confirm_removal(self, kind: str, count: int, fields: int) -> str:
        """The question asked before a container and its content go.

        Counted in fields when there are any, since that is what the user
        would lose; in elements otherwise -- a group of two empty groups is
        still not nothing.
        """
        what = self._describe_kind(kind)
        if fields == 1:
            return _("Remove this %s and the field in it? Confirm to proceed.", what)
        if fields:
            return _(
                "Remove this %(what)s and the %(count)d fields in it? "
                "Confirm to proceed.",
                what=what,
                count=fields,
            )
        if count == 1:
            return _("Remove this %s and the element in it? Confirm to proceed.", what)
        return _(
            "Remove this %(what)s and the %(count)d elements in it? "
            "Confirm to proceed.",
            what=what,
            count=count,
        )

    @api.model
    def _field_info(self, model_name: str, node: LxmlElement) -> FieldInfoJSON | None:
        """What the sidebar needs in order to offer the right options.

        Options are type-aware -- a column sum belongs on a number and nowhere
        else -- so the panel is built from the live field rather than guessed
        from the arch.
        """
        if node.tag != "field" or model_name not in self.env:
            return None
        field = self.env[model_name]._fields.get(cast("str", node.get("name")))
        if not field:
            return None
        info: FieldInfoJSON = {
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
    def editing_context(
        self,
        view_id: int | None = None,
        model: str | None = None,
        view_type: str | None = None,
    ) -> EditingContextJSON:
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
        typed.security(self)._assert_studio_user()
        # Same `View` shadowing trap as `_get_or_create_extension` above.
        view_model = typed.model(self.env, View)
        view = view_model.browse(view_id).exists() if view_id else view_model.browse()
        if not view and model and view_type:
            view = view_model.browse(
                cast("int", view_model.default_view(model, view_type))
            )
        if not view and model and not view_type:
            # Only the model in hand -- Home's Open, the crumb's picker, a
            # URL without a view: the form first, since that is where a
            # field goes, then whichever view the model has.
            existing: dict[str, int] = {
                v["type"]: v["view_id"] for v in self._views_of(model)
            }
            for candidate in ("form", "list", "kanban", *existing):
                if candidate in existing:
                    view = view_model.browse(existing[candidate])
                    break
        if not view:
            raise UserError(
                _(
                    "There is no %(type)s view of %(model)s to edit.",
                    type=view_type or _("such"),
                    model=model or _("that model"),
                )
            )
        packages = typed.model(self.env, StudioPackage).search([])
        # Same `studio.owned.mixin` composed-elsewhere cast as
        # `_find_extension` above.
        owner = cast("StudioPackage", cast("StudioOwnedMixin", view).studio_package_id)
        suggested = owner or packages._suggested()
        python_owner = (
            cast("_ComposedViewEditor", self)._python_owner(cast("str", view.model))
            if view.model
            else packages.browse()
        )
        return {
            "view": {
                "id": cast("int", view.id),
                "name": cast("str", view.name),
                "type": cast("str", view.type),
                "model": view.model,
                "mode": cast("str", view.mode),
            },
            # Every kind of view the model has, for the console's switcher.
            # One per type, chosen the way Odoo chooses when an action does
            # not pin one, so switching lands on the view the user would see.
            "views": self._views_of(view.model),
            # Whether a new field here is a class attribute waiting for an
            # Apply, or a row that is live at once -- the two paths a field
            # drop can take, decided before the palette is drawn.
            "python_owned": bool(python_owner),
            "python_owner_id": cast("int", python_owner.id) if python_owner else False,
            "field_types": modelspec.available_field_types(
                self._python_spec(python_owner, view.model), self.env._
            ),
            # The draft this user already has open on the model, if any. Never
            # created here: opening the editor is not an edit.
            "draft_id": self._open_draft_id(view.model),
            "reload_mode": (python_owner or suggested).reload_mode
            if (python_owner or suggested)
            else False,
            "record_count": self._record_count(view.model),
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
            "options": view_options.groups_json(cast("str", view.type), self.env._),
            "catalogue": catalogue.catalogue_json(self.env._),
            "groups": self._selectable_groups(),
            # Whether an edit rewrites this view or emits a patch against it.
            # The preview shows the combined result either way, so saying which
            # is the difference between understanding the output and not.
            "owned": bool(owner) and self._owns_outright(view, owner),
            "packages": [
                {
                    "id": cast("int", p.id),
                    "name": cast("str", p.name),
                    "writable": p.writable,
                }
                for p in packages
            ],
            "suggested_package_id": cast("int", suggested.id) if suggested else False,
        }

    @api.model
    def _views_of(
        self, model_name: str | Literal[False] | None
    ) -> list[ViewOfEntryJSON]:
        """One view per type the model has, as Odoo would pick it.

        The types come from ``get_view_info`` -- the registry every module
        extends when it contributes a view type -- and the view for each from
        ``default_view``, so a type an OCA addon adds shows up here without
        this list knowing about it, and the view offered for it is the one
        an action without a pinned view would render.
        """
        if not model_name:
            return []
        # Same `View` shadowing trap as `_get_or_create_extension` above.
        view_model = typed.model(self.env, View)
        out: list[ViewOfEntryJSON] = []
        # `get_view_info` is declared only by `web`'s own `_inherit =
        # "ir.ui.view"` extension (`odoo/addons/web/models/ir_ui_view.py`),
        # not `base`'s real class `typed.model()` targets above -- a
        # genuine core-vendor composed-elsewhere gap (this project's own
        # `View` import is `base`'s, per TYPING.md's traced classes list),
        # worked around the same narrow way as `studio.owned.mixin`'s own,
        # for a dependency this addon already declares (`web`, in its
        # manifest) rather than one this migration adds.
        for view_type in cast("WebView", view_model).get_view_info():
            view_id = cast("int", view_model.default_view(model_name, view_type))
            if not view_id:
                continue
            view = view_model.browse(view_id)
            # Ownership is an xmlid lookup, which only an administrator may
            # make; the fact itself is not a secret. Same `studio.owned
            # .mixin` composed-elsewhere cast as `_find_extension` above.
            owner = cast(
                "StudioPackage", cast("StudioOwnedMixin", view.sudo()).studio_package_id
            )
            out.append(
                {
                    "type": view_type,
                    "view_id": cast("int", view.id),
                    "name": cast("str", view.name),
                    "owned": bool(owner) and self._owns_outright(view, owner),
                }
            )
        return out

    @api.model
    def _python_spec(
        self, package: StudioPackage, model_name: str | Literal[False]
    ) -> modelspec.ModelSpec | None:
        """The spec the field picker decides its offer from.

        The on-disk spec of a Python-owned model, since that is where a
        field created for it will land. A model no package defines in
        Python has no file to read, but the picker's one question -- does
        an amount have a currency field to lean on -- has an answer in the
        registry all the same, so the live model is described just far
        enough to answer it. Without that the Amount tile is greyed out on
        ``sale.order`` with a reason that is false for it.
        """
        if not model_name or model_name not in self.env:
            return None
        if package:
            entry = typed.model(self.env, StudioPackageModel).search(
                [
                    ("package_id", "=", cast("int", package.id)),
                    ("model", "=", model_name),
                ],
                limit=1,
            )
            if entry:
                return entry._current_spec()
        return self._live_spec(model_name)

    @api.model
    def _live_spec(self, model_name: str) -> modelspec.ModelSpec:
        """A spec of the registry's model, saying only what the picker asks.

        The relational fields, by name and comodel: enough to find a
        currency. Not a description of the model -- ``modelspec`` reads
        those from source, and a spec that pretended to be one would be
        mistaken for something that could be written back.
        """
        model = self.env[model_name]
        return modelspec.ModelSpec(
            name=model_name,
            description=model._description or model_name,
            class_name="",
            fields=tuple(
                modelspec.FieldSpec(
                    name=name, ttype=field.type, comodel=field.comodel_name
                )
                for name, field in sorted(model._fields.items())
                if field.type == "many2one"
            ),
        )

    @api.model
    def _open_draft_id(
        self, model_name: str | Literal[False] | None
    ) -> int | Literal[False]:
        """The newest draft this user has on ``model_name``, or ``False``."""
        if not model_name or "studio.model.draft" not in self.env:
            return False
        draft = typed.model(self.env, StudioModelDraft).search(
            [
                ("package_model_id.model", "=", model_name),
                ("create_uid", "=", self.env.uid),
                ("parent_draft_id", "=", False),
            ],
            order="id desc",
            limit=1,
        )
        return cast("int", draft.id) or False

    @api.model
    def _record_count(self, model_name: str | Literal[False] | None) -> int:
        """How many records the model has, archived ones included, up to
        ``RECORD_COUNT_CAP``.

        Read for the canvas rather than the sidebar: a list or a kanban of
        nothing renders as nothing, and the builder then asks the view for
        sample rows so there are still columns and cards to drop onto.
        That needs "none or some"; the number shown needs "how many, about"
        -- and neither is worth a full count of ``mail.message`` on every
        gesture, so the count stops at the cap.
        """
        if not model_name or model_name not in self.env:
            return 0
        model = self.env[model_name]
        if model._abstract or not model.has_access("read"):
            return 0
        return model.with_context(active_test=False).search_count(
            [], limit=RECORD_COUNT_CAP
        )

    # Types the builder can create from nothing, and what each one needs first.
    # What the builder can create from nothing. Deliberately *not* the list of
    # view types -- that comes from Odoo, via `ir.ui.view.get_view_info()`, which
    # is the registry every module extends when it contributes one. Core seeds
    # seven, `mail` adds activity, `web_timeline` adds timeline,
    # `web_view_leaflet_map` adds leaflet_map.
    #
    # Deriving the list rather than declaring it buys three things: a site that
    # installs an OCA view type sees it here as soon as somebody writes a
    # scaffold, a site running enterprise sees gantt and cohort, and the engine
    # depends on none of them.
    # Derived, not repeated. This list and the app builder's were separate and
    # had drifted: the editor offered eight types and `create_app` built three.
    # `search` is excluded because it is not something Add view creates -- it
    # comes with the model and is edited as three lists.
    VIEW_SCAFFOLDS = tuple(t for t in scaffold.SCAFFOLD_BUILDERS if t != "search")

    # Types that are never *added*: a search view furnishes another view's
    # control panel rather than being one, and qweb is a template.
    NOT_ADDABLE = ("search", "qweb")

    @api.model
    def _placeable_fields(
        self, model: BaseModel, types: tuple[str, ...]
    ) -> list[PlaceableFieldEntryJSON]:
        """Stored fields of ``types``, as the picker needs them.

        `create_date` and `write_date` are dates too, and a calendar of when
        records happened to be typed in is not a calendar anybody wants. They
        also make every model look like it has a date, which would hide the
        "add one first" answer the user actually needs.
        """
        return [
            {"name": name, "string": field.string or name}
            for name, field in sorted(model._fields.items())
            if field.type in types
            and field.store
            and name not in modelspec.MAGIC_COLUMNS
        ]

    @api.model
    def _view_prerequisites(
        self, model: BaseModel, view_type: str
    ) -> tuple[str, _ViewPrerequisiteExtraJSON]:
        """What this view type needs from this model before it can exist.

        Returns the reason it cannot, plus whatever the caller has to choose.
        Reported rather than hidden: somebody looking for a calendar should
        learn that the model has no date and what to do about it, instead of
        concluding the builder cannot do calendars.
        """
        dates = self._placeable_fields(model, ("date", "datetime"))
        groups = self._placeable_fields(model, ("many2one", "selection"))
        if view_type == "calendar":
            if not dates:
                return _(
                    "A calendar needs a date field to place records on, and "
                    "this model has none. Add one first."
                ), {"date_fields": dates}
            return "", {"date_fields": dates}
        if view_type == "timeline":
            if not dates:
                return _(
                    "A timeline needs a date field to place records on, and "
                    "this model has none. Add one first."
                ), {}
            if not groups:
                return _(
                    "A timeline needs something to make its rows from — a "
                    "link or a selection. This model has neither."
                ), {}
            return "", {"date_fields": dates, "group_fields": groups}
        if view_type == "activity" and "activity_ids" not in model._fields:
            return _(
                "An activity view shows scheduled activities, and this model "
                "does not have them. Turn on Messaging & activities first."
            ), {}
        return "", {}

    @api.model
    def addable_view_types(self, model_name: str) -> list[AddableViewTypeEntryJSON]:
        """Which views this model could have, and why not where it could not."""
        typed.security(self)._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        model = self.env[model_name]
        existing = set(
            typed.model(self.env, View)
            .search([("model", "=", model_name), ("mode", "=", "primary")])
            .mapped("type")
        )
        # Same `web`-only `get_view_info` composed-elsewhere cast as
        # `_views_of` above.
        known = cast("WebView", typed.model(self.env, View)).get_view_info()
        out: list[AddableViewTypeEntryJSON] = []
        for view_type, meta in known.items():
            if view_type in self.NOT_ADDABLE:
                continue
            entry: AddableViewTypeEntryJSON = {
                "type": view_type,
                "label": meta.get("display_name") or view_type,
                "icon": meta.get("icon") or "",
                "enabled": True,
                "reason": "",
                "date_fields": [],
                "group_fields": [],
            }
            if view_type in existing:
                entry["enabled"] = False
                entry["reason"] = _("This model already has a %s view.", view_type)
            elif view_type not in self.VIEW_SCAFFOLDS:
                entry["enabled"] = False
                # Named rather than hidden: the type is installed and Odoo can
                # render it, so "the builder cannot make one yet" is the true
                # answer and a different one from "this does not exist".
                entry["reason"] = _(
                    "The builder cannot create a %s view yet. One made by hand "
                    "can still be edited here.",
                    meta.get("display_name") or view_type,
                )
            else:
                reason, extra = self._view_prerequisites(model, view_type)
                entry["reason"] = reason
                entry["enabled"] = not reason
                # `dict.update()` on a `TypedDict` wants its argument's own
                # type to already be a `Partial` of the *same* TypedDict
                # (typeshed's own `update()` overloads), which
                # `_ViewPrerequisiteExtraJSON` -- a real but different,
                # narrower TypedDict -- does not structurally satisfy even
                # though every key it ever carries is one of this one's
                # own; merged by hand instead, keeping `.update()`'s own
                # "only a key actually present overwrites" behavior.
                if "date_fields" in extra:
                    entry["date_fields"] = extra["date_fields"]
                if "group_fields" in extra:
                    entry["group_fields"] = extra["group_fields"]
            out.append(entry)
        return out

    @api.model
    def add_view(
        self,
        model_name: str,
        view_type: str,
        package_id: int,
        date_field: str | None = None,
        group_field: str | None = None,
    ) -> AddViewJSON:
        """Create a view of ``view_type`` for ``model_name``, and make it
        reachable.

        Creating the record is the easy half. A view no action offers is a view
        nobody can open, so the window actions this package owns for the model
        gain the type in their ``view_mode`` -- otherwise the builder would
        report success and the user would never find what it built.
        """
        typed.security(self)._assert_studio_manager()
        if view_type not in self.VIEW_SCAFFOLDS:
            raise UserError(_("The builder does not create %s views.", view_type))
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this view in."))
        package._assert_writable()

        model = self.env[model_name]
        existing = typed.model(self.env, View).search(
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

        if view_type in ("calendar", "timeline") and (
            not date_field or date_field not in model._fields
        ):
            raise UserError(
                _(
                    "A %(type)s has to know which date to place records on. "
                    "Choose a date field on %(model)s first.",
                    type=view_type,
                    model=model_name,
                )
            )
        if view_type == "timeline" and (
            not group_field or group_field not in model._fields
        ):
            # Unlike Gantt, where rows are optional, web_timeline requires
            # default_group_by -- so this is the view refusing to open rather
            # than a preference of ours.
            raise UserError(
                _(
                    "A timeline has to know what to make its rows from. Choose "
                    "a field on %s to group by.",
                    model_name,
                )
            )
        arch = self._scaffold_arch(model, view_type, date_field, group_field)
        # Same `create()` single-dict vendor gap as `_get_or_create_extension`
        # above.
        vals = {
            "name": "%s.%s" % (model_name, view_type),
            "model": model_name,
            "type": view_type,
            "arch": cast("str", etree.tostring(arch, encoding="unicode")),
        }
        view = typed.model(self.env, View).create(vals)  # pyright: ignore[reportArgumentType]
        package.studio_capture(view)
        self._offer_view_in_actions(package, model_name, view_type)
        package.action_write_files()
        return {"view_id": cast("int", view.id), "type": view_type}

    @api.model
    def _scaffold_arch(
        self,
        model: BaseModel,
        view_type: str,
        date_field: str | None = None,
        group_field: str | None = None,
    ) -> LxmlElement:
        """The starting arch for a new view, built from the live model."""
        spec = self._spec_for(model)
        options = scaffold.ScaffoldOptions.from_keys(
            key
            for key, present in (
                ("stage", "state" in model._fields),
                ("user", "user_id" in model._fields),
                ("chatter", "message_ids" in model._fields),
            )
            if present
        )
        builders: dict[str, Callable[[], LxmlElement]] = {
            "kanban": lambda: scaffold.scaffold_kanban_arch(model, spec, options),
            "calendar": lambda: scaffold.scaffold_calendar_arch(
                model, spec, date_field, options
            ),
            "list": lambda: scaffold.scaffold_list_arch(model, spec, options),
            "form": lambda: scaffold.scaffold_form_arch(model, spec, options),
            "pivot": lambda: scaffold.scaffold_pivot_arch(model, spec, options),
            "graph": lambda: scaffold.scaffold_graph_arch(model, spec, options),
            "activity": lambda: scaffold.scaffold_activity_arch(model, spec, options),
            "timeline": lambda: scaffold.scaffold_timeline_arch(
                model, spec, date_field, group_field, options
            ),
        }
        build = builders.get(view_type)
        if build is None:
            raise UserError(_("The builder does not create %s views.", view_type))
        return build()

    @api.model
    def _spec_for(self, model: BaseModel) -> modelspec.ModelSpec:
        """A spec describing the live model, for the scaffold to read.

        The scaffolds take a spec because that is what building a *new* model
        produces. Here the model already exists, so one is derived from the
        registry -- the same direction adoption uses.
        """
        entry = typed.model(self.env, StudioPackageModel).search(
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
            name=cast("str", model._name),
            description=model._description or cast("str", model._name),
            class_name=pycodegen.class_name_for(cast("str", model._name)),
            fields=tuple(fields_),
            rec_name=model._rec_name or "name",
        )

    @api.model
    def _offer_view_in_actions(
        self, package: StudioPackage, model_name: str, view_type: str
    ) -> BaseModel:
        """Add the new view type to the window actions that show this model."""
        actions = typed.model(self.env, IrActionsActWindow).search(
            [("res_model", "=", model_name)]
        )
        touched = actions.browse()
        for action in actions:
            # Same `studio.owned.mixin` composed-elsewhere cast as
            # `_find_extension` above, on a different owned model.
            if (
                cast(
                    "StudioPackage", cast("StudioOwnedMixin", action).studio_package_id
                )
                != package
            ):
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
    def _preview_for(self, view: View) -> PreviewInfoJSON:
        """How to render the view being edited.

        Every type renders itself, except search: a search view has no
        rendering of its own, it furnishes another view's control panel. So it
        previews as the model's list *with this search view attached*, which
        means the Filters and Group By menus on screen are the ones being
        edited rather than an approximation of them.
        """
        if view.type != "search":
            return {
                "type": cast("str", view.type),
                "view_id": cast("int", view.id),
                "search_view_id": False,
            }
        host = cast("int", typed.model(self.env, View).default_view(view.model, "list"))
        return {
            "type": "list",
            "view_id": host or False,
            "search_view_id": cast("int", view.id),
            # Without a list to host it there is nothing to show. Editing still
            # works -- the sidebar is the editor for a search view anyway.
            "unavailable": not host,
        }

    @api.model
    def _selectable_groups(self) -> list[SelectableGroupEntryJSON]:
        """Groups a ``groups=""`` attribute can name.

        Only ones with an external id: the attribute takes xmlids, and a group
        without one cannot be referred to from an arch at all -- so offering it
        would produce a view that silently shows the field to everybody.
        """
        groups = typed.model(self.env, Groups).sudo().search([])
        external = cast("dict[int, str]", groups.get_external_id())
        out: list[SelectableGroupEntryJSON] = [
            {
                "id": cast("int", group.id),
                "xmlid": cast("str", external.get(cast("int", group.id))),
                "name": cast("str", group.display_name),
            }
            for group in groups
            if external.get(cast("int", group.id))
        ]
        return sorted(out, key=lambda entry: entry["name"])

    @api.model
    def _model_fields(
        self, model_name: str | Literal[False] | None
    ) -> list[EditingContextFieldEntryJSON]:
        """Every stored field of a model, for option rows that name one."""
        # `not in` does not narrow a union the way `is None`/truthiness
        # would -- `self.env`'s own `__contains__` tells pyright nothing
        # about `model_name`'s type -- so the empty-string/`False`/`None`
        # cases this guard actually rules out at runtime need a cast to
        # read back as the plain `str` `self.env[...]` below takes.
        if model_name not in self.env:
            return []
        model_name = cast("str", model_name)
        return [
            {"name": name, "string": field.string or name, "type": field.type}
            for name, field in sorted(self.env[model_name]._fields.items())
            if field.store and name not in modelspec.MAGIC_COLUMNS
        ]

    @api.model
    def get_addable_fields(
        self, model_name: str, view_id: int | None = None
    ) -> list[AddableFieldEntryJSON]:
        """Fields on the model that are not already in the combined arch."""
        typed.security(self)._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        model = self.env[model_name]
        present: set[str | None] = set()
        if view_id:
            view = typed.model(self.env, View).browse(view_id).exists()
            if view:
                arch = cast(
                    "LxmlElement", etree.fromstring(view.get_combined_arch().encode())
                )
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
        result: list[AddableFieldEntryJSON] = []
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

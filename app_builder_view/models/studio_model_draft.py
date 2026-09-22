# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Where a staged field was dropped, and putting it there after Apply.

A field dropped on the canvas of a Python-owned model cannot appear until
the class is re-imported, but the *place* it was dropped is known at once
and has to survive until then. The base draft records which views a field
goes in (``placement_json``) and never where in them: a drop location is a
fact about one arch -- a view and a position inside it -- and minting or
resolving one is the view editor's business. So this addon adds the anchor
store and the two things that read it: the canvas, which draws a ghost at
the anchor while the field is pending, and Apply, which puts the real field
exactly there through the same operation a live drop uses.

An anchor holds both an xpath and the version of the arch it was minted on,
plus a legacy descriptor of the neighbour. The xpath is exact while the
arch is unchanged; when something else has edited the view in between, the
descriptor -- "after the field called email" -- is what the drop meant, and
it is re-minted. When even that is gone, the field is placed by the
balanced fallback rather than lost, and the canvas says so beforehand.

A neighbour can itself be a field that does not exist yet: the second of two
fields dropped in a row lands "after the first ghost", which is nothing an
xpath can say. Such an anchor names the other staged field (``pending``)
instead of a place in the arch, and is resolved once that field is somewhere
-- a ghost on the canvas, a real ``<field>`` after Apply. Two things keep
that from tangling. Whatever is anchored on a field follows its *place*
when that field is moved, removed or un-anchored: the dependents take over
its old anchor, so the canvas stays as the user left it and no anchor can
ever point in a circle. And an anchor only ever names a field with a lower
sequence, so resolving them in drop order resolves every neighbour first.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal, TypedDict, cast

# lxml ships no type stubs in this environment, the same gap `xml_writer.py`/
# `placement.py`/`studio_serializer.py`/`studio_view_editor.py` already
# document -- `reportMissingTypeStubs` only escalates to `error` under
# `tools/`'s own `executionEnvironments` override (`pyrightconfig.json`), not
# at this (model) level, so the one real hit here (`etree` itself, an
# unresolvable import symbol with no stub) is the only one that needs
# silencing.
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import sql

from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.models.studio_model_draft import (
    AnchorJSON as _BaseAnchorJSON,
)
from odoo.addons.app_builder_base.tools import modelspec, scaffold, typed

from .studio_view_editor import StudioViewEditor

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from odoo.sql_db import Cursor

    from odoo.addons.app_builder_base.models.studio_model_draft import (
        DraftPayloadJSON,
    )
    from odoo.addons.app_builder_base.models.studio_model_draft import (
        StudioModelDraft as StudioModelDraftBase,
    )
    from odoo.addons.app_builder_base.models.studio_package import StudioPackage
    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement
    from odoo.addons.app_builder_base.tools.modelspec import (
        FieldSpec,
        ModelSpec,
        SpecDiff,
    )

    # This file is a pure `_inherit = "studio.model.draft"` extension, the
    # same `_name` `app_builder_base`'s own file declares -- a real,
    # *different* Python class the registry merges with this file's own at
    # runtime, so it is aliased on import rather than colliding with this
    # file's own class of the identical name (precedent: `studio_view_edito
    # r.py`'s own `_DraftHandle` Protocol casts to this same alias for
    # `set_anchor` below). Cast to it wherever this file calls a
    # field/method the real base declares (`_spec`, `_placement`,
    # `package_id`, ...) and this file does not -- invisible to pyright on
    # a bare `self` otherwise.
    #
    # `_anchor_locator`/`_pending_locator` are declared on `studio_view_canv
    # as.py`'s own `_inherit = "studio.view.editor"` extension, not on
    # `studio_view_editor.py`'s real `StudioViewEditor` this file's own
    # `typed.model()` call below targets -- the identical composed-
    # elsewhere gap, for a different sibling file, aliased the same way.
    from .studio_view_canvas import StudioViewEditor as StudioViewEditorCanvas

_logger = logging.getLogger(__name__)

# What an anchor carries. `seq` orders two fields dropped at the same spot:
# the second one dropped "after email" goes after the first, which is what
# the user saw on the canvas. `pending` names another staged field as the
# neighbour, in place of the xpath and descriptor a real one has. No widget:
# that is the placement's to say, and it changes when the field is retyped.
ANCHOR_KEYS = (
    "view_id",
    "xpath",
    "position",
    "arch_version",
    "descriptor",
    "pending",
    "seq",
)


class AnchorJSON(_BaseAnchorJSON):
    """Every key ``ANCHOR_KEYS`` stores, past the base's own ``view_id``
    (``app_builder_base``'s own ``_anchors()`` docstring: "app_builder_view's
    override supplies the rest of the shape"). ``set_anchor`` always fills
    every one of ``ANCHOR_KEYS``, ``None`` where the anchor has nothing to
    say there, so nothing here is ``NotRequired``. A real, non-
    ``TYPE_CHECKING`` import of the parent TypedDict, since ``class X(Y):``
    executes at import time."""

    xpath: str | None
    position: str | None
    arch_version: str | None
    descriptor: dict[str, object] | None
    pending: str | None
    seq: int


class PlacePendingJSON(TypedDict):
    """``place_pending()``'s own return."""

    placed: bool
    reason: str


class StudioModelDraft(models.TransientModel):
    _inherit = "studio.model.draft"

    anchors_json = fields.Text(
        default="{}",
        help="Where each staged field was dropped: a view, an xpath minted "
        "on it, and the neighbour it was dropped beside. View intent, like "
        "placement, and kept apart from it because the placement slots are "
        "a fixed vocabulary.",
    )

    # -- the store ----------------------------------------------------------

    def _anchors(self) -> dict[str, AnchorJSON]:
        """``{name: anchor}`` for every staged field that was dropped somewhere."""
        self.ensure_one()
        try:
            data = json.loads(self.anchors_json or "{}")
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def _store_anchors(self, data: dict[str, AnchorJSON]) -> Literal[True]:
        self.ensure_one()
        self.anchors_json = json.dumps(data, sort_keys=True)
        return True

    def set_anchor(
        self,
        name: str,
        anchor: dict[str, object],
        release_dependents: bool = True,
    ) -> object:
        """Remember where ``name`` was dropped.

        Only a field the draft is adding can be anchored: an existing field
        is already somewhere, and a drop of one is a move the view editor
        makes live. The anchor is reduced to the keys the store knows, so
        a client cannot smuggle an xpath of its own making past the ones
        the editor minted. One that names another staged field as the
        neighbour has to name one that is pending too, and not itself; a
        ghost has no inside to be dropped into.

        Whatever was anchored beside ``name`` keeps its place: the ghosts
        that sat next to this one were put there on purpose, and moving it
        away must not drag them along -- nor leave them pointing at a ghost
        that is now somewhere else, which is how a circle would start.
        ``release_dependents`` off is for the one caller that is not moving
        the ghost at all -- the view editor re-anchoring a whole gap on a
        real node that just landed in it -- and re-anchors the dependents
        itself, in canvas order, so handing them the old anchor first would
        be work undone a line later. The sequence is fresh either way, so
        an anchor still only ever names a field dropped -- or re-anchored
        -- before it.
        """
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        anchor = dict(anchor or {})
        if not anchor.get("view_id") or anchor.get("position") not in (
            "before",
            "after",
            "inside",
        ):
            raise UserError(_("An anchor needs a view and a side to be dropped on."))
        added = self._added_names()
        if name not in added:
            raise UserError(_("There is no pending field called '%s' to place.", name))
        other = anchor.get("pending") or None
        if other is not None:
            if other == name:
                raise UserError(_("A field cannot be placed beside itself."))
            if other not in added:
                raise UserError(
                    _("There is no pending field called '%s' to place beside.", other)
                )
            if anchor["position"] == "inside":
                raise UserError(_("A pending field has nothing to be dropped into."))
        data = self._anchors()
        if release_dependents:
            self._release_dependents(data, name)
        stored = {key: anchor.get(key) for key in ANCHOR_KEYS}
        stored["view_id"] = int(cast("int | str", anchor["view_id"]))
        stored["pending"] = other
        stored["seq"] = 1 + max([a.get("seq") or 0 for a in data.values()] or [0])
        data[name] = cast("AnchorJSON", stored)
        return self._store_anchors(data)

    def clear_anchor(self, name: str) -> bool:
        """Forget where ``name`` was dropped; it is then placed by the
        balanced fallback like a field staged in the composer. What was
        anchored beside it inherits its place."""
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        data = self._anchors()
        if name not in data:
            return False
        self._release_dependents(data, name)
        data.pop(name, None)
        return self._store_anchors(data)

    @staticmethod
    def _release_dependents(data: dict[str, AnchorJSON], name: str) -> None:
        """Hand the anchor of ``name`` to every field anchored beside it.

        In place, on ``data``. The dependents keep their own sequence: it
        is later than the one they were anchored on, and the anchor they
        take over names something earlier still, so drop order goes on
        resolving every neighbour before what sits beside it. A field
        with no anchor of its own leaves its dependents unanchored, which
        is the balanced fallback for them as for it.
        """
        old = data.get(name)
        for anchor in data.values():
            if anchor.get("pending") != name:
                continue
            if old is None:
                anchor["pending"] = None
                continue
            # `.update()` through a plain-`dict` cast: the source mapping
            # is built from a dynamic (non-literal) `ANCHOR_KEYS` key each
            # iteration, so `AnchorJSON`'s own per-key value types cannot
            # line up with it structurally -- the same widening this
            # file's other dynamic-dict-into-`AnchorJSON` sites use.
            cast("dict[str, object]", anchor).update(
                {
                    key: cast("dict[str, object]", old).get(key)
                    for key in ANCHOR_KEYS
                    if key != "seq"
                }
            )

    def _added_names(self) -> tuple[str, ...]:
        """The fields this draft is adding, in class order."""
        self.ensure_one()
        base = cast("StudioModelDraftBase", self)
        return modelspec.diff_specs(base._base_spec(), base._spec()).added

    def _pending_anchored(self) -> list[dict[str, object]]:
        """Every field the draft is adding, with its anchor when it has one.

        In the order they were dropped, then class order for the rest, so a
        canvas lists them the way the user made them.
        """
        self.ensure_one()
        base = cast("StudioModelDraftBase", self)
        spec = base._spec()
        anchors = self._anchors()
        placement = base._placement()
        out: list[dict[str, object]] = []
        for name in self._added_names():
            spec_field = spec.field(name)
            if spec_field is None:
                continue
            where = placement.get(name, modelspec.default_placement(spec_field.ttype))
            out.append(
                {
                    "name": name,
                    "label": spec_field.string or name,
                    "ttype": spec_field.ttype,
                    "widget": where.get("widget") or "",
                    "anchor": anchors.get(name),
                }
            )
        out.sort(
            key=lambda entry: (
                (
                    cast("AnchorJSON | None", entry.get("anchor"))
                    or cast("AnchorJSON", {})
                ).get("seq")
                or 0
            )
        )
        return out

    # -- lifecycle: anchors follow the fields they belong to ----------------

    def remove_field(self, name: str) -> Literal[True]:
        self.clear_anchor(name)
        return cast("StudioModelDraftBase", super()).remove_field(name)

    def action_discard(self) -> Literal[True]:
        self._store_anchors({})
        return cast("StudioModelDraftBase", super()).action_discard()

    @api.model
    def open_for_model(self, model_name: str) -> DraftPayloadJSON:
        """A clean draft re-read from disk has no pending field for an
        anchor to belong to, so its anchors go the way its placements do."""
        loaded = cast("StudioModelDraftBase", super()).open_for_model(model_name)
        draft = self.browse(loaded["id"])
        base_draft = cast("StudioModelDraftBase", draft)
        if not base_draft.dirty and draft._anchors():
            draft._store_anchors({})
            loaded = base_draft.load()
        return loaded

    # -- placement after Apply ------------------------------------------------

    def _place_anchored(
        self,
        view: View,
        name: str,
        anchor: AnchorJSON,
        widget: str,
        _placing: tuple[str, ...] = (),
    ) -> bool:
        """Put ``name`` exactly where it was dropped, through the view editor.

        The same ``add_field`` operation a live drop runs, so the result is
        the same source a live drop would have written: the owned view
        edited in place, a foreign one patched with an inheriting view, and
        an entry in the undo history either way. The file is not written
        here; ``_place_in_views`` writes the package once when every field
        is in.

        Resolution follows the anchor's own claim. An xpath minted on the
        arch the view still has is used as it is; otherwise the neighbour
        is looked up again by its descriptor and the locator re-minted.
        Either way the node found is handed on with the locator, as a live
        drop's is, so the owned path checks the primary arch has the same
        node where the combined one had it. A neighbour that is another
        staged field is placed first when it is not in the view yet, and
        the field then goes beside the real ``<field>`` it became. A
        neighbour that is gone, or a locator core cannot apply -- a foreign
        extension shifted a positional path under an owned view -- is a
        ``False``: the balanced fallback places the field, which is the
        honest outcome, and better than an Apply that rolled back after the
        reload it was made of.
        """
        self.ensure_one()
        base = cast("StudioModelDraftBase", self)
        editor = typed.model(self.env, StudioViewEditor)
        other = anchor.get("pending")
        chain = _placing + (name,)
        if other and (other in _placing or not self._ensure_placed(view, other, chain)):
            return False
        root = cast(
            "LxmlElement",
            etree.fromstring(cast("str", view.get_combined_arch()).encode()),
        )
        if other:
            located = cast("StudioViewEditorCanvas", editor)._pending_locator(
                root, other
            )
        else:
            located = cast("StudioViewEditorCanvas", editor)._anchor_locator(
                view, root, cast("dict[str, object]", anchor)
            )
        if not located:
            return False
        xpath, expectation = located
        position = anchor.get("position") or "after"
        found = editor._resolve_xpath(root, xpath) or []
        operation: dict[str, object] = {
            "type": "add_field",
            "name": name,
            "attrs": {"widget": widget} if widget else {},
            "xpath": xpath,
            "position": position,
            "_expect": expectation,
            # Labelled where the form would not label it, as a live drop is.
            "label": len(found) == 1 and editor._label_wanted(view, found[0], position),
        }
        try:
            with cast("Cursor", self.env.cr).savepoint():
                editor.apply_operation(
                    cast("int", view.id),
                    cast("int", cast("StudioPackage", base.package_id).id),
                    operation,
                    write_files=False,
                )
        except UserError as err:
            _logger.warning(
                "Anchored placement of %s.%s in view %s declined (%s); "
                "falling back to balanced placement.",
                base.model,
                name,
                view.id,
                err,
            )
            return False
        return True

    def _ensure_placed(self, view: View, name: str, _placing: tuple[str, ...]) -> bool:
        """Whether ``name`` is in ``view``, placing it by its own anchor
        when it is not there yet. What a field anchored beside it needs
        before it can be placed itself."""
        if self._combined_names(view, name):
            return True
        anchor = self._anchors().get(name)
        spec_field = cast("StudioModelDraftBase", self)._spec().field(name)
        if not anchor or anchor.get("view_id") != view.id or spec_field is None:
            return False
        return bool(
            self._place_anchored(
                view, name, anchor, self._widget_for(spec_field), _placing
            )
        )

    def _widget_for(self, spec_field: FieldSpec) -> str:
        """The widget a field is placed with: the placement's, which is
        what the entry implied and what a re-edit since has changed."""
        where = (
            cast("StudioModelDraftBase", self)
            ._placement()
            .get(spec_field.name, modelspec.default_placement(spec_field.ttype))
        )
        return where.get("widget") or ""

    def _place_in_views(self, spec: ModelSpec, diff: SpecDiff) -> bool:
        """Owned views as before, plus the views the anchors name.

        The base draft places only into views the package owns, since
        those are the only ones it may write outright. An anchor can name
        any view of the model -- a form another module declares, a kanban
        the package owns but the base never places into -- and the view
        editor's operation handles all of them as a patch. So anchored
        placements into views the base pass would not visit run here, in
        drop order so a field anchored beside another finds it placed,
        and the package is written once for both.

        Idempotent like the base: a view whose combined arch already names
        the field is left alone, and an anchor is forgotten once its field
        has been placed, so a second run has nothing to do.
        """
        if not diff.added:
            return False
        base = cast("StudioModelDraftBase", self)
        owned = {view.id for view in base._owned_views().values()}
        anchors = self._anchors()
        # Named `view_model`, not `View` (the real class this method's own
        # signature is typed against): a local `View = self.env[...]`
        # would shadow that import for the rest of this function -- and,
        # worse, `View = typed.model(self.env, View)` would try to read
        # the not-yet-assigned local `View` on its own right-hand side
        # (Python's own scoping), an `UnboundLocalError` this conversion
        # must not introduce. Same trap `studio_view_editor.py`'s own
        # `_get_or_create_extension` already documents.
        view_model = typed.model(self.env, View)
        foreign = False
        by_drop_order = sorted(
            diff.added,
            key=lambda n: (anchors.get(n) or cast("AnchorJSON", {})).get("seq") or 0,
        )
        for name in by_drop_order:
            anchor = anchors.get(name)
            spec_field = spec.field(name)
            if not anchor or anchor.get("view_id") in owned or spec_field is None:
                continue
            view = view_model.browse(anchor["view_id"]).exists()
            if not view or view.model != base.model:
                continue
            if self._combined_names(view, name):
                continue
            foreign |= bool(
                self._place_anchored(view, name, anchor, self._widget_for(spec_field))
            )
        placed = cast("StudioModelDraftBase", super())._place_in_views(spec, diff)
        if foreign and not placed:
            # The base wrote the files when it placed something; when it
            # did not, the patches made above are still only in the database.
            cast("StudioPackage", base.package_id).action_write_files()
        added = set(diff.added)
        if added & set(anchors):
            self._store_anchors({k: v for k, v in anchors.items() if k not in added})
        return bool(placed or foreign)

    def _apply_features(self) -> bool:
        """What a staged feature owes the views, now that its columns exist.

        Stages wants a kanban and Date & calendar a calendar -- the same
        views the app builder scaffolds for a new model -- and Messaging
        wants the form to end in a ``<chatter/>``. Each is skipped when the
        model already has it, so a second run is harmless, like placement.
        """
        self.ensure_one()
        base = cast("StudioModelDraftBase", self)
        keys = base._features()
        if not keys:
            return False
        editor = typed.model(self.env, StudioViewEditor)
        package = cast("StudioPackage", base.package_id)
        model_name = cast("str", base.model)
        existing = {
            view["type"] for view in editor._views_of(model_name) if view.get("view_id")
        }
        done = False
        for key in keys:
            feature = scaffold.FEATURES_BY_KEY.get(key)
            if feature is None:
                continue
            for view_type in feature.views:
                if view_type in existing:
                    continue
                arguments: dict[str, str] = {}
                if view_type in ("calendar", "timeline"):
                    date_field = scaffold.first_field_of(
                        self.env[model_name],
                        ("date", "datetime"),
                        prefer=("date", "date_start"),
                    )
                    if not date_field:
                        continue
                    arguments["date_field"] = date_field
                editor.add_view(
                    model_name, view_type, cast("int", package.id), **arguments
                )
                existing.add(view_type)
                done = True
            if key == "chatter":
                form = editor._views_of(model_name)
                form_view = next(
                    (v for v in form if v["type"] == "form" and v.get("view_id")),
                    None,
                )
                if form_view:
                    done |= bool(
                        editor.add_chatter(
                            form_view["view_id"], cast("int", package.id)
                        )
                    )
        base.features_json = "[]"
        return done

    @api.model
    def _combined_names(self, view: View, name: str) -> bool:
        """Whether ``name`` is already in the view as it renders, its
        extensions included -- the check a patched view needs, since the
        field lands in the extension and not in ``view.arch``."""
        root = cast(
            "LxmlElement",
            etree.fromstring(cast("str", view.get_combined_arch()).encode()),
        )
        return bool(root.xpath(".//field[@name='%s']" % name))

    # -- after a reload that outran the request -------------------------------

    def place_pending(self) -> PlacePendingJSON:
        """Finish an Apply the server restarted in the middle of.

        Under a ``restart`` reload the request that pressed Apply dies with
        the server, somewhere after the package was written and committed
        and before the fields were placed in their views and the draft's
        baseline moved -- that part of the transaction rolled back. The
        console reconnects to a registry that has the columns and a draft
        that still says they are pending. This is the rest of that Apply:
        the same placement, from the same anchors, and the baseline moved
        after it, for this draft and its companions alike.

        Only once the reload really happened. A draft whose fields the
        registry does not have -- the request died before the write, or
        the restart has not picked the package up -- is still pending in
        fact, and says so rather than placing fields that do not exist.
        """
        typed.security(self)._assert_studio_manager()
        self.ensure_one()
        drafts = self | cast("StudioModelDraftBase", self).companion_ids
        planned: list[tuple[StudioModelDraft, ModelSpec, SpecDiff]] = []
        for draft in drafts:
            base_draft = cast("StudioModelDraftBase", draft)
            spec = base_draft._spec()
            diff = modelspec.diff_specs(base_draft._base_spec(), spec)
            missing = draft._missing_from_registry(diff)
            if missing:
                return {
                    "placed": False,
                    "reason": _(
                        "%(model)s does not have %(fields)s yet; the apply "
                        "did not go through.",
                        model=base_draft.model,
                        fields=", ".join(missing),
                    ),
                }
            planned.append((draft, spec, diff))
        for draft, spec, diff in planned:
            draft._place_in_views(spec, diff)
            draft._apply_features()
        for draft in drafts:
            base_draft = cast("StudioModelDraftBase", draft)
            base_draft.base_spec_json = base_draft.spec_json
        return {"placed": True, "reason": ""}

    def _missing_from_registry(self, diff: SpecDiff) -> list[str]:
        """The added fields the running registry does not have as columns,
        and the removed ones it still has: either says the reload has not
        happened. A field the class declares but the table lacks counts as
        missing too -- a server restarted on the new source without the
        upgrade that creates the column is exactly the half-way state a
        restart-mode apply can leave."""
        self.ensure_one()
        Model = self.env.get(cast("str", cast("StudioModelDraftBase", self).model))
        if Model is None:
            return list(diff.added)
        missing = []
        for name in diff.added:
            field = Model._fields.get(name)
            if field is None or (
                field.store
                and field.column_type
                and not Model._abstract
                and not sql.column_exists(self.env.cr, Model._table, name)
            ):
                missing.append(name)
        missing += [name for name in diff.removed if name in Model._fields]
        return missing

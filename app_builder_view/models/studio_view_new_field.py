# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Creating a field from inside the view editor, where you noticed it was missing.

The gesture has two answers, and choosing between them is most of the work.

On a model this package **defines in Python**, a clean-named field is a class
attribute, and a new column needs the class re-imported -- so the honest
behaviour is to stage it: the field goes on the user's draft with the drop
location remembered as an anchor, a ghost stands in for it on the canvas,
and one Apply writes and reloads the whole changeset and puts the real field
exactly where the ghost was.

On a **core or adopted** model there is no such wait: a manual field is an
``ir.model.fields`` row, it is live the moment it is written, and the ``x_``
prefix Odoo requires there is expected anyway. So create-and-place is one
gesture, and the field lands on the screen you were looking at as an inheriting
view.

Both answers take the same vocabulary -- the picker's entries, with their
presets -- so one tile drops on either kind of model and means the same
thing: Priority is four values and a star on both paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias, TypedDict, cast

from typing_extensions import NotRequired

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.base.models.ir_model import IrModelFields, IrModelSelection
from odoo.addons.base.models.ir_ui_view import View
from odoo.addons.app_builder_base.models.studio_model_draft import StudioModelDraft
from odoo.addons.app_builder_base.models.studio_package import StudioPackage
from odoo.addons.app_builder_base.tools import modelspec, typed

from ..tools import manualfield

if TYPE_CHECKING:
    # Only for the annotations/casts below; with `from __future__ import
    # annotations` nothing here needs these at runtime, the same bargain
    # every other Phase 1c file's `TYPE_CHECKING` block makes.
    from collections.abc import Iterable, Mapping

    from odoo.addons.app_builder_base.tools.lxml_types import LxmlElement

    from ..tools import canvas_stamp

    # This file is a pure `_inherit = "studio.view.editor"` extension, the
    # same `_name` TWO other real, different Python classes declare -- the
    # registry composes all three into one model at runtime, but neither is
    # a real Python base of this file's own class, so each is aliased on
    # import rather than colliding with this file's own class of the
    # identical name (rule 7, precedent: `studio_package_model.py`'s own
    # `StudioPackageModelBase`). Cast to each wherever this file calls a
    # method, or reads a class attribute, the other file declares and this
    # one does not -- invisible to pyright on a bare `self` otherwise.
    from .studio_view_canvas import CanvasFieldInfoJSON, FieldDefinitionJSON
    from .studio_view_canvas import StudioViewEditor as StudioViewEditorCanvas
    from .studio_view_editor import DropCreatedFieldJSON, DropSuccessJSON
    from .studio_view_editor import StudioViewEditor as StudioViewEditorBase

    class _DraftHandle(Protocol):
        """``draft.set_anchor()``/``draft._added_names()`` are declared on
        ``app_builder_view/models/studio_model_draft.py``'s own pure
        ``_inherit`` extension of ``studio.model.draft`` -- not
        ``app_builder_base``'s own base class (``typed.model()``'s real
        target elsewhere in this file for ``StudioModelDraft`` itself), and
        not yet converted -- so invisible to pyright on a plain
        ``StudioModelDraft``-typed ``draft``. The same narrow
        composed-elsewhere workaround ``studio_view_editor.py``'s own
        ``_DraftHandle`` Protocol is, for the same sibling file, here for
        the two methods this file's own ``_drop_field_definition`` calls.
        """

        def set_anchor(
            self,
            name: str,
            anchor: dict[str, object],
            release_dependents: bool = True,
        ) -> object: ...
        def _added_names(self) -> list[str]: ...


# What the panel offered before the picker did. Kept because the answer to
# ``quick_field_types`` is an RPC older clients still make; every entry of it
# is a plain type whose whole definition is a name and a label, and each is
# a subset of what ``create_field_at`` takes now.
QUICK_TYPES = (
    ("char", "Text"),
    ("text", "Multiline text"),
    ("integer", "Whole number"),
    ("float", "Decimal"),
    ("monetary", "Money"),
    ("boolean", "Checkbox"),
    ("date", "Date"),
    ("datetime", "Date & time"),
    ("html", "Rich text"),
    ("binary", "File"),
    ("many2one", "Link to a record"),
)

# Keys a client may write on a manual field's definition. ``selection``
# stands for its rows, synchronised by value. Not ``name`` or ``ttype``:
# renaming a column or changing its type is a migration, not an edit.
MANUAL_FIELD_WRITABLE = (
    "field_description",
    "help",
    "required",
    "readonly",
    "index",
    "translate",
    "selection",
)


# -- wire types -----------------------------------------------------------
#
# Cross-checked against `app_builder_view/static/src/console/wire.ts` and
# `.../console/types.ts`, the same read-only references
# `studio_view_editor.py`'s own wire types are checked against.


class QuickFieldTypeJSON(TypedDict):
    """One entry of ``quick_field_types()``'s own answer -- the pre-picker
    vocabulary an older client still asks for over RPC."""

    value: str
    label: str


class PickerFieldTypeJSON(modelspec.FieldTypeJSON):
    """``field_types_for()``'s own entry: ``available_field_types``'s
    (``modelspec.py``) ``FieldTypeJSON`` plus whether a drop here is live
    or needs a dialog first. A real, non-``TYPE_CHECKING`` import of the
    parent TypedDict (rule 9, the same shape `studio_view_canvas.py`'s own
    ``CanvasFieldInfoJSON`` already established): ``class X(Y):`` executes
    at import time."""

    live: bool
    needs_dialog: bool


class _NewFieldPlanRefusedJSON(TypedDict):
    can_create: Literal[False]
    reason: str
    handoff: NotRequired[int]
    model: NotRequired[str]


class _NewFieldPlanAllowedJSON(TypedDict):
    can_create: Literal[True]
    model: str
    prefix: str


#: ``new_field_plan()``'s whole return: which of the two answers -- live or
#: staged -- applies here, and what to say about it.
NewFieldPlanJSON: TypeAlias = _NewFieldPlanRefusedJSON | _NewFieldPlanAllowedJSON


class StudioViewEditor(models.AbstractModel):
    _inherit = "studio.view.editor"

    @api.model
    def quick_field_types(self) -> list[QuickFieldTypeJSON]:
        typed.security(self)._assert_studio_user()
        return [{"value": key, "label": label} for key, label in QUICK_TYPES]

    @api.model
    def _python_owner(self, model_name: str) -> StudioPackage:
        """The package that defines ``model_name`` as a Python class, if any."""
        for package in typed.model(self.env, StudioPackage).search([]):
            if model_name in package._python_model_set():
                return package
        return typed.model(self.env, StudioPackage).browse()

    @api.model
    def new_field_plan(self, view_id: int) -> NewFieldPlanJSON:
        """Which of the two answers applies here, and what to say about it.

        Asked before the form is shown rather than after it is submitted: a
        panel that takes a name and a type and then explains it cannot use them
        is worse than one that says so first.
        """
        typed.security(self)._assert_studio_user()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view or not view.model:
            return {"can_create": False, "reason": _("This view has no model.")}
        owner = self._python_owner(cast("str", view.model))
        if owner:
            return {
                "can_create": False,
                "handoff": cast("int", owner.id),
                "model": cast("str", view.model),
                "reason": _(
                    "%(model)s is defined in Python by %(package)s, so a new "
                    "field is a class attribute and the model has to be "
                    "re-imported before it exists. Dropping it stages it here, "
                    "where it lands on Apply.",
                    model=view.model,
                    package=owner.name,
                ),
            }
        return {"can_create": True, "model": cast("str", view.model), "prefix": "x_"}

    @api.model
    def field_types_for(self, model_name: str) -> list[PickerFieldTypeJSON]:
        """The picker's tiles for one model, with what each tile will do.

        ``modelspec.available_field_types`` says what the type is and
        whether the model can take it at all; two facts are added here that
        only the model decides. ``live``: whether a drop creates the field
        on the spot -- a manual row on a model no package defines in Python
        -- or stages it on a draft. ``needs_dialog``: whether the tile has
        to ask something before the first request can be made. A scalar is
        created as "New Text" and the label row takes the cursor; a link
        has to be told what it links to first.

        ``live`` is a fact about the type, not a promise: a related list
        still needs a link back on the other model, and an amount a
        currency field, and both are asked for in the dialog and refused in
        a sentence when they are missing.
        """
        typed.security(self)._assert_studio_user()
        if model_name not in self.env:
            raise UserError(_("Unknown model '%s'.", model_name))
        owner = self._python_owner(model_name)
        # `available_field_types` returns plain `FieldTypeJSON` entries; the
        # two extra keys this method adds below are only true once they are
        # set, so the list is cast to this file's own subclass (rule 9,
        # the same idiom `studio_view_canvas.py`'s own `_canvas_field_info`
        # uses for its own `CanvasFieldInfoJSON`) rather than declared that
        # shape from the start.
        entries = cast(
            "list[PickerFieldTypeJSON]",
            modelspec.available_field_types(
                cast("StudioViewEditorBase", self)._python_spec(owner, model_name),
                self.env._,
            ),
        )
        has_currency = bool(manualfield.default_currency_field(model_name, self.env))
        for entry in entries:
            key = entry["value"]
            entry["live"] = (
                not owner and entry["enabled"] and manualfield.creatable_live(key)
            )
            entry["needs_dialog"] = manualfield.needs_dialog(key, has_currency)
        return entries

    # -- the live path --------------------------------------------------------

    @api.model
    def create_field_at(
        self,
        view_id: int,
        package_id: int,
        anchor: dict[str, object],
        values: Mapping[str, Any] | None,
        position: object = None,
        expected_arch_version: str | None = None,
        write_files: bool = True,
    ) -> DropCreatedFieldJSON:
        """Create a manual field and place it, in one gesture.

        Only on a model no package defines in Python: everywhere else this
        would write a row that the next Apply has to reconcile against a class,
        which is the drift the project exists to prevent.

        ``values`` is the picker's vocabulary -- an entry key for ``ttype``,
        ``comodel``, ``selection``, ``related`` and the rest -- expanded by
        ``modelspec.apply_preset`` and translated to a row by
        ``manualfield``. The order is disk after database: the row is
        written, the view is patched, and the package goes to disk once at
        the end, so a view operation that fails leaves no field on disk for
        a row the transaction then rolls back.
        """
        typed.security(self)._assert_studio_manager()
        view = typed.model(self.env, View).browse(view_id).exists()
        if not view:
            raise UserError(_("The view being edited no longer exists."))
        plan = self.new_field_plan(view_id)
        if not plan.get("can_create"):
            raise UserError(plan.get("reason") or _("A field cannot be created here."))

        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this field in."))

        values = dict(values or {})
        label: str = (
            values.get("field_description") or values.get("string") or ""
        ).strip()
        if not label:
            raise UserError(_("The field needs a label."))
        values, widget = modelspec.apply_preset(values)
        values["field_description"] = label
        if not values.get("name"):
            values["name"] = self._quick_field_name(label, view.model)
        payload = manualfield.ir_model_fields_vals(
            values, cast("str", view.model), self.env
        )
        name = cast("str", payload["name"])

        field = (
            typed.model(self.env, IrModelFields)
            .with_context(studio_skip_autocapture=True)
            .create(payload)  # pyright: ignore[reportArgumentType]
        )
        # `create()` only declares `list[ValuesType]`; the single-dict form
        # is accepted at runtime (`@api.model_create_multi`), the same
        # decorator-stub gap `studio_view_editor.py`'s own
        # `_get_or_create_extension` already documents.
        #
        # Ownership now, files later. The selection rows are captured by
        # hand: nothing autocaptures `ir.model.fields.selection`, and a
        # Priority whose values stayed out of the package XML would come
        # back from the next database as a selection with no values.
        # `field.selection_ids` reads as a wider union than `BaseModel` here
        # -- a plain-string-comodel `One2many`'s own read type, per rule 5 --
        # cast at this real read site.
        package._assign([field, cast("IrModelSelection", field.selection_ids)])
        # And onto the screen it was created from. Creating a field and leaving
        # the user to find it in a palette is two gestures for one intention.
        operation: dict[str, object] = {"type": "add_field", "name": name}
        if widget:
            operation["attrs"] = {"widget": widget}
        position = cast("StudioViewEditorBase", self)._explicit_position(position)
        if position:
            operation["position"] = position
        cast("StudioViewEditorBase", self).apply_at(
            view_id,
            package_id,
            anchor,
            operation,
            expected_arch_version=expected_arch_version,
            write_files=False,
        )
        if write_files and package.writable:
            package.action_write_files()
        return {"name": name, "label": label, "live": True}

    @api.model
    def _quick_field_name(
        self, label: str, model_name: str | Literal[False] | None = None
    ) -> str:
        """The ``x_`` name a label implies, kept clear of what the model
        has: a second Text tile dropped before the first was renamed is
        ``x_new_text_2``, not a refusal."""
        name = manualfield.field_name_for(label, prefix="x_")
        taken = (
            self.env[cast("str", model_name)]._fields if model_name in self.env else ()
        )
        return manualfield.unique_name(name, taken)

    @api.model
    def update_manual_field(
        self,
        model_name: str,
        name: str,
        values: Mapping[str, Any] | None,
        package_id: int,
    ) -> FieldDefinitionJSON | None:
        """Change the definition of a manual field, and write it to source.

        Only a manual field: a core field's label is Python, and writing
        the row behind it would put a value in the database that the next
        upgrade overwrites without a word. The keys are the ones the
        properties panel offers (``MANUAL_FIELD_WRITABLE``); the selection
        rows are synchronised by value -- created, relabelled, removed --
        rather than replaced, so a value records already hold keeps its
        row and its id.

        Captured once, field and rows together, and written once.
        """
        typed.security(self)._assert_studio_manager()
        record = typed.model(self.env, IrModelFields)._get(model_name, name)
        if not record:
            raise UserError(
                _(
                    "%(field)s is not a field of %(model)s.",
                    field=name,
                    model=model_name,
                )
            )
        if record.state != "manual":
            raise UserError(
                _(
                    "%(field)s is defined in Python; its definition can only "
                    "be changed in the code that declares it.",
                    field=name,
                )
            )
        package = typed.model(self.env, StudioPackage).browse(package_id).exists()
        if not package:
            raise UserError(_("Choose a studio package to record this change in."))
        values = dict(values or {})
        unknown = set(values) - set(MANUAL_FIELD_WRITABLE)
        if unknown:
            raise UserError(
                _(
                    "Not something the builder changes on a field: %s",
                    ", ".join(sorted(unknown)),
                )
            )
        writes: dict[str, Any] = {}
        if "field_description" in values:
            label: str = (values["field_description"] or "").strip()
            if not label:
                raise UserError(_("The field needs a label."))
            writes["field_description"] = label
        if "help" in values:
            writes["help"] = values["help"] or False
        for key in ("required", "readonly", "index"):
            if key in values:
                writes[key] = bool(values[key])
        if "translate" in values:
            if values["translate"] and record.ttype not in manualfield.TRANSLATABLE:
                raise UserError(_("Only text fields can be translated."))
            writes["translate"] = bool(values["translate"])
        if writes:
            record.write(writes)
        if "selection" in values:
            if record.ttype not in ("selection", "reference"):
                raise UserError(_("%s is not a selection.", name))
            self._sync_selection(record, values["selection"])
        package.studio_capture(
            [record, cast("IrModelSelection", record.selection_ids)], write_files=True
        )
        return cast("StudioViewEditorCanvas", self)._field_definition(
            model_name, cast("CanvasFieldInfoJSON", {"name": name, "origin": "manual"})
        )

    @api.model
    def _sync_selection(
        self, record: IrModelFields, entries: Iterable[Mapping[str, Any]] | None
    ) -> Literal[True]:
        """Make the rows match ``entries`` by value."""
        rows = manualfield.selection_rows(entries, self.env)
        wanted = {row["value"]: row for row in rows}
        existing = {
            line.value: line for line in cast("IrModelSelection", record.selection_ids)
        }
        for value, line in existing.items():
            if value not in wanted:
                line.unlink()
        Selection = typed.model(self.env, IrModelSelection)
        for row in rows:
            line = existing.get(row["value"])
            if line is None:
                # Same `create()`-stub gap as `create_field_at`'s own
                # `.create(payload)` above.
                Selection.create({"field_id": record.id, **row})  # pyright: ignore[reportArgumentType]
                continue
            changes = {
                key: row[key]
                for key in ("name", "sequence")
                if getattr(line, key) != row[key]
            }
            if changes:
                line.write(changes)
        return True

    # -- the drop -------------------------------------------------------------

    @api.model
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
    ) -> DropSuccessJSON:
        """A ``new_field`` or ``move_pending`` drop, on whichever path applies.

        Called by ``drop_at`` once the target has passed the same checks
        every drop passes. Which path is ``new_field_plan``'s answer: a
        model no package defines in Python takes the field live, through
        ``create_field_at`` with the disk gate closed; a Python-owned one
        stages it on the user's draft and anchors it at the target. The
        answer has the shape of every other drop's, plus ``created`` for a
        live field or ``staged`` for a pending one and the draft's state
        when there is a draft, so the tray and the canvas move together.
        """
        kind = payload.get("kind")
        plan = self.new_field_plan(cast("int", view.id))
        if kind == "new_field" and plan.get("can_create"):
            return self._drop_live_field(
                view, package, token, position, container, payload, options
            )
        if not plan.get("handoff"):
            if kind == "move_pending":
                raise UserError(
                    _(
                        "Nothing is pending on %s; fields here are created live.",
                        view.model,
                    )
                )
            raise UserError(plan.get("reason") or _("A field cannot be created here."))
        Draft = typed.model(self.env, StudioModelDraft)
        draft = Draft.browse(Draft.open_for_model(cast("str", view.model))["id"])
        anchor = self._mint_anchor(view, stamped, root, token, position)
        if kind == "new_field":
            values = dict(
                # `payload["values"]` is a genuinely `Any`-shaped RPC dict
                # here (not yet through `modelspec.apply_preset`); cast
                # rather than left as the declared `dict[str, object]`, so
                # `.strip()` below and `draft.add_field`'s own `dict[str,
                # Any]` parameter type-check the same way `create_field_at`'s
                # identical line does.
                cast("dict[str, Any]", payload.get("values") or {})
            )
            label: str = (
                values.get("field_description") or values.get("string") or ""
            ).strip()
            if not label:
                raise UserError(_("The field needs a label."))
            values["string"] = label
            values.pop("field_description", None)
            if not values.get("name"):
                values["name"] = self._staged_field_name(
                    label, cast("str", view.model), draft
                )
            name = cast("str", values["name"])
            if not name.isidentifier():
                raise UserError(_("'%s' is not a usable field name.", name))
            # The placement slots keep saying which views the field goes
            # in, and carry the widget the entry implies; the anchor says
            # where in this one. A field dropped on the form still gets
            # its list column.
            draft.add_field(values)
        else:
            name = cast("str", payload.get("name"))
            if name not in cast("_DraftHandle", draft)._added_names():
                raise UserError(
                    _("There is no pending field called '%s' to place.", name)
                )
            if anchor.get("pending") == name:
                raise UserError(_("A field cannot be placed beside itself."))
        cast("_DraftHandle", draft).set_anchor(name, anchor)
        loaded = draft.load()
        label = next((f["string"] for f in loaded["fields"] if f["name"] == name), name)
        options = dict(options, draft_id=draft.id)
        canvas = cast("StudioViewEditorCanvas", self).canvas(
            cast("int", view.id), options
        )
        return {
            "stale": False,
            "select": cast("StudioViewEditorCanvas", self).PENDING_TOKEN_PREFIX + name,
            "created": None,
            "staged": {
                "name": name,
                "label": label or name,
                "draft_id": cast("int", draft.id),
            },
            "canvas": canvas,
            "history": canvas["history"],
            "draft": loaded,
        }

    @api.model
    def _drop_live_field(
        self,
        view: View,
        package: StudioPackage,
        token: canvas_stamp.Token,
        position: str,
        container: canvas_stamp.StudioNode,
        payload: dict[str, object],
        options: dict[str, object],
    ) -> DropSuccessJSON:
        """The live half of a ``new_field`` drop."""
        created = self.create_field_at(
            cast("int", view.id),
            cast("int", package.id),
            {"kind": "node", "token": token},
            cast("dict[str, Any]", payload.get("values") or {}),
            position=position,
            write_files=False,
        )
        if package.writable:
            package.action_write_files()
        canvas = cast("StudioViewEditorCanvas", self).canvas(
            cast("int", view.id), options
        )
        return {
            "stale": False,
            "select": cast("StudioViewEditorBase", self)._token_named(
                canvas["nodes"],
                created["name"],
                "field",
                within=(container["tag"], container["name"]),
            ),
            "created": created,
            "staged": None,
            "canvas": canvas,
            "history": canvas["history"],
            "draft": None,
        }

    @api.model
    def _staged_field_name(
        self, label: str, model_name: str, draft: StudioModelDraft
    ) -> str:
        """The clean name a label implies for a class attribute, kept clear
        of what the model has and what the draft is already adding."""
        name = manualfield.field_name_for(label, prefix="")
        taken = set(self.env[model_name]._fields) | {
            f.name for f in draft._spec().fields
        }
        return manualfield.unique_name(name, taken)

    @api.model
    def _mint_anchor(
        self,
        view: View,
        stamped: canvas_stamp.StampResult,
        root: LxmlElement,
        token: canvas_stamp.Token,
        position: str,
    ) -> dict[str, object]:
        """Everything a drop location is, minted now for a field that is not.

        The xpath and the arch version it holds on, so Apply can use it as
        it is while the view is unchanged; and the neighbour by what it is
        -- a legacy descriptor, "the field called email" -- so it can be
        found again when the view has moved on. The version is the
        neutral one every edit is checked against, not the one this user's
        language produced.

        A ghost as the target has no place in the arch to mint from: the
        anchor names the staged field instead, and is resolved wherever
        that field turns out to be.
        """
        base = cast("StudioViewEditorBase", self)
        entry = stamped.nodes[token]
        if entry["kind"] == "pending":
            return {
                "view_id": view.id,
                "position": position,
                # `"pending"` is `NotRequired` on `StudioNode` in general
                # (real for every node this branch selects, a `kind:
                # "pending"` ghost) -- `.get()` plus a cast, the same
                # `_reanchor_gap`'s own workaround in `studio_view_editor.py`.
                "pending": cast("canvas_stamp.PendingFieldInfo", entry.get("pending"))[
                    "name"
                ],
            }
        node = stamped.elements[token]
        return {
            "view_id": view.id,
            "xpath": base._locator_for(node, base._occurrences(root)),
            "position": position,
            "arch_version": base._version_of(
                cast("int", view.id), base._neutral_combined_arch(view)
            ),
            "descriptor": self._legacy_descriptor(stamped, root, token),
        }

    @api.model
    def _legacy_descriptor(
        self,
        stamped: canvas_stamp.StampResult,
        root: LxmlElement,
        token: canvas_stamp.Token,
    ) -> dict[str, object] | None:
        """The ``{kind, name}`` descriptor for a node, or ``None``.

        The vocabulary ``_find_descriptor`` resolves without a token: the
        root; a named node of a kind the table knows, while nothing else
        in the arch answers to that name; a tab by its index among the
        tabs, since core pages seldom carry a name; a singleton container
        -- the sheet, the header -- by its kind alone. A node with none of
        these -- an unnamed group, a field whose name a header repeats --
        has no name to be found by later, and ``None`` says so: the exact
        xpath still serves while the arch is unchanged, and the balanced
        fallback after that. A name shared with another node would be
        found again as whichever comes first, which is a guess dressed as
        an answer.
        """
        entry = stamped.nodes[token]
        node = stamped.elements[token]
        kind = entry["kind"]
        if kind == "root":
            return {"kind": "root"}
        base = cast("StudioViewEditorBase", self)
        if kind not in base.DESCRIPTOR_TAGS:
            return None
        tag = base.DESCRIPTOR_TAGS[kind]
        candidates = [
            candidate
            for candidate in root.iter(tag)
            if not any(a.tag == "field" for a in candidate.iterancestors())
        ]
        name = node.get("name")
        if name:
            # Counted the way `_find_descriptor` will look: outside subviews.
            if sum(1 for c in candidates if c.get("name") == name) == 1:
                return {"kind": kind, "name": name}
            return None
        if tag == "page":
            return {"kind": kind, "index": candidates.index(node)}
        if len(candidates) == 1:
            return {"kind": kind}
        return None

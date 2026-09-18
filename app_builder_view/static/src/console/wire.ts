/** @odoo-module **/
/**
 * The shapes `app_builder_base/tools/catalogue.py`'s `to_json()`s actually
 * send -- the vocabulary of what a row/widget/group is, not any one
 * node's current values (`types.ts` has those).
 *
 * Hand-kept in sync with the Python `TypedDict`s of the same names, as
 * that file's own docstring says it must be until TYPING.md's Phase 2d
 * generator exists: change one side, change the other in the same
 * commit. Field order matches the Python source so a diff of either file
 * lines up with the other.
 */

/** `app_builder_base/tools/catalogue.py:RowJSON`. */
export interface RowJSON {
    name: string;
    label: string;
    type: string;
    target: string;
    help: string;
    invert: boolean;
    choices: [string, string][];
    source: string;
    field_types: string[];
    only_for: string[];
    placeholder_from: string;
    allow_empty: boolean;
    empty_label: string;
    comodel: string;
    comodel_domain: string;
    selection_from: string;
    visible_when: [string, string[]][];
    required: boolean;
    language: string;
}

/** `app_builder_base/tools/catalogue.py:SectionJSON`. */
export interface SectionJSON {
    id: string;
    title: string;
    rows: RowJSON[];
    visible_when: [string, string[]][];
}

/** `app_builder_base/tools/catalogue.py:WidgetJSON`. */
export interface WidgetJSON {
    value: string;
    label: string;
    types: string[];
    rows: RowJSON[];
}

/** `app_builder_base/tools/catalogue.py:OptionGroupJSON`. */
export interface OptionGroupJSON {
    id: string;
    title: string;
    view_types: string[];
    kinds: string[];
    rows: RowJSON[];
}

/** `app_builder_base/tools/catalogue.py:CatalogueJSON` -- the whole
 * vocabulary, as `context.catalogue` carries it (`console_model.js`). */
export interface CatalogueJSON {
    widgets: WidgetJSON[];
    image_sizes: [string, string][];
    relational_rows: RowJSON[];
}

// -- studio.model.draft ------------------------------------------------
//
// `app_builder_base/tools/modelspec.py` (the `FieldSpec`/`SelectionSpec`
// dataclasses and `available_field_types`/`default_placement`) and
// `app_builder_base/models/studio_model_draft.py` (`load`,
// `pending_changes`/`_own_changes`).

/** `modelspec.py:SelectionSpec`, as `asdict()` sends it. */
export interface SelectionSpecJSON {
    value: string;
    label: string;
    sequence: number;
}

/**
 * `modelspec.py:FieldSpec`, as `asdict()` sends it (`spec_to_json`) --
 * one entry of `DraftPayload.fields`, before `load()` adds `type_label`/
 * `placement` (see `DraftFieldJSON`). `None` on the Python side is
 * `null` here, not an absent key: `asdict()` always emits every
 * dataclass field.
 */
export interface FieldSpecJSON {
    name: string;
    ttype: string;
    string: string | null;
    help: string | null;
    comodel: string | null;
    inverse_name: string | null;
    relation_table: string | null;
    column1: string | null;
    column2: string | null;
    domain: string | null;
    ondelete: string | null;
    selection: SelectionSpecJSON[];
    size: number | null;
    digits: [number, number] | null;
    currency_field: string | null;
    translate: boolean | null;
    required: boolean | null;
    readonly: boolean | null;
    index: boolean | null;
    copy: boolean | null;
    store: boolean | null;
    tracking: number | null;
    group_expand: string | boolean | null;
    default: string | null;
    related: string | null;
    compute: string | null;
    compute_body: string | null;
    depends: string[];
    extra: [string, string][];
}

/** `modelspec.py:default_placement` -- which views a field shows in. */
export interface PlacementJSON {
    form: boolean;
    list: boolean;
    search: boolean;
    group_by: boolean;
    widget: string;
}

/** One entry of `DraftPayload.fields`: a `FieldSpecJSON` plus the two
 * keys `load()` adds itself (`studio_model_draft.py:load`). */
export interface DraftFieldJSON extends FieldSpecJSON {
    type_label: string;
    placement: PlacementJSON;
}

/** One entry of the field-type picker (`modelspec.py:available_field_types`). */
export interface AvailableFieldTypeJSON {
    value: string;
    ttype: string;
    widget: string;
    label: string;
    group: string;
    params: string[];
    enabled: boolean;
    tooltip: string;
    placement: PlacementJSON;
    widgets: WidgetJSON[];
}

/** One line of `DraftPayload.pending`
 * (`studio_model_draft.py:_own_changes`/`pending_changes`). `model` is
 * present only on a companion model's change, spliced in by
 * `pending_changes`; `destructive` only on a `"removed"` one. */
export interface PendingChangeJSON {
    kind: "model" | "added" | "changed" | "removed";
    name: string;
    detail: string;
    destructive?: boolean;
    model?: string;
}

/** `DraftPayload.package` (`studio_model_draft.py:load`). */
export interface DraftPackageJSON {
    id: number;
    name: string;
    writable: boolean;
    reload_mode: string;
}

// -- studio.workspace ----------------------------------------------------
//
// `app_builder_base/models/studio_workspace.py`.

/** `studio_workspace.py:_apply_dict` -- one row of `PackageEntry.applies.last`. */
export interface ApplyEntryJSON {
    id: number;
    reason: string;
    state: string;
    error: string;
    create_date: string | false;
    user: { id: number; name: string };
    backup_path: string;
    has_backup: boolean;
    files: { path: string; existed: boolean }[];
    can_rollback: boolean;
}

/** `studio_workspace.py:_package_dict` -- one entry of `packages()`, the
 * shell's own `packages` list and `package` getter. */
export interface PackageEntryJSON {
    id: number;
    name: string;
    title: string;
    summary: string;
    version: string;
    root_path: string;
    writable: boolean;
    reload_mode: string;
    state: string;
    drift_count: number;
    file_count: number;
    record_count: number;
    module_state: string;
    git: {
        is_git: boolean;
        branch: string;
        dirty: number;
        untracked: number;
    };
    models: {
        python: number;
        frozen: number;
        extends: number;
        xml: number;
    };
    applies: {
        pending: number;
        failed: number;
        awaiting_restart: number;
        last: ApplyEntryJSON | null;
    };
    drafts: number;
    health: string[];
    suggested: boolean;
}

/** `studio_workspace.py:PREF_KEYS` -- `user_prefs()`'s whole return, one
 * key per remembered preference. */
export interface UserPrefsJSON {
    last_package_id?: number | false;
    checklist_dismissed?: boolean;
    recent_models?: string[];
    sidebar_width?: number | false;
}

/**
 * `studio.model.draft.load()`'s whole round trip
 * (`studio_model_draft.py:load`). `spec`/`view`/`anchors`/`field_types`
 * are not yet given a precise shape here -- nothing converted so far
 * reads them (`shell/draft_model.ts` only reads `id`, `package`,
 * `pending`, `change_count`, `fields`, `errors`); narrow them when the
 * file that actually consumes one is converted, per this migration's own
 * rule against typing ahead of a real reader.
 */
export interface DraftPayload {
    id: number;
    model: string;
    package: DraftPackageJSON;
    spec: unknown;
    fields: DraftFieldJSON[];
    pending: PendingChangeJSON[];
    change_count: number;
    field_types: AvailableFieldTypeJSON[];
    errors: string[];
    view: unknown;
    anchors: unknown;
}

// -- studio.record.surface -----------------------------------------------
//
// `app_builder_base/models/studio_record_surface.py`. One `AbstractModel`
// per kind of record a record pane lists (automations, rules,
// approvals, an automation's own steps as `children`); every surface
// shares this one wire contract (DESIGN.md).

/** One row of `catalogue()`'s `templates` -- what the New tiles offer
 * (`studio_record_surface.py:templates`). */
export interface RecordTemplateJSON {
    key: string;
    label: string;
    help: string;
    values: Record<string, unknown>;
    needs: string[];
}

/** `catalogue()`'s whole return (`studio_record_surface.py:catalogue`). */
export interface RecordCatalogueJSON {
    model: string;
    sections: SectionJSON[];
    templates: RecordTemplateJSON[];
}

/** One badge on a row's card (`studio_record_surface.py:_badges`). */
export interface RecordBadgeJSON {
    key: string;
    label: string;
}

/** One entry of `rows()`: a record as a card
 * (`studio_record_surface.py:_row`). */
export interface RecordRowJSON {
    id: number;
    title: string;
    sentence: string;
    badges: RecordBadgeJSON[];
    active: boolean;
    owned: boolean;
    owner: string | false;
    in_source: boolean;
    editable: boolean;
    reason: string;
    model: string;
    /** Only the menu surface's own `rows()` override sends this
     * (`app_builder_ui/models/studio_menu_surface.py`'s `row["depth"] =
     * depth`), for its tree indentation. */
    depth?: number;
}

/** One button `describe()`'s `actions` offers besides Advanced/Remove
 * (`studio_record_surface.py:_actions`). */
export interface RecordActionJSON {
    key: string;
    label: string;
    icon: string;
    enabled: boolean;
    reason: string;
    danger: boolean;
}

/**
 * The children of a described record -- an automation's steps, each
 * described by their own surface (`studio_automation_surface.py:
 * _describe_extra`, the pattern every child-bearing surface follows).
 * `items` is recursive: each one is a full `RecordDescription` from that
 * child surface's own `describe()`.
 */
export interface RecordChildrenJSON {
    surface: string;
    label: string;
    /** The singular noun for one child ("step"), for "Add a %(one)s". */
    one: string;
    items: RecordDescription[];
    /** `[value, label]` pairs (`Step._states()`,
     * `app_builder_ui/models/studio_automation_surface.py`) -- not a bare
     * `string[]`. */
    kinds: [string, string][];
    kind_field: string;
    /** The method name `addChild` calls on `surface`. */
    add: string;
    /** The method name `moveChild` calls on `surface`, when children can
     * be reordered at all. */
    move?: string;
    empty: string;
}

/**
 * `describe()`'s whole return: everything the sidebar needs for one
 * selected record (`studio_record_surface.py:describe`). `children` and
 * anything else past `sentence` comes from a surface's own
 * `_describe_extra` override (the base returns nothing extra); nothing
 * beyond `children` is named yet, since no converted file reads another
 * key -- narrow further when one does.
 */
export interface RecordDescription {
    row: RecordRowJSON;
    values: Record<string, unknown>;
    sections: SectionJSON[];
    actions: RecordActionJSON[];
    notes: unknown[];
    advanced: {
        res_model: string;
        res_id: number;
        context: { studio_package_id: number | false };
    };
    sentence: string;
    children?: RecordChildrenJSON;
    [key: string]: unknown;
}

// -- studio.view.editor / studio.view.canvas -----------------------------
//
// `app_builder_view/models/studio_view_editor.py`,
// `app_builder_view/models/studio_view_canvas.py`,
// `app_builder_view/models/studio_view_new_field.py`. The Views pane's own
// RPC surface (`console_model.ts`) -- every mutator funnels through
// `apply_operation` or `drop_at`, so their two answer shapes
// (`OperationResult`, `DropSuccessResult`) cover every edit the canvas
// makes. `CanvasPayload` itself, and everything that carries a `Token` or
// a `NodeTable`, lives in `types.ts` instead -- that module's own concern,
// per its docstring, and where `Token`/`NodeTable` are already declared.

/** One view of a model, as `_views_of` picks it (`editing_context`'s own
 * `views`, the console's switcher). */
export interface ViewOfEntry {
    type: string;
    view_id: number;
    name: string;
    owned: boolean;
}

/** A field entry `_model_fields` builds for options that name one
 * (`studio_view_editor.py:_model_fields`, `editing_context`'s `fields`). */
export interface EditingContextFieldEntry {
    name: string;
    string: string;
    type: string;
}

/**
 * `_preview_for`'s whole return (`studio_view_editor.py:_preview_for`,
 * called from `editing_context()`'s own `"preview": self._preview_for(view)`) --
 * how to render the view being edited. Every type previews itself, so
 * `view_id` is that same view and `unavailable` is never set -- except a
 * search view, which has no rendering of its own and previews as the
 * model's list with this search view attached instead (`search_view_id`),
 * and can point at no list at all (`unavailable: true`) when the model
 * has none. `search_view_id` is always present, `false` when not
 * applicable -- not absent -- matching the non-search branch's own
 * `{"type": view.type, "view_id": view.id, "search_view_id": False}`
 * literal exactly. `canvases/search_lists_canvas.ts` is the first real
 * reader.
 */
export interface PreviewInfo {
    type: string;
    view_id: number | false;
    search_view_id: number | false;
    unavailable?: boolean;
}

/**
 * `editing_context()`'s whole return (`studio_view_editor.py:
 * editing_context`) -- everything the editor needs to open on a view.
 * `options`/`catalogue`/`groups`/`packages` are left `unknown`: nothing
 * converted so far reads them (they belong to components this migration
 * has not reached); narrow when a real reader appears, per this
 * migration's own rule against typing ahead of a consumer.
 */
/** One group a `groups=""` attribute can name
 * (`studio_view_editor.py:_selectable_groups`) -- only ones with an
 * external id, since the attribute takes xmlids and a group without one
 * cannot be referred to from an arch at all. */
export interface SelectableGroupEntry {
    id: number;
    xmlid: string;
    name: string;
}

export interface EditingContext {
    view: { id: number; name: string; type: string; model: string | false; mode: string };
    views: ViewOfEntry[];
    python_owned: boolean;
    python_owner_id: number | false;
    field_types: AvailableFieldTypeJSON[];
    draft_id: number | false;
    reload_mode: string | false;
    record_count: number;
    fields: EditingContextFieldEntry[];
    preview: PreviewInfo;
    /** `studio_view_editor.py:editing_context`'s own `"options":
     * view_options.groups_json(...)` -- the same shape `options.ts`'s own
     * `optionsFor` already takes for the canvas's `OptionsContext`. */
    options: OptionGroupJSON[];
    /** `editing_context`'s own `"catalogue": catalogue.catalogue_json(...)`. */
    catalogue: CatalogueJSON;
    groups: SelectableGroupEntry[];
    owned: boolean;
    packages: unknown;
    suggested_package_id: number | false;
}

/** The picker's tile for one field type, as `field_types_for` augments
 * `AvailableFieldTypeJSON` with two facts only the model decides
 * (`studio_view_new_field.py:field_types_for`). An older server's
 * fallback (`editing_context().field_types`, read when `field_types_for`
 * itself refuses) carries neither key, hence `loadFieldTypes`'s own
 * `!== undefined` check before trusting them -- so the *input* to that
 * check is `Partial`, and only the client-augmented `FieldTypeEntry`
 * (below) guarantees both. */
export type FieldTypeRawEntry = AvailableFieldTypeJSON & {
    live?: boolean;
    needs_dialog?: boolean;
};

/** `ConsoleModel.fieldTypes`'s own entries, every one carrying both flags
 * the picker needs (`console_model.ts:loadFieldTypes`). */
export type FieldTypeEntry = AvailableFieldTypeJSON & {
    live: boolean;
    needs_dialog: boolean;
};

/** Which of the two new-field answers applies to a view, and what to say
 * about it (`studio_view_new_field.py:new_field_plan`). */
export interface NewFieldPlan {
    can_create: boolean;
    reason?: string;
    handoff?: number;
    model?: string;
    prefix?: string;
}

/** One field `get_addable_fields` offers: not already in the arch, with
 * enough to show and place it (`studio_view_editor.py:get_addable_fields`). */
export interface AddableFieldEntry {
    name: string;
    string: string;
    type: string;
    required: boolean;
    readonly: boolean;
    manual: boolean;
}

/** A field the picker offers for a date or a group-by, when creating
 * another kind of view (`studio_view_editor.py:_placeable_fields`). */
export interface PlaceableFieldEntry {
    name: string;
    string: string;
}

/** One kind of view `addable_view_types` offers, and why not when it does
 * not (`studio_view_editor.py:addable_view_types`). */
export interface AddableViewTypeEntry {
    type: string;
    label: string;
    icon: string;
    enabled: boolean;
    reason: string;
    date_fields: PlaceableFieldEntry[];
    group_fields: PlaceableFieldEntry[];
}

/** One row of `search_elements()`'s `filters`/`group_bys`
 * (`studio_view_editor.py:search_elements`). */
export interface SearchFilterEntry {
    name: string;
    string: string;
    domain: string;
}

/** `search_elements()`'s whole return: what a search view offers, in the
 * three groups the sidebar shows (`studio_view_editor.py:search_elements`). */
export interface SearchElements {
    fields: { name: string; string: string }[];
    filters: SearchFilterEntry[];
    group_bys: SearchFilterEntry[];
    addable: AddableFieldEntry[];
}

/** What could link a comodel back to this one, for the relation picker
 * (`studio_model_draft.py:inverse_options`, and the live-model path
 * `console_model.ts:inverseOptions` builds the same shape for by hand). */
export interface InverseOptions {
    candidates: { name: string; string: string }[];
    can_create: boolean;
    suggested: string;
    reason: string;
}

/** What a related path points at, or why it does not lead anywhere
 * (`studio_model_draft.py:resolve_related`, and the live-model path
 * `console_model.ts:resolveRelated` builds the same shape for by hand). */
export type ResolveRelatedResult =
    | { ok: true; ttype: string; comodel: string; string: string; stored: boolean }
    | { ok: false; reason: string };

/**
 * What `apply_operation` answers -- every structural edit that is not a
 * drop (`apply_at`, `remove_at`, `show_label_at`, `add_container_at`,
 * `add_search_element`, `remove_search_element`, all of which funnel
 * through it). Never carries `canvas`, so `_mutate` always follows it
 * with a `refresh()` -- `created_name` is the one thing it can select
 * without one.
 */
export interface OperationResult {
    view_id: number;
    arch: string;
    combined_arch: string;
    arch_version: string;
    created_name?: string | null;
}

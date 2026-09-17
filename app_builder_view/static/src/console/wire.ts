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
    kinds: string[];
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

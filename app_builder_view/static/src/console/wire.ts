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

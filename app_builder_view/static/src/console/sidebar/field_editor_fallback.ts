/** @odoo-module **/
/**
 * The field editor the console falls back on, and how the console opens
 * whichever one it has.
 *
 * A field of a type that cannot be made from a label alone -- a relation
 * without a model, a selection without values, a related field without
 * its chain -- is asked for before anything is sent, so that Cancel is no
 * request at all. What asks is whatever is registered first in
 * `app_builder.field_editor`: `app_builder_model` registers its own
 * full popover there, and this module is the answer when nothing is --
 * the label, the type and the minimal parameters each type needs, and
 * not one row more. Both speak one contract, so the palette and the
 * properties open either the same way:
 *
 *   field          the staged definition to edit, or nothing for a new one
 *   initial        `{ttype, string}` a new field starts from -- the tile
 *   mode           `live` (an `ir.model.fields` row) or `staged` (a draft)
 *   fieldTypes     the picker's entries for the model
 *   existingNames  what the model already calls its fields
 *   modelName      the model the field belongs to
 *   inverseOptions `(comodel) => {candidates, can_create, suggested, reason}`
 *   resolveRelated `(path) => {ok, ttype, comodel, string, stored | reason}`
 *   onSave         `(values)` -- the draft's spec shape: `string`, `ttype`,
 *                  `comodel`, `inverse_name`, `selection`, `related`, ...
 *   onDelete       optional; offered for a staged field
 *   close          closes the popover
 *
 * `useFieldEditor` is the one way the console opens it: a popover beside
 * what was clicked, kept open through the model and field pickers the
 * editor itself opens, which are not its DOM children.
 *
 * `FieldEditorProps` (the shape this whole docstring above describes) is
 * declared in `types.ts`, not here -- it is the contract every registrant
 * of `app_builder.field_editor` shares (this file's own fallback, and
 * `app_builder_model/static/src/console_items.js`'s `ConsoleFieldEditor`,
 * an addon outside this tree that has not converted yet but depends on
 * the same shape), so it belongs where a shared contract lives, the same
 * reasoning `PaneRegistration`/`PaneContext` already follow there.
 */

import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { ModelSelector } from "@web/core/model_selector/model_selector";
import { usePopover } from "@web/core/popover/popover_hook";
import { registry } from "@web/core/registry";
import type { FieldEditorProps } from "../types";
import type { InverseOptions, ResolveRelatedResult } from "../wire";
import type { SelectionOption } from "../types";

// `registry.category()`'s own signature (`web/static/src/core/registry.js`)
// only accepts a name that is a known key of `GlobalRegistryCategories`
// (`registries.d.ts`) -- `app_builder.field_editor` is declared in
// `../odoo.ts` (Phase 2c's facade, "fenced in one place"; see this
// module's own `newSharedTypes` note), the same way `app_builder.panes` is
// for `shell/pane_registry.ts`. No import needed here to bring it into
// scope: a `declare module` augmentation merges into the whole program
// once any file in it is compiled, regardless of which file declares it.
const editorRegistry = registry.category("app_builder.field_editor");

/** The props every editor takes; a registered one may accept more. */
export const FIELD_EDITOR_PROPS = {
    field: { type: [Object, { value: null }], optional: true },
    initial: { type: Object, optional: true },
    mode: { type: String, optional: true },
    fieldTypes: Array,
    existingNames: Array,
    modelName: String,
    inverseOptions: Function,
    resolveRelated: Function,
    onSave: Function,
    onDelete: { type: [Function, { value: null }], optional: true },
    close: Function,
};

/** The editor to open: the first one registered, else the fallback. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function fieldEditorComponent(): typeof Component<any, any> {
    const entries = editorRegistry.getEntries();
    // `entries.length` being truthy does not, to `noUncheckedIndexedAccess`,
    // prove `entries[0]` exists -- asserted the same way this migration
    // already does for other length-guarded first/last-element reads
    // (`console_model.ts`'s `lastStep`).
    return entries.length ? entries[0]![1] : FieldEditorFallback;
}

/**
 * Overlays the editor opens that are not inside it: a click in one of
 * them is not a click away. The same list the field editor keeps.
 */
const KEEPS_OPEN = [
    ".o_datetime_picker",
    ".o_model_field_selector_popover",
    ".o-autocomplete--dropdown-menu",
    ".o_domain_selector_dialog",
    ".o_select_menu_menu",
    ".o_popover",
    ".modal",
    ".o_tag_popover",
];

/** `usePopover` on the registered editor, with the escape list. */
export function useFieldEditor() {
    return usePopover(fieldEditorComponent(), {
        popoverClass: "o_studio_field_editor_popover",
        position: "right",
        closeOnClickAway: (target: HTMLElement) =>
            !KEEPS_OPEN.some((selector) => target.closest && target.closest(selector)),
    });
}

/**
 * The editor's own local, mutable copy of the field being built or
 * edited -- initialized from `props.field` (a real `DraftFieldJSON`,
 * spread whole) or from `props.initial` for a brand new field, then
 * edited in place until `onSave` hands the result back. `comodel`/
 * `inverse_name`/`related`/`currency_field` carry `DraftFieldJSON`'s own
 * `T | null` (a real field, possibly empty) when spread from `props.field`,
 * but are also genuinely absent altogether on a brand new field and
 * deleted outright by `onTypeChange` when a chosen type no longer needs
 * one -- hence optional *and* nullable, rather than either alone.
 * `selection` is optional for the same reason `onSave` can `delete
 * values.selection` when nothing was entered. Every other `DraftFieldJSON`
 * field this component never reads (`help`, `domain`, `size`, ...) rides
 * along under the index signature, round-tripped back to the server on
 * save without this file ever needing to name it.
 */
interface FieldEditorState {
    ttype: string;
    string: string | null;
    selection?: SelectionOption[];
    error: string;
    inverse: InverseOptions | null;
    relatedInfo: ResolveRelatedResult | null;
    /** `| undefined`, not just optional: `onSave`'s own `values.comodel =
     * relatedInfo.comodel || undefined` writes a literal `undefined` when
     * a resolved related path leads to a non-relational field, which
     * `exactOptionalPropertyTypes` treats differently from the key being
     * merely absent -- the same distinction `types.ts`'s own
     * `DragPayload.component` already documents. */
    comodel?: string | null | undefined;
    inverse_name?: string | null;
    related?: string | null;
    create_inverse?: boolean;
    currency_field?: string | null;
    [key: string]: unknown;
}

/** The values a new field starts from, as the editor's state. */
function initialState(props: FieldEditorProps) {
    if (props.field) {
        return { ...props.field };
    }
    const initial = props.initial || {};
    const entry = props.fieldTypes.find((t) => t.value === initial.ttype);
    return {
        ttype: initial.ttype || "char",
        string: initial.string || String(entry ? _t("New %s", entry.label) : _t("New field")),
        selection: [],
    };
}

export class FieldEditorFallback extends Component<FieldEditorProps> {
    static override template = "app_builder_view.FieldEditorFallback";
    static components = { ModelSelector, ModelFieldSelector };
    static override props = FIELD_EDITOR_PROPS;

    isNew!: boolean;
    labelRef!: { el: HTMLInputElement | null };
    state!: FieldEditorState;

    override setup(): void {
        this.isNew = !this.props.field;
        this.labelRef = useRef<HTMLInputElement>("label");
        this.state = useState<FieldEditorState>({
            ...initialState(this.props),
            error: "",
            inverse: null,
            relatedInfo: null,
        });
        onMounted(() => {
            if (this.state.ttype === "one2many" && this.state.comodel) {
                void this.loadInverseOptions(this.state.comodel);
            }
            const input = this.labelRef.el;
            if (input) {
                input.focus();
                if (this.isNew) {
                    // Selected, not just focused: the placeholder label is
                    // a starting point, and typing replaces it outright.
                    input.select();
                }
            }
        });
    }

    // -- what the type needs ------------------------------------------------

    get currentType(): Partial<FieldEditorProps["fieldTypes"][number]> {
        return this.props.fieldTypes.find((t) => t.value === this.state.ttype) || {};
    }

    /** The picker entries that can be chosen here. */
    get typeChoices() {
        return this.props.fieldTypes.filter(
            (entry) => entry.enabled && (this.props.mode !== "live" || entry.live !== false),
        );
    }

    shows(param: string): boolean {
        return (this.currentType.params || []).includes(param);
    }

    onTypeChange(value: string): void {
        const entry = this.props.fieldTypes.find((t) => t.value === value);
        if (!entry || !entry.enabled) {
            return;
        }
        this.state.ttype = value;
        for (const param of ["comodel", "inverse_name", "related", "currency_field"] as const) {
            if (!entry.params.includes(param)) {
                delete this.state[param];
            }
        }
        if (!entry.params.includes("selection")) {
            this.state.selection = [];
        }
    }

    // -- relations ----------------------------------------------------------

    async onComodelSelected(model: { technical: string }): Promise<void> {
        this.state.comodel = model.technical;
        if (this.state.ttype === "one2many" || this.state.ttype === "lines") {
            await this.loadInverseOptions(model.technical);
        }
    }

    async loadInverseOptions(comodel: string): Promise<void> {
        this.state.inverse = await this.props.inverseOptions(comodel);
        const { candidates, can_create: canCreate, suggested } = this.state.inverse;
        if (candidates.length) {
            this.state.create_inverse = false;
            // `candidates.length` just confirmed index 0 exists;
            // `noUncheckedIndexedAccess` cannot see that from the length
            // check alone.
            this.state.inverse_name = candidates[0]!.name;
        } else if (canCreate) {
            this.state.create_inverse = true;
            this.state.inverse_name = suggested;
        }
    }

    get inverse(): InverseOptions {
        return (
            this.state.inverse || { candidates: [], can_create: false, suggested: "", reason: "" }
        );
    }

    get needsInverse(): boolean {
        return ["one2many", "lines"].includes(this.state.ttype) && Boolean(this.state.comodel);
    }

    onInverseChange(value: string): void {
        if (value === "__new__") {
            this.state.create_inverse = true;
            this.state.inverse_name = this.inverse.suggested;
        } else {
            this.state.create_inverse = false;
            this.state.inverse_name = value;
        }
    }

    // -- related ------------------------------------------------------------

    async onRelatedChange(path: string): Promise<void> {
        this.state.related = path;
        this.state.relatedInfo = await this.props.resolveRelated(path);
        if (this.state.relatedInfo.ok && this.isNew) {
            this.state.string = this.state.relatedInfo.string;
        }
    }

    // -- selection values ---------------------------------------------------

    get selectionRows(): SelectionOption[] {
        return this.state.selection || [];
    }

    addSelectionRow(): void {
        this.state.selection = [
            ...this.selectionRows,
            { value: "", label: "", sequence: (this.selectionRows.length + 1) * 10 },
        ];
    }

    updateSelectionRow(index: number, key: string, value: string): void {
        const rows = [...this.selectionRows];
        // `index` always names a row the template itself just rendered
        // from `rows`, an invariant `noUncheckedIndexedAccess` cannot see
        // from the signature alone -- asserted the same way
        // `loadInverseOptions`'s `candidates[0]` is, just below.
        rows[index] = { ...rows[index]!, [key]: value };
        const updatedRow = rows[index];
        if (key === "label" && !updatedRow.value) {
            updatedRow.value = (value || "")
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "_")
                .replace(/^_+|_+$/g, "");
        }
        this.state.selection = rows;
    }

    removeSelectionRow(index: number): void {
        this.state.selection = this.selectionRows.filter((_row, i) => i !== index);
    }

    // -- commit -------------------------------------------------------------

    validate(): string {
        if (!(this.state.string || "").trim()) {
            return String(_t("Give the field a label."));
        }
        if (this.shows("comodel") && !this.state.comodel) {
            return String(_t("Choose the model this points at."));
        }
        if (this.needsInverse && !this.state.inverse_name) {
            return String(_t("Choose how %s links back to this model.", this.state.comodel));
        }
        if (this.shows("selection") && !this.selectionRows.some((row) => row.value)) {
            return String(_t("A selection needs at least one value."));
        }
        if (this.shows("related")) {
            if (!this.state.related) {
                return String(_t("Choose the field this one follows."));
            }
            if (this.state.relatedInfo && !this.state.relatedInfo.ok) {
                return this.state.relatedInfo.reason;
            }
        }
        return "";
    }

    onSave(): void {
        const problem = this.validate();
        if (problem) {
            this.state.error = problem;
            return;
        }
        const { error, inverse, relatedInfo, ...values } = this.state;
        if (relatedInfo && relatedInfo.ok) {
            // The resolved chain, not the picker's placeholder: a related
            // field is whatever the chain ends at.
            values.ttype = relatedInfo.ttype;
            values.comodel = relatedInfo.comodel || undefined;
        }
        values.selection = this.selectionRows.filter((row) => row.value);
        if (!values.selection.length) {
            delete values.selection;
        }
        this.props.onSave(values);
    }

    onKeydown(ev: KeyboardEvent): void {
        if (
            ev.key === "Enter" &&
            !ev.shiftKey &&
            (ev.target as HTMLElement).tagName !== "TEXTAREA"
        ) {
            ev.preventDefault();
            this.onSave();
        }
        if (ev.key === "Escape") {
            ev.preventDefault();
            this.props.close();
        }
    }
}

/** @odoo-module **/
/**
 * The field editor, modelled on core's `properties` field popover.
 *
 * Two behaviours are lifted deliberately, because they are what make that
 * editor feel finished:
 *
 *  - **Never a blank required-field wall.** A new field arrives already named
 *    and typed, and the label is focused *and selected*, so typing replaces it.
 *  - **Type-conditional rows.** The server's field-type catalogue names the
 *    parameters each type actually needs, so the form shows exactly those and
 *    nothing else. Unusable types are listed disabled with the reason rather
 *    than hidden -- somebody who cannot find "Amount" learns nothing, whereas
 *    "needs a Currency field on this model" tells them what to do next.
 *
 * `FieldPopoverProps` is `FieldEditorProps` (`@app_builder_view/console/
 * types` -- the whole-tree contract every registrant of
 * `app_builder.field_editor` shares, `field_editor_fallback.ts`'s own
 * module docstring names it in full) minus the two keys only the console's
 * own subclass adds (`initial`, `mode`; `app_builder_model/static/src/
 * console_items.js`'s `ConsoleFieldEditor`, still `.js`, not converted by
 * this file). This popover also has an older, plainer life of its own --
 * `field: { type: [Object, { value: null }], optional: true }` plus
 * `fieldTypes`/`existingNames`/`modelName`/`onSave`/`onDelete`/
 * `inverseOptions`/`resolveRelated`/`close` is the whole of its own
 * original contract, which is exactly that subset.
 */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { ModelSelector } from "@web/core/model_selector/model_selector";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import type {
    DraftFieldJSON,
    FieldTypeEntry,
    InverseOptions,
    PlacementJSON,
    ResolveRelatedResult,
} from "@app_builder_view/console/wire";
import type { FieldEditorProps, SelectionOption } from "@app_builder_view/console/types";

export type FieldPopoverProps = Omit<FieldEditorProps, "initial" | "mode">;

const ONDELETE_CHOICES: { value: string; label: ReturnType<typeof _t> }[] = [
    { value: "set null", label: _t("Leave empty") },
    { value: "restrict", label: _t("Prevent deletion") },
    { value: "cascade", label: _t("Delete this record too") },
];

/**
 * The popover's own local, mutable copy of the field being built or
 * edited -- initialized either from `props.field` (a real `DraftFieldJSON`,
 * spread whole: every key present, `null` rather than absent per that
 * type's own docstring) or from the three keys a brand new field starts
 * with (`name`, `ttype`, `string`), then edited in place until `onSave`
 * hands the result back. Built from `DraftFieldJSON` itself via
 * `Partial`/`Omit` rather than hand-listed field by field -- this
 * component reads or writes nearly every key that type has -- with three
 * fields corrected against what the code actually reads or writes:
 *
 *  - `comodel` is `| undefined`, not just optional: `onSave`'s own
 *    `values.comodel = relatedInfo.comodel || undefined` writes a literal
 *    `undefined` when a resolved related path leads to a non-relational
 *    field, which `exactOptionalPropertyTypes` treats differently from the
 *    key being merely absent -- the same distinction
 *    `field_editor_fallback.ts`'s own `FieldEditorState` already documents
 *    for the identical assignment.
 *  - `depends` is genuinely `string | string[]` at runtime, not just the
 *    `string[]` `DraftFieldJSON` declares: it arrives as a `string[]` when
 *    spread from an existing field, but the compute panel's plain
 *    `<input>` (`onKeydown`'s sibling, the `t-on-input` in the template)
 *    and `toggleCompute`'s own clear both write a comma-separated *string*
 *    instead -- which is what `studio_model_draft.py:addNewField` actually
 *    expects back (`isinstance(depends, str)` there splits it apart
 *    again). Typed to what it actually is on both sides of that round
 *    trip, not narrowed to only the read shape.
 *  - every other `DraftFieldJSON` field this component never reads
 *    (`relation_table`, `column1`, `column2`, `domain`, `size`, `digits`,
 *    `copy`, `tracking`, `group_expand`, `compute`, `extra`) rides along
 *    under the index signature below, the same as
 *    `field_editor_fallback.ts`'s own state does for its own unread
 *    remainder -- also what lets `onSave` hand `values` straight to
 *    `props.onSave`'s `Record<string, unknown>`.
 *
 * `inverse`/`relatedInfo`/`showCompute` are genuinely absent (not `null`)
 * until `loadInverseOptions`/`onRelatedChange`/`toggleCompute` first set
 * them -- this popover's own `setup()`, unlike `field_editor_fallback.ts`'s,
 * never pre-seeds them. `create_inverse` is UI-only, not part of
 * `DraftFieldJSON` at all, but is deliberately *not* deleted in `onSave`:
 * the server reads it directly when deciding whether to create the
 * inverse link in the same step.
 */
interface FieldPopoverState extends Partial<
    Omit<DraftFieldJSON, "name" | "ttype" | "string" | "comodel" | "depends">
> {
    name: string;
    ttype: string;
    string: string | null;
    comodel?: string | null | undefined;
    depends?: string | string[];
    error?: string;
    inverse?: InverseOptions | null;
    relatedInfo?: ResolveRelatedResult | null;
    showCompute?: boolean;
    create_inverse?: boolean;
    [key: string]: unknown;
}

// Generic over its own Props, not fixed to `FieldPopoverProps`: this
// addon's own `console_items.ts` subclasses `FieldPopover` as
// `ConsoleFieldEditor`, adding back the two props (`initial`, `mode`)
// this file's own module docstring says the console's contract needs
// and this popover's "older, plainer life of its own" does not --
// `FieldEditorProps` (`@app_builder_view/console/types`) is exactly
// `FieldPopoverProps` plus those two, both optional, so it structurally
// satisfies `P extends FieldPopoverProps` and the subclass's own
// `this.props` is correctly widened with no cast needed anywhere in
// either file. The first real instance in this migration of one
// converted component subclassing another (`ConsoleFieldEditor extends
// FieldPopover`), not `Component` directly.
export class FieldPopover<P extends FieldPopoverProps = FieldPopoverProps> extends Component<P> {
    static override template = "app_builder_model.FieldPopover";
    static components = { CheckBox, ModelSelector, ModelFieldSelector, SelectMenu };
    static override props = {
        field: { type: [Object, { value: null }], optional: true },
        fieldTypes: Array,
        existingNames: Array,
        modelName: String,
        onSave: Function,
        onDelete: { type: [Function, { value: null }], optional: true },
        inverseOptions: Function,
        resolveRelated: Function,
        close: Function,
    };

    isNew!: boolean;
    labelRef!: { el: HTMLInputElement | null };
    state!: FieldPopoverState;

    override setup(): void {
        const field = this.props.field;
        this.isNew = !field;
        this.labelRef = useRef<HTMLInputElement>("label");

        this.state = useState<FieldPopoverState>(
            field
                ? { ...field }
                : {
                      // Created already valid, so the popover opens on something
                      // editable rather than on a wall of required inputs.
                      name: this.suggestName(String(_t("New field"))),
                      ttype: "char",
                      string: String(_t("New field")),
                  },
        );
        this.state.error = "";

        onMounted(() => {
            if (this.state.ttype === "one2many" && this.state.comodel) {
                void this.loadInverseOptions(this.state.comodel);
            }
            const input = this.labelRef.el;
            if (input) {
                input.focus();
                if (this.isNew) {
                    // Selected, not just focused: the placeholder name is a
                    // starting point, and typing should replace it outright.
                    input.select();
                }
            }
        });
    }

    // -- naming -----------------------------------------------------------

    /**
     * The technical name is derived once, from the first label, and then left
     * alone. Renaming a column is a migration, not a typing gesture.
     */
    suggestName(label: string | null): string {
        const slug = (label || "")
            .toLowerCase()
            .normalize("NFKD")
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_+|_+$/g, "");
        let candidate = slug || "field";
        if (/^[0-9]/.test(candidate)) {
            candidate = `f_${candidate}`;
        }
        let unique = candidate;
        let counter = 2;
        while (this.props.existingNames.includes(unique)) {
            unique = `${candidate}_${counter++}`;
        }
        return unique;
    }

    onLabelInput(ev: Event): void {
        this.state.string = (ev.target as HTMLInputElement).value;
        if (this.isNew) {
            this.state.name = this.suggestName(this.state.string);
        }
    }

    // -- types ------------------------------------------------------------

    get typeGroups(): { name: string; choices: FieldTypeEntry[] }[] {
        const groups: Record<string, FieldTypeEntry[]> = {};
        for (const entry of this.props.fieldTypes) {
            (groups[entry.group] ||= []).push(entry);
        }
        return Object.entries(groups).map(([name, choices]) => ({ name, choices }));
    }

    get currentType(): Partial<FieldTypeEntry> {
        return this.props.fieldTypes.find((t) => t.value === this.state.ttype) || {};
    }

    get params(): string[] {
        return this.currentType.params || [];
    }

    shows(param: string): boolean {
        return this.params.includes(param);
    }

    get ondeleteChoices(): { value: string; label: ReturnType<typeof _t> }[] {
        return ONDELETE_CHOICES;
    }

    // -- relationships ----------------------------------------------------

    /**
     * Odoo needs a many2one on the other side before a related list can exist.
     * Making the user go and build it there first is the gesture every studio
     * gets wrong, so the choice is offered inline: reuse a link that already
     * points back, or have one made in the same Apply.
     */
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
            this.state.inverse ||
                // The fallback was missing `suggested` (`InverseOptions`,
                // `wire.ts`, requires all four fields) -- the identical gap
                // `field_editor_fallback.ts`'s own `get inverse()` had and
                // fixed the same way (cluster 4 wave 1), unreachable today
                // since the branch that reads `suggested` is gated behind
                // `can_create`, which this same fallback also sets `false`.
                { candidates: [], can_create: false, suggested: "", reason: "" }
        );
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

    async onComodelSelected(model: { technical: string }): Promise<void> {
        this.state.comodel = model.technical;
        if (this.state.ttype === "one2many") {
            await this.loadInverseOptions(model.technical);
        }
    }

    // -- related ------------------------------------------------------------

    /**
     * A related field has no type of its own: `partner_id.email` is a char
     * because `email` is. So the chain is what the user picks, and the type
     * comes back from the server -- asking them to state it as well would be
     * asking them to be right about something the model already knows, where
     * being wrong is a registry error at load time rather than a message.
     */
    async onRelatedChange(path: string): Promise<void> {
        this.state.related = path;
        this.state.relatedInfo = await this.props.resolveRelated(path);
        // Captured once: a getter/property re-read does not carry the
        // narrowing on `.ok` from one access to the next the way a local
        // `const` does.
        const relatedInfo = this.state.relatedInfo;
        if (relatedInfo.ok) {
            this.state.error = "";
            if (!this.state.string || this.state.string === String(_t("New field"))) {
                this.state.string = relatedInfo.string;
                this.state.name = this.suggestName(this.state.string);
            }
        }
    }

    get relatedInfo(): ResolveRelatedResult | null {
        return this.state.relatedInfo || null;
    }

    // -- computed ---------------------------------------------------------

    get computeOpen(): boolean {
        return Boolean(this.state.showCompute || this.state.compute_body);
    }

    toggleCompute(): void {
        this.state.showCompute = !this.computeOpen;
        if (!this.state.showCompute) {
            // Clearing the body is what clears the compute: a spec that keeps
            // the method name would declare one the generator has nothing to
            // write.
            this.state.compute_body = "";
            this.state.depends = "";
        }
    }

    // -- placement --------------------------------------------------------

    /**
     * Placement is view intent, not part of the field definition, so it lives
     * beside the spec rather than in it. It is edited here anyway because
     * "where does this show up" is the question people ask *while* adding a
     * field, not on a separate screen afterwards.
     */
    get placement(): Partial<PlacementJSON> {
        return this.state.placement || this.currentType.placement || {};
    }

    /**
     * Only ever called with one of the four boolean slots the template's
     * checkboxes cover (`form`/`list`/`search`/`group_by`) -- `widget` is
     * never set through here, only ever copied whole from a field type's
     * own placement (`onTypeChange`). The cast reflects that every real
     * `this.placement` is a full `PlacementJSON` (either a prior full
     * assignment, or a real field type's own catalogue entry) except the
     * defensive `{}` fallback the getter above falls back to when
     * `state.ttype` genuinely names no known type -- a case this method,
     * like that getter, does not newly invent a `widget` for.
     */
    setPlacement(slot: "form" | "list" | "search" | "group_by", value: boolean): void {
        this.state.placement = { ...this.placement, [slot]: value } as PlacementJSON;
    }

    get canGroupBy(): boolean {
        return ["many2one", "selection", "date", "datetime", "boolean"].includes(this.state.ttype);
    }

    get wantsPage(): boolean {
        return ["one2many", "many2many", "html", "text"].includes(this.state.ttype);
    }

    onTypeChange(value: string): void {
        const entry = this.props.fieldTypes.find((t) => t.value === value);
        if (!entry || !entry.enabled) {
            return;
        }
        this.state.ttype = value;
        // Placement follows the type: a long note does not belong in a list
        // column just because the char field it started as did.
        this.state.placement = { ...entry.placement };
        // Parameters that no longer apply would otherwise be written out on a
        // field whose type cannot carry them.
        for (const param of ["comodel", "inverse_name", "selection", "currency_field"] as const) {
            if (!entry.params.includes(param)) {
                delete this.state[param];
            }
        }
    }

    // -- selection values -------------------------------------------------

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
        // `index` always names a row the template itself just rendered from
        // `rows`, an invariant `noUncheckedIndexedAccess` cannot see from
        // the signature alone -- asserted the same way `loadInverseOptions`'s
        // `candidates[0]` is, above.
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

    // -- commit -----------------------------------------------------------

    validate(): string {
        if (!this.state.string?.trim()) {
            return String(_t("Give the field a label."));
        }
        if (this.shows("comodel") && !this.state.comodel) {
            return String(_t("Choose the model this points at."));
        }
        if (this.state.ttype === "one2many" && !this.state.inverse_name) {
            return String(
                _t(
                    "Choose how %s links back to this model.",
                    this.state.comodel || String(_t("the other model")),
                ),
            );
        }
        if (
            ["selection", "reference"].includes(this.state.ttype) &&
            !this.selectionRows.filter((r) => r.value).length
        ) {
            return String(_t("A selection needs at least one value."));
        }
        if (this.shows("related")) {
            if (!this.state.related) {
                return String(_t("Choose the field this one follows."));
            }
            const relatedInfo = this.relatedInfo;
            if (relatedInfo && !relatedInfo.ok) {
                return relatedInfo.reason;
            }
        }
        if (this.state.compute_body && !this.state.depends) {
            // Odoo will not recompute without it, and a stored computed field
            // that never recomputes is the worst thing this can produce:
            // correct on creation and quietly wrong from then on.
            return String(
                _t("A computed field needs the fields it reads, so Odoo knows when to recompute."),
            );
        }
        return "";
    }

    onSave(): void {
        const problem = this.validate();
        if (problem) {
            this.state.error = problem;
            return;
        }
        const values = { ...this.state };
        delete values.error;
        delete values.type_label;
        // Picker state, not field definition: the server re-derives what it
        // needs from create_inverse and would reject the rest.
        delete values.inverse;
        delete values.showCompute;
        // Captured once, rather than read twice off the getter below (a
        // getter re-invocation does not carry narrowing from one call to
        // the next the way a local `const` does).
        const relatedInfo = this.relatedInfo;
        // The resolved chain, not the panel's copy of it: `ttype` is whatever
        // the related field turned out to be.
        if (relatedInfo && relatedInfo.ok) {
            values.ttype = relatedInfo.ttype;
            values.comodel = relatedInfo.comodel || undefined;
        }
        delete values.relatedInfo;
        values.placement = { ...this.placement } as PlacementJSON;
        if (values.selection) {
            values.selection = this.selectionRows.filter((r) => r.value);
        }
        this.props.onSave(values);
    }

    onDelete(): void {
        this.props.onDelete?.();
    }

    onKeydown(ev: KeyboardEvent): void {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSave();
        }
    }
}

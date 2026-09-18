/** @odoo-module **/
/**
 * A record pane: the model's records of one kind, as cards, with what
 * each does in a sentence; a properties sidebar for the one selected.
 *
 * The content slot lists the rows a server surface hands back (see
 * `record_pane_model.ts`), owned by this package first, dimmed when
 * archived, badged when another module owns them or nothing does. New
 * is inline: the two or three questions a record cannot exist without,
 * from a template's `needs`, then the sidebar carries on. Odoo's own
 * form is one button in the sidebar, `Advanced…`, and never the first
 * thing on screen.
 *
 * A data-only registration (`{surface, surfaceArgs, rowActions}`) from
 * another addon resolves to these components, so a pane costs its owner
 * a few lines and no import.
 */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { FormViewDialog as FormViewDialogImpl } from "@web/views/view_dialogs/form_view_dialog";
import * as compat from "../compat";
import { ConfirmationDialog, useService } from "../odoo";
import type { DialogService } from "../odoo";
import { setPaneResolver } from "../shell/pane_registry";
import type { StudioShell } from "../shell/shell_model";
import type {
    RecordActionJSON,
    RecordChildrenJSON,
    RecordDescription,
    RecordRowJSON,
    RecordTemplateJSON,
    RowJSON,
    SectionJSON,
} from "../wire";
import { RecordPaneModel } from "./record_pane_model";
import type { CreatingState, RecordPaneEntry } from "./record_pane_model";
import { RowEditor } from "./row_editor";

// -- `FormViewDialog`, typed the same way `odoo.ts` already re-exports
// `ConfirmationDialog` -------------------------------------------------
//
// `@web/views/view_dialogs/form_view_dialog.js`'s `FormViewDialog`,
// rendered via `DialogService.add` by `onAdvanced` below. Not imported
// straight from the vendor module, for the identical reason `odoo.ts`
// already re-exports `ConfirmationDialog` rather than doing that (see that
// file's own long comment on `ConfirmationDialog`, reproduced in short
// here): the vendor class carries no `@extends {Component<Props>}` JSDoc,
// so under this project's `checkJs: false` setting its own inferred type
// does not carry `Component`'s instance members (`props`, `env`, `render`,
// `__owl__`) at all -- confirmed the same way `odoo.ts`'s own comment was,
// by the same class of failure: `DialogService.add`'s generic constructor
// check rejects the vendor class against *any* `Component<P>`
// instantiation. `record_pane.ts` is the first file in this migration to
// render `FormViewDialog`; this cast should move to `odoo.ts` alongside
// `ConfirmationDialog` the day a second file needs it too -- carried here
// locally until then, the same "carry it in the one file that needs it"
// precedent `pane_registry.ts`'s registry categories set in cluster 3.

/** What `onAdvanced` below actually supplies -- narrower than the vendor's
 * own much larger `static props` schema (`resModel`, `context`, `mode`,
 * `nextRecordsContext`, `onRecordDiscarded`, `removeRecord`, `viewId`,
 * `preventCreate`, `preventEdit`, `isToMany`, `size`, all left out since
 * nothing here passes them). `onRecordSaved` is genuinely awaited by the
 * vendor component itself (`await this.props.onRecordSaved(record)`,
 * `form_view_dialog.js`), so the async callback below fits it directly. */
interface FormViewDialogProps {
    resModel: string;
    resId?: number | false;
    context?: Record<string, unknown>;
    title?: string;
    onRecordSaved?: () => void | Promise<void>;
}

const FormViewDialog = FormViewDialogImpl as unknown as new (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ...args: any[]
) => Component<FormViewDialogProps>;

// -- the gate: what `extra.gate` carries (`app_builder_approval`'s own
// surface) --------------------------------------------------------------
//
// Traced to the real Python construction rather than guessed
// (`app_builder_approval/models/studio_approval_surface.py:catalogue`,
// `.../studio_approval.py:candidate_state_fields`) -- only the approvals
// surface (`studio.approval`) ever sets `extra.gate`; grepping every
// `catalogue()` implementation in the tree (`studio_record_surface.py`'s
// base and this one gate override -- nothing else defines the method)
// confirms it is the only source. Local to this file rather than promoted
// to `wire.ts`: `extra` is this addon's own per-surface grab-bag
// (`RecordPaneEntry`/`RecordPaneModel.extra`, `record_pane_model.ts`'s own
// choice to leave it a `Record<string, unknown>`), not part of the
// `catalogue()`/`describe()` wire contract every surface shares.

interface GateStateFieldValue {
    value: string;
    label: string;
}

interface GateStateField {
    name: string;
    string: string;
    values: GateStateFieldValue[];
}

/** `{on, title, help, consequence, state_fields, call}`, as
 * `studio_approval_surface.py:catalogue` always sends it when the surface
 * is `studio.approval` -- every other surface's `extra` simply has no
 * `"gate"` key, which `get gate()` below already reads as "no gate". */
interface GateInfo {
    on: boolean;
    title: string;
    help: string;
    consequence: string;
    state_fields: GateStateField[];
    call: string;
}

// -- `entry`'s own vocabulary, the rest of "a record pane" -----------------
//
// `RecordPaneEntry` (`record_pane_model.ts`) now names `label`/`empty`/
// `rowActions` directly (widened once this file -- the real first reader
// of any of the three -- needed them; `types.ts`'s own `PaneRegistration`
// comment said they would stay unmodeled "until one of those is
// converted", which this file now is), so no local shape or bracket-access
// cast is needed here any more.

/** What `actionsFor` returns: a contributed action with its `run` rebound
 * to close over `shell`/`row`/`model`, or one of the two built-in ones
 * (`key: "remove"`/`"duplicate"`) -- the template's own reads
 * (`record_pane.xml`: `action.key`, `.label`, `.icon`, `.danger`,
 * `.run()`). `when?` is carried over too (never read again once
 * `actionsFor` has already used it to decide whether to push the action at
 * all), so a contributed action's `{...action, run: ...}` spread -- kept
 * exactly as the original JS built it, not reconstructed field by field --
 * has nothing left over this type does not already name. */
interface RowAction {
    key: string;
    label: unknown;
    icon: string;
    danger?: boolean;
    when?: (row: RecordRowJSON) => boolean;
    run: () => void;
}

/** One selectable group offered to a `"groups"`-typed row's editor
 * (`row_editor.ts`'s own, unexported `RowEditorGroup` -- duplicated here
 * rather than imported, since that file's own comment says this getter is
 * the one that builds it and neither interface is exported). */
interface RowContextGroup {
    id: number;
    name: string;
}

/** `RowEditor`'s own `context` prop -- the subject model, and the groups
 * on offer. */
interface RowContext {
    resModel: string;
    groups: RowContextGroup[];
}

/** What `describe()` sends back under a key no `RecordDescription` field
 * names (`studio_record_surface.py:_check_domain`, the real source behind
 * every surface's own `"matches": self._check_domain(...)`) -- read
 * through `RecordDescription`'s own index signature, so the two real
 * shapes it returns are named exactly rather than widened to `unknown`. */
type RecordMatches =
    { valid: true; count: number; total?: number } | { valid: false; reason: string };

/** `{shell, model}`, as `static props` below validates it -- `model` is
 * marked `optional: true` there only for Owl's own runtime schema
 * looseness (the same shape every real registration under
 * `app_builder.panes` actually supplies); every real caller in this tree
 * passes both, the same way `flows/flow.ts`'s own `Props` already treats
 * its identical `{shell, model}` schema as non-optional here. */
interface Props {
    shell: StudioShell;
    model: RecordPaneModel;
}

interface GateState {
    field: string;
    from: string[];
    to: string[];
    cancel: string;
}

interface RecordPaneState {
    gate: GateState;
}

export class RecordPane extends Component<Props> {
    static override template = "app_builder_view.RecordPane";
    static components = { RowEditor };
    static override props = { shell: Object, model: { type: Object, optional: true } };

    // Assigned in `setup()`, which Owl calls synchronously right after
    // construction and before the first render -- always set by the time
    // any getter or template read runs (TYPING.md's own "Known traps").
    shell!: StudioShell;
    model!: RecordPaneModel;
    dialog!: DialogService;
    state!: RecordPaneState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        // The gate form, when the surface reports one (approvals): which
        // state field, from which states, into which, and the cancel one.
        // `useState`'s own generic is given explicitly (as `apply_dialog.ts`'s
        // own `ApplyDialogState` already does): inferred from the literal
        // alone, `from: []`/`to: []` would type as `never[]`, not `string[]`.
        this.state = useState<RecordPaneState>({
            gate: { field: "", from: [], to: [], cancel: "" },
        });
    }

    get label(): unknown {
        return this.model.entry.label || _t("Records");
    }

    get modelLabel(): string {
        return this.shell.modelLabel || this.shell.modelName;
    }

    get rows(): RecordRowJSON[] {
        return this.model.visibleRows;
    }

    get empty(): boolean {
        return !this.model.loading && !this.model.rows.length;
    }

    get templates(): RecordTemplateJSON[] {
        return this.model.templates;
    }

    get canCreate(): boolean {
        const scoped = this.model.entry.scope === "package" || Boolean(this.shell.modelName);
        return this.shell.packageWritable && scoped && !this.gateClosed;
    }

    // -- the gate: a surface whose records need the model prepared first -----------

    /** `{on, title, help, consequence, state_fields, call}` or null. */
    get gate(): GateInfo | null {
        return (this.model.extra["gate"] as GateInfo | undefined) || null;
    }

    get gateClosed(): boolean {
        return Boolean(this.gate && !this.gate.on);
    }

    get gateField(): GateStateField | null {
        const gate = this.gate;
        if (!gate) {
            return null;
        }
        const fields = gate.state_fields || [];
        return fields.find((f) => f.name === this.state.gate.field) || fields[0] || null;
    }

    /** The values the chosen state field has, for the from/to pickers. */
    get gateValues(): GateStateFieldValue[] {
        const field = this.gateField;
        return field ? field.values : [];
    }

    onGateField(ev: Event): void {
        const target = ev.target as HTMLSelectElement;
        this.state.gate.field = target.value;
        this.state.gate.from = [];
        this.state.gate.to = [];
        this.state.gate.cancel = "";
    }

    onGateStates(key: "from" | "to", ev: Event): void {
        const target = ev.target as HTMLSelectElement;
        this.state.gate[key] = [...target.selectedOptions].map((o) => o.value);
    }

    /** What the gate will say, before it is written. */
    get gateSentence(): ReturnType<typeof _t> {
        const field = this.gateField;
        const { from, to } = this.state.gate;
        if (!field || !to.length) {
            return _t("Say which state needs approving into.");
        }
        const label = (value: string): string => {
            const found = field.values.find((v) => v.value === value);
            return found ? found.label : value;
        };
        return _t(
            "Approval is asked for when %s goes from %s to %s.",
            field.string,
            from.length ? from.map(label).join(", ") : _t("any state"),
            to.map(label).join(", "),
        );
    }

    get gateReady(): boolean {
        return Boolean(this.gateField && this.state.gate.to.length && this.shell.packageWritable);
    }

    async onEnableGate(): Promise<void> {
        const gate = this.gate;
        const field = this.gateField;
        if (!gate || !field || !this.gateReady) {
            return;
        }
        const { from, to, cancel } = this.state.gate;
        const result = await this.model.call(gate.call, [
            this.shell.packageId,
            this.shell.modelName,
            field.name,
            from.length ? from : false,
            to,
            cancel || false,
        ]);
        if (result !== undefined) {
            // The model's class changed under the web client: its views
            // carry buttons now.
            compat.clearViewCaches(this.env);
            this.shell.refreshChanges();
        }
    }

    /** The empty state's words: the pane's own, else the plain ones. */
    get emptyState(): { title: unknown; help: unknown } {
        const empty = this.model.entry.empty || {};
        return {
            title: empty.title || _t("%s of %s", this.label, this.modelLabel),
            help: empty.help || _t("Nothing here yet."),
        };
    }

    /** Indentation for a row that came back with a depth (a tree). `depth`
     * is set only by the menu surface's own `rows()` override
     * (`app_builder_ui/models/studio_menu_surface.py`'s own `row["depth"] =
     * depth`) -- optional on `RecordRowJSON` since no other surface sends
     * it, but this generic component is the one real reader that needs it
     * regardless of which surface is in play. */
    rowStyle(row: RecordRowJSON): string {
        const depth = row.depth;
        return depth ? `padding-left: ${8 + depth * 18}px` : "";
    }

    /** What a card offers on hover: the pane's own actions, then the surface's. */
    actionsFor(row: RecordRowJSON): RowAction[] {
        const actions: RowAction[] = [];
        const rowActions = this.model.entry.rowActions || [];
        for (const action of rowActions) {
            if (!action.when || action.when(row)) {
                actions.push({ ...action, run: () => action.run(this.shell, row, this.model) });
            }
        }
        if (row.editable) {
            actions.push({
                key: "remove",
                label: _t("Remove"),
                icon: "fa fa-trash-o",
                danger: true,
                run: () => this.onRemove(row),
            });
        } else if (row.in_source && this.shell.packageWritable) {
            actions.push({
                key: "duplicate",
                label: _t("Duplicate into %s", this.shell.package ? this.shell.package.name : ""),
                icon: "fa fa-clone",
                run: () => {
                    void this.model.duplicate(row.id);
                },
            });
        }
        return actions;
    }

    onSelect(row: RecordRowJSON): void {
        if (this.model.selectedId !== row.id) {
            void this.model.select(row.id);
        }
    }

    onRemove(row: RecordRowJSON): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove"),
            body: _t("Remove %s? It is taken out of the package's files as well.", row.title),
            confirmLabel: _t("Remove"),
            confirm: () => {
                void this.model.remove(row.id, true);
            },
            cancel: () => {},
        });
    }

    // -- the inline New form ------------------------------------------------------

    get creating(): CreatingState | null {
        return this.model.creating;
    }

    /** The rows the inline form asks for, in catalogue order. */
    get createRows(): RowJSON[] {
        const creating = this.creating;
        if (!creating) {
            return [];
        }
        const byName = this.model.rowsByName;
        const names = [...(creating.needs || [])];
        for (const name of this.model.requiredRowNames()) {
            if (!names.includes(name)) {
                names.push(name);
            }
        }
        // `.filter(Boolean)` alone does not narrow `(RowJSON | undefined)[]`
        // to `RowJSON[]` under `noUncheckedIndexedAccess` -- `Boolean` is a
        // plain function reference here, not a type-predicate callback
        // (`drag.ts`'s own `watchEdge` comment on the identical gap).
        return names.map((name) => byName[name]).filter((row): row is RowJSON => Boolean(row));
    }

    onCreateValue(row: RowJSON, value: unknown): void {
        // Only rendered while `this.creating` is truthy (the inline New
        // form) -- the same real invariant the original JS relied on
        // without a guard.
        this.model.creating!.values[row.name] = value;
    }

    async onCreate(): Promise<void> {
        await this.model.create();
    }

    get rowContext(): RowContext {
        return {
            resModel: this.shell.modelName,
            // `extra.groups` has never been a key any real `catalogue()`
            // implementation sets -- grepped every one in the tree
            // (`studio_record_surface.py`'s base and
            // `studio_approval_surface.py`'s gate override, the only two
            // that exist) and neither returns a top-level `"groups"` key.
            // Always `[]`, the same "typed to what it actually always
            // evaluates to" treatment cluster 1's `row.placeholder` and
            // `row_editor.ts`'s own `row.follow` already got.
            groups: (this.model.extra["groups"] as RowContextGroup[] | undefined) || [],
        };
    }
}

interface RecordSidebarState {
    openChild: number | false;
}

export class RecordSidebar extends Component<Props> {
    static override template = "app_builder_view.RecordSidebar";
    static components = { RowEditor };
    static override props = { shell: Object, model: { type: Object, optional: true } };

    shell!: StudioShell;
    model!: RecordPaneModel;
    dialog!: DialogService;
    state!: RecordSidebarState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        // Which child is unfolded; the last one added opens itself.
        this.state = useState<RecordSidebarState>({ openChild: false });
    }

    get record(): RecordDescription | null {
        return this.model.record;
    }

    get row(): RecordRowJSON | null {
        return this.record ? this.record.row : null;
    }

    get editable(): boolean {
        return Boolean(this.row && this.row.editable);
    }

    /** The sections that apply to the record's current values, with their rows. */
    get sections(): SectionJSON[] {
        const record = this.record;
        if (!record) {
            return [];
        }
        return (record.sections || [])
            .filter((section) => this.model.visible(section.visible_when, record.values))
            .map((section) => ({
                ...section,
                rows: section.rows.filter((row) =>
                    this.model.visible(row.visible_when, record.values),
                ),
            }))
            .filter((section) => section.rows.length);
    }

    get actions(): RecordActionJSON[] {
        return (this.record && this.record.actions) || [];
    }

    get notes(): unknown[] {
        return (this.record && this.record.notes) || [];
    }

    /** `{valid, count, total}` or `{valid: false, reason}` when the surface counts a condition. */
    get matches(): RecordMatches | null {
        return (this.record && (this.record["matches"] as RecordMatches | undefined)) || null;
    }

    get rowContext(): RowContext {
        return {
            resModel: this.shell.modelName,
            // See `RecordPane.rowContext`'s own comment: always `[]`.
            groups: (this.model.extra["groups"] as RowContextGroup[] | undefined) || [],
        };
    }

    onChange(row: RowJSON, value: unknown): void {
        void this.model.write({ [row.name]: value });
    }

    // -- children -----------------------------------------------------------------

    get children(): RecordChildrenJSON | null {
        return this.model.children;
    }

    /** A child's sections that apply to its values, with their rows. */
    childSections(child: RecordDescription): SectionJSON[] {
        return (child.sections || [])
            .filter((section) => this.model.visible(section.visible_when, child.values))
            .map((section) => ({
                ...section,
                rows: section.rows.filter((row) =>
                    this.model.visible(row.visible_when, child.values),
                ),
            }))
            .filter((section) => section.rows.length);
    }

    /** The kinds a child can be added as, as objects: a pair is no key for a loop. */
    get childKinds(): { value: string; label: string }[] {
        const kinds = (this.children && this.children.kinds) || [];
        return kinds.map(([value, label]) => ({ value, label }));
    }

    childKindLabel(child: RecordDescription): unknown {
        // Called only for a rendered child, where `this.children` is
        // always set -- the same real invariant the original JS relied on
        // without a guard.
        const children = this.children!;
        const value = child.values[children.kind_field];
        const kind = children.kinds.find((k) => k[0] === value);
        return kind ? kind[1] : value;
    }

    isOpen(child: RecordDescription): boolean {
        return this.state.openChild === child.row.id;
    }

    toggleChild(child: RecordDescription): void {
        this.state.openChild = this.isOpen(child) ? false : child.row.id;
    }

    onChildChange(child: RecordDescription, row: RowJSON, value: unknown): void {
        void this.model.writeChild(child.row.id, { [row.name]: value });
    }

    async onAddChild(ev: Event): Promise<void> {
        const target = ev.target as HTMLSelectElement;
        const kind = target.value;
        target.value = "";
        if (!kind) {
            return;
        }
        // `add_step` (`app_builder_ui/models/studio_automation_surface.py`,
        // the only real `children.add` implementation confirmed so far)
        // returns `describe()`'s own shape -- traced to the real Python
        // method, not guessed. `RecordPaneModel.addChild`'s own return
        // type stays `Promise<unknown>` rather than narrowed tree-wide,
        // since `children.add` genuinely names a different method per
        // surface and not every real implementation has been checked.
        const added = (await this.model.addChild(kind)) as RecordDescription | undefined;
        if (added && added.row) {
            this.state.openChild = added.row.id;
        }
    }

    /** Up: before the previous one. Down: before the one after the next, or last. */
    onMoveChild(child: RecordDescription, direction: number): void {
        // Only rendered inside `this.children`'s own list -- the same
        // real invariant the original JS relied on without a guard.
        const children = this.children!;
        const items = children.items;
        const index = items.findIndex((item) => item.row.id === child.row.id);
        const target = direction < 0 ? items[index - 1] : items[index + 2];
        if (direction < 0 && index === 0) {
            return;
        }
        if (direction > 0 && index >= items.length - 1) {
            return;
        }
        void this.model.moveChild(child.row.id, target ? target.row.id : false);
    }

    onRemoveChild(child: RecordDescription): void {
        // Only rendered inside `this.children`'s own list -- same
        // invariant as `onMoveChild` above.
        const children = this.children!;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove"),
            body: _t("Remove this %s? The rest stay as they are.", children.one),
            confirmLabel: _t("Remove"),
            confirm: () => {
                void this.model.removeChild(child.row.id);
            },
            cancel: () => {},
        });
    }

    onChildAction(child: RecordDescription, action: RecordActionJSON): void {
        if (!action.enabled) {
            return;
        }
        void this.model.runChild(child.row.id, action.key);
    }

    onAction(action: RecordActionJSON): void {
        if (!action.enabled) {
            return;
        }
        void this.model.runAction(action.key);
    }

    /** Odoo's own form on the record, inside the console, capturing on save. */
    onAdvanced(): void {
        // The "Advanced…" button only renders once `this.editable` is
        // true, which itself requires a selected record -- the same real
        // invariant the original JS relied on without a guard. `row.title`
        // is read off the same `record` rather than through the `this.row`
        // getter again, since both name the identical value
        // (`record.row`) and this avoids a second non-null assertion.
        const record = this.record!;
        const advanced = record.advanced;
        this.dialog.add(FormViewDialog, {
            resModel: advanced.res_model,
            resId: advanced.res_id,
            context: advanced.context || {},
            title: record.row.title,
            onRecordSaved: async () => {
                await this.model.loadRows();
                await this.model.describe();
                this.shell.refreshChanges();
            },
        });
    }

    onRemove(): void {
        // The Remove button only renders while `this.editable` is true --
        // same invariant as `onAdvanced` above.
        const row = this.row!;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove"),
            body: _t("Remove %s? It is taken out of the package's files as well.", row.title),
            confirmLabel: _t("Remove"),
            confirm: () => {
                void this.model.remove(row.id, true);
            },
            cancel: () => {},
        });
    }

    onDuplicate(): void {
        // The Duplicate button only renders while `this.row` is set (the
        // `t-elif` beside the Remove button above, both behind a selected
        // record) -- same invariant.
        const row = this.row!;
        void this.model.duplicate(row.id);
    }
}

setPaneResolver("record", (entry) => ({
    Component: RecordPane,
    sidebar: RecordSidebar,
    // `entry` is `PaneEntry` here (`PaneResolver`'s own parameter type,
    // `shell/pane_registry.ts`); `resolvePane` only ever calls the
    // "record" resolver from its own `if (entry.surface)` branch, so
    // `entry.surface` is always set by the time this runs -- not an
    // invariant `tsc` can see across that module boundary, hence the cast
    // rather than a redundant guard. Through `unknown` rather than a
    // single `as`: `PaneEntry.surface` is optional and `RecordPaneEntry`'s
    // own index signature answers `unknown` rather than `string` for an
    // unnamed key, so neither type is assignable to the other and a
    // direct `entry as RecordPaneEntry` is refused ("neither type
    // sufficiently overlaps with the other") -- the same fix this
    // migration already uses for an unrelated pair of unrelated-looking
    // interfaces (`identity.test.ts`'s own finding on this exact
    // message). `shell` is cast with a single `as` since its own
    // contextual type is bare `unknown` (`PaneRegistration.makeModel`'s
    // signature), which any single `as` accepts -- the same cast
    // `flow.ts`'s identical "flow" resolver already does.
    makeModel: (shell) =>
        new RecordPaneModel(shell as StudioShell, entry as unknown as RecordPaneEntry),
}));

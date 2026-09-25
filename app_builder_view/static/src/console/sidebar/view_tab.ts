/** @odoo-module **/
/**
 * View: the settings of the view itself, and what the studio has written.
 *
 * The root's option rows -- a list's inline editing, a form's title, a
 * calendar's date field -- edited the same way as any node's, against the
 * root token. Beside them, what the canvas cannot show: hidden nodes
 * (a switch that re-renders the canvas with them dimmed), the views this
 * model could still gain, the arch the studio has written for this view
 * so far, and the changes that can be undone, with who made them.
 *
 * For a model the package defines in Python, also the model itself: its
 * fields in class order -- the order they are written to Python and the
 * order a scaffolded view shows them in -- each with what the draft holds
 * for it. This is where a field that is on no view of the model, or on a
 * view other than this one, is still reachable: edited, removed, moved, or
 * added without a place to drop it on.
 */

import { Component, onWillDestroy, onWillStart, useEffect, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { ConfirmationDialog, useService } from "../odoo";
import type { DialogService } from "../odoo";
import type { ConsoleModel } from "../console_model";
import { optionsFor, visibleRows, writeValue } from "../options";
import type { OptionsContext, ResolvedRow } from "../options";
import { iconForType } from "../pending_widget";
import type { DraftFieldWithPending } from "../shell/draft_model";
import type { DescribedTarget, HistoryEntry } from "../types";
import type { DraftFieldJSON } from "../wire";
import { useFieldEditor } from "./field_editor_fallback";

interface Props {
    model: ConsoleModel;
}

/** One rendered options group, as `panels` hands it to the template. */
interface PanelGroup {
    id: string;
    title: string;
    rows: ResolvedRow[];
}

/** One entry of `modelFields` below: a draft field (or a plain synthetic
 * `{name, string, pendingKind: "removed"}` -- see `DraftFieldWithPending`'s
 * own comment for when that happens) with the icon and type label the row
 * needs to draw itself. */
interface ModelFieldRow extends DraftFieldWithPending {
    icon: string;
    typeLabel: string;
}

/** The component's own UI state: `describe(root)`'s answer for the
 * current selection, refreshed by the `useEffect` below whenever the
 * selection or the arch version changes. */
interface ViewTabState {
    target: DescribedTarget | null;
}

export class ViewTab extends Component<Props> {
    static override template = "app_builder_view.ViewTab";
    static override props = { model: Object };

    // Every field below is assigned unconditionally in `setup()` --
    // Owl components initialize through that lifecycle hook, not a
    // constructor this class writes its own, so `strictPropertyInitialization`
    // (which only ever looks at a real constructor) cannot see it; the
    // definite-assignment assertion says so instead (TYPING.md's own
    // "Known traps").
    model!: ConsoleModel;
    dialog!: DialogService;
    editor!: ReturnType<typeof useFieldEditor>;
    state!: ViewTabState;

    override setup(): void {
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        this.editor = useFieldEditor();
        this.state = useState<ViewTabState>({ target: null });
        onWillStart(async () => {
            // The model list reads the draft; a Python-owned model with
            // nothing staged has none until asked. A clean draft is nothing
            // to apply, so opening one here costs nothing.
            if (this.model.pythonOwned && !this.model.draft) {
                await this.model._ensureDraft();
            }
        });
        let alive = true;
        onWillDestroy(() => {
            alive = false;
        });
        useEffect(
            (root, version) => {
                this.state.target = null;
                if (!root || !version) {
                    return;
                }
                // Fire-and-forget from this (non-async) effect's own point
                // of view, same as every other unhandled mutation call in
                // this tree -- `void` says so explicitly rather than
                // leaving the chained promise floating.
                void this.model.describe(root).then((target) => {
                    if (alive && this.model.archVersion === version) {
                        this.state.target = target;
                    }
                });
            },
            () => [this.model.root, this.model.archVersion],
        );
    }

    get panels(): PanelGroup[] {
        const target = this.state.target;
        if (!target || !target.found) {
            return [];
        }
        const raw = this.model.context;
        const context: OptionsContext = raw
            ? { catalogue: raw.catalogue, fields: raw.fields, options: raw.options }
            : {};
        return optionsFor(context, target).map((group) => ({
            id: group.id,
            title: group.title,
            rows: visibleRows(group, target, context),
        }));
    }

    get source(): unknown {
        return this.model.canvas ? this.model.canvas.source : null;
    }

    get ownershipNote(): string | ReturnType<typeof _t> {
        if (!this.model.context) {
            return "";
        }
        return this.model.context.owned
            ? _t("This package owns this view, so changes are written into it directly.")
            : _t(
                  "This view belongs to another module. Changes become a separate " +
                      "inheriting view, so the original keeps working and upgrades " +
                      "cleanly.",
              );
    }

    get recentChanges(): HistoryEntry[] {
        return this.model.history.undo || [];
    }

    // -- the model ------------------------------------------------------------

    get showsModel(): boolean {
        return Boolean(this.model.pythonOwned);
    }

    get modelFields(): ModelFieldRow[] {
        return this.model.modelFields.map((field) => ({
            ...field,
            icon: iconForType(field.ttype, field.ttype),
            typeLabel: field.type_label || field.ttype || "",
        }));
    }

    pendingBadge(field: ModelFieldRow): string | ReturnType<typeof _t> {
        switch (field.pendingKind) {
            case "added":
                return _t("new");
            case "changed":
                return _t("edited");
            case "removed":
                return _t("removed");
            default:
                return "";
        }
    }

    editorProps(anchorName: string | null, field: DraftFieldJSON | null) {
        const names = this.model.modelFields.map((f) => f.name).filter((n) => n !== anchorName);
        return {
            field: field ? { ...field } : null,
            mode: "staged",
            fieldTypes: this.model.fieldTypes,
            existingNames: names,
            modelName: this.model.modelName,
            inverseOptions: (comodel: string) => this.model.inverseOptions(comodel),
            resolveRelated: (path: string) => this.model.resolveRelated(path),
        };
    }

    // Not `async`: nothing in this method's own body is awaited (the
    // `await` lives inside the nested `onSave` callback, its own function
    // scope) -- `async` here would be a no-op wrapping an already-`void`
    // return in a `Promise`, exactly what `require-await` exists to catch.
    onEditModelField(ev: MouseEvent, entry: ModelFieldRow): void {
        const staged = this.model.stagedField(entry.name);
        if (!staged) {
            return;
        }
        const name = entry.name;
        this.editor.open(ev.currentTarget as HTMLElement, {
            ...this.editorProps(name, staged),
            onSave: async (values: Record<string, unknown>) => {
                this.editor.close();
                await this.model.updateStaged(name, values);
            },
            onDelete: () => {
                this.editor.close();
                this.onRemoveModelField(entry);
            },
        });
    }

    onRemoveModelField(entry: ModelFieldRow): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Remove field from the model"),
            body: _t(
                "Remove %s from the model? Nothing changes until Apply; then its " +
                    "column is dropped and its data kept aside by a migration. " +
                    "Discard the pending changes to take it back before that.",
                entry.string || entry.name,
            ),
            confirmLabel: _t("Stage the removal"),
            confirm: () => {
                // `ConfirmationDialogProps.confirm` is `() => void`, so a
                // Promise-returning callback here is a real
                // `no-misused-promises` finding, not just a style
                // preference -- `void` fire-and-forgets it, the same fix
                // already established for `apply_dialog.ts`'s own
                // `onDiscard`/`sidebar/remove_flow.ts`.
                void this.model.removePending(entry.name);
            },
            cancel: () => {},
        });
    }

    /** A new field with no place on this canvas: Apply places it. */
    onAddModelField(ev: MouseEvent): void {
        this.editor.open(ev.currentTarget as HTMLElement, {
            ...this.editorProps(null, null),
            initial: { ttype: "char" },
            onSave: async (values: Record<string, unknown>) => {
                this.editor.close();
                await this.model.addModelField(values);
            },
            onDelete: null,
        });
    }

    async onMoveUp(entry: ModelFieldRow): Promise<void> {
        const names = this.model.modelFields
            .filter((f) => f.pendingKind !== "removed")
            .map((f) => f.name);
        const index = names.indexOf(entry.name);
        if (index > 0) {
            await this.model.moveField(entry.name, names[index - 1]);
        }
    }

    async onMoveDown(entry: ModelFieldRow): Promise<void> {
        const names = this.model.modelFields
            .filter((f) => f.pendingKind !== "removed")
            .map((f) => f.name);
        const index = names.indexOf(entry.name);
        if (index >= 0 && index < names.length - 1) {
            await this.model.moveField(entry.name, names[index + 2] || null);
        }
    }

    async onRowChange(row: ResolvedRow, rawValue: unknown): Promise<void> {
        // Captured into locals right after the check: reading
        // `this.model.root`/`this.state.target` again afterward would
        // lose the narrowing the moment anything in between is a call
        // (TYPING.md's own "Known traps" -- confirmed necessary here since
        // `writeValue(...)`, the very next expression, is exactly such a
        // call).
        const root = this.model.root;
        const target = this.state.target;
        if (!root || !target) {
            return;
        }
        await this.model.setAttributes(root, writeValue(row, rawValue, target));
    }

    onToggle(row: ResolvedRow, ev: Event): Promise<void> {
        return this.onRowChange(row, (ev.target as HTMLInputElement).checked);
    }

    onInput(row: ResolvedRow, ev: Event): Promise<void> {
        return this.onRowChange(row, (ev.target as HTMLInputElement | HTMLSelectElement).value);
    }
}

/** @odoo-module **/
/**
 * What a record pane knows, and every call it makes.
 *
 * A record pane shows the rows of one server *surface* -- `studio.automation`,
 * `studio.rule.surface` -- for the model in hand: the rows as cards, one
 * selected record described for the sidebar, and the mutations the
 * surface offers (`write_record`, `create_record`, `remove_record`,
 * `duplicate_record`, `run`). The surface's contract is what makes one
 * component serve every kind of record: rows say who owns them and
 * whether they can be edited here, a description carries the sections
 * and the values the sidebar renders, and templates say what the New
 * tiles offer.
 *
 * The same three rules the canvas follows (`console_model.js`): a
 * refusal is a sentence shown as the server said it, the list is
 * replaced rather than patched after every write, and nothing here
 * rethrows what the caller has nothing to add to.
 *
 * No Owl in here. Reactivity is the caller's business (`useState` on the
 * instance); this class is plain so it can be tested and ported as it is.
 */

import { markRaw } from "@odoo/owl";
import { _t } from "../l10n";
import * as compat from "../compat";
import { messageOf } from "../shell/draft_model";
import type { StudioShell } from "../shell/shell_model";
import type { OdooRpcError, OrmService, PaneActivity, PaneModel } from "../types";
import type {
    RecordCatalogueJSON,
    RecordChildrenJSON,
    RecordDescription,
    RecordRowJSON,
    RecordTemplateJSON,
    SectionJSON,
} from "../wire";

/** One entry of `entry.rowActions`, contributed alongside the built-in
 * Remove/Duplicate row actions (`app_builder_ui/static/src/console_items.js`'s
 * "menu" pane is the one real registration today). */
export interface RowActionSpec {
    key: string;
    label: unknown;
    icon: string;
    when?: (row: RecordRowJSON) => boolean;
    run: (shell: StudioShell, row: RecordRowJSON, model: RecordPaneModel) => void;
}

/** The pane's registry entry, the fields this model itself reads
 * (`shell/pane_registry.js`'s own docstring: "a record pane: surface,
 * surfaceArgs, rowActions, newFlow") plus `label`/`empty`, which
 * `record_pane.ts` -- the real, first reader of either -- needs off the
 * same entry. */
export interface RecordPaneEntry {
    surface: string;
    surfaceArgs?: Record<string, unknown>;
    scope?: "package" | "model" | "view";
    /** `_t(...)`'s own lazy return type, the same convention `FlowStep.label`
     * already uses -- every real registration passes `_t(...)`, never a
     * plain string. */
    label?: unknown;
    empty?: { title?: unknown; help?: unknown };
    rowActions?: RowActionSpec[];
    [key: string]: unknown;
}

/** What `open()`/`reactivate()` is handed: `shell.openTarget`'s answer
 * for a record pane. */
export interface RecordPaneTarget {
    rec?: string | number | false;
    [key: string]: unknown;
}

/** The inline New form's state (`startCreate`/`creatingValues`). */
export interface CreatingState {
    template: string | null;
    needs: string[];
    values: Record<string, unknown>;
    error: string;
}

/** A row's own visibility clauses -- the same `[name, allowed]` shape
 * `RowJSON.visible_when`/`SectionJSON.visible_when` carry. */
export type VisibleWhenClauses = readonly (readonly [string, readonly string[]])[];

export class RecordPaneModel implements PaneModel {
    shell: StudioShell;
    env: StudioShell["env"];
    orm: OrmService;
    notification: StudioShell["notification"];
    entry: RecordPaneEntry;
    surface: string;
    surfaceArgs: Record<string, unknown>;

    rows: RecordRowJSON[];
    catalogue: Pick<RecordCatalogueJSON, "sections" | "templates" | "model"> | null;
    loading: boolean;
    search: string;
    filter: "all" | "mine";
    showInactive: boolean;
    selectedId: number | false;
    record: RecordDescription | null;
    describing: boolean;
    busy: boolean;
    status: string;
    statusError: string;
    /** The inline New form: the template chosen and the values typed. */
    creating: CreatingState | null;
    opened: boolean;
    /** Pane-level extras a surface may carry (a gate, an enable step). */
    extra: Record<string, unknown>;

    constructor(shell: StudioShell, entry: RecordPaneEntry) {
        this.shell = shell;
        this.env = shell.env;
        this.orm = shell.orm;
        this.notification = shell.notification;
        this.entry = entry;
        this.surface = entry.surface;
        this.surfaceArgs = entry.surfaceArgs || {};

        this.rows = [];
        this.catalogue = null;
        this.loading = false;
        this.search = "";
        this.filter = "all";
        this.showInactive = false;
        this.selectedId = false;
        this.record = null;
        this.describing = false;
        this.busy = false;
        this.status = "saved";
        this.statusError = "";
        this.creating = null;
        this.opened = false;
        this.extra = {};
    }

    // -- reading ------------------------------------------------------------

    get modelName(): string {
        return this.shell.modelName;
    }

    get packageId(): number | false {
        return this.shell.packageId;
    }

    get activity(): PaneActivity {
        return {
            busy: this.busy,
            status: this.status,
            error: this.statusError,
            drag: null,
            applying: this.shell.draft.applying,
        };
    }

    get history(): null {
        return null;
    }

    get sections(): SectionJSON[] {
        return this.catalogue?.sections || [];
    }

    get templates(): RecordTemplateJSON[] {
        return this.catalogue?.templates || [];
    }

    /** The rows the toolbar's search, filter and inactive switch let through. */
    get visibleRows(): RecordRowJSON[] {
        const term = this.search.trim().toLowerCase();
        return this.rows.filter((row) => {
            if (this.filter === "mine" && !row.owned) {
                return false;
            }
            if (!this.showInactive && row.active === false) {
                return false;
            }
            if (!term) {
                return true;
            }
            return (
                (row.title || "").toLowerCase().includes(term) ||
                (row.sentence || "").toLowerCase().includes(term)
            );
        });
    }

    get selectedRow(): RecordRowJSON | null {
        return this.rows.find((row) => row.id === this.selectedId) || null;
    }

    /** Every row of the catalogue, by name. */
    get rowsByName(): Record<string, SectionJSON["rows"][number]> {
        const out: Record<string, SectionJSON["rows"][number]> = {};
        for (const section of this.sections) {
            for (const row of section.rows) {
                out[row.name] = row;
            }
        }
        return out;
    }

    // -- loading ------------------------------------------------------------

    async open(target: RecordPaneTarget = {}): Promise<void> {
        this.creating = null;
        this.selectedId = false;
        this.record = null;
        await this.load();
        if (target.rec) {
            await this.select(target.rec as number, { push: false });
        }
    }

    /** The list again -- another pane may have changed ownership. */
    async reactivate(): Promise<void> {
        await this.loadRows();
        if (this.selectedId) {
            if (this.rows.some((row) => row.id === this.selectedId)) {
                await this.describe();
            } else {
                this.clearSelection();
            }
        }
    }

    async afterApply(): Promise<void> {
        await this.load();
        if (this.selectedId) {
            await this.describe();
        }
    }

    async load(): Promise<void> {
        this.loading = true;
        try {
            await Promise.all([this.loadCatalogue(), this.loadRows()]);
        } finally {
            this.loading = false;
        }
    }

    async loadCatalogue(): Promise<void> {
        const payload = await this.orm.call<RecordCatalogueJSON>(this.surface, "catalogue", [
            this.modelName || false,
        ]);
        const { sections, templates, model, ...extra } = payload;
        this.catalogue = markRaw({ sections, templates, model });
        this.extra = markRaw(extra);
    }

    async loadRows(): Promise<void> {
        // A model-scoped surface has nothing to list without a model; a
        // package-scoped one (the menu) lists the package's and takes the
        // model, when there is one, as a highlight.
        if (!this.modelName && this.entry.scope !== "package") {
            this.rows = [];
            return;
        }
        const rows = await this.orm.call<RecordRowJSON[]>(
            this.surface,
            "rows",
            [this.modelName || false, this.packageId || false],
            { ...this.surfaceArgs },
        );
        this.rows = rows;
    }

    // -- selection ------------------------------------------------------------

    async select(id: number | false, { push = true }: { push?: boolean } = {}): Promise<void> {
        this.creating = null;
        this.selectedId = id;
        if (push) {
            this.shell.setPaneState({ rec: id });
        }
        await this.describe();
    }

    clearSelection(): void {
        this.selectedId = false;
        this.record = null;
        this.shell.setPaneState({ rec: undefined });
    }

    async describe(): Promise<RecordDescription | null> {
        const id = this.selectedId;
        if (!id) {
            this.record = null;
            return null;
        }
        this.describing = true;
        try {
            const record = await this.orm.call<RecordDescription>(this.surface, "describe", [
                id,
                this.packageId || false,
            ]);
            if (this.selectedId === id) {
                this.record = markRaw(record);
            }
            return record;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.notification.add(messageOf(err), { type: "warning" });
            this.record = null;
            return null;
        } finally {
            this.describing = false;
        }
    }

    /** Whether a row or a section applies to the record's current values. */
    visible(
        clauses: VisibleWhenClauses | null | undefined,
        values: Record<string, unknown> | null = null,
    ): boolean {
        const current: Record<string, unknown> =
            values || (this.record && this.record.values) || this.creatingValues();
        for (const [name, allowed] of clauses || []) {
            const value = current[name];
            const key = (
                value && typeof value === "object" ? (value as { id?: unknown }).id : value
            ) as string | number | boolean | null | undefined;
            if (!allowed.includes(key === false ? "" : String(key === undefined ? "" : key))) {
                return false;
            }
        }
        return true;
    }

    // -- mutating -------------------------------------------------------------

    /**
     * One wrapper for every edit: the status pill, the two refusals a
     * client can act on (a stale answer, a confirmation asked for) and the
     * server's sentence for everything else.
     */
    async _mutate<T>(run: () => Promise<T>): Promise<T | undefined> {
        if (!this.packageId) {
            this.notification.add(String(_t("Choose a package to record this change in first.")), {
                type: "warning",
            });
            return undefined;
        }
        this.busy = true;
        this.status = "saving";
        this.statusError = "";
        try {
            const result = await run();
            this.status = "saved";
            return result;
        } catch (err) {
            if (compat.isConfirmError(err)) {
                this.status = "saved";
                throw err;
            }
            if (!(err as OdooRpcError)?.data) {
                this.status = "error";
                this.statusError = String(err);
                throw err;
            }
            this.status = "error";
            this.statusError = messageOf(err);
            this.notification.add(this.statusError, { type: "warning" });
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /** Write row values on the selected record, then read it again. */
    async write(values: Record<string, unknown>): Promise<RecordRowJSON | undefined> {
        const id = this.selectedId;
        if (!id) {
            return undefined;
        }
        const row = await this._mutate(() =>
            this.orm.call<RecordRowJSON>(this.surface, "write_record", [
                id,
                values,
                this.packageId || false,
            ]),
        );
        if (row !== undefined) {
            await this.loadRows();
            await this.describe();
            this.shell.refreshChanges();
        }
        return row;
    }

    /** Begin the inline New form, from a template or from nothing. */
    startCreate(template: RecordTemplateJSON | null = null): void {
        this.selectedId = false;
        this.record = null;
        this.shell.setPaneState({ rec: undefined });
        this.creating = {
            template: template ? template.key : null,
            needs: template ? template.needs : this.requiredRowNames(),
            values: {},
            error: "",
        };
    }

    cancelCreate(): void {
        this.creating = null;
    }

    creatingValues(): Record<string, unknown> {
        return (this.creating && this.creating.values) || {};
    }

    /** The rows the inline form asks for: what the template needs, else what is required. */
    requiredRowNames(): string[] {
        return Object.values(this.rowsByName)
            .filter((row) => row.required)
            .map((row) => row.name);
    }

    async create(): Promise<RecordRowJSON | undefined> {
        if (!this.creating) {
            return undefined;
        }
        const { template, values } = this.creating;
        const row = await this._mutate(() =>
            this.orm.call<RecordRowJSON>(this.surface, "create_record", [
                this.modelName || false,
                this.packageId || false,
                values,
                template || false,
            ]),
        );
        if (row === undefined) {
            return undefined;
        }
        this.creating = null;
        await this.loadRows();
        await this.select(row.id);
        this.shell.refreshChanges();
        return row;
    }

    /**
     * Take a record out. A refusal asking for confirmation is handed back
     * as `{confirm: sentence}` so the pane can ask and call again.
     */
    async remove(id: number, force = false): Promise<unknown> {
        try {
            const result = await this._mutate(() =>
                this.orm.call(this.surface, "remove_record", [id, this.packageId || false], {
                    force,
                }),
            );
            if (result !== undefined) {
                if (this.selectedId === id) {
                    this.clearSelection();
                }
                await this.loadRows();
                this.shell.refreshChanges();
            }
            return result;
        } catch (err) {
            if (compat.isConfirmError(err)) {
                return { confirm: messageOf(err) };
            }
            throw err;
        }
    }

    async duplicate(id: number): Promise<RecordRowJSON | undefined> {
        const row = await this._mutate(() =>
            this.orm.call<RecordRowJSON>(this.surface, "duplicate_record", [
                id,
                this.packageId || false,
            ]),
        );
        if (row !== undefined) {
            await this.loadRows();
            await this.select(row.id);
            this.shell.refreshChanges();
        }
        return row;
    }

    /** A named action of the surface on the selected record. */
    async runAction(key: string): Promise<RecordDescription | undefined> {
        const id = this.selectedId;
        if (!id) {
            return undefined;
        }
        const record = await this._mutate(() =>
            this.orm.call<RecordDescription>(this.surface, "run", [
                id,
                key,
                this.packageId || false,
            ]),
        );
        if (record !== undefined) {
            this.record = markRaw(record);
            await this.loadRows();
            this.shell.refreshChanges();
        }
        return record;
    }

    // -- children ---------------------------------------------------------------
    //
    // A description may carry `children`: the records that belong to the
    // one selected (an automation's steps), each described by their own
    // surface. Every edit below goes through that surface and reads the
    // parent again, since its sentence is made of them.

    get children(): RecordChildrenJSON | null {
        return (this.record && this.record.children) || null;
    }

    async _childMutate(
        method: string,
        args: unknown[],
        kwargs: Record<string, unknown> = {},
    ): Promise<unknown> {
        const children = this.children;
        if (!children) {
            return undefined;
        }
        const result = await this._mutate(() =>
            this.orm.call(children.surface, method, args, kwargs),
        );
        if (result !== undefined) {
            await this.loadRows();
            await this.describe();
            this.shell.refreshChanges();
        }
        return result;
    }

    writeChild(id: number, values: Record<string, unknown>): Promise<unknown> {
        return this._childMutate("write_record", [id, values, this.packageId || false]);
    }

    /** A new child of the selected record, of one of `children.kinds`. */
    async addChild(kind: string | null): Promise<unknown> {
        const children = this.children;
        const parentId = this.selectedId;
        if (!children || !parentId) {
            return undefined;
        }
        const values = kind ? { [children.kind_field]: kind } : {};
        const added = await this._childMutate(children.add, [
            parentId,
            this.packageId || false,
            values,
        ]);
        return added;
    }

    async moveChild(id: number, beforeId: number | false = false): Promise<unknown> {
        const children = this.children;
        if (!children || !children.move) {
            return undefined;
        }
        return this._childMutate(children.move, [id, beforeId || false, this.packageId || false]);
    }

    removeChild(id: number): Promise<unknown> {
        return this._childMutate("remove_record", [id, this.packageId || false], {
            force: true,
        });
    }

    runChild(id: number, key: string): Promise<unknown> {
        return this._childMutate("run", [id, key, this.packageId || false]);
    }

    /** A call on the surface that is neither a row nor a record: a gate, an enable. */
    async call(
        method: string,
        args: unknown[] = [],
        kwargs: Record<string, unknown> = {},
    ): Promise<unknown> {
        const result = await this._mutate(() => this.orm.call(this.surface, method, args, kwargs));
        if (result !== undefined) {
            await this.load();
            if (this.selectedId) {
                await this.describe();
            }
            this.shell.refreshChanges();
        }
        return result;
    }
}

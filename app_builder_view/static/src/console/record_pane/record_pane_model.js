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
import { _t } from "@web/core/l10n/translation";
import * as compat from "../compat";
import { messageOf } from "../shell/draft_model";

export class RecordPaneModel {
    /**
     * @param {Object} shell the `StudioShell`
     * @param {Object} entry the pane's registry entry: `surface`,
     *   `surfaceArgs`, `rowActions`, `label`, `key`
     */
    constructor(shell, entry) {
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
        // The inline New form: the template chosen and the values typed.
        this.creating = null;
        this.opened = false;
        // Pane-level extras a surface may carry (a gate, an enable step).
        this.extra = {};
    }

    // -- reading ------------------------------------------------------------

    get modelName() {
        return this.shell.modelName;
    }

    get packageId() {
        return this.shell.packageId;
    }

    get activity() {
        return {
            busy: this.busy,
            status: this.status,
            error: this.statusError,
            drag: null,
            applying: this.shell.draft.applying,
        };
    }

    get history() {
        return null;
    }

    get sections() {
        return (this.catalogue && this.catalogue.sections) || [];
    }

    get templates() {
        return (this.catalogue && this.catalogue.templates) || [];
    }

    /** The rows the toolbar's search, filter and inactive switch let through. */
    get visibleRows() {
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

    get selectedRow() {
        return this.rows.find((row) => row.id === this.selectedId) || null;
    }

    /** Every row of the catalogue, by name. */
    get rowsByName() {
        const out = {};
        for (const section of this.sections) {
            for (const row of section.rows) {
                out[row.name] = row;
            }
        }
        return out;
    }

    // -- loading ------------------------------------------------------------

    async open(target = {}) {
        this.creating = null;
        this.selectedId = false;
        this.record = null;
        await this.load();
        if (target.rec) {
            await this.select(target.rec, { push: false });
        }
    }

    /** The list again -- another pane may have changed ownership. */
    async reactivate() {
        await this.loadRows();
        if (this.selectedId) {
            if (this.rows.some((row) => row.id === this.selectedId)) {
                await this.describe();
            } else {
                this.clearSelection();
            }
        }
    }

    async afterApply() {
        await this.load();
        if (this.selectedId) {
            await this.describe();
        }
    }

    async load() {
        this.loading = true;
        try {
            await Promise.all([this.loadCatalogue(), this.loadRows()]);
        } finally {
            this.loading = false;
        }
    }

    async loadCatalogue() {
        const payload = await this.orm.call(this.surface, "catalogue", [this.modelName || false]);
        const { sections, templates, model, ...extra } = payload;
        this.catalogue = markRaw({ sections, templates, model });
        this.extra = markRaw(extra);
    }

    async loadRows() {
        // A model-scoped surface has nothing to list without a model; a
        // package-scoped one (the menu) lists the package's and takes the
        // model, when there is one, as a highlight.
        if (!this.modelName && this.entry.scope !== "package") {
            this.rows = [];
            return;
        }
        const rows = await this.orm.call(
            this.surface,
            "rows",
            [this.modelName || false, this.packageId || false],
            { ...this.surfaceArgs }
        );
        this.rows = rows;
    }

    // -- selection ------------------------------------------------------------

    async select(id, { push = true } = {}) {
        this.creating = null;
        this.selectedId = id;
        if (push) {
            this.shell.setPaneState({ rec: id });
        }
        await this.describe();
    }

    clearSelection() {
        this.selectedId = false;
        this.record = null;
        this.shell.setPaneState({ rec: undefined });
    }

    async describe() {
        const id = this.selectedId;
        if (!id) {
            this.record = null;
            return null;
        }
        this.describing = true;
        try {
            const record = await this.orm.call(this.surface, "describe", [
                id,
                this.packageId || false,
            ]);
            if (this.selectedId === id) {
                this.record = markRaw(record);
            }
            return record;
        } catch (err) {
            if (!(err && err.data)) {
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
    visible(clauses, values = null) {
        const current = values || (this.record && this.record.values) || this.creatingValues();
        for (const [name, allowed] of clauses || []) {
            const value = current[name];
            const key = value && typeof value === "object" ? value.id : value;
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
    async _mutate(run) {
        if (!this.packageId) {
            this.notification.add(_t("Choose a package to record this change in first."), {
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
            if (!(err && err.data)) {
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
    async write(values) {
        const id = this.selectedId;
        if (!id) {
            return undefined;
        }
        const row = await this._mutate(() =>
            this.orm.call(this.surface, "write_record", [id, values, this.packageId || false])
        );
        if (row !== undefined) {
            await this.loadRows();
            await this.describe();
            this.shell.refreshChanges();
        }
        return row;
    }

    /** Begin the inline New form, from a template or from nothing. */
    startCreate(template = null) {
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

    cancelCreate() {
        this.creating = null;
    }

    creatingValues() {
        return (this.creating && this.creating.values) || {};
    }

    /** The rows the inline form asks for: what the template needs, else what is required. */
    requiredRowNames() {
        return Object.values(this.rowsByName)
            .filter((row) => row.required)
            .map((row) => row.name);
    }

    async create() {
        if (!this.creating) {
            return undefined;
        }
        const { template, values } = this.creating;
        const row = await this._mutate(() =>
            this.orm.call(this.surface, "create_record", [
                this.modelName || false,
                this.packageId || false,
                values,
                template || false,
            ])
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
    async remove(id, force = false) {
        try {
            const result = await this._mutate(() =>
                this.orm.call(this.surface, "remove_record", [id, this.packageId || false], {
                    force,
                })
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

    async duplicate(id) {
        const row = await this._mutate(() =>
            this.orm.call(this.surface, "duplicate_record", [id, this.packageId || false])
        );
        if (row !== undefined) {
            await this.loadRows();
            await this.select(row.id);
            this.shell.refreshChanges();
        }
        return row;
    }

    /** A named action of the surface on the selected record. */
    async runAction(key) {
        const id = this.selectedId;
        if (!id) {
            return undefined;
        }
        const record = await this._mutate(() =>
            this.orm.call(this.surface, "run", [id, key, this.packageId || false])
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

    get children() {
        return (this.record && this.record.children) || null;
    }

    async _childMutate(method, args, kwargs = {}) {
        const children = this.children;
        if (!children) {
            return undefined;
        }
        const result = await this._mutate(() =>
            this.orm.call(children.surface, method, args, kwargs)
        );
        if (result !== undefined) {
            await this.loadRows();
            await this.describe();
            this.shell.refreshChanges();
        }
        return result;
    }

    writeChild(id, values) {
        return this._childMutate("write_record", [id, values, this.packageId || false]);
    }

    /** A new child of the selected record, of one of `children.kinds`. */
    async addChild(kind) {
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

    moveChild(id, beforeId = false) {
        const children = this.children;
        if (!children || !children.move) {
            return undefined;
        }
        return this._childMutate(children.move, [id, beforeId || false, this.packageId || false]);
    }

    removeChild(id) {
        return this._childMutate("remove_record", [id, this.packageId || false], {
            force: true,
        });
    }

    runChild(id, key) {
        return this._childMutate("run", [id, key, this.packageId || false]);
    }

    /** A call on the surface that is neither a row nor a record: a gate, an enable. */
    async call(method, args = [], kwargs = {}) {
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

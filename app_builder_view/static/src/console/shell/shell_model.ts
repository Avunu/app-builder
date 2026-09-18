/** @odoo-module **/
/**
 * What the console is looking at, whichever pane is on.
 *
 * One package in the top bar, one model on the crumb, one view when the
 * Views pane is on, one pane in the content slot: that is the shell's
 * state, and it is what the URL carries so that a reload or a Back
 * lands on the same screen. Every pane gets the shell as a prop and
 * reads it through `useState`; a pane's own model -- the canvas, a
 * record list -- is made once per pane and kept while its scope holds
 * (a package-scoped model is dropped when the package changes, a
 * model-scoped one when the model does).
 *
 * The draft of a Python-owned model is the shell's too
 * (`draft_model.js`): the pill that counts what is pending and the
 * button that applies it are on every pane.
 *
 * Navigation never remounts the console. A pane switch, a package switch
 * or a record selected inside a pane changes this object and pushes the
 * URL through `updateActionState`; only a browser Back or a reload goes
 * through the action service again, which mounts a new console on the
 * params the URL kept.
 *
 * No Owl in here. Reactivity is the caller's business (`useState` on the
 * instance); this class is plain so it can be tested and ported as it is.
 */

import { _t } from "@web/core/l10n/translation";
import { DraftModel, messageOf } from "./draft_model";
import type { ApplyResult } from "./draft_model";
import { paneAvailable, paneRegistry, resolvePane, warnLegacyTabs } from "./pane_registry";
import type {
    FieldService,
    NotificationService,
    OdooRpcError,
    OrmService,
    PaneActivity,
    PaneContext,
    PaneEntry,
    PaneModel,
} from "../types";
import type { PackageEntryJSON, UserPrefsJSON } from "../wire";

const NEUTRAL_ACTIVITY: PaneActivity = Object.freeze({
    busy: false,
    status: "saved",
    error: "",
    drag: null,
    applying: false,
});

/** The view target held on the URL: the Views pane's own scope. */
export interface ShellViewState {
    view_id: number | false;
    view_type: string | false;
    res_id: number | false;
}

/** `{pushState(state), setTitle(title)}` -- the action service's
 * `updateActionState` and `setDisplayName`, handed in by whatever
 * mounted the console. */
export interface ShellHooks {
    pushState?: (state: ShellUrlState) => void;
    setTitle?: (title: string) => void;
}

/** How the console was entered; never in the URL. */
export interface ShellEntry {
    opened_from?: string;
    previous_action?: unknown;
    previous_view_type?: string | false;
    action_id?: number | false;
}

/** What `StudioShell.fromParams` makes of the action's params, and what
 * the constructor takes. */
export interface ShellParams {
    package_id?: number | false;
    res_model?: string;
    view: ShellViewState;
    pane?: string;
    rec?: string | false;
    entry?: ShellEntry;
}

/** What the view's editing context says the shell should know
 * (`learnContext`), from the editor's `editing_context`/`describe_node`
 * RPCs. */
export interface ShellLearnedContext {
    python_owned?: boolean;
    python_owner_id?: number | false;
    suggested_package_id?: number | false;
    // `model: string | false`, not just `string`: traced against the real
    // `editing_context()` now that `console_model.ts` carries the whole
    // shape (`wire.ts:EditingContext`) -- `view.model` is a plain Char
    // field read off `ir.ui.view`, `False` for a model-less view (a QWeb
    // report template).
    view?: { model?: string | false; id?: number | false; type?: string | false };
    draft_id?: number | false;
    reload_mode?: string | false;
}

/** What a `setModel`/`openView` caller hands in as the view target. */
export interface OpenViewTarget {
    model?: string;
    res_model?: string;
    view_id?: number | false;
    view_type?: string | false;
    res_id?: number | false;
}

/** What `urlState`/`pushUrl` sends the action service. */
export interface ShellUrlState {
    pane: string;
    package_id: number | false | undefined;
    res_model: string | undefined;
    view_type: string | false | undefined;
    view_id: number | false | undefined;
    res_id: number | false | undefined;
    rec: string | false | undefined;
}

/** `env.services`, plus `bus` -- the real Owl `env` every real caller
 * constructs `StudioShell` with (`shell.ts`'s own `new StudioShell(this.env,
 * ...)`) carries both, though this type named only `orm`/`notification`
 * until `panes/views_pane.ts` needed `field`/`bus` too, to construct a
 * `ConsoleModel`. The same shape `console_model.ts`'s own (unexported)
 * `ConsoleEnv` already names for the identical real object. */
interface ShellEnv {
    services: { orm: OrmService; notification: NotificationService; field: FieldService };
    bus: { trigger: (name: string) => void };
}

export class StudioShell {
    env: ShellEnv;
    orm: OrmService;
    notification: NotificationService;
    hooks: ShellHooks;
    params: ShellParams;
    packages: PackageEntryJSON[];
    packageId: number | false;
    modelName: string;
    modelLabel: string;
    inventory: unknown;
    prefs: UserPrefsJSON;
    /** The Views pane's target; URL state, so held here. */
    view: ShellViewState;
    pane: string;
    paneState: { rec?: string | false; [key: string]: unknown };
    /** One model per pane key, kept while its scope holds. A plain
     * object, so a pane model read through the shell is reactive. */
    paneModels: Record<string, PaneModel | undefined>;
    loading: boolean;
    error: string;
    draft: DraftModel;
    /** What the editing context said last about the model in hand. */
    learned: { python_owned: boolean; python_owner_id: number | false };
    entry: ShellEntry;
    sidebarWidth: number | null;
    /** `{key, title, lines}` after a flow completes: shown once, under
     * the bar, until dismissed or the next flow. */
    callout: { key: string; title: string; lines: string[] } | null;
    _changesTimer?: ReturnType<typeof setTimeout>;

    constructor(env: ShellEnv, params: ShellParams, hooks: ShellHooks = {}) {
        this.env = env;
        this.orm = env.services.orm;
        this.notification = env.services.notification;
        this.hooks = hooks;
        this.params = params;

        this.packages = [];
        this.packageId = params.package_id || false;
        this.modelName = params.res_model || "";
        this.modelLabel = "";
        this.inventory = null;
        this.prefs = {};
        this.view = {
            view_id: params.view.view_id || false,
            view_type: params.view.view_type || false,
            res_id: params.view.res_id || false,
        };
        this.pane = params.pane || "home";
        this.paneState = params.rec ? { rec: params.rec } : {};
        this.paneModels = {};
        this.loading = false;
        this.error = "";
        this.draft = new DraftModel(env, this);
        this.learned = { python_owned: false, python_owner_id: false };
        this.entry = params.entry || {};
        this.sidebarWidth = null;
        this.callout = null;
        warnLegacyTabs();
    }

    // -- reading ------------------------------------------------------------

    /** The chosen package's entry from `packages()`, or `null`. */
    get package(): PackageEntryJSON | null {
        return this.packages.find((p) => p.id === this.packageId) || null;
    }

    get packageWritable(): boolean {
        return Boolean(this.package && this.package.writable);
    }

    get pythonOwned(): boolean {
        return Boolean(this.learned.python_owned);
    }

    get activePane(): PaneEntry | null {
        return paneRegistry.contains(this.pane) ? resolvePane(this.pane) : null;
    }

    get activeModel(): PaneModel | null {
        return this.paneModels[this.pane] || null;
    }

    /** What panes and tabs are told about the shell. */
    get paneContext(): PaneContext {
        return {
            packageId: this.packageId,
            package: this.package,
            modelName: this.modelName,
            view: this.view,
            pane: this.pane,
            inventory: this.inventory,
            pythonOwned: this.pythonOwned,
        };
    }

    /** What the status pill reads, from the active pane or nothing. */
    get activity(): PaneActivity {
        const model = this.activeModel;
        return (model && model.activity) || NEUTRAL_ACTIVITY;
    }

    /** The active pane's undo stack, when it has one. */
    get history(): unknown {
        const model = this.activeModel;
        return (model && model.history) || null;
    }

    get pendingCount(): number {
        return this.draft.pendingCount;
    }

    /** What the Changes badge counts: pending fields, drifted files, failed applies. */
    get changesCount(): number {
        const info = this.package;
        return (
            this.pendingCount +
            (info ? info.drift_count || 0 : 0) +
            (info ? info.applies.failed || 0 : 0)
        );
    }

    get restartRequired(): boolean {
        const info = this.package;
        return Boolean(info && info.applies && info.applies.awaiting_restart);
    }

    // -- loading ------------------------------------------------------------

    /**
     * What every pane needs before it opens: the packages, and which one
     * is in hand -- the URL's, else the one last used, else the suggested
     * one, else the only one.
     */
    async load(): Promise<void> {
        const [packages, prefs] = await Promise.all([
            this.orm.call<PackageEntryJSON[]>("studio.workspace", "packages", []),
            this.orm.call<UserPrefsJSON>("studio.workspace", "user_prefs", []),
        ]);
        this.packages = packages;
        this.prefs = prefs || {};
        if (!this.packageId || !this.package) {
            const remembered = this.prefs.last_package_id;
            const candidates = [
                packages.find((p) => p.id === remembered),
                packages.find((p) => p.suggested),
                packages.find((p) => p.writable),
                packages[0],
            ];
            const chosen = candidates.find(Boolean);
            this.packageId = chosen ? chosen.id : false;
        }
        if (this.modelName) {
            await this._loadModelLabel();
        }
    }

    async refreshPackages(): Promise<void> {
        this.packages = await this.orm.call<PackageEntryJSON[]>("studio.workspace", "packages", []);
    }

    /**
     * The package's counters again, a moment after the last change:
     * several writes in a row ask once.
     */
    refreshChanges(): void {
        clearTimeout(this._changesTimer);
        this._changesTimer = setTimeout(() => {
            this.refreshPackages().catch(() => {});
        }, 800);
    }

    async _loadModelLabel(): Promise<void> {
        if (!this.modelName) {
            this.modelLabel = "";
            return;
        }
        const names = await this.orm.call<{ display_name?: string }[]>(
            "ir.model",
            "display_name_for",
            [[this.modelName]],
        );
        this.modelLabel = names[0]?.display_name || this.modelName;
    }

    async loadInventory(): Promise<unknown> {
        if (!this.packageId) {
            this.inventory = null;
            return null;
        }
        this.inventory = await this.orm.call("studio.workspace", "inventory", [this.packageId]);
        return this.inventory;
    }

    /**
     * What a view's editing context says the shell should know: the model
     * the view is of, whether a package defines it in Python, the package
     * to suggest when none is chosen, and the draft that may exist.
     */
    async learnContext(context: ShellLearnedContext): Promise<void> {
        this.learned = {
            python_owned: Boolean(context.python_owned),
            python_owner_id: context.python_owner_id || false,
        };
        // A Python-owned model can only be edited in the package that
        // defines it: the switcher follows, and says why.
        if (context.python_owner_id && context.python_owner_id !== this.packageId) {
            this.packageId = context.python_owner_id;
        } else if (!this.packageId && context.suggested_package_id) {
            this.packageId = context.suggested_package_id;
        }
        const model = context.view && context.view.model;
        if (model && model !== this.modelName) {
            this.modelName = model;
            await this._loadModelLabel();
        }
        // The view the server resolved when only a model or a type was
        // given: held here so the URL names it and a reload lands on it.
        if (context.view && context.view.id) {
            this.view = {
                view_id: context.view.id,
                view_type: context.view.type || this.view.view_type,
                res_id: this.view.res_id,
            };
        }
        this.draft.setHints(context);
        if (this.draft.draftId && !this.draft.draft) {
            await this.draft.load();
        }
    }

    // -- navigation ---------------------------------------------------------

    /**
     * Show a pane. Its model is made on first use and told to open or
     * reactivate; the URL follows; a refusal on the way -- a view that
     * does not resolve -- lands in `error` for this pane only, so the
     * bar and the other panes stay usable.
     */
    async openPane(key: string, patch: Record<string, unknown> = {}): Promise<void> {
        if (!paneRegistry.contains(key)) {
            key = "home";
        }
        const entry = resolvePane(key);
        if (!paneAvailable(entry, this.paneContext)) {
            key = "home";
        }
        this.pane = key;
        this.paneState = { ...patch };
        this.error = "";
        this.loading = true;
        try {
            const model = this.paneModel(key);
            if (model) {
                if (model.opened) {
                    await model.reactivate?.();
                } else {
                    await model.open(this.openTarget(key));
                    model.opened = true;
                }
            }
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                this.loading = false;
                throw err;
            }
            this.error = messageOf(err);
        }
        this.loading = false;
        this.pushUrl();
        this.setTitle();
    }

    /** What a pane model's `open` is handed. */
    openTarget(key: string): unknown {
        if (key === "views") {
            return { ...this.view, model: this.modelName };
        }
        return { model: this.modelName, packageId: this.packageId, ...this.paneState };
    }

    /** The pane's model, made once and kept while its scope holds. */
    paneModel(key: string): PaneModel | null {
        if (!this.paneModels[key]) {
            const entry = resolvePane(key);
            if (!entry.makeModel) {
                return null;
            }
            const model = entry.makeModel(this);
            model.opened = false;
            this.paneModels[key] = model;
        }
        return this.paneModels[key] || null;
    }

    /** Open a view of the model in hand on the Views pane. */
    async openView(target: OpenViewTarget): Promise<void> {
        const model = target.model || target.res_model;
        if (model && model !== this.modelName) {
            await this.setModel(model, { open: false });
        }
        this.view = {
            view_id: target.view_id || false,
            view_type: target.view_type || false,
            res_id: target.res_id || false,
        };
        const views = this.paneModels["views"];
        if (views) {
            // A new target: the model opens on it rather than reactivating.
            views.opened = false;
        }
        await this.openPane("views");
    }

    /** Switch the package in the top bar; everything package-scoped starts over. */
    async setPackage(packageId: number | false): Promise<void> {
        if (packageId === this.packageId) {
            return;
        }
        this.packageId = packageId;
        this.inventory = null;
        this._dropPaneModels("package");
        await this.rememberPref("last_package_id", packageId);
        const entry = this.activePane;
        if (entry && paneAvailable(entry, this.paneContext)) {
            await this.openPane(this.pane, this.paneState);
        } else {
            await this.openPane("home");
        }
    }

    /**
     * Change the model on the crumb. Model-scoped pane models start over;
     * the pane in hand is re-opened on the new model, or Home when it
     * cannot be shown without one.
     */
    async setModel(modelName: string, { open = true }: { open?: boolean } = {}): Promise<void> {
        if (modelName === this.modelName) {
            return;
        }
        this.modelName = modelName || "";
        this.learned = { python_owned: false, python_owner_id: false };
        this.draft.reset();
        this.view = { view_id: false, view_type: false, res_id: false };
        this._dropPaneModels("model");
        await this._loadModelLabel();
        if (modelName) {
            this.orm.call("studio.workspace", "remember_model", [modelName]).catch(() => {});
        }
        if (!open) {
            return;
        }
        const entry = this.activePane;
        if (entry && entry.scope === "model") {
            await this.openPane(this.pane);
        } else {
            this.pushUrl();
        }
    }

    _dropPaneModels(scope: "package" | "model"): void {
        for (const key of Object.keys(this.paneModels)) {
            const entry = paneRegistry.contains(key) ? resolvePane(key) : null;
            const paneScope = entry ? entry.scope : "model";
            if (scope === "package" && paneScope === "package") {
                delete this.paneModels[key];
            }
            if (scope === "model" && paneScope !== "package") {
                delete this.paneModels[key];
            }
        }
    }

    /** Pane-local state that belongs in the URL: a selected record. */
    setPaneState(patch: Record<string, unknown>): void {
        this.paneState = { ...this.paneState, ...patch };
        this.pushUrl();
    }

    // -- the url ------------------------------------------------------------

    /**
     * What the URL carries. `res_model` rather than `model`: the router
     * keeps `model` for a window action's path and drops it from a
     * client action's query. Keys absent from a pane are set to
     * `undefined`, which the router leaves out.
     */
    urlState(): ShellUrlState {
        const onViews = this.pane === "views";
        return {
            pane: this.pane,
            package_id: this.packageId || undefined,
            res_model: this.modelName || undefined,
            view_type: (onViews && this.view.view_type) || undefined,
            view_id: (onViews && this.view.view_id) || undefined,
            res_id: (onViews && this.view.res_id) || undefined,
            rec: this.paneState.rec || undefined,
        };
    }

    pushUrl(): void {
        if (this.hooks.pushState) {
            this.hooks.pushState(this.urlState());
        }
    }

    setTitle(): void {
        if (!this.hooks.setTitle) {
            return;
        }
        const entry = this.activePane;
        const parts = [String(_t("Studio"))];
        if (this.modelLabel && entry && entry.scope !== "package") {
            parts.push(this.modelLabel);
        }
        if (entry && entry.key !== "views") {
            parts.push(entry.label);
        } else if (this.view.view_type) {
            parts.push(this.view.view_type);
        }
        this.hooks.setTitle(parts.join(" · "));
    }

    // -- the draft and the package -------------------------------------------

    /** Apply the draft, then let the active pane read everything again. */
    async apply(allowDestructive = false): Promise<ApplyResult> {
        const result = await this.draft.apply(allowDestructive);
        if (result && result.ok) {
            const model = this.activeModel;
            if (model && model.afterApply) {
                await model.afterApply();
            }
            await this.refreshPackages();
        }
        return result;
    }

    /** Discard the draft, then let the active pane drop its ghosts. */
    async discard(): Promise<unknown> {
        const result = await this.draft.discard();
        const model = this.activeModel;
        if (result !== undefined && model && model.refresh) {
            await model.refresh();
        }
        return result;
    }

    async rememberPref(key: string, value: unknown): Promise<void> {
        this.prefs = { ...this.prefs, [key]: value };
        try {
            await this.orm.call("studio.workspace", "set_user_pref", [key, value]);
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
        }
    }

    // -- entry ----------------------------------------------------------------

    /**
     * One shape for every way in: the cog, the systray, `action_compose`,
     * the report editor's alias, the Studio menu, and a reload of the
     * console's own URL (the router state comes back as `action.params`).
     */
    static fromParams(raw: Record<string, unknown> | null | undefined): ShellParams {
        const params = raw || {};
        const view: ShellViewState = {
            view_id: (params["view_id"] as number | false) || false,
            view_type: (params["view_type"] as string | false) || false,
            res_id: (params["res_id"] as number | false) || false,
        };
        const pane =
            (params["pane"] as string) || (view.view_type || view.view_id ? "views" : "home");
        return {
            pane,
            package_id: (params["package_id"] as number | false) || false,
            res_model: (params["res_model"] as string) || (params["model"] as string) || "",
            view,
            rec: (params["rec"] as string | false) || false,
            entry: {
                opened_from: (params["opened_from"] as string) || "",
                previous_action: params["previous_action"] || null,
                previous_view_type: (params["previous_view_type"] as string | false) || false,
                action_id: (params["action_id"] as number | false) || false,
            },
        };
    }
}

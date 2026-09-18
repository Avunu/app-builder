/** @odoo-module **/
/**
 * Home: the package as a workspace.
 *
 * What the package is and how it is doing -- writable, drifted,
 * uncommitted, a failed apply with a rollback on offer -- then the five
 * things to do from here (build an app, adopt a model, open a view, edit
 * the menus, look at the changes), then the models the package defines
 * and the ones it touches, and the getting-started list until it is
 * dismissed. With no package yet, the create-package flow is the page.
 */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "../odoo";
import { messageOf } from "../shell/draft_model";
import { paneFlows, paneRegistry } from "../shell/pane_registry";
import type { OpenViewTarget, StudioShell } from "../shell/shell_model";
import { healthDot } from "../top_bar";
import { Flow, FlowModel } from "../flows/flow";
import "../flows/create_package_flow";
import type {
    FlowSpec,
    OdooRpcError,
    OrmService,
    PaneActivity,
    PaneModel,
    PaneRegistration,
} from "../types";
import type { PackageEntryJSON } from "../wire";

// -- the inventory (`studio.workspace.inventory()`) ------------------------
//
// `StudioShell.inventory` is deliberately typed `unknown` (`shell_model.ts`)
// -- nothing had a real shape to trace it against until this file, the
// first real reader anywhere in this tree. Traced directly from
// `app_builder_base/models/studio_workspace.py:inventory`/`_inventory_models`
// rather than guessed, and kept local here rather than promoted to
// `types.ts`/`wire.ts` -- the same "first real reader, kept local pending a
// second one" precedent `canvas.ts`'s own `CanvasModelEntry` and
// `changes_pane.ts`'s whole RPC surface already set.

/** One entry of every `inventory()` group except `models` -- a record the
 * package owns, grouped by what it is (`_inventory_group`). */
interface InventoryRecordEntry {
    id: number;
    model: string;
    /** The model the record is *about*, when the serializer names one
     * (`serializer._group_model`); `""` when it does not. */
    subject: string;
    xmlid: string;
    display_name: string;
    file: string | null;
}

/** One entry of `inventory()`'s own `models` list (`_inventory_models`). */
interface InventoryModelEntry {
    model: string;
    display_name: string;
    id: number | false;
    /** `row.source`, or `"extends"` when the row's own `extends` flag is
     * set (`_inventory_models`) -- the same four values
     * `studio_package_model.py`'s `source` field and this file's own
     * "extends" override between them ever produce. */
    source: "python" | "xml" | "frozen" | "extends";
    parse_error: string;
    python_path: string;
    in_registry: boolean;
    field_count: number;
    owned_field_count: number;
    views: string[];
    /** One count per other inventory group the model is touched through
     * (`INVENTORY_GROUPS`, minus `"models"` itself). */
    counts: Record<string, number>;
}

/** `inventory()`'s whole return: a dict built as `{key: [] for key in
 * INVENTORY_GROUPS}` then `groups["models"]` overwritten in place -- so
 * the real key order (and the order `Object.entries` would walk it in) is
 * `models` first, then every other group in `INVENTORY_GROUPS`' own
 * order. */
interface Inventory {
    models: InventoryModelEntry[];
    fields: InventoryRecordEntry[];
    views: InventoryRecordEntry[];
    actions: InventoryRecordEntry[];
    menus: InventoryRecordEntry[];
    automations: InventoryRecordEntry[];
    access: InventoryRecordEntry[];
    rules: InventoryRecordEntry[];
    approvals: InventoryRecordEntry[];
    reports: InventoryRecordEntry[];
    other: InventoryRecordEntry[];
}

/** `Inventory`'s own keys besides `models` -- `INVENTORY_GROUPS` with
 * `"models"` dropped, in its real order, named once so `extended` (below)
 * can walk them without an `Object.entries(inventory)` whose value type
 * would otherwise have to cover `models` too (`InventoryModelEntry[]` has
 * no `.subject`, unlike every one of these). */
const RECORD_GROUP_KEYS = [
    "fields",
    "views",
    "actions",
    "menus",
    "automations",
    "access",
    "rules",
    "approvals",
    "reports",
    "other",
] as const;

/** `models`' own row, with the badge/label the pane adds. */
interface ModelRow extends InventoryModelEntry {
    sourceLabel: ReturnType<typeof _t>;
    adoptable: boolean;
}

/** `extended`'s own row: a model the package touches without defining. */
interface TouchedModelEntry {
    model: string;
    counts: Record<string, number>;
}

const SOURCE_LABELS: Record<InventoryModelEntry["source"], ReturnType<typeof _t>> = {
    python: _t("Python"),
    frozen: _t("Python (code-owned)"),
    extends: _t("Extends"),
    xml: _t("data records"),
};

/** `shell.inventory`, cast to its real shape and `null` when nothing has
 * loaded one yet -- the one place this file downcasts the `unknown`
 * field, so every getter below reads a real `Inventory | null`. */
function inventoryOf(shell: StudioShell): Inventory | null {
    return (shell.inventory as Inventory | null) ?? null;
}

// -- the checklist (`studio.workspace.checklist()`) -------------------------

/** `checklist()`'s whole return (`studio_workspace.py:checklist`) -- one
 * boolean per getting-started step, always all five keys whether or not a
 * package is in hand. */
interface ChecklistJSON {
    package: boolean;
    app: boolean;
    field: boolean;
    automation: boolean;
    commit: boolean;
}

interface ChecklistItem {
    key: keyof ChecklistJSON;
    label: ReturnType<typeof _t>;
}

// -- the app builder's features (`studio.app.builder.features`/`add_feature`) --

/** One entry of `features()`'s own list (`scaffold.features_json()` plus
 * the per-feature extras `StudioAppBuilder.features` adds) -- `label`/
 * `help` are plain `str` on `scaffold.Feature` (literal strings at every
 * declaration site, not `_lt(...)`; unlike `catalogue.py`'s `Row.label`,
 * grepped before trusting it), never a lazy translation. */
interface FeatureEntry {
    key: string;
    label: string;
    help: string;
    default: boolean;
    views: string[];
    implies: string[];
    companion: string;
    offered: boolean;
}

/** `studio.app.builder.features()`'s whole return. */
interface FeaturesAnswer {
    features: FeatureEntry[];
    defaults: string[];
}

/** `studio.app.builder.add_feature()`'s whole return
 * (`studio_app_builder.py:add_feature`). Only `added` is read here; the
 * rest is typed fully anyway since it was traced from the real return,
 * the same "type the whole real answer, not just today's reads" choice
 * `changes_pane.ts`'s own `ChangesPayload` makes throughout. */
interface AddFeatureResult {
    draft_id: number;
    added: string[];
    already: string[];
    options: Record<string, unknown>;
    views: string[];
    chatter: boolean;
}

export class HomeModel implements PaneModel {
    shell: StudioShell;
    orm: OrmService;
    checklist: ChecklistJSON | null;
    busy: boolean;
    error: string;
    opened: boolean;
    // The create-package flow, hosted here on a first run.
    createFlow: FlowModel | null;
    /** The scaffold features the app builder offers, when it is
     * installed. Only ever assigned by `loadFeatures()` (never in the
     * constructor), so this stays `T | undefined` with no `!` -- true to
     * its real state before the first `open()`/`reactivate()` runs. */
    features?: FeatureEntry[];

    constructor(shell: StudioShell) {
        this.shell = shell;
        this.orm = shell.orm;
        this.checklist = null;
        this.busy = false;
        this.error = "";
        this.opened = false;
        this.createFlow = null;
    }

    get activity(): PaneActivity {
        return { busy: this.busy, status: "saved", error: "", drag: null, applying: false };
    }

    get history(): null {
        return null;
    }

    async open(): Promise<void> {
        await this.reactivate();
    }

    async reactivate(): Promise<void> {
        this.error = "";
        await this.shell.refreshPackages();
        if (!this.shell.packageId) {
            this.shell.inventory = null;
            this.checklist = null;
            return;
        }
        this.busy = true;
        try {
            const [, checklist] = await Promise.all([
                this.shell.loadInventory(),
                this.orm.call<ChecklistJSON>("studio.workspace", "checklist", [
                    this.shell.packageId,
                ]),
                this.loadFeatures(),
            ]);
            this.checklist = checklist;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.error = messageOf(err);
        } finally {
            this.busy = false;
        }
    }

    /**
     * The features a Python model of the package can still take on
     * (`studio.app.builder.features`), when the app builder is installed
     * -- it registers the build_app flow, which is how this addon, which
     * does not depend on it, knows.
     */
    async loadFeatures(): Promise<void> {
        if (this.features !== undefined) {
            return;
        }
        const builder = paneRegistry.contains("build_app");
        if (!builder) {
            this.features = [];
            return;
        }
        const answer = await this.orm.call<FeaturesAnswer>("studio.app.builder", "features", []);
        this.features = answer.features.filter((f) => f.offered);
    }

    /**
     * Stage a feature on a model the package defines in Python: fields and
     * model options on the draft, applied like any other change.
     */
    async addFeature(modelName: string, key: string): Promise<AddFeatureResult | undefined> {
        this.busy = true;
        this.error = "";
        try {
            const added = await this.orm.call<AddFeatureResult>(
                "studio.app.builder",
                "add_feature",
                [this.shell.packageId, modelName, key],
            );
            return added;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.shell.notification.add(messageOf(err), { type: "warning" });
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /** One call on the workspace about the package, then everything read again. */
    async act<T = unknown>(method: string, ...args: unknown[]): Promise<T | undefined> {
        this.busy = true;
        this.error = "";
        try {
            const result = await this.orm.call<T>("studio.workspace", method, [
                this.shell.packageId,
                ...args,
            ]);
            await this.reactivate();
            return result;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.error = messageOf(err);
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /** The create-package flow, made once. */
    get firstRun(): FlowModel {
        if (!this.createFlow) {
            // `Registry.get`'s own JSDoc leaves `defaultValue` undocumented
            // (so TS infers it as required) -- the identical trap
            // `pane_registry.ts`'s own `resolvePane` already hit and fixed
            // the same way: a cast to a one-argument-capable signature,
            // `.call`ed with `paneRegistry` as `this` since the real
            // `get()` reads `this.content`.
            const entry = (paneRegistry.get as (key: string) => PaneRegistration).call(
                paneRegistry,
                "create_package",
            );
            // Every real "create_package" registration sets `flow`
            // (`flows/create_package_flow.ts`'s own `paneRegistry.add`);
            // `PaneRegistration.flow` is optional only because not every
            // kind of pane has one, not because this one might not.
            this.createFlow = new FlowModel(this.shell, entry.flow as FlowSpec);
        }
        return this.createFlow;
    }
}

/** The flags `summaryOf` (below) checks, worst first -- a fixed subset of
 * `HEALTH_LINES`' own keys. */
const WORST_HEALTH_ORDER = [
    "read_only",
    "missing",
    "failed_apply",
    "drifted",
    "restart_required",
    "pending",
    "uncommitted",
] as const;

const HEALTH_LINES: Record<string, () => ReturnType<typeof _t>> = {
    read_only: () => _t("Read-only · the directory cannot be written"),
    missing: () => _t("Files missing on disk"),
    not_installed: () => _t("Not installed · Odoo has not loaded this module yet"),
    failed_apply: () => _t("Last apply failed · a rollback is available"),
    restart_required: () => _t("Restart to load · files were written that only a restart can load"),
    drifted: () => _t("Files edited on disk"),
    pending: () => _t("Changes pending on a model"),
    pending_write: () => _t("Pending write"),
    uncommitted: () => _t("Uncommitted changes"),
    no_git: () => _t("Not a git repository"),
    manual_reload: () => _t("Restart to apply · this server runs workers"),
};

interface HealthAction {
    label: ReturnType<typeof _t>;
    pane?: string | null;
    method?: string;
}

const HEALTH_ACTIONS: Record<string, HealthAction> = {
    not_installed: { label: _t("Install it"), pane: null, method: "reload" },
    failed_apply: { label: _t("Roll back…"), pane: "changes" },
    restart_required: { label: _t("See what is waiting"), pane: "changes" },
    drifted: { label: _t("Review"), pane: "changes" },
    missing: { label: _t("Write to disk"), method: "write_files" },
    pending_write: { label: _t("Write to disk"), method: "write_files" },
    pending: { label: _t("Apply…"), pane: "changes" },
    uncommitted: { label: _t("Commit"), pane: "changes" },
    no_git: { label: _t("Initialise git…"), method: "git_init" },
};

const FLAG_DOT: Record<string, string> = {
    read_only: "grey",
    no_git: "grey",
    manual_reload: "grey",
    missing: "red",
    failed_apply: "red",
    drifted: "red",
};

const CHECKLIST: ChecklistItem[] = [
    { key: "package", label: _t("Create a package") },
    { key: "app", label: _t("Build an app") },
    { key: "field", label: _t("Add a field") },
    { key: "automation", label: _t("Automate something") },
    { key: "commit", label: _t("Commit") },
];

/** One package in the crumb-less package cards: the package entry plus its
 * health dot and whether it is the one in hand. */
interface PackageCard extends PackageEntryJSON {
    dot: string;
    active: boolean;
    summaryLine: ReturnType<typeof _t>;
}

/** One row of `health`: a flag with its label and what to do about it. */
interface HealthRow {
    flag: string;
    label: ReturnType<typeof _t> | string;
    action: HealthAction | null;
    dot: string;
}

/** One tile of `tiles`: a thing to do from Home. */
interface TileEntry {
    key: string;
    label: ReturnType<typeof _t>;
    icon: string;
    hint: ReturnType<typeof _t>;
    enabled: boolean;
    reason: ReturnType<typeof _t> | string;
    run: () => void;
}

interface HomePaneState {
    modelSearch: string;
}

interface Props {
    shell: StudioShell;
    model: HomeModel;
}

export class HomePane extends Component<Props> {
    // `template`/`props` are both declared on Owl's own `Component` base
    // class, so `noImplicitOverride` requires `override` here; `components`
    // is not a `Component` class-body member (only of the separate
    // `StaticComponentProperties`/`ComponentConstructor` helper types), so
    // it takes no `override` (TYPING.md's own "Known traps").
    static override template = "app_builder_view.HomePane";
    static components = { Flow };
    static override props = { shell: Object, model: { type: Object, optional: true } };

    /** Assigned in `setup()`, which Owl calls synchronously right after
     * construction and before the first render -- always set by the time
     * any getter or template read runs. */
    shell!: StudioShell;
    model!: HomeModel;
    orm!: OrmService;
    state!: HomePaneState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.orm = useService("orm");
        this.state = useState<HomePaneState>({ modelSearch: "" });
    }

    get package(): PackageEntryJSON | null {
        return this.shell.package;
    }

    get packages(): PackageCard[] {
        return this.shell.packages.map((info) => ({
            ...info,
            dot: healthDot(info),
            active: info.id === this.shell.packageId,
            summaryLine: this.summaryOf(info),
        }));
    }

    summaryOf(info: PackageEntryJSON): ReturnType<typeof _t> {
        const flags = info.health || [];
        const worst = WORST_HEALTH_ORDER.find((f) => flags.includes(f));
        if (!worst) {
            return _t("in sync");
        }
        // `worst` only ever comes from `WORST_HEALTH_ORDER`, a fixed list
        // of `HEALTH_LINES`' own keys -- an invariant
        // `noUncheckedIndexedAccess` cannot see through a plain
        // `Record<string, ...>`, the same shape of gap `flow.ts`'s own
        // `get step()` already has a `!` for.
        return HEALTH_LINES[worst]!();
    }

    get firstRun(): boolean {
        return !this.shell.packages.length;
    }

    get noneWritable(): boolean {
        return this.shell.packages.length > 0 && !this.shell.packages.some((p) => p.writable);
    }

    /** The health line: the worst things first, each with what to do. */
    get health(): HealthRow[] {
        const info = this.package;
        if (!info) {
            return [];
        }
        const order = Object.keys(HEALTH_LINES);
        return (info.health || [])
            .slice()
            .sort((a, b) => order.indexOf(a) - order.indexOf(b))
            .map((flag): HealthRow => {
                // Repeated-bracket-index trap: `HEALTH_LINES[flag]` is read
                // once here and reused, rather than indexed twice (once to
                // test, once to call).
                const line = HEALTH_LINES[flag];
                return {
                    flag,
                    label: line ? line() : flag,
                    action: HEALTH_ACTIONS[flag] || null,
                    dot: FLAG_DOT[flag] || "amber",
                };
            });
    }

    get healthy(): boolean {
        const info = this.package;
        return (
            Boolean(info) &&
            !this.health.some((h) => h.flag !== "no_git" && h.flag !== "manual_reload")
        );
    }

    get gitLine(): string {
        const info = this.package;
        if (!info || !info.git.is_git) {
            return "";
        }
        const dirty = info.git.dirty + info.git.untracked;
        return dirty
            ? String(_t("⎇ %s · %s uncommitted", info.git.branch, dirty))
            : String(_t("⎇ %s · nothing to commit", info.git.branch));
    }

    async onHealthAction(entry: HealthRow): Promise<void> {
        const action = entry.action;
        if (!action) {
            return;
        }
        if (action.pane) {
            await this.shell.openPane(action.pane);
            return;
        }
        if (action.method) {
            await this.model.act(action.method);
        }
    }

    // -- tiles ---------------------------------------------------------------

    get tiles(): TileEntry[] {
        const flows = paneFlows(this.shell.paneContext);
        const writable = this.shell.packageWritable;
        const has = (key: string): boolean => flows.some((f) => f.key === key);
        // `TileEntry.run: () => void`, each opening a pane with a Promise
        // this file has nowhere to await -- `void`-wrapped in a block body
        // rather than left as an expression-bodied arrow's implicit
        // return, matching `record_pane.ts`'s own identical "duplicate"
        // tile (its "remove" tile's own `run: () => this.onRemove(row)`
        // stays a bare expression there only because `onRemove` itself
        // returns `void`, not a `Promise`, unlike every `run` here).
        return [
            {
                key: "build_app",
                label: _t("Build an app"),
                icon: "fa fa-cubes",
                hint: _t("A model, its views, menu and access"),
                enabled: writable && has("build_app"),
                reason: !writable ? _t("The package is read-only.") : "",
                run: () => {
                    void this.shell.openPane("build_app");
                },
            },
            {
                key: "adopt_model",
                label: _t("Adopt a model"),
                icon: "fa fa-download",
                hint: _t("Bring a hand-made x_ model under Python"),
                enabled: writable && has("adopt_model"),
                reason: !writable ? _t("The package is read-only.") : "",
                run: () => {
                    void this.shell.openPane("adopt_model");
                },
            },
            {
                key: "open_view",
                label: _t("Open a view"),
                icon: "fa fa-pencil-square-o",
                hint: _t("Any model, any view"),
                enabled: true,
                reason: "",
                run: () => {
                    void this.shell.openPane("open_view");
                },
            },
            {
                key: "menu",
                label: _t("Edit menus"),
                icon: "fa fa-bars",
                hint: _t("The apps this package owns"),
                enabled: paneRegistry.contains("menu"),
                reason: paneRegistry.contains("menu") ? "" : _t("Install app_builder_ui."),
                run: () => {
                    void this.shell.openPane("menu");
                },
            },
            {
                key: "changes",
                label: _t("Changes"),
                icon: "fa fa-code-fork",
                hint: this.shell.changesCount
                    ? _t("%s to look at", this.shell.changesCount)
                    : _t("Nothing pending"),
                enabled: true,
                reason: "",
                run: () => {
                    void this.shell.openPane("changes");
                },
            },
        ];
    }

    // -- models ---------------------------------------------------------------

    get models(): ModelRow[] {
        const inventory = inventoryOf(this.shell);
        const term = this.state.modelSearch.toLowerCase();
        const rows = (inventory ? inventory.models : []).filter(
            (m) => !term || m.model.includes(term) || m.display_name.toLowerCase().includes(term),
        );
        return rows.map((m) => ({
            ...m,
            sourceLabel: SOURCE_LABELS[m.source],
            adoptable: m.source === "xml",
        }));
    }

    /** Models the package touches without defining: from the picker's lists. */
    get extended(): TouchedModelEntry[] {
        const inventory = inventoryOf(this.shell);
        if (!inventory) {
            return [];
        }
        const defined = new Set(inventory.models.map((m) => m.model));
        const touched: Record<string, TouchedModelEntry> = {};
        for (const key of RECORD_GROUP_KEYS) {
            for (const entry of inventory[key]) {
                if (!entry.subject || defined.has(entry.subject)) {
                    continue;
                }
                const subject = entry.subject;
                const row = touched[subject] ?? { model: subject, counts: {} };
                row.counts[key] = (row.counts[key] || 0) + 1;
                touched[subject] = row;
            }
        }
        return Object.values(touched).sort((a, b) => a.model.localeCompare(b.model));
    }

    countsLine(counts: Record<string, number>): string {
        const parts: string[] = [];
        const labels: Record<string, ReturnType<typeof _t>> = {
            fields: _t("field"),
            views: _t("view"),
            automations: _t("automation"),
            rules: _t("rule"),
            reports: _t("report"),
            approvals: _t("approval"),
            menus: _t("menu"),
            access: _t("access line"),
        };
        for (const [key, label] of Object.entries(labels)) {
            const n = counts[key] || 0;
            if (n) {
                parts.push(n === 1 ? `1 ${label}` : `${n} ${label}s`);
            }
        }
        return parts.join(" · ");
    }

    async onOpenModel(entry: { model: string }): Promise<void> {
        await this.shell.openView({ model: entry.model });
    }

    /** Never called from `home_pane.xml` -- no `t-on-click` (or anything
     * else) reaches it anywhere in this tree (checked with a tree-wide
     * grep before trusting that). Kept as-is, unused, exactly as the
     * original JS had it; not this migration's job to remove dead code. */
    async onModelFields(entry: { model: string }): Promise<void> {
        await this.shell.openView({ model: entry.model, view_type: "form" });
    }

    async onAdopt(entry: { model: string }): Promise<void> {
        await this.shell.setModel(entry.model, { open: false });
        await this.shell.openPane("adopt_model", { model: entry.model });
    }

    /** The features a row offers: the builder's, on a model written in Python. */
    featuresFor(entry: ModelRow): FeatureEntry[] {
        if (entry.source !== "python" || !this.shell.packageWritable) {
            return [];
        }
        return this.model.features || [];
    }

    /** A feature chosen on a model row: staged, then the form shows the ghosts. */
    async onAddFeature(entry: ModelRow, ev: Event): Promise<void> {
        const target = ev.target as HTMLSelectElement;
        const key = target.value;
        target.value = "";
        if (!key) {
            return;
        }
        const added = await this.model.addFeature(entry.model, key);
        if (!added) {
            return;
        }
        const count = (added.added || []).length;
        this.shell.notification.add(
            count
                ? String(
                      _t("%s staged on %s: apply from the Views pane.", count, entry.display_name),
                  )
                : String(_t("%s already has that.", entry.display_name)),
            { type: "info" },
        );
        // The Views pane learns the draft from the editing context it
        // loads on open; the form then shows the staged fields as ghosts.
        await this.shell.openView({ model: entry.model, view_type: "form" });
    }

    // -- checklist ------------------------------------------------------------

    get checklist(): (ChecklistItem & { done: boolean })[] {
        const done = this.model.checklist;
        if (!done || this.shell.prefs.checklist_dismissed) {
            return [];
        }
        return CHECKLIST.map((item) => ({ ...item, done: Boolean(done[item.key]) }));
    }

    dismissChecklist(): void {
        void this.shell.rememberPref("checklist_dismissed", true);
    }
}

paneRegistry.add(
    "home",
    {
        // `PaneRegistration.label` is a plain, required `string`
        // (`shell_model.ts:setTitle` pushes it straight into a
        // `string[]`), never the `string | Markup | LazyTranslatedString`
        // union `_t()` itself returns -- the same `String(_t(...))`
        // pattern every other converted pane registration already uses
        // (`changes_pane.ts`, `create_package_flow.ts`).
        label: String(_t("Home")),
        icon: "fa fa-home",
        scope: "package",
        Component: HomePane,
        sidebar: null,
        // `PaneRegistration.makeModel` is a *property* typed as an arrow
        // function, not a method-shorthand signature, so it is checked
        // contravariantly under `strictFunctionTypes` -- `HomeModel`'s
        // constructor keeps taking the real `StudioShell` (matching
        // `record_pane_model.ts`/`changes_pane.ts`'s own precedent) and
        // the cast happens here instead, inside a wrapper whose own
        // parameter is left unannotated so TS infers it as the target
        // property's `unknown` from context.
        makeModel: (shell) => new HomeModel(shell as StudioShell),
    },
    { sequence: 0 },
);

// Open a view: a model, then the Views pane on it.

/** One value `pick()` sets on the flow's own `values` bag. */
interface OpenViewValues {
    model?: string;
    label?: string;
}

/** A model this step offers: from `shell.inventory` (defined here) or from
 * `ir.model` (matched here). */
interface OpenViewSuggestion {
    model: string;
    display_name: string;
}

interface OpenViewStepProps {
    shell: StudioShell;
    flow: { values: OpenViewValues };
}

class OpenViewStep extends Component<OpenViewStepProps> {
    static override template = "app_builder_view.OpenViewStep";
    static override props = { shell: Object, flow: Object };

    shell!: StudioShell;
    flow!: { values: OpenViewValues };
    orm!: OrmService;
    state!: { term: string; matches: OpenViewSuggestion[] };

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState<{ term: string; matches: OpenViewSuggestion[] }>({
            term: "",
            matches: [],
        });
    }

    get suggestions(): OpenViewSuggestion[] {
        const inventory = inventoryOf(this.shell);
        return (inventory ? inventory.models : []).map((m) => ({
            model: m.model,
            display_name: m.display_name,
        }));
    }

    async onSearch(ev: InputEvent): Promise<void> {
        const target = ev.target as HTMLInputElement;
        const term = (target.value || "").trim();
        this.state.term = term;
        if (term.length < 2) {
            this.state.matches = [];
            return;
        }
        const rows = await this.orm.searchRead<{ model: string; name: string }>(
            "ir.model",
            ["|", ["name", "ilike", term], ["model", "ilike", term], ["transient", "=", false]],
            ["model", "name"],
            { limit: 12 },
        );
        if (this.state.term === term) {
            this.state.matches = rows.map((r) => ({ model: r.model, display_name: r.name }));
        }
    }

    pick(entry: OpenViewSuggestion): void {
        this.flow.values.model = entry.model;
        this.flow.values.label = entry.display_name;
    }
}

/** The one `shell` member `onDone` (below) actually calls -- the same
 * narrow-owner-interface idea `create_package_flow.ts`'s own `FlowShell`
 * already uses for the identical situation; the real `StudioShell`
 * satisfies this structurally with no change on its own side. */
interface OpenViewShell {
    openView(target: OpenViewTarget): Promise<void>;
}

paneRegistry.add("open_view", {
    // Wrapped with `String(...)` throughout this registration, the same
    // "worth doing consistently, not only where the type forces it" choice
    // `create_package_flow.ts`'s own registration already made for the
    // identical `label`/`title`/`doneLabel`/step-`label` shapes.
    label: String(_t("Open a view")),
    icon: "fa fa-pencil-square-o",
    scope: "package",
    tab: false,
    flow: {
        key: "open_view",
        title: String(_t("Open a view")),
        doneLabel: String(_t("Open")),
        steps: [
            {
                key: "model",
                label: String(_t("Model")),
                Component: OpenViewStep,
                validate: (values: OpenViewValues): string =>
                    values.model ? "" : String(_t("Pick a model.")),
            },
        ],
        onDone: async (shell: OpenViewShell, flow: { values: OpenViewValues }): Promise<void> => {
            // `validate` (above) already refused to let the flow finish
            // without `values.model` set -- an invariant this call cannot
            // see across the flow's own control flow, the same shape of
            // traced-but-uncheckable guarantee `HomeModel.firstRun`'s own
            // `entry.flow as FlowSpec` relies on just above.
            await shell.openView({ model: flow.values.model as string });
        },
    },
});

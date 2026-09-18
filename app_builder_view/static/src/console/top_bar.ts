/** @odoo-module **/
/**
 * The top bar: where you are, what else the console can open, and the
 * buttons that matter -- Undo, Redo, Close -- with the status pill and
 * the Changes badge between them.
 *
 * Where you are is `package › model › view`: the package is a switcher
 * over the workspaces the studio has, the model a picker over what the
 * package defines and touches, the view a label on the Views pane. The
 * tabs are the panes of `app_builder.panes`, in sequence; a pane that
 * needs a model is dimmed with the reason rather than hidden, so the bar
 * reads the same on every pane.
 *
 * Undo and Redo show when the active pane keeps a history -- the Views
 * pane does -- and name the change and its author in their tooltips,
 * because the stack is per view, not per user, and taking back somebody
 * else's edit should be a decision rather than a surprise.
 *
 * The pill is package-wide: on a Python-owned model it counts what is
 * staged -- "2 pending · Apply" -- on every pane, and is the way to the
 * Apply dialog, with a Discard beside it. The badge beside it counts what
 * has accumulated -- pending fields, drifted files, failed applies -- and
 * opens the Changes pane.
 */

import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog, useService } from "./odoo";
import type { DialogService } from "./odoo";
import { ApplyDialog } from "./apply_dialog";
import { paneTabs } from "./shell/pane_registry";
import type { PaneTab } from "./shell/pane_registry";
import type { ConsoleModel } from "./console_model";
import type { StudioShell } from "./shell/shell_model";
import type { OrmService, HistoryEntry } from "./types";
import type { AddableViewTypeEntry, PackageEntryJSON, ViewOfEntry } from "./wire";

/** `{shell, onClose}`, as `static props` below validates it: the shell in
 * hand (read live through `useState`, same object the rest of the console
 * shares) and the host's own way to dismiss the console. */
interface Props {
    shell: StudioShell;
    onClose: () => void;
}

/** `models_for_picker`'s own per-row shape (`studio_workspace.py`), the
 * same three keys whichever of `defined`/`extended`/`recent` a row comes
 * from -- `source`/`count` are only ever set on `defined`/`extended`
 * rows respectively, never read by this file itself (only by the
 * template), so both stay optional on one shared shape rather than three
 * near-identical ones. Also `state.modelMatches`'s own row shape
 * (`onModelSearch`, below), which never sets either. */
interface ModelPickerEntry {
    model: string;
    display_name: string;
    source?: string;
    count?: number;
}

/** `models_for_picker`'s whole return (`studio_workspace.py:
 * models_for_picker`). */
interface ModelPicker {
    defined: ModelPickerEntry[];
    extended: ModelPickerEntry[];
    recent: ModelPickerEntry[];
}

/** The top bar's own local state -- the model search box and the picker
 * it opens with (`loadPicker`, below). */
interface TopBarState {
    modelSearch: string;
    modelMatches: ModelPickerEntry[];
    picker: ModelPicker | null;
}

/** A resolved pane tab (`shell/pane_registry.ts:paneTabs`) plus whether
 * it is the one currently open. */
interface TopBarTab extends PaneTab {
    active: boolean;
}

/** One package in the crumb's dropdown: the package entry plus its health
 * dot and whether it is the one in hand. */
interface PackageTab extends PackageEntryJSON {
    dot: string;
    active: boolean;
}

/** One tile the view switcher offers: an existing view of the model, or
 * a kind it could still add. `view`/`active` are only ever set on the
 * former, `add` only on the latter -- `onSwitch`'s own two-way branch,
 * below, reads exactly that split. */
interface SwitcherEntry {
    key: string;
    type: string;
    label: string;
    icon: string;
    active?: boolean;
    view?: ViewOfEntry;
    add?: AddableViewTypeEntry;
}

/** What the status pill shows. */
interface StatusInfo {
    cls: string;
    label: string;
    tooltip: string;
}

/** `PaneActivity.drag` is `unknown` in `types.ts` -- most pane models
 * never set it. The only real shape a pane ever puts there is
 * `console_model.ts`'s own private `DragState` (`{label, caption}`, set
 * by `beginDrag`/`setDragCaption`); not exported, so named again here
 * structurally rather than imported, the same downcast-by-tracing
 * reasoning `apply_dialog.ts`'s own `views` getter already documents for
 * `shell.activeModel`. */
interface DragStatus {
    label: string;
    caption: string;
}

// The icons `ir.ui.view.get_view_info` returns for core's own types, for a
// view the switcher shows before the addable list has been fetched.
const VIEW_ICONS: Record<string, string> = {
    list: "oi oi-view-list",
    form: "fa fa-address-card",
    kanban: "oi oi-view-kanban",
    calendar: "fa fa-calendar",
    pivot: "oi oi-view-pivot",
    graph: "fa fa-area-chart",
    activity: "fa fa-clock-o",
    search: "oi oi-search",
    qweb: "fa fa-file-text-o",
};

const HEALTH_DOT: Record<string, string> = {
    read_only: "grey",
    missing: "red",
    failed_apply: "red",
    drifted: "red",
    restart_required: "amber",
    pending: "amber",
    pending_write: "amber",
    uncommitted: "amber",
    not_installed: "amber",
};

/** The colour a package's health dot takes: the worst thing wins.
 * `info` stays `| null | undefined`, matching this function's own
 * defensive `info &&` read below -- `home_pane.js` (still untyped) is a
 * second real caller besides this file's own two, so nothing here
 * asserts a stronger guarantee than the function's own body already
 * relies on. */
export function healthDot(info: PackageEntryJSON | null | undefined): string {
    const flags = (info && info.health) || [];
    if (flags.some((f) => HEALTH_DOT[f] === "red")) {
        return "red";
    }
    if (flags.includes("read_only")) {
        return "grey";
    }
    if (flags.some((f) => HEALTH_DOT[f] === "amber")) {
        return "amber";
    }
    return "green";
}

// Selectors an undo hotkey must not reach into: an editor with a history
// of its own.
const EDITABLE_TARGET = ".ace_editor, input, textarea, select, [contenteditable]";

export class TopBar extends Component<Props> {
    // `template`/`props` are both declared on Owl's own `Component` base
    // class, so `noImplicitOverride` requires `override` here; `components`
    // is not a `Component` class-body member (only of the separate
    // `StaticComponentProperties`/`ComponentConstructor` helper types), so
    // it takes no `override` (TYPING.md's own "Known traps").
    static override template = "app_builder_view.TopBar";
    static components = { Dropdown, DropdownItem };
    static override props = {
        shell: Object,
        onClose: Function,
    };

    // Assigned in `setup()`, not a field initializer or a constructor this
    // class writes its own -- `declare` adds a compile-time type only, so
    // the emitted `.js` is unchanged and `strictPropertyInitialization`
    // does not ask for an assignment it cannot see (the same pattern
    // `apply_dialog.ts` already uses).
    declare shell: StudioShell;
    declare dialog: DialogService;
    declare orm: OrmService;
    declare state: TopBarState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.state = useState<TopBarState>({ modelSearch: "", modelMatches: [], picker: null });
        // `useHotkey`'s own callback (`HotkeyCallback`,
        // `hotkey_service.js`) is documented as `(context: {area:
        // HTMLElement, target: EventTarget}) => void` -- but the real
        // dispatch (`hotkey_service.js:dispatch`) builds `target` from a
        // live `KeyboardEvent`'s own `.target`, which lib.dom types
        // `EventTarget | null`: the same JSDoc-vs-runtime nullability gap
        // TYPING.md's "Known traps" already tracks elsewhere (there for a
        // vendor JSDoc typing a parameter required that the real call site
        // treats as optional; here for a field typed non-null that the
        // real value backing it can be null). Typed to the traced-real
        // shape rather than the JSDoc's own optimistic one; only `target`
        // is read here, so the parameter names nothing else.
        const guarded =
            (run: () => void) =>
            (ev: { target: EventTarget | null }): void => {
                // Known-trap fix (d): `ev.target` is `EventTarget | null`,
                // not `Element` -- narrow before calling a DOM method.
                // `ev` itself is never falsy in a real dispatch (always a
                // literal `{area, target}`), so the original `ev &&` guard
                // is not carried over.
                const target = ev.target instanceof Element ? ev.target : null;
                if (target && target.closest(EDITABLE_TARGET)) {
                    return;
                }
                run();
            };
        useHotkey(
            "control+z",
            guarded(() => this.onUndo()),
        );
        useHotkey(
            "control+shift+z",
            guarded(() => this.onRedo()),
        );
        useHotkey(
            "control+y",
            guarded(() => this.onRedo()),
        );
    }

    // -- the package ---------------------------------------------------------

    get packages(): PackageTab[] {
        return this.shell.packages.map((info) => ({
            ...info,
            dot: healthDot(info),
            active: info.id === this.shell.packageId,
        }));
    }

    get packageLabel(): string {
        const info = this.shell.package;
        return String(info ? info.name : _t("No package"));
    }

    get packageDot(): string {
        return this.shell.package ? healthDot(this.shell.package) : "grey";
    }

    /** A Python-owned model is edited in the package that defines it. */
    get packagePinned(): boolean {
        return Boolean(this.shell.learned.python_owner_id);
    }

    get packagePinnedReason(): string {
        return String(
            _t(
                "%s is defined by %s, so its fields can only change there. Pick another model to switch.",
                this.shell.modelLabel || this.shell.modelName,
                this.packageLabel,
            ),
        );
    }

    onPackage(info: PackageTab): void {
        if (!info.active && !this.packagePinned) {
            void this.shell.setPackage(info.id);
        }
    }

    onNewPackage(): void {
        void this.shell.openPane("create_package");
    }

    // -- the model -----------------------------------------------------------

    get modelLabel(): string {
        return this.shell.modelLabel || this.shell.modelName || "";
    }

    /** The picker's lists, read when it opens. */
    async loadPicker(): Promise<void> {
        this.state.picker = await this.orm.call<ModelPicker>(
            "studio.workspace",
            "models_for_picker",
            [this.shell.packageId || false],
        );
    }

    async onModelSearch(ev: Event): Promise<void> {
        const term = ((ev.target as HTMLInputElement).value || "").trim();
        this.state.modelSearch = term;
        if (term.length < 2) {
            this.state.modelMatches = [];
            return;
        }
        const rows = await this.orm.searchRead<{ model: string; name: string }>(
            "ir.model",
            ["|", ["name", "ilike", term], ["model", "ilike", term], ["transient", "=", false]],
            ["model", "name"],
            { limit: 12 },
        );
        if (this.state.modelSearch === term) {
            this.state.modelMatches = rows.map((r) => ({ model: r.model, display_name: r.name }));
        }
    }

    async onModel(entry: ModelPickerEntry): Promise<void> {
        if (entry.model !== this.shell.modelName) {
            await this.shell.setModel(entry.model);
        }
        if (this.shell.pane === "home") {
            await this.shell.openView({ model: entry.model });
        }
    }

    onBuildApp(): void {
        void this.shell.openPane("build_app");
    }

    onAdoptModel(): void {
        void this.shell.openPane("adopt_model");
    }

    get canBuild(): boolean {
        return this.shell.packageWritable;
    }

    // -- the panes -----------------------------------------------------------

    get tabs(): TopBarTab[] {
        return paneTabs(this.shell.paneContext).map((tab) => ({
            ...tab,
            active: tab.key === this.shell.pane,
        }));
    }

    openTab(tab: TopBarTab): void {
        if (!tab.available || tab.active) {
            return;
        }
        void this.shell.openPane(tab.key);
    }

    get onViews(): boolean {
        return this.shell.pane === "views";
    }

    /**
     * The Views pane's own model, when it is on. `shell.activeModel` is
     * typed to the generic `PaneModel` contract every pane satisfies
     * (`shell_model.ts`); the real object it holds whenever
     * `pane === "views"` is always a `ConsoleModel` (`views_pane.js`'s own
     * registration is the one thing that ever puts something there under
     * that key) -- the identical downcast `apply_dialog.ts`'s own `views`
     * getter already makes for this same field.
     */
    get viewsModel(): ConsoleModel | null {
        return this.onViews ? (this.shell.activeModel as ConsoleModel | null) : null;
    }

    get viewTypeLabel(): string {
        const model = this.viewsModel;
        const type = (model && model.viewType) || this.shell.view.view_type || "";
        const known = ((model && model.addable) || []).find((entry) => entry.type === type);
        return String((known && known.label) || VIEW_TYPE_LABELS[type] || type);
    }

    /** The model's views, then the types the builder could still add. */
    get switcher(): SwitcherEntry[] {
        const model = this.viewsModel;
        if (!model || !model.context) {
            return [];
        }
        // `model.context` is narrowed non-null by the guard above (a
        // plain field read straight back with nothing intervening); the
        // original's own `|| {}` fallback is dropped rather than kept as
        // `EditingContext | {}`, which would lose `.views` on the empty
        // branch -- the branch was never reachable, only ever there as
        // defensive JS style.
        const context = model.context;
        const current = model.viewId;
        const addable = model.addable || [];
        const iconOf = (type: string): string => {
            const entry = addable.find((e) => e.type === type);
            return (entry && entry.icon) || VIEW_ICONS[type] || "fa fa-square-o";
        };
        const existing: SwitcherEntry[] = (context.views || []).map((view) => ({
            key: `view-${view.view_id}`,
            type: view.type,
            label: view.name,
            icon: iconOf(view.type),
            active: view.view_id === current,
            view,
        }));
        const present = new Set(existing.map((entry) => entry.type));
        const creatable: SwitcherEntry[] = addable
            .filter((entry) => entry.enabled && !present.has(entry.type))
            .map((entry) => ({
                key: `add-${entry.type}`,
                type: entry.type,
                label: String(_t("Add a %s view", entry.label || entry.type)),
                icon: iconOf(entry.type),
                add: entry,
            }));
        return [...existing, ...creatable];
    }

    onSwitch(entry: SwitcherEntry): void {
        const model = this.viewsModel;
        if (entry.view) {
            if (!entry.active) {
                void this.shell.openView({
                    view_id: entry.view.view_id,
                    view_type: entry.view.type,
                    res_id: this.shell.view.res_id,
                });
            }
        } else if (entry.add && model) {
            void model.addView(entry.add);
        }
    }

    // -- undo / redo ----------------------------------------------------------

    /**
     * `StudioShell.history` is `unknown` (any pane model may or may not
     * have one); the only real shape a pane ever puts there is
     * `console_model.ts`'s own `{undo, redo}` getter (`HistoryEntry[]`
     * each) -- `record_pane_model.ts`'s own `history` getter returns
     * `null` instead of a differently-shaped object, never something this
     * downcast would misread. Same tracing-a-real-shape-through-`unknown`
     * reasoning as `status`'s own `drag`, below.
     */
    get history(): { undo: HistoryEntry[]; redo: HistoryEntry[] } | null {
        return this.shell.history as { undo: HistoryEntry[]; redo: HistoryEntry[] } | null;
    }

    get undoEntry(): HistoryEntry | null {
        const history = this.history;
        return (history && history.undo[0]) || null;
    }

    get redoEntry(): HistoryEntry | null {
        const history = this.history;
        return (history && history.redo[0]) || null;
    }

    get undoTooltip(): string {
        const entry = this.undoEntry;
        return String(
            entry
                ? _t("Undo: %(summary)s · by %(author)s", {
                      summary: entry.summary,
                      author: entry.author,
                  })
                : _t("Nothing to undo"),
        );
    }

    get redoTooltip(): string {
        const entry = this.redoEntry;
        return String(
            entry
                ? _t("Redo: %(summary)s · by %(author)s", {
                      summary: entry.summary,
                      author: entry.author,
                  })
                : _t("Nothing to redo"),
        );
    }

    get busy(): boolean {
        return this.shell.activity.busy;
    }

    onUndo(): void {
        // `shell_model.ts` itself never reads `.undo`/`.redo` off
        // `activeModel` (only `.history`), so `PaneModel` -- traced only
        // from that file's own reads, per its doc comment -- has no
        // business naming either: `undo`/`redo` are `console_model.ts`'s
        // own real methods, and `this.undoEntry` being truthy already
        // proves `activeModel` is that `ConsoleModel` right now (only it
        // ever produces a non-null `history`) -- the same
        // invariant-by-a-different-observable `apply_dialog.ts`'s own
        // `views` getter downcasts on via `pane === "views"`.
        const model = this.shell.activeModel as ConsoleModel | null;
        if (this.undoEntry && !this.busy && model && model.undo) {
            void model.undo();
        }
    }

    onRedo(): void {
        const model = this.shell.activeModel as ConsoleModel | null;
        if (this.redoEntry && !this.busy && model && model.redo) {
            void model.redo();
        }
    }

    // -- the draft: Apply and Discard ------------------------------------------

    get pendingCount(): number {
        return this.shell.pendingCount;
    }

    get applying(): boolean {
        return this.shell.draft.applying;
    }

    /** Why Apply is greyed out, for its tooltip; `""` when it is not. */
    get applyTooltip(): string {
        return this.shell.draft.applyBlocker;
    }

    get applyLabel(): string {
        return this.shell.draft.reloadMode === "manual"
            ? String(_t("Write & restart…"))
            : String(_t("Apply"));
    }

    openApply(): void {
        if (!this.pendingCount) {
            return;
        }
        // `ApplyDialog`'s own `Props` (`apply_dialog.ts`) declares `close`
        // as a required member (it mirrors the component's real, Owl-
        // validated `static props`, which does require it) -- but
        // `dialog_service.js`'s own `add()` always injects the real
        // `close` itself (`subProps: markRaw({ ...props, close })`,
        // `close` spread in *last*, so any value passed here is
        // overwritten before the component ever sees it). Neither real
        // caller (`top_bar.js` here, `panes/changes_pane.js`, still `.js`)
        // has ever supplied one. `odoo.ts`'s own `ConfirmationDialogProps`
        // is deliberately typed *without* `close` for exactly this reason
        // (see its doc comment); `ApplyDialog`'s own `Props` was not given
        // the same treatment when it converted -- flagged in this file's
        // own findings rather than fixed here, since this pass only
        // touches `top_bar.ts`. A no-op placeholder satisfies
        // `DialogService.add`'s generic `P` (inferred from `ApplyDialog`'s
        // own `Component<Props>` base) without changing what actually
        // runs.
        this.dialog.add(ApplyDialog, { shell: this.props.shell, close: () => {} });
    }

    onDiscard(): void {
        if (!this.pendingCount || this.busy) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
                this.pendingCount,
            ),
            confirmLabel: _t("Discard"),
            confirm: () => {
                void this.shell.discard();
            },
            cancel: () => {},
        });
    }

    // -- the status pill ------------------------------------------------------

    get status(): StatusInfo {
        const activity = this.shell.activity;
        const drag = activity.drag as DragStatus | null;
        if (drag) {
            // While something is dragged the pill names it and, once a
            // zone is under the pointer, where it would land.
            const label = drag.caption
                ? _t("%(what)s → %(where)s", { what: drag.label, where: drag.caption })
                : _t("Dragging %s", drag.label);
            return {
                cls: "dragging",
                label: String(label),
                tooltip: String(_t("Press any key to cancel")),
            };
        }
        if (activity.applying) {
            return { cls: "saving", label: String(_t("Applying…")), tooltip: "" };
        }
        if (activity.status === "saving") {
            return { cls: "saving", label: String(_t("Saving…")), tooltip: "" };
        }
        if (activity.status === "error") {
            return { cls: "error", label: String(_t("Not saved")), tooltip: activity.error };
        }
        if (this.pendingCount) {
            return {
                cls: "pending",
                label: String(_t("%s pending · %s", this.pendingCount, this.applyLabel)),
                tooltip: String(
                    this.applyTooltip || _t("Staged on this model's draft; click to apply."),
                ),
            };
        }
        if (this.shell.restartRequired) {
            return {
                cls: "pending",
                label: String(_t("Restart needed")),
                tooltip: String(
                    _t("Something was written to disk that only a restart of the server can load."),
                ),
            };
        }
        if (this.shell.package && !this.shell.packageWritable) {
            return { cls: "readonly", label: String(_t("Read-only")), tooltip: "" };
        }
        return { cls: "saved", label: String(_t("Saved")), tooltip: "" };
    }

    /** The pill is the way to Apply when something is pending. */
    onStatusClick(): void {
        if (this.status.cls === "pending" && this.pendingCount) {
            this.openApply();
        } else if (this.status.cls === "pending") {
            void this.shell.openPane("changes");
        }
    }

    // -- the changes badge ----------------------------------------------------

    get changesCount(): number {
        return this.shell.changesCount;
    }

    openChanges(): void {
        void this.shell.openPane("changes");
    }
}

const VIEW_TYPE_LABELS: Record<string, ReturnType<typeof _t>> = {
    list: _t("List"),
    form: _t("Form"),
    kanban: _t("Kanban"),
    calendar: _t("Calendar"),
    pivot: _t("Pivot"),
    graph: _t("Graph"),
    search: _t("Search"),
    qweb: _t("Report"),
    activity: _t("Activity"),
};

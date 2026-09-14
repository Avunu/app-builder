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
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { ApplyDialog } from "./apply_dialog";
import { paneTabs } from "./shell/pane_registry";

// The icons `ir.ui.view.get_view_info` returns for core's own types, for a
// view the switcher shows before the addable list has been fetched.
const VIEW_ICONS = {
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

const HEALTH_DOT = {
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

/** The colour a package's health dot takes: the worst thing wins. */
export function healthDot(info) {
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

export class TopBar extends Component {
    static template = "app_builder_view.TopBar";
    static components = { Dropdown, DropdownItem };
    static props = {
        shell: Object,
        onClose: Function,
    };

    setup() {
        this.shell = useState(this.props.shell);
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.state = useState({ modelSearch: "", modelMatches: [], picker: null });
        const guarded = (run) => (ev) => {
            const target = ev && ev.target;
            if (target && target.closest && target.closest(EDITABLE_TARGET)) {
                return;
            }
            run();
        };
        useHotkey("control+z", guarded(() => this.onUndo()));
        useHotkey("control+shift+z", guarded(() => this.onRedo()));
        useHotkey("control+y", guarded(() => this.onRedo()));
    }

    // -- the package ---------------------------------------------------------

    get packages() {
        return this.shell.packages.map((info) => ({
            ...info,
            dot: healthDot(info),
            active: info.id === this.shell.packageId,
        }));
    }

    get packageLabel() {
        const info = this.shell.package;
        return info ? info.name : _t("No package");
    }

    get packageDot() {
        return this.shell.package ? healthDot(this.shell.package) : "grey";
    }

    /** A Python-owned model is edited in the package that defines it. */
    get packagePinned() {
        return Boolean(this.shell.learned.python_owner_id);
    }

    get packagePinnedReason() {
        return _t(
            "%s is defined by %s, so its fields can only change there. Pick another model to switch.",
            this.shell.modelLabel || this.shell.modelName,
            this.packageLabel
        );
    }

    onPackage(info) {
        if (!info.active && !this.packagePinned) {
            this.shell.setPackage(info.id);
        }
    }

    onNewPackage() {
        this.shell.openPane("create_package");
    }

    // -- the model -----------------------------------------------------------

    get modelLabel() {
        return this.shell.modelLabel || this.shell.modelName || "";
    }

    /** The picker's lists, read when it opens. */
    async loadPicker() {
        this.state.picker = await this.orm.call("studio.workspace", "models_for_picker", [
            this.shell.packageId || false,
        ]);
    }

    async onModelSearch(ev) {
        const term = (ev.target.value || "").trim();
        this.state.modelSearch = term;
        if (term.length < 2) {
            this.state.modelMatches = [];
            return;
        }
        const rows = await this.orm.searchRead(
            "ir.model",
            ["|", ["name", "ilike", term], ["model", "ilike", term], ["transient", "=", false]],
            ["model", "name"],
            { limit: 12 }
        );
        if (this.state.modelSearch === term) {
            this.state.modelMatches = rows.map((r) => ({ model: r.model, display_name: r.name }));
        }
    }

    async onModel(entry) {
        if (entry.model !== this.shell.modelName) {
            await this.shell.setModel(entry.model);
        }
        if (this.shell.pane === "home") {
            await this.shell.openView({ model: entry.model });
        }
    }

    onBuildApp() {
        this.shell.openPane("build_app");
    }

    onAdoptModel() {
        this.shell.openPane("adopt_model");
    }

    get canBuild() {
        return this.shell.packageWritable;
    }

    // -- the panes -----------------------------------------------------------

    get tabs() {
        return paneTabs(this.shell.paneContext).map((tab) => ({
            ...tab,
            active: tab.key === this.shell.pane,
        }));
    }

    openTab(tab) {
        if (!tab.available || tab.active) {
            return;
        }
        this.shell.openPane(tab.key);
    }

    get onViews() {
        return this.shell.pane === "views";
    }

    /** The Views pane's model, when it is on. */
    get viewsModel() {
        return this.onViews ? this.shell.activeModel : null;
    }

    get viewTypeLabel() {
        const model = this.viewsModel;
        const type = (model && model.viewType) || this.shell.view.view_type || "";
        const known = ((model && model.addable) || []).find((entry) => entry.type === type);
        return (known && known.label) || VIEW_TYPE_LABELS[type] || type;
    }

    /** The model's views, then the types the builder could still add. */
    get switcher() {
        const model = this.viewsModel;
        if (!model || !model.context) {
            return [];
        }
        const context = model.context || {};
        const current = model.viewId;
        const addable = model.addable || [];
        const iconOf = (type) => {
            const entry = addable.find((e) => e.type === type);
            return (entry && entry.icon) || VIEW_ICONS[type] || "fa fa-square-o";
        };
        const existing = (context.views || []).map((view) => ({
            key: `view-${view.view_id}`,
            type: view.type,
            label: view.name,
            icon: iconOf(view.type),
            active: view.view_id === current,
            view,
        }));
        const present = new Set(existing.map((entry) => entry.type));
        const creatable = addable
            .filter((entry) => entry.enabled && !present.has(entry.type))
            .map((entry) => ({
                key: `add-${entry.type}`,
                type: entry.type,
                label: _t("Add a %s view", entry.label || entry.type),
                icon: iconOf(entry.type),
                add: entry,
            }));
        return [...existing, ...creatable];
    }

    onSwitch(entry) {
        const model = this.viewsModel;
        if (entry.view) {
            if (!entry.active) {
                this.shell.openView({
                    view_id: entry.view.view_id,
                    view_type: entry.view.type,
                    res_id: this.shell.view.res_id,
                });
            }
        } else if (entry.add && model) {
            model.addView(entry.add);
        }
    }

    // -- undo / redo ----------------------------------------------------------

    get history() {
        return this.shell.history;
    }

    get undoEntry() {
        return (this.history && this.history.undo[0]) || null;
    }

    get redoEntry() {
        return (this.history && this.history.redo[0]) || null;
    }

    get undoTooltip() {
        const entry = this.undoEntry;
        return entry
            ? _t("Undo: %(summary)s · by %(author)s", { summary: entry.summary, author: entry.author })
            : _t("Nothing to undo");
    }

    get redoTooltip() {
        const entry = this.redoEntry;
        return entry
            ? _t("Redo: %(summary)s · by %(author)s", { summary: entry.summary, author: entry.author })
            : _t("Nothing to redo");
    }

    get busy() {
        return this.shell.activity.busy;
    }

    onUndo() {
        const model = this.shell.activeModel;
        if (this.undoEntry && !this.busy && model && model.undo) {
            model.undo();
        }
    }

    onRedo() {
        const model = this.shell.activeModel;
        if (this.redoEntry && !this.busy && model && model.redo) {
            model.redo();
        }
    }

    // -- the draft: Apply and Discard ------------------------------------------

    get pendingCount() {
        return this.shell.pendingCount;
    }

    get applying() {
        return this.shell.draft.applying;
    }

    /** Why Apply is greyed out, for its tooltip; `""` when it is not. */
    get applyTooltip() {
        return this.shell.draft.applyBlocker;
    }

    get applyLabel() {
        return this.shell.draft.reloadMode === "manual" ? _t("Write & restart…") : _t("Apply");
    }

    openApply() {
        if (!this.pendingCount) {
            return;
        }
        this.dialog.add(ApplyDialog, { shell: this.props.shell });
    }

    onDiscard() {
        if (!this.pendingCount || this.busy) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
                this.pendingCount
            ),
            confirmLabel: _t("Discard"),
            confirm: () => this.shell.discard(),
            cancel: () => {},
        });
    }

    // -- the status pill ------------------------------------------------------

    get status() {
        const activity = this.shell.activity;
        const drag = activity.drag;
        if (drag) {
            // While something is dragged the pill names it and, once a
            // zone is under the pointer, where it would land.
            const label = drag.caption
                ? _t("%(what)s → %(where)s", { what: drag.label, where: drag.caption })
                : _t("Dragging %s", drag.label);
            return { cls: "dragging", label, tooltip: _t("Press any key to cancel") };
        }
        if (activity.applying) {
            return { cls: "saving", label: _t("Applying…"), tooltip: "" };
        }
        if (activity.status === "saving") {
            return { cls: "saving", label: _t("Saving…"), tooltip: "" };
        }
        if (activity.status === "error") {
            return { cls: "error", label: _t("Not saved"), tooltip: activity.error };
        }
        if (this.pendingCount) {
            return {
                cls: "pending",
                label: _t("%s pending · %s", this.pendingCount, this.applyLabel),
                tooltip: this.applyTooltip || _t("Staged on this model's draft; click to apply."),
            };
        }
        if (this.shell.restartRequired) {
            return {
                cls: "pending",
                label: _t("Restart needed"),
                tooltip: _t(
                    "Something was written to disk that only a restart of the server can load."
                ),
            };
        }
        if (this.shell.package && !this.shell.packageWritable) {
            return { cls: "readonly", label: _t("Read-only"), tooltip: "" };
        }
        return { cls: "saved", label: _t("Saved"), tooltip: "" };
    }

    /** The pill is the way to Apply when something is pending. */
    onStatusClick() {
        if (this.status.cls === "pending" && this.pendingCount) {
            this.openApply();
        } else if (this.status.cls === "pending") {
            this.shell.openPane("changes");
        }
    }

    // -- the changes badge ----------------------------------------------------

    get changesCount() {
        return this.shell.changesCount;
    }

    openChanges() {
        this.shell.openPane("changes");
    }
}

const VIEW_TYPE_LABELS = {
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

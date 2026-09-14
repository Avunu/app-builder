/** @odoo-module **/
/**
 * The top bar: where you are, what else the console can open, and the
 * three buttons that matter -- Undo, Redo, Close -- with the status pill
 * between them.
 *
 * The tabs come from the `app_builder.console_tabs` registry so that the
 * addons which own reports, automations and approvals can offer their
 * screens here without this one importing them: an entry is `{label,
 * isAvailable(ctx), open(env, ctx)}` and Views is the one built in. The
 * view switcher shows the views the model has and, as a "+", the ones the
 * builder could still create, with the reason when it cannot.
 *
 * Undo and Redo name the change and its author in their tooltips, because
 * the stack is per view, not per user, and taking back somebody else's
 * edit should be a decision rather than a surprise.
 *
 * On a Python-owned model the pill counts what is staged -- "2 pending ·
 * Apply" -- and is the way to the Apply dialog, with a Discard beside
 * it; Undo and Redo do not reach the draft, which has its own tray.
 */

import { Component, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ApplyDialog } from "./apply_dialog";

const tabRegistry = registry.category("app_builder.console_tabs");

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

export class TopBar extends Component {
    static template = "app_builder_view.TopBar";
    static props = {
        model: Object,
        onClose: Function,
        onSwitchView: Function,
        modelLabel: { type: String, optional: true },
    };

    setup() {
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        useHotkey("control+z", () => this.onUndo());
        useHotkey("control+shift+z", () => this.onRedo());
        useHotkey("control+y", () => this.onRedo());
    }

    get tabs() {
        const ctx = this.tabContext;
        return tabRegistry
            .getEntries()
            .map(([key, entry]) => ({ key, ...entry }))
            .filter((entry) => !entry.isAvailable || entry.isAvailable(ctx));
    }

    get tabContext() {
        return {
            model: this.model.modelName,
            view: this.model.view,
            context: this.model.context,
            packageId: this.model.packageId,
        };
    }

    openTab(entry) {
        if (entry.key === "views") {
            return;
        }
        entry.open(this.env, this.tabContext);
    }

    get modelLabel() {
        return this.props.modelLabel || this.model.modelName || "";
    }

    get viewTypeLabel() {
        const type = this.model.viewType || "";
        const known = (this.model.addable || []).find((entry) => entry.type === type);
        return (known && known.label) || VIEW_TYPE_LABELS[type] || type;
    }

    /** The model's views, then the types the builder could still add. */
    get switcher() {
        const context = this.model.context || {};
        const current = this.model.viewId;
        const addable = this.model.addable || [];
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
        if (entry.view) {
            if (!entry.active) {
                this.props.onSwitchView(entry.view);
            }
        } else if (entry.add) {
            this.model.addView(entry.add);
        }
    }

    // -- undo / redo ----------------------------------------------------------

    get undoEntry() {
        return this.model.history.undo[0] || null;
    }

    get redoEntry() {
        return this.model.history.redo[0] || null;
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

    onUndo() {
        if (this.undoEntry && !this.model.busy) {
            this.model.undo();
        }
    }

    onRedo() {
        if (this.redoEntry && !this.model.busy) {
            this.model.redo();
        }
    }

    // -- the draft: Apply and Discard ------------------------------------------

    get pendingCount() {
        return this.model.pendingCount;
    }

    /** Why Apply is greyed out, for its tooltip; `""` when it is not. */
    get applyTooltip() {
        return this.model.applyBlocker;
    }

    openApply() {
        if (!this.pendingCount) {
            return;
        }
        this.dialog.add(ApplyDialog, { model: this.props.model });
    }

    onDiscard() {
        if (!this.pendingCount || this.model.busy) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
                this.pendingCount
            ),
            confirmLabel: _t("Discard"),
            confirm: () => this.model.discardDraft(),
            cancel: () => {},
        });
    }

    // -- the status pill ------------------------------------------------------

    get status() {
        const drag = this.model.drag;
        if (drag) {
            // While something is dragged the pill names it and, once a
            // zone is under the pointer, where it would land.
            const label = drag.caption
                ? _t("%(what)s → %(where)s", { what: drag.label, where: drag.caption })
                : _t("Dragging %s", drag.label);
            return { cls: "dragging", label, tooltip: _t("Press any key to cancel") };
        }
        if (this.model.applying) {
            return { cls: "saving", label: _t("Applying…"), tooltip: "" };
        }
        if (this.model.status === "saving") {
            return { cls: "saving", label: _t("Saving…"), tooltip: "" };
        }
        if (this.model.status === "error") {
            return { cls: "error", label: _t("Not saved"), tooltip: this.model.statusError };
        }
        if (this.pendingCount) {
            return {
                cls: "pending",
                label: _t("%s pending · Apply", this.pendingCount),
                tooltip: this.applyTooltip || _t("Staged on this model's draft; click to apply."),
            };
        }
        return { cls: "saved", label: _t("Saved"), tooltip: "" };
    }

    /** The pill is the way to Apply when something is pending. */
    onStatusClick() {
        if (this.status.cls === "pending") {
            this.openApply();
        }
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

tabRegistry.add(
    "views",
    {
        label: _t("Views"),
        isAvailable: () => true,
        open: () => {},
    },
    { sequence: 10 }
);

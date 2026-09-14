/** @odoo-module **/
/**
 * The studio console: the real view on the right, what you can do to it on
 * the left, and one bar across the top.
 *
 * Full-screen, because building a screen is not something done in the
 * corner of another one: `static target = "fullscreen"` hides the navbar
 * in 18, 19 and master however the action was launched. The sidebar has
 * three tabs -- Add, View, Properties -- and Properties opens by itself
 * when something is selected. The canvas is whichever component the
 * `app_builder.canvas` registry maps the view's `editable_as` to: the
 * rendered view for anything with a rendering, the three lists for a
 * search view, and -- registered by `app_builder_report`, which owns the
 * RPCs it calls -- the printed document for a report. Other addons add
 * theirs to that registry and to `app_builder.console_tabs` without this
 * module importing them.
 *
 * Every RPC and every piece of state lives in `console_model.js`; this
 * component wires the parts together and answers Close.
 */

import { Component, onWillStart, useEffect, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ResizablePanel } from "@web/core/resizable_panel/resizable_panel";
import { useService } from "@web/core/utils/hooks";
import { StudioCanvas } from "./canvas";
import { SearchListsCanvas } from "./canvases/search_lists_canvas";
import * as compat from "./compat";
import { ConsoleModel } from "./console_model";
import { AddTab } from "./sidebar/add_tab";
import { PropertiesTab } from "./sidebar/properties_tab";
import { ViewTab } from "./sidebar/view_tab";
import { TopBar } from "./top_bar";

const canvasRegistry = registry.category("app_builder.canvas");
canvasRegistry.add("canvas", StudioCanvas);
canvasRegistry.add("search_lists", SearchListsCanvas);

// Empty until the staged-field step: what edits a new field's definition
// before it is created, keyed by what the field editor is for.
registry.category("app_builder.field_editor");

export const SIDEBAR_TABS = [
    { key: "add", label: _t("Add") },
    { key: "view", label: _t("View") },
    { key: "properties", label: _t("Properties") },
];

export class StudioConsole extends Component {
    static template = "app_builder_view.StudioConsole";
    static components = { ResizablePanel, TopBar, AddTab, ViewTab, PropertiesTab };
    static props = { "*": true };
    static target = "fullscreen";

    setup() {
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.model = useState(new ConsoleModel(this.env, this.params));
        this.state = useState({
            tab: "add",
            loading: true,
            error: "",
            // The Studio menu opens the console with nothing in hand, on a
            // view it picked; the banner says which and how to get to
            // another, and goes away when read.
            openedFromMenu: this.params.opened_from === "menu",
        });

        onWillStart(async () => {
            try {
                await this.model.load();
            } catch (err) {
                if (!(err && err.data)) {
                    throw err;
                }
                this.state.error = err.data.message;
            }
            this.state.loading = false;
        });

        // Properties opens on selection; a remount that carries the same
        // selection across is not a selection and leaves the tab alone.
        useEffect(
            (serial) => {
                if (serial) {
                    this.state.tab = "properties";
                }
            },
            () => [this.model.selectionSerial]
        );
    }

    /**
     * What to open. The console's own params, the legacy editor's
     * (`view_id, res_model, view_type`), and the same in the context so
     * the console survives a reload from its own URL, the way a client action
     * does.
     */
    get params() {
        const action = this.props.action || {};
        return { ...(action.context || {}), ...(action.params || {}) };
    }

    get tabs() {
        return SIDEBAR_TABS;
    }

    /** What the menu's banner calls the view on screen. */
    get openedOn() {
        const label = this.model.modelLabel || this.model.modelName || "";
        return _t("the %s %s", label, this.model.viewType || "");
    }

    get canvasComponent() {
        const key = this.model.editableAs;
        return canvasRegistry.contains(key) ? canvasRegistry.get(key) : StudioCanvas;
    }

    get canvasProps() {
        const props = { model: this.model };
        if (this.canvasComponent === StudioCanvas) {
            props.onRemove = (token) => this.removeFromCanvas(token);
        }
        return props;
    }

    get packageMissing() {
        return Boolean(this.model.context) && !this.model.packageId;
    }

    async removeFromCanvas(token) {
        this.model.select(token);
        this.state.tab = "properties";
        // The panel owns the confirmation; a click on the frame's cross is
        // the same request as its Remove button.
        const result = await this.model.remove(token, false);
        if (result && result.confirm) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Remove from view"),
                body: result.confirm,
                confirmLabel: _t("Remove"),
                confirm: () => this.model.remove(token, true),
                cancel: () => {},
            });
        }
    }

    /** Open another view of the same model in this console. */
    async switchView(view) {
        await this.action.doAction(
            {
                type: "ir.actions.client",
                tag: "app_builder_console",
                name: _t("Edit %s view", view.type),
                params: {
                    view_id: view.view_id,
                    model: this.model.modelName,
                    view_type: view.type,
                    action_id: this.params.action_id || false,
                    res_id: this.params.res_id || false,
                    // Close goes back to where the console was opened
                    // from, whichever view it is on by then.
                    previous_action: this.params.previous_action || null,
                    previous_view_type: this.previousViewType,
                },
                context: {
                    view_id: view.view_id,
                    model: this.model.modelName,
                    view_type: view.type,
                },
            },
            { clearBreadcrumbs: false, stackPosition: "replaceCurrentAction" }
        );
    }

    /**
     * The type of the view the console was opened from: the one the cog
     * was on, kept across a switch inside the console.
     */
    get previousViewType() {
        return this.params.previous_view_type || this.params.view_type || false;
    }

    /**
     * Leave the console. Back to where the user came from when there is
     * somewhere to go back to; else to the action they named; else to the
     * model's first window action. The real views load through a cache
     * the canvas never touched, so it is dropped first for them to show
     * the edits.
     *
     * Back to a list or a kanban is not a restore. A restored controller
     * comes back with the model state it exported on leaving -- the
     * fields it was reading records with -- so it renders the new arch
     * and reads the old field set, and every card or row shows a field
     * dropped meanwhile as blank until the next reload. A form builds
     * its model afresh and is restored as it is. So for those two the
     * action the cog item handed over is run again in the previous
     * action's place: the same evaluated context and domain, the same
     * search state (it travels on the action object), and a model that
     * reads what the arch now shows. The search view it carries is
     * dropped first, since the action service adds it back on the way in
     * and would otherwise list it twice.
     */
    async close() {
        compat.clearViewCaches(this.env);
        const breadcrumbs = (this.env.config && this.env.config.breadcrumbs) || [];
        if (breadcrumbs.length > 1) {
            const previous = this.params.previous_action;
            if (previous && previous.type === "ir.actions.act_window" && this.rerunsOnClose) {
                const action = {
                    ...previous,
                    views: (previous.views || []).filter((view) => view[1] !== "search"),
                };
                // What the service fills in on the way in, and what it
                // could not serialise from a copy that still held them.
                delete action._originalAction;
                delete action.controllers;
                return this.action.doAction(action, {
                    stackPosition: "replacePreviousAction",
                    viewType: this.previousViewType,
                });
            }
            return this.action.restore();
        }
        if (this.params.action_id) {
            return this.action.doAction(this.params.action_id);
        }
        const modelName = this.model.modelName;
        if (modelName) {
            const actions = await this.env.services.orm.searchRead(
                "ir.actions.act_window",
                [["res_model", "=", modelName]],
                ["id"],
                { limit: 1, order: "id" }
            );
            if (actions.length) {
                return this.action.doAction(actions[0].id);
            }
        }
        // Nowhere in particular to go back to: the default app.
        this.env.bus.trigger("WEBCLIENT:LOAD_DEFAULT_APP");
        return undefined;
    }

    /** Whether Close re-runs the previous action rather than restoring it. */
    get rerunsOnClose() {
        return ["list", "kanban"].includes(this.previousViewType);
    }
}

registry.category("actions").add("app_builder_console", StudioConsole);
// The tag the cog item and the report action sent before the console
// existed, kept so a bookmarked URL and an older caller still open it.
registry.category("actions").add("app_builder_view_wysiwyg", StudioConsole);

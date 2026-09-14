/** @odoo-module **/
/**
 * The studio console: one bar across the top, and under it whichever
 * pane is on -- its content on the right and, when it has one, its
 * sidebar on the left.
 *
 * Full-screen, because building a screen is not something done in the
 * corner of another one: `static target = "fullscreen"` hides the navbar
 * in 18, 19 and master however the action was launched. `static path`
 * gives it a URL of its own, `/odoo/studio`, and what the shell holds --
 * the package, the model, the pane, the view, a record -- rides on that
 * URL through `updateActionState`, so a reload lands where it left off.
 *
 * Every RPC and every piece of state lives in `shell_model.js` and the
 * panes' own models; this component wires the parts together and answers
 * Close.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ResizablePanel } from "@web/core/resizable_panel/resizable_panel";
import { useService } from "@web/core/utils/hooks";
import * as compat from "../compat";
import { TopBar } from "../top_bar";
import { StudioShell } from "./shell_model";

export class StudioConsole extends Component {
    static template = "app_builder_view.StudioConsole";
    static components = { ResizablePanel, TopBar };
    static props = { "*": true };
    static target = "fullscreen";
    static path = "studio";

    setup() {
        this.action = useService("action");
        this.shell = useState(
            new StudioShell(this.env, StudioShell.fromParams(this.params), {
                pushState: (state) => this.pushState(state),
                setTitle: (title) => this.setTitle(title),
            })
        );
        this.state = useState({ ready: false, error: "" });

        onWillStart(async () => {
            try {
                await this.shell.load();
            } catch (err) {
                if (!(err && err.data)) {
                    throw err;
                }
                this.state.error = err.data.message;
                this.state.ready = true;
                return;
            }
            await this.shell.openPane(this.shell.pane, this.shell.paneState);
            this.state.ready = true;
        });
    }

    /**
     * What to open: the console's own params, the legacy editor's
     * (`view_id, res_model, view_type`), and on a reload the router's
     * state, which the action service hands back as params.
     */
    get params() {
        const action = this.props.action || {};
        return { ...(action.context || {}), ...(action.params || {}) };
    }

    pushState(state) {
        if (this.props.updateActionState) {
            this.props.updateActionState(state);
        }
    }

    setTitle(title) {
        const config = this.env.config;
        if (config && config.setDisplayName) {
            config.setDisplayName(title);
        }
    }

    // -- the pane on screen ----------------------------------------------------

    get pane() {
        return this.shell.activePane;
    }

    get content() {
        return this.pane ? this.pane.Component : null;
    }

    get sidebar() {
        return this.pane ? this.pane.sidebar : null;
    }

    get paneProps() {
        return { shell: this.shell, model: this.shell.activeModel || undefined };
    }

    get sidebarWidth() {
        return this.shell.sidebarWidth || 360;
    }

    onSidebarResize(width) {
        this.shell.sidebarWidth = width;
    }

    get readOnly() {
        return Boolean(this.shell.package) && !this.shell.packageWritable;
    }

    get readOnlyNote() {
        const info = this.shell.package;
        return _t(
            "%s is read-only: its directory cannot be written. This is normal on a deployment — build where the files are writable and ship the result through git.",
            info ? info.name : ""
        );
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
        const entry = this.shell.entry || {};
        const breadcrumbs = (this.env.config && this.env.config.breadcrumbs) || [];
        if (breadcrumbs.length > 1) {
            const previous = entry.previous_action;
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
        if (entry.action_id) {
            return this.action.doAction(entry.action_id);
        }
        const modelName = this.shell.modelName;
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

    /**
     * The type of the view the console was opened from: the one the cog
     * was on, kept across a switch inside the console.
     */
    get previousViewType() {
        const entry = this.shell.entry || {};
        return entry.previous_view_type || this.params.view_type || false;
    }

    /** Whether Close re-runs the previous action rather than restoring it. */
    get rerunsOnClose() {
        return ["list", "kanban"].includes(this.previousViewType);
    }
}

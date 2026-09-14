/** @odoo-module **/
/**
 * "Studio" in the systray -- the way into the console from any screen.
 *
 * The cog item reaches the console from inside a view's control panel; this
 * one sits in the navbar, where Enterprise puts its toggle, and is there
 * whatever the screen shows. It offers itself only when the screen is a
 * window action -- a list, a form, a kanban of some model -- because that is
 * the only thing the console has a canvas for: a dashboard, a settings page
 * or the console itself gets nothing.
 *
 * What the console is told comes from `actionService.currentController`,
 * and nothing else is reachable from here: the navbar is a sibling of the
 * action container, so `env.config` -- where the cog item reads the view
 * id -- is not set on it, and the id the View resolved lives in a copy of
 * the config that never leaves the View. So the model and the view type
 * travel, the view id only when the action pins one, and the server
 * resolves the default view from the rest, the way it already does for
 * the cog item on an ordinary `view_mode="list,form"` action.
 *
 * The navbar re-renders its systray on registry changes and app changes
 * only, never on navigation; so this item listens for the action manager's
 * own "a controller is mounted" event and re-renders itself.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";

export class StudioSystrayItem extends Component {
    static template = "app_builder_view.StudioSystrayItem";
    static props = {};

    setup() {
        this.action = useService("action");
        this.state = useState({ allowed: false });
        // Gated on the studio group the way the cog item is: the server
        // guards the writes, this only keeps the button out of the way of
        // people it would do nothing for.
        onWillStart(async () => {
            this.state.allowed = await user.hasGroup("app_builder_base.group_studio_user");
        });
        // Fired after the new controller is mounted and the stack committed
        // (18, 19 and master alike), so what is read below is current.
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.render());
    }

    /**
     * What the console would be opened on, or `null` when the screen is
     * not a view of a model.
     *
     * A controller restored from the URL may be a `virtual` placeholder
     * with an empty action and no props; a client action -- the console
     * among them -- has a tag and no `resModel`. Both are refused by the
     * one check on the action's type, the placeholder by its own flag too.
     */
    get target() {
        if (!this.state.allowed) {
            return null;
        }
        const ctrl = this.action.currentController;
        if (!ctrl || ctrl.virtual || !ctrl.action || !ctrl.props) {
            return null;
        }
        if (ctrl.action.type !== "ir.actions.act_window" || !ctrl.props.resModel) {
            return null;
        }
        const viewType = ctrl.props.type;
        const views = ctrl.action.views || [];
        const pinned = views.find((view) => view[1] === viewType);
        const state = ctrl.currentState || {};
        return {
            model: ctrl.props.resModel,
            view_type: viewType,
            view_id: (pinned && pinned[0]) || false,
            action_id: ctrl.action.id || false,
            res_id: state.resId || ctrl.props.resId || false,
        };
    }

    get label() {
        return _t("Studio");
    }

    get tooltip() {
        const target = this.target;
        return target
            ? _t("Edit this %s view in Studio", target.view_type)
            : _t("Open Studio");
    }

    /**
     * Open the console on the screen, on its Views pane. What the console
     * needs to come back to this screen after a reload it keeps in its
     * own URL, so nothing is mirrored into the context.
     */
    open() {
        const target = this.target;
        if (!target) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.client",
            tag: "app_builder_console",
            target: "fullscreen",
            name: _t("Studio"),
            params: { ...target, pane: "views" },
        });
    }
}

registry
    .category("systray")
    .add("app_builder.toggle", { Component: StudioSystrayItem, isDisplayed: () => true }, {
        sequence: 5,
    });

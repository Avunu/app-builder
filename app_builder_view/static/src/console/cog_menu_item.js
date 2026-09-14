/** @odoo-module **/
/**
 * "Edit this view" — the way in, from anywhere.
 *
 * One registration covers every view in the product because `env.config`
 * already carries what the editor needs (`web/static/src/views/view.js:148`):
 * the model, the view id and the view type. There is no per-view wiring and
 * nothing to add when a new view type becomes editable.
 *
 * Gated on the studio group, not merely hidden: the editor writes Python-free
 * but real files into an addons path, so the guard that matters is the one on
 * the server (`studio.security.mixin`). This only keeps the menu out of the way
 * of people it would do nothing for.
 */

import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

// Types the editor can open. A settings-only view (pivot, graph, timeline)
// belongs here as much as a clickable one: what it *is* lives in its root
// attributes, and the panel edits those whether or not there is a node to aim
// at. Anything not listed simply shows no menu item, which is the honest answer
// for a view the editor has nothing to say about yet.
const EDITABLE_TYPES = [
    "list",
    "form",
    "kanban",
    "calendar",
    "search",
    "pivot",
    "graph",
    "timeline",
];

export class EditThisView extends Component {
    static template = "app_builder_view.EditThisView";
    static components = { DropdownItem };
    static props = {};

    setup() {
        this.action = useService("action");
    }

    onEdit() {
        const config = this.env.config;
        // viewId is deliberately allowed to be false. An ordinary action does
        // not pin one -- view_mode="list,form" resolves its views at load time
        // -- so the model and the view type are what we can always supply, and
        // the server asks core's own default_view for the rest. The record on
        // screen and the action travel too, so the console renders the record
        // the user was looking at and Close brings them back to it.
        const controller = this.action.currentController;
        const state = (controller && controller.currentState) || {};
        const params = {
            view_id: config.viewId || false,
            res_model: config.resModel,
            model: config.resModel,
            view_type: config.viewType,
            action_id: config.actionId || false,
            res_id: state.resId || false,
        };
        this.action.doAction({
            type: "ir.actions.client",
            tag: "app_builder_console",
            name: `Edit ${config.viewType} view`,
            // The action this view belongs to, as the action service holds
            // it -- context evaluated, search state on it -- so Close can
            // run it again for a list or kanban, whose restored controller
            // would otherwise read records with the fields it was opened
            // with and show a new one blank. In params only: an action
            // object is not context to send with every request, and not
            // something a URL carries.
            params: { ...params, previous_action: controller ? controller.action : null },
            // Also in context so the console survives a page reload from its
            // own URL, the same way a resumable client action does.
            context: params,
        });
    }
}

export const editThisViewItem = {
    Component: EditThisView,
    groupNumber: 40,
    isDisplayed: async (env) =>
        EDITABLE_TYPES.includes(env.config.viewType) &&
        (await user.hasGroup("app_builder_base.group_studio_user")),
};

registry.category("cogMenu").add("app-builder-edit-view", editThisViewItem, {
    sequence: 40,
});

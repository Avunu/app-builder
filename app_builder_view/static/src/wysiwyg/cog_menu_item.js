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

const EDITABLE_TYPES = ["list", "form", "kanban", "calendar", "search"];

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
        // the server asks core's own default_view for the rest.
        const params = {
            view_id: config.viewId || false,
            res_model: config.resModel,
            view_type: config.viewType,
        };
        this.action.doAction({
            type: "ir.actions.client",
            tag: "app_builder_view_wysiwyg",
            name: `Edit ${config.viewType} view`,
            params,
            // Also in context so the editor survives a page reload from its own
            // URL, the same way the model composer does.
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

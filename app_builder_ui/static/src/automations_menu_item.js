/** @odoo-module **/
/**
 * "Automations" — the rules for *this* model, from wherever you are.
 *
 * Odoo has one list of automations for the whole database, under Settings →
 * Technical, and finding the three that apply to the screen in front of you
 * means knowing the model's technical name and filtering by it. That is the
 * whole reason Odoo Studio has an Automations button: not a better form, a
 * shorter distance.
 *
 * The action itself is computed on the server, because "which package should a
 * rule created here be written into" is a question only the server can answer —
 * see `studio.automation.action_open`.
 */

import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

export class StudioAutomations extends Component {
    static template = "app_builder_ui.StudioAutomations";
    static components = { DropdownItem };
    static props = {};

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onOpen() {
        const action = await this.orm.call("studio.automation", "action_open", [], {
            model_name: this.env.config.resModel,
        });
        this.action.doAction(action);
    }
}

export const studioAutomationsItem = {
    Component: StudioAutomations,
    groupNumber: 40,
    isDisplayed: async (env) =>
        Boolean(env.config.resModel) &&
        (await user.hasGroup("app_builder_base.group_studio_user")),
};

registry
    .category("cogMenu")
    .add("app-builder-automations", studioAutomationsItem, { sequence: 41 });

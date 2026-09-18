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
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@app_builder_view/console/odoo";
import type { ActionService, CogMenuItem, ViewEnv } from "@app_builder_view/console/odoo";
import type { OrmService } from "@app_builder_view/console/types";

// No props: `static props = {}` below is a strict empty schema, the same
// "genuinely takes nothing" situation `cog_menu_item.ts`'s own `Props`
// already documents -- `Record<string, never>`, not a bare `{}`, for the
// identical reason given there.
type Props = Record<string, never>;

export class StudioAutomations extends Component<Props, ViewEnv> {
    static override template = "app_builder_ui.StudioAutomations";
    static components = { DropdownItem };
    static override props = {};

    action!: ActionService;
    orm!: OrmService;

    override setup(): void {
        this.action = useService("action");
        this.orm = useService("orm");
    }

    /** The console, on its Automations pane for the model on screen. */
    onOpen(): void {
        void this.action.doAction({
            type: "ir.actions.client",
            tag: "app_builder_console",
            target: "fullscreen",
            name: String(_t("Studio")),
            params: {
                pane: "automations",
                res_model: this.env.config.resModel,
                action_id: this.env.config.actionId || false,
            },
        });
    }
}

export const studioAutomationsItem: CogMenuItem = {
    Component: StudioAutomations,
    groupNumber: 40,
    isDisplayed: async (env) =>
        Boolean(env.config.resModel) && (await user.hasGroup("app_builder_base.group_studio_user")),
};

registry.category("cogMenu").add("app-builder-automations", studioAutomationsItem, { sequence: 41 });

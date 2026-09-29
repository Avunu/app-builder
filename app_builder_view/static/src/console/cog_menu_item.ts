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
import { useService, user } from "./odoo";
import type { ActionController, ActionService, CogMenuItem, ViewEnv } from "./odoo";

// `registry.category("cogMenu")`'s item shape (`CogMenuItem`), the
// `env.config` slice it reads (`ViewEnv`/`ViewEnvConfig`), and the
// `declare module "registries"` augmentation all live in `odoo.ts` now --
// "the framework boundary, fenced in one place" (TYPING.md, Phase 2c) --
// alongside `app_builder.panes`/`console_tabs`/`systray`. Note for whoever
// converts `app_builder_ui/static/src/automations_menu_item.js`: it
// registers into this same "cogMenu" category and reads exactly
// `resModel`/`actionId` off its own `env.config`, both already named in
// `ViewEnvConfig` -- import from `odoo.ts` rather than re-declaring.

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

// No props: `static props = {}` below is a strict empty schema (no `"*"`
// wildcard), so Owl rejects any prop this component is ever given -- there
// simply is none to name. `Record<string, never>` rather than a bare
// `{}`: TypeScript treats an empty *interface* as accepting almost any
// value structurally, which is not what is meant here -- the same move
// `systray_item.ts`'s own `Props` already makes for the identical
// situation.
type Props = Record<string, never>;

export class EditThisView extends Component<Props, ViewEnv> {
    static override template = "app_builder_view.EditThisView";
    static components = { DropdownItem };
    static override props = {};

    action!: ActionService;

    override setup(): void {
        this.action = useService("action");
    }

    onEdit(): void {
        const config = this.env.config;
        // viewId is deliberately allowed to be false. An ordinary action does
        // not pin one -- view_mode="list,form" resolves its views at load time
        // -- so the model and the view type are what we can always supply, and
        // the server asks core's own default_view for the rest. The record on
        // screen and the action travel too, so the console renders the record
        // the user was looking at and Close brings them back to it.
        const controller = this.action.currentController;
        // Annotated explicitly (reusing `ActionController`'s own
        // `currentState` shape rather than re-declaring it) so the `{}`
        // fallback -- which has no `resId` member of its own -- is checked
        // against this type instead of widening to a bare `{}` that would
        // reject the later `state.resId` read.
        const state: NonNullable<ActionController["currentState"]> =
            (controller && controller.currentState) || {};
        // `env.config` does not carry the model on every view; the action
        // the controller runs always does. Without it a model with no
        // stored view of this type (a fresh manual model) would open the
        // console with nothing to show.
        const resModel =
            config.resModel || (controller && controller.action && controller.action.res_model);
        const params = {
            view_id: config.viewId || false,
            res_model: resModel,
            model: resModel,
            view_type: config.viewType,
            action_id: config.actionId || false,
            res_id: state.resId || false,
        };
        void this.action.doAction({
            type: "ir.actions.client",
            tag: "app_builder_console",
            name: `Edit ${config.viewType} view`,
            // The action this view belongs to, as the action service holds
            // it -- context evaluated, search state on it -- so Close can
            // run it again for a list or kanban, whose restored controller
            // would otherwise read records with the fields it was opened
            // with and show a new one blank. In params only: an action
            // object is not context to send with every request, and not
            // something a URL carries. The rest the console keeps in its
            // own URL, so nothing is mirrored into the context.
            params: {
                ...params,
                pane: "views",
                previous_action: controller ? controller.action : null,
            },
        });
    }
}

export const editThisViewItem: CogMenuItem = {
    Component: EditThisView,
    groupNumber: 40,
    isDisplayed: async (env) =>
        EDITABLE_TYPES.includes(env.config.viewType) &&
        (await user.hasGroup("app_builder_base.group_studio_user")),
};

registry.category("cogMenu").add("app-builder-edit-view", editThisViewItem, {
    sequence: 40,
});

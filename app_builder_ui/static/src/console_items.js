/** @odoo-module **/
/**
 * What this addon adds to the studio console: the tabs for everything
 * about a model that is not a view.
 *
 * The console's top bar takes its tabs from the `app_builder.console_tabs`
 * registry, so Automations, Webhooks, Access Control and Filter Rules sit
 * beside Views without the console knowing this addon exists. None of them
 * is a new screen: each opens Odoo's own list, scoped to the model on the
 * canvas and with a package in context, and the scoping is done on the
 * server -- `studio.automation.action_open`, `studio.security.surface
 * .action_access` / `.action_rules`. The package is the console's own: the
 * one its top bar shows and its drops are recorded into, so a rule made
 * from a tab lands in the same addon as the view it was made beside; the
 * server only falls back to guessing for a caller that has no console.
 * Edit Menu is the one wizard: the New Menu form, with the model and the
 * package filled in.
 *
 * Navigation, not embedded panes: `doAction` stacks the list on top of the
 * console, and the breadcrumb brings the user back to a console that is
 * exactly as they left it.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const tabs = registry.category("app_builder.console_tabs");

/** A tab that opens a server-computed list for the model on the canvas. */
function scopedList(key, label, sequence, model, method, kwargs = {}) {
    tabs.add(
        key,
        {
            label,
            // Every list here is a list *for a model*: a report console has
            // none, and a tab that opened the whole database would be a
            // longer road to the same screen.
            isAvailable: (ctx) => Boolean(ctx.model),
            async open(env, ctx) {
                const action = await env.services.orm.call(model, method, [], {
                    model_name: ctx.model,
                    package_id: ctx.packageId || false,
                    ...kwargs,
                });
                await env.services.action.doAction(action);
            },
        },
        { sequence }
    );
}

scopedList("automations", _t("Automations"), 30, "studio.automation", "action_open");
scopedList("webhooks", _t("Webhooks"), 40, "studio.automation", "action_open", {
    webhooks: true,
});
scopedList("access", _t("Access Control"), 50, "studio.security.surface", "action_access");
scopedList("rules", _t("Filter Rules"), 60, "studio.security.surface", "action_rules");

tabs.add(
    "edit_menu",
    {
        label: _t("Edit Menu"),
        isAvailable: (ctx) => Boolean(ctx.model),
        async open(env, ctx) {
            // The wizard's own action, so its form and target come from the
            // XML; only the defaults are ours. `ir.model` is keyed by id
            // where the console knows the name, so the id is looked up here
            // rather than asking the wizard to grow a second picker.
            const models = await env.services.orm.searchRead(
                "ir.model",
                [["model", "=", ctx.model]],
                ["id"],
                { limit: 1 }
            );
            const context = { default_model_id: models.length ? models[0].id : false };
            if (ctx.packageId) {
                context.default_package_id = ctx.packageId;
            }
            await env.services.action.doAction("app_builder_ui.studio_menu_wizard_action", {
                additionalContext: context,
            });
        },
    },
    { sequence: 80 }
);

/** @odoo-module **/
/**
 * What this addon adds to the studio console: an "Approvals" tab.
 *
 * The console's top bar takes its tabs from the `app_builder.console_tabs`
 * registry, so the approval rules of the model being edited are one click
 * away from its views without the console knowing this addon exists. The
 * tab opens the engine's own rule list -- `studio.approval.action_open
 * (model, package)` -- scoped on the server to the model on the canvas and
 * to the console's own package, so a rule made there lands in the addon
 * the view is being edited in. Navigation, not an embedded pane: the
 * breadcrumb brings the user back to the console.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

registry.category("app_builder.console_tabs").add(
    "approvals",
    {
        label: _t("Approvals"),
        // A rule gates a model's records: without a model there is nothing
        // to list.
        isAvailable: (ctx) => Boolean(ctx.model),
        async open(env, ctx) {
            const action = await env.services.orm.call("studio.approval", "action_open", [], {
                model_name: ctx.model,
                package_id: ctx.packageId || false,
            });
            await env.services.action.doAction(action);
        },
    },
    { sequence: 70 }
);

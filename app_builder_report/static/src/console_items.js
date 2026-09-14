/** @odoo-module **/
/**
 * What this addon adds to the studio console: a "Reports" tab.
 *
 * The console's top bar takes its tabs from the `app_builder.console_tabs`
 * registry, so the reports of the model being edited are one click away
 * from its views without the console knowing this addon exists. The tab
 * opens the same scoped list the Studio menu does -- `studio.report
 * .action_open(model)` -- computed on the server, because which package a
 * report created there is written into is a question only the server can
 * answer. Navigation, not an embedded pane: the breadcrumb brings the user
 * back to the console.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

registry.category("app_builder.console_tabs").add(
    "reports",
    {
        label: _t("Reports"),
        // A report is printed over a model's records: without a model
        // there is nothing to list.
        isAvailable: (ctx) => Boolean(ctx.model),
        async open(env, ctx) {
            const action = await env.services.orm.call("studio.report", "action_open", [], {
                model_name: ctx.model,
            });
            await env.services.action.doAction(action);
        },
    },
    { sequence: 20 }
);

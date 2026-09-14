/** @odoo-module **/
/**
 * The Approvals pane, as data: a record pane over `studio.approval`.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

registry.category("app_builder.panes").add(
    "approvals",
    {
        label: _t("Approvals"),
        icon: "fa fa-check-square-o",
        scope: "model",
        surface: "studio.approval",
        empty: {
            title: _t("Say who must approve, and in what order"),
            help: _t(
                "A rule names the reviewer and the records it covers. Rules you add are written to security/<model>_approval.xml."
            ),
        },
    },
    { sequence: 70 }
);

/** @odoo-module **/
/**
 * The Approvals pane, as data: a record pane over `builder.approval`.
 */

import {_t as _tUntyped} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";
import type {TranslateFn} from "@app_builder_view/console/l10n";

// `app_builder_approval` does not depend on `app_builder_view` (its manifest), so
// nothing from that addon may be imported here at runtime -- it would be
// missing from this addon's bundle whenever it is installed without it.
// The typed facades are taken as *types* only (`import type`, erased from
// the emitted `.js`) and applied to Odoo's own functions, which is all
// `console/l10n.ts` and `console/odoo.ts` do at runtime anyway.
const _t = _tUntyped as TranslateFn;

registry.category("app_builder.panes").add(
  "approvals",
  {
    label: _t("Approvals"),
    icon: "fa fa-check-square-o",
    scope: "model",
    surface: "builder.approval",
    empty: {
      title: _t("Say who must approve, and in what order"),
      help: _t(
        "A rule names the reviewer and the records it covers. Rules you add are written to security/<model>_approval.xml."
      ),
    },
  },
  {sequence: 70}
);

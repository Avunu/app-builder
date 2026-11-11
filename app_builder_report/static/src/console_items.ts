/** @odoo-module **/
/**
 * The Reports pane, as data: a record pane over `builder.report`, whose
 * one row action opens a report's template on the canvas -- inside the
 * console, on the same pane.
 */

import {_t} from "@app_builder_view/console/l10n";
import {registry} from "@web/core/registry";
import type {RecordRowJSON} from "@app_builder_view/console/wire";
import type {BuilderShell} from "@app_builder_view/console/shell/shell_model";

registry.category("app_builder.panes").add(
  "reports",
  {
    label: _t("Reports"),
    icon: "fa fa-file-text-o",
    scope: "model",
    surface: "builder.report",
    empty: {
      title: _t("Put this on paper"),
      help: _t(
        "New reports are written into the package. Reports that came with Odoo are editable too: your changes land in a view of your own that inherits theirs, so the original keeps receiving fixes."
      ),
    },
    // The layout is editable whether or not the report is ours: a
    // foreign template is patched through an inheriting view.
    rowActions: [
      {
        key: "edit",
        label: _t("Edit layout"),
        icon: "fa fa-pencil",
        when: (row: RecordRowJSON) => Boolean(row.view_id),
        run: (shell: BuilderShell, row: RecordRowJSON) =>
          shell.openView({view_id: row.view_id || false, view_type: "qweb"}),
      },
    ],
  },
  {sequence: 20}
);

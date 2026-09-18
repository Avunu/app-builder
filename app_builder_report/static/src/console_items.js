import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
registry.category("app_builder.panes").add(
  "reports",
  {
    label: _t("Reports"),
    icon: "fa fa-file-text-o",
    scope: "model",
    surface: "studio.report",
    empty: {
      title: _t("Put this on paper"),
      help: _t(
        "New reports are written into the package. Reports that came with Odoo are editable too: your changes land in a view of your own that inherits theirs, so the original keeps receiving fixes."
      )
    },
    // The layout is editable whether or not the report is ours: a
    // foreign template is patched through an inheriting view.
    rowActions: [
      {
        key: "edit",
        label: _t("Edit layout"),
        icon: "fa fa-pencil",
        when: (row) => Boolean(row.view_id),
        run: (shell, row) => shell.openView({ view_id: row.view_id || false, view_type: "qweb" })
      }
    ]
  },
  { sequence: 20 }
);

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
const panes = registry.category("app_builder.panes");
function pane(key, label, icon, sequence, surface, extra = {}) {
  const value = {
    label: String(label),
    icon,
    scope: "model",
    surface,
    ...extra
  };
  panes.add(key, value, { sequence });
}
pane("automations", _t("Automations"), "fa fa-bolt", 30, "studio.automation", {
  empty: {
    title: _t("Make something happen on its own"),
    help: _t(
      "Pick what to watch for and what to do about it. Rules you add are written to data/<model>_automation.xml and ship with the package."
    )
  }
});
pane("webhooks", _t("Webhooks"), "fa fa-plug", 40, "studio.automation", {
  surfaceArgs: { webhooks: true },
  empty: {
    title: _t("Let another system drive this database"),
    help: _t(
      "A webhook gives you a URL. Anything that can send it a POST can create or update records of this model."
    )
  }
});
pane("access", _t("Access Control"), "fa fa-lock", 50, "studio.access.surface", {
  empty: {
    title: _t("Nobody but the administrator can see this model"),
    help: _t("One line per group. Lines you add are written to security/ir.model.access.csv.")
  }
});
pane("rules", _t("Filter Rules"), "fa fa-filter", 60, "studio.rule.surface", {
  empty: {
    title: _t("Decide which records each group sees"),
    help: _t(
      "A rule is a condition on the records, per group. Rules you add are written to security/<model>_security.xml."
    )
  }
});
function sibling(model, row, direction) {
  const siblings = model.rows.filter((r) => r.parent_id === row.parent_id);
  const index = siblings.findIndex((r) => r.id === row.id);
  return siblings[index + direction] || null;
}
pane("menu", _t("Menu"), "fa fa-bars", 80, "studio.menu", {
  scope: "package",
  empty: {
    title: _t("Nothing in the apps menu yet"),
    help: _t(
      "An app is a root menu with an icon; a submenu opens a model's views. Both are written to views/menus.xml."
    )
  },
  // Up and down among the menus beside it: the surface renumbers the
  // package's own siblings 10/20/30 and leaves the others' numbers alone.
  rowActions: [
    {
      key: "up",
      label: _t("Move up"),
      icon: "fa fa-arrow-up",
      when: (row) => row.editable,
      run: (shell, row, model) => {
        const before = sibling(model, row, -1);
        if (before) {
          void model.call("move", [
            row.id,
            row.parent_id || false,
            before.id,
            shell.packageId
          ]);
        }
      }
    },
    {
      key: "down",
      label: _t("Move down"),
      icon: "fa fa-arrow-down",
      when: (row) => row.editable,
      run: (shell, row, model) => {
        const after = sibling(model, row, 1);
        if (after) {
          const target = sibling(model, after, 1);
          void model.call("move", [
            row.id,
            row.parent_id || false,
            target ? target.id : false,
            shell.packageId
          ]);
        }
      }
    }
  ]
});

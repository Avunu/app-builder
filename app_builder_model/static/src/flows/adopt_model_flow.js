import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@app_builder_view/console/odoo";
import * as compat from "@app_builder_view/console/compat";
import { paneRegistry } from "@app_builder_view/console/shell/pane_registry";
class ChooseStep extends Component {
  static template = "app_builder_model.AdoptChoose";
  static props = { shell: Object, flow: Object };
  flow;
  orm;
  state;
  setup() {
    this.flow = useState(this.props.flow);
    this.orm = useService("orm");
    this.state = useState({
      models: [],
      loading: true
    });
    onWillStart(async () => {
      this.state.models = await this.orm.call(
        "studio.app.builder",
        "adoptable_models",
        []
      );
      this.state.loading = false;
      const preset = this.flow.target && this.flow.target.model;
      if (preset && !this.flow.values.models) {
        this.flow.values.models = this.state.models.some((m) => m.model === preset) ? [preset] : [];
      }
      this.flow.values.models = this.flow.values.models || [];
      const previewEntries = this.state.models.map((m) => [
        m.model,
        m.preview
      ]);
      this.flow.values.previews = Object.fromEntries(previewEntries);
    });
  }
  isOn(name) {
    return (this.flow.values.models || []).includes(name);
  }
  toggle(name) {
    const current = new Set(this.flow.values.models || []);
    if (current.has(name)) {
      current.delete(name);
    } else {
      current.add(name);
    }
    this.flow.values.models = [...current];
  }
  /** Where the model came from, in a phrase. */
  origin(entry) {
    if (entry.owner_package) {
      return _t("Made by the studio in %s, as records", entry.owner_package.name);
    }
    return _t("Made by hand in Settings › Technical");
  }
}
class PreviewStep extends Component {
  static template = "app_builder_model.AdoptPreview";
  static props = { shell: Object, flow: Object };
  flow;
  setup() {
    this.flow = useState(this.props.flow);
  }
  get previews() {
    const previews = this.flow.values.previews || {};
    return (this.flow.values.models || []).map((name) => ({
      name,
      code: previews[name] || ""
    }));
  }
}
class ReviewStep extends Component {
  static template = "app_builder_model.AdoptReview";
  static props = { shell: Object, flow: Object };
  flow;
  shell;
  setup() {
    this.flow = useState(this.props.flow);
    this.shell = useState(this.props.shell);
  }
  get files() {
    return (this.flow.values.models || []).map(
      (name) => `models/${name.replace(/\./g, "_")}.py`
    );
  }
  get manual() {
    return Boolean(this.shell.package && this.shell.package.reload_mode === "manual");
  }
}
paneRegistry.add("adopt_model", {
  // `PaneRegistration.label` is a plain `string`, never the lazy
  // `_t(...)` union itself -- `String(...)` throughout this
  // registration, matching `create_package_flow.ts`'s own precedent.
  label: String(_t("Adopt a model")),
  icon: "fa fa-download",
  scope: "package",
  tab: false,
  flow: {
    key: "adopt_model",
    title: String(_t("Adopt a model")),
    doneLabel: String(_t("Adopt")),
    steps: [
      {
        key: "choose",
        label: String(_t("Choose")),
        Component: ChooseStep,
        validate: (values) => (values.models || []).length ? "" : String(_t("Choose at least one model."))
      },
      { key: "preview", label: String(_t("Preview")), Component: PreviewStep },
      { key: "review", label: String(_t("Review")), Component: ReviewStep }
    ],
    onDone: async (shell, flow) => {
      const names = flow.values.models || [];
      const answer = await shell.orm.call("studio.app.builder", "adopt", [
        shell.packageId,
        names
      ]);
      compat.clearViewCaches(shell.env);
      await shell.refreshPackages();
      shell.inventory = null;
      const firstName = names[0];
      await shell.openView({ model: firstName, view_type: "form" });
      shell.callout = {
        key: "adopted",
        title: answer.restart_required ? String(_t("%s is written; restart to make it Python", names.join(", "))) : String(_t("%s is Python now", names.join(", "))),
        lines: [
          String(
            _t(
              "Its fields live in models/ as a class; the studio keeps the marked block in sync and leaves the rest to you."
            )
          ),
          String(_t("New fields on it are staged and applied with one reload."))
        ],
        model: firstName
      };
      return answer;
    }
  }
});

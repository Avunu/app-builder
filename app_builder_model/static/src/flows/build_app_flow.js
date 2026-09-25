import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@app_builder_view/console/l10n";
import { useService } from "@app_builder_view/console/odoo";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import * as compat from "@app_builder_view/console/compat";
import { paneRegistry } from "@app_builder_view/console/shell/pane_registry";
function slug(text) {
  return (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
class NameStep extends Component {
  static template = "app_builder_model.BuildAppName";
  static props = { shell: Object, flow: Object };
  flow;
  orm;
  state;
  setup() {
    this.flow = useState(this.props.flow);
    this.orm = useService("orm");
    this.state = useState({ suggested: "", taken: false, checking: false });
    if (this.flow.values.label) {
      void this.suggest();
    }
  }
  onLabel(ev) {
    this.flow.values.label = ev.target.value;
    if (!this.flow.values.nameTouched) {
      this.flow.values.model_name = "";
    }
    void this.suggest();
  }
  onName(ev) {
    this.flow.values.model_name = ev.target.value.trim();
    this.flow.values.nameTouched = true;
  }
  async suggest() {
    const label = (this.flow.values.label || "").trim();
    if (!label || !this.props.shell.packageId) {
      this.state.suggested = "";
      this.state.taken = false;
      return;
    }
    this.state.checking = true;
    try {
      const answer = await this.orm.call(
        "studio.app.builder",
        "suggest_name",
        [label, this.props.shell.packageId]
      );
      if ((this.flow.values.label || "").trim() === label) {
        this.state.suggested = answer.model;
        this.state.taken = answer.taken;
        if (!this.flow.values.nameTouched) {
          this.flow.values.model_name = answer.model;
        }
      }
    } finally {
      this.state.checking = false;
    }
  }
  get modelName() {
    return this.flow.values.model_name || this.state.suggested || "";
  }
}
class FeaturesStep extends Component {
  static template = "app_builder_model.BuildAppFeatures";
  static props = { shell: Object, flow: Object };
  flow;
  orm;
  state;
  setup() {
    this.flow = useState(this.props.flow);
    this.orm = useService("orm");
    this.state = useState({
      features: [],
      defaults: []
    });
    onWillStart(async () => {
      const answer = await this.orm.call(
        "studio.app.builder",
        "features",
        []
      );
      this.state.features = answer.features;
      this.state.defaults = answer.defaults;
      if (!this.flow.values.features) {
        this.flow.values.features = [...answer.defaults];
      }
    });
  }
  /** What the tiles offer: a feature another one implies is not a tile. */
  get offered() {
    return this.state.features.filter((f) => f.offered);
  }
  isOn(key) {
    return (this.flow.values.features || []).includes(key);
  }
  toggle(key) {
    const current = new Set(this.flow.values.features || []);
    if (current.has(key)) {
      current.delete(key);
    } else {
      current.add(key);
    }
    this.flow.values.features = [...current];
  }
  /** The one sentence a tile carries: what it builds, and its cost. */
  consequence(feature) {
    const parts = [];
    if (feature.help) {
      parts.push(feature.help);
    }
    if (feature.views && feature.views.length) {
      parts.push(String(_t("Adds: %s", feature.views.map((v) => "+ " + v).join(" "))));
    }
    if (feature.companion) {
      parts.push(
        String(
          _t(
            "Builds a second model (%s). Decided now: adding it later means building another app.",
            feature.companion
          )
        )
      );
    }
    return parts.join(" ");
  }
}
class WhoStep extends Component {
  static template = "app_builder_model.BuildAppWho";
  static components = { MultiRecordSelector };
  static props = { shell: Object, flow: Object };
  flow;
  orm;
  setup() {
    this.flow = useState(this.props.flow);
    this.orm = useService("orm");
    onWillStart(async () => {
      if (!this.flow.values.groups) {
        const ids = await this.orm.call(
          "ir.model.data",
          "search_read",
          [
            [
              ["module", "=", "base"],
              ["name", "=", "group_user"]
            ],
            ["res_id"]
          ]
        );
        const first = ids[0];
        this.flow.values.groups = first ? [first.res_id] : [];
      }
    });
  }
  get groupIds() {
    return this.flow.values.groups || [];
  }
  onGroups(ids) {
    this.flow.values.groups = ids;
  }
}
class MenuStep extends Component {
  static template = "app_builder_model.BuildAppMenu";
  static components = { RecordSelector };
  static props = { shell: Object, flow: Object };
  flow;
  setup() {
    this.flow = useState(this.props.flow);
    if (!this.flow.values.menu_kind) {
      this.flow.values.menu_kind = "new_root";
    }
  }
  get parentId() {
    return this.flow.values.parent_menu_id || false;
  }
  onParent(id) {
    this.flow.values.parent_menu_id = id || false;
  }
}
class ReviewStep extends Component {
  static template = "app_builder_model.BuildAppReview";
  static props = { shell: Object, flow: Object };
  flow;
  shell;
  setup() {
    this.flow = useState(this.props.flow);
    this.shell = useState(this.props.shell);
  }
  get modelName() {
    return this.flow.values.model_name;
  }
  get fileName() {
    return (this.modelName || "").replace(/\./g, "_");
  }
  /** What lands on disk, in the order the package loads it. */
  get files() {
    const name = this.fileName;
    const features = this.flow.values.features || [];
    const files = [`models/${name}.py`];
    if (features.includes("tags")) {
      files.push(`models/${name}_tag.py`);
    }
    if (features.includes("lines")) {
      files.push(`models/${name}_line.py`);
    }
    files.push(`views/${name}_views.xml`, "views/menus.xml", "security/ir.model.access.csv");
    if (features.includes("reference")) {
      files.push(`data/${name}_sequence.xml`);
    }
    return files;
  }
  get manual() {
    return Boolean(this.shell.package && this.shell.package.reload_mode === "manual");
  }
}
paneRegistry.add("build_app", {
  // Lazy `_t` values, not `String(...)`: this runs at module load, before
  // translations exist (`PaneRegistration.label`).
  label: _t("Build an app"),
  icon: "fa fa-cubes",
  scope: "package",
  tab: false,
  flow: {
    key: "build_app",
    title: _t("Build an app"),
    doneLabel: _t("Build it"),
    steps: [
      {
        key: "name",
        label: _t("Name"),
        Component: NameStep,
        validate: (values) => {
          if (!(values.label || "").trim()) {
            return String(_t("The app needs a name."));
          }
          const modelName = values.model_name;
          if (modelName && !/^[a-z][a-z0-9_.]*$/.test(modelName)) {
            return String(
              _t(
                "'%s' is not a valid model name: lowercase letters, digits, dots and underscores.",
                modelName
              )
            );
          }
          return "";
        }
      },
      { key: "features", label: _t("Features"), Component: FeaturesStep },
      {
        key: "who",
        label: _t("Who can use it"),
        Component: WhoStep,
        validate: (values) => (values.groups || []).length ? "" : String(_t("Pick at least one group, or nobody can open it."))
      },
      {
        key: "menu",
        label: _t("Menu"),
        Component: MenuStep,
        validate: (values) => values.menu_kind === "under" && !values.parent_menu_id ? String(_t("Say which app the menu goes under.")) : ""
      },
      { key: "review", label: _t("Review"), Component: ReviewStep }
    ],
    onDone: async (shell, flow) => {
      const values = flow.values;
      const built = await shell.orm.call(
        "studio.app.builder",
        "create_app_rpc",
        [
          shell.packageId,
          {
            label: (values.label || "").trim(),
            model_name: values.model_name || "",
            features: values.features || [],
            groups: values.groups || [],
            menu: values.menu_kind === "under" ? { parent_id: values.parent_menu_id } : { new_root: true }
          }
        ]
      );
      compat.clearViewCaches(shell.env);
      await shell.refreshPackages();
      shell.inventory = null;
      await shell.openView({
        model: built.model,
        view_type: "form",
        view_id: built.views["form"] || false
      });
      shell.callout = {
        key: "built_app",
        title: String(_t("%s is live", (values.label || "").trim())),
        lines: [
          String(
            _t(
              "Its form is on the canvas: drop fields on it, or open the other views from the switcher."
            )
          ),
          String(_t("Automations, access and rules are one tab away."))
        ],
        model: built.model
      };
      return built;
    }
  }
});

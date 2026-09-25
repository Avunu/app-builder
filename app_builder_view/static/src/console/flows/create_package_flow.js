import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { useService } from "../odoo";
import { paneRegistry } from "../shell/pane_registry";
class NameStep extends Component {
  static template = "app_builder_view.CreatePackageName";
  static props = { shell: Object, flow: Object };
  flow;
  setup() {
    this.flow = useState(this.props.flow);
  }
  onTitle(ev) {
    const title = ev.target.value;
    this.flow.values.title = title;
    if (!this.flow.values.nameTouched) {
      this.flow.values.name = slug(title);
    }
  }
  onName(ev) {
    this.flow.values.name = ev.target.value.trim();
    this.flow.values.nameTouched = true;
  }
}
function slug(text) {
  const base = (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return base && /^[a-z]/.test(base) ? base : base ? "x_" + base : "";
}
class WhereStep extends Component {
  static template = "app_builder_view.CreatePackageWhere";
  static props = { shell: Object, flow: Object };
  flow;
  orm;
  state;
  setup() {
    this.flow = useState(this.props.flow);
    this.orm = useService("orm");
    this.state = useState({ dirs: [] });
    onWillStart(async () => {
      this.state.dirs = await this.orm.call(
        "studio.workspace",
        "addons_dirs",
        []
      );
      const offered = this.state.dirs.filter((d) => d.writable);
      const first = offered[0];
      if (!this.flow.values.root_dir && first) {
        this.flow.values.root_dir = first.path;
      }
    });
  }
  get offered() {
    return this.state.dirs.filter((d) => d.kind !== "core");
  }
  get none() {
    return this.state.dirs.length > 0 && !this.offered.some((d) => d.writable);
  }
}
class GitStep extends Component {
  static template = "app_builder_view.CreatePackageGit";
  static props = { shell: Object, flow: Object };
  flow;
  setup() {
    this.flow = useState(this.props.flow);
    if (this.flow.values.git_init === void 0) {
      this.flow.values.git_init = true;
    }
    if (!this.flow.values.auto_commit) {
      this.flow.values.auto_commit = "stage";
    }
  }
  get autoCommitHint() {
    const key = this.flow.values.auto_commit ?? "stage";
    return String(
      {
        off: _t("Off: nothing is staged or committed; git is yours to run."),
        stage: _t(
          "Stage only: every write is staged; you commit from Changes with a message of your own."
        ),
        commit: _t(
          "Commit each change: every write is a commit, with a message the studio makes up."
        )
      }[key]
    );
  }
}
class ReviewStep extends Component {
  static template = "app_builder_view.CreatePackageReview";
  static props = { shell: Object, flow: Object };
  flow;
  setup() {
    this.flow = useState(this.props.flow);
  }
  get path() {
    const values = this.flow.values;
    return values.root_dir ? `${values.root_dir}/${values.name}` : values.name;
  }
}
paneRegistry.add("create_package", {
  // Lazy `_t` values, not `String(...)`: this runs at module load, before
  // translations exist (`PaneRegistration.label`).
  label: _t("Create a package"),
  icon: "fa fa-cube",
  scope: "package",
  tab: false,
  flow: {
    key: "create_package",
    title: _t("Create a package"),
    doneLabel: _t("Create package"),
    steps: [
      {
        key: "name",
        label: _t("Name"),
        Component: NameStep,
        validate: (values) => {
          if (!values.name) {
            return String(_t("The package needs a technical name."));
          }
          if (!/^[a-z][a-z0-9_]*$/.test(values.name)) {
            return String(
              _t(
                "'%s' is not a valid module name: lowercase letters, digits and underscores, starting with a letter.",
                values.name
              )
            );
          }
          return "";
        }
      },
      {
        key: "where",
        label: _t("Where"),
        Component: WhereStep,
        validate: (values) => values.root_dir ? "" : String(_t("No entry on the addons path can be written to."))
      },
      { key: "git", label: _t("Git"), Component: GitStep },
      { key: "review", label: _t("Review"), Component: ReviewStep }
    ],
    onDone: async (shell, flow) => {
      const values = flow.values;
      const created = await shell.orm.call(
        "studio.workspace",
        "create_package",
        [
          {
            name: values.name,
            title: values.title || values.name,
            summary: values.summary || "",
            root_dir: values.root_dir,
            git_init: Boolean(values.git_init),
            auto_commit: values.auto_commit || "stage"
          }
        ]
      );
      await shell.refreshPackages();
      await shell.setPackage(created.id);
      await shell.openPane("home", { created: created.id });
      return created;
    }
  }
});

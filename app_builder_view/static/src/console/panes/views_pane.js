import { Component, useEffect, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { registry } from "@web/core/registry";
import { StudioCanvas } from "../canvas";
import { SearchListsCanvas } from "../canvases/search_lists_canvas";
import { ConsoleModel } from "../console_model";
import { useService } from "../odoo";
import { paneRegistry } from "../shell/pane_registry";
import { AddTab } from "../sidebar/add_tab";
import { Outline } from "../sidebar/outline";
import { PropertiesTab } from "../sidebar/properties_tab";
import { removeWithConfirm } from "../sidebar/remove_flow";
import { ViewTab } from "../sidebar/view_tab";
const canvasRegistry = registry.category("app_builder.canvas");
canvasRegistry.add("canvas", StudioCanvas);
canvasRegistry.add("search_lists", SearchListsCanvas);
registry.category("app_builder.field_editor");
const SIDEBAR_TABS = [
  { key: "add", label: _t("Add") },
  { key: "view", label: _t("View") },
  { key: "properties", label: _t("Properties") }
];
class ViewsPane extends Component {
  static template = "app_builder_view.ViewsPane";
  static props = { shell: Object, model: { type: Object, optional: true } };
  // Assigned in `setup()`, which Owl calls synchronously right after
  // construction and before the first render -- always set by the time
  // any getter or template read runs (TYPING.md's own "Known traps").
  shell;
  model;
  dialog;
  setup() {
    this.shell = useState(this.props.shell);
    this.model = useState(this.props.model);
    this.dialog = useService("dialog");
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  get canvasComponent() {
    const key = this.model.editableAs;
    if (!canvasRegistry.contains(key)) {
      return StudioCanvas;
    }
    return (
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      canvasRegistry.get.call(
        canvasRegistry,
        key
      )
    );
  }
  get canvasProps() {
    const props = { model: this.model };
    if (this.canvasComponent === StudioCanvas) {
      props.onRemove = (token) => {
        void this.removeFromCanvas(token);
      };
    }
    return props;
  }
  async removeFromCanvas(token) {
    this.model.select(token);
    await removeWithConfirm({ model: this.model, dialog: this.dialog, token });
  }
}
class ViewsSidebar extends Component {
  static template = "app_builder_view.ViewsSidebar";
  static components = { Outline, AddTab, ViewTab, PropertiesTab };
  static props = { shell: Object, model: { type: Object, optional: true } };
  shell;
  model;
  state;
  setup() {
    this.shell = useState(this.props.shell);
    this.model = useState(this.props.model);
    this.state = useState({ tab: "add" });
    useEffect(
      (serial) => {
        if (serial) {
          this.state.tab = "properties";
        }
      },
      () => [this.model.selectionSerial]
    );
  }
  get tabs() {
    return SIDEBAR_TABS;
  }
  get packageMissing() {
    return Boolean(this.model.context) && !this.shell.packageId;
  }
  /** The outline lists a node table: what a rendered canvas has and a search view or a report has not. */
  get showOutline() {
    return Boolean(this.model.root) && this.model.editableAs === "canvas";
  }
}
paneRegistry.add(
  "views",
  {
    label: _t("Views"),
    icon: "fa fa-th-large",
    scope: "model",
    // A view id names its model: the cog and the systray send one
    // without the model, and the server tells the shell which it is.
    isAvailable: (ctx) => Boolean(ctx.modelName || ctx.view && ctx.view.view_id),
    Component: ViewsPane,
    sidebar: ViewsSidebar,
    // `PaneRegistration.makeModel` is a *property* typed as an arrow
    // function (`((shell: unknown) => PaneModel) | null`), checked
    // contravariantly under `strictFunctionTypes` -- the same shape
    // `changes_pane.ts`'s own `makeModel` already hit, and the same
    // fix: the callback's own `shell` parameter is left unannotated
    // so TS infers it from context (`unknown`), then cast once inside.
    // `StudioShell.env` (`ShellEnv`, `shell_model.ts`) structurally
    // satisfies `ConsoleModel`'s own constructor env parameter, widened
    // to carry `services.field`/`bus` once this file needed it to
    // construct a `ConsoleModel` here.
    makeModel: (shell) => new ConsoleModel(shell.env, shell)
  },
  { sequence: 10 }
);
export {
  SIDEBAR_TABS,
  ViewsPane,
  ViewsSidebar
};

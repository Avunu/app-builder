import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useBus } from "@web/core/utils/hooks";
import { useService } from "./odoo";
class StudioSystrayItem extends Component {
  static template = "app_builder_view.StudioSystrayItem";
  static props = {};
  // Assigned in `setup()`, not the constructor -- Owl's own idiom, and
  // the constructor here is entirely framework-driven -- so declared
  // with the definite-assignment assertion rather than given an
  // initializer or an `| undefined` that would make every read below
  // narrow for nothing.
  action;
  state;
  setup() {
    this.action = useService("action");
    this.state = useState({ allowed: false });
    onWillStart(async () => {
      this.state.allowed = await user.hasGroup("app_builder_base.group_studio_user");
    });
    useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.render());
  }
  /**
   * What the console would be opened on, or `null` when the screen is
   * not a view of a model.
   *
   * A controller restored from the URL may be a `virtual` placeholder
   * with an empty action and no props; a client action -- the console
   * among them -- has a tag and no `resModel`. Both are refused by the
   * one check on the action's type, the placeholder by its own flag too.
   */
  get target() {
    if (!this.state.allowed) {
      return null;
    }
    const ctrl = this.action.currentController;
    if (!ctrl || ctrl.virtual || !ctrl.action || !ctrl.props) {
      return null;
    }
    if (ctrl.action.type !== "ir.actions.act_window" || !ctrl.props.resModel) {
      return null;
    }
    const viewType = ctrl.props.type;
    const views = ctrl.action.views || [];
    const pinned = views.find((view) => view[1] === viewType);
    const state = ctrl.currentState || {};
    return {
      model: ctrl.props.resModel,
      view_type: viewType,
      view_id: pinned && pinned[0] || false,
      action_id: ctrl.action.id || false,
      res_id: state.resId || ctrl.props.resId || false
    };
  }
  get label() {
    return String(_t("Studio"));
  }
  get tooltip() {
    const target = this.target;
    return target ? String(_t("Edit this %s view in Studio", target.view_type)) : String(_t("Open Studio"));
  }
  /**
   * Open the console on the screen, on its Views pane. What the console
   * needs to come back to this screen after a reload it keeps in its
   * own URL, so nothing is mirrored into the context.
   */
  open() {
    const target = this.target;
    if (!target) {
      return;
    }
    void this.action.doAction({
      type: "ir.actions.client",
      tag: "app_builder_console",
      target: "fullscreen",
      name: String(_t("Studio")),
      params: { ...target, pane: "views" }
    });
  }
}
registry.category("systray").add(
  "app_builder.toggle",
  { Component: StudioSystrayItem, isDisplayed: () => true },
  {
    sequence: 5
  }
);
export {
  StudioSystrayItem
};

import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService, user } from "./odoo";
const EDITABLE_TYPES = [
  "list",
  "form",
  "kanban",
  "calendar",
  "search",
  "pivot",
  "graph",
  "timeline"
];
class EditThisView extends Component {
  static template = "app_builder_view.EditThisView";
  static components = { DropdownItem };
  static props = {};
  action;
  setup() {
    this.action = useService("action");
  }
  onEdit() {
    const config = this.env.config;
    const controller = this.action.currentController;
    const state = controller && controller.currentState || {};
    const resModel = config.resModel || controller && controller.action && controller.action.res_model;
    const params = {
      view_id: config.viewId || false,
      res_model: resModel,
      model: resModel,
      view_type: config.viewType,
      action_id: config.actionId || false,
      res_id: state.resId || false
    };
    void this.action.doAction({
      type: "ir.actions.client",
      tag: "app_builder_console",
      name: `Edit ${config.viewType} view`,
      // The action this view belongs to, as the action service holds
      // it -- context evaluated, search state on it -- so Close can
      // run it again for a list or kanban, whose restored controller
      // would otherwise read records with the fields it was opened
      // with and show a new one blank. In params only: an action
      // object is not context to send with every request, and not
      // something a URL carries. The rest the console keeps in its
      // own URL, so nothing is mirrored into the context.
      params: {
        ...params,
        pane: "views",
        previous_action: controller ? controller.action : null
      }
    });
  }
}
const editThisViewItem = {
  Component: EditThisView,
  groupNumber: 40,
  isDisplayed: async (env) => EDITABLE_TYPES.includes(env.config.viewType) && await user.hasGroup("app_builder_base.group_studio_user")
};
registry.category("cogMenu").add("app-builder-edit-view", editThisViewItem, {
  sequence: 40
});
export {
  EditThisView,
  editThisViewItem
};

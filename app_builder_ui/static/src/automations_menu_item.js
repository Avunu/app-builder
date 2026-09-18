import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@app_builder_view/console/odoo";
class StudioAutomations extends Component {
  static template = "app_builder_ui.StudioAutomations";
  static components = { DropdownItem };
  static props = {};
  action;
  orm;
  setup() {
    this.action = useService("action");
    this.orm = useService("orm");
  }
  /** The console, on its Automations pane for the model on screen. */
  onOpen() {
    void this.action.doAction({
      type: "ir.actions.client",
      tag: "app_builder_console",
      target: "fullscreen",
      name: String(_t("Studio")),
      params: {
        pane: "automations",
        res_model: this.env.config.resModel,
        action_id: this.env.config.actionId || false
      }
    });
  }
}
const studioAutomationsItem = {
  Component: StudioAutomations,
  groupNumber: 40,
  isDisplayed: async (env) => Boolean(env.config.resModel) && await user.hasGroup("app_builder_base.group_studio_user")
};
registry.category("cogMenu").add("app-builder-automations", studioAutomationsItem, { sequence: 41 });
export {
  StudioAutomations,
  studioAutomationsItem
};

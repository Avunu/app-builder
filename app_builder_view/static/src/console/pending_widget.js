import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
class PendingFieldWidget extends Component {
  static template = "app_builder_view.PendingFieldWidget";
  static props = {
    ...standardWidgetProps,
    name: { type: String, optional: true },
    label: { type: String, optional: true },
    ttype: { type: String, optional: true },
    resolved: { type: Boolean, optional: true }
  };
  get label() {
    return this.props.label || this.props.name || "";
  }
  get icon() {
    return iconForType(this.props.ttype, this.props.ttype);
  }
}
const TYPE_ICONS = {
  char: "fa fa-font",
  text: "fa fa-align-left",
  html: "fa fa-file-text-o",
  boolean: "fa fa-check-square-o",
  integer: "fa fa-hashtag",
  float: "fa fa-superscript",
  monetary: "fa fa-money",
  date: "fa fa-calendar",
  datetime: "fa fa-clock-o",
  selection: "fa fa-list-ul",
  binary: "fa fa-file-o",
  many2one: "fa fa-link",
  one2many: "fa fa-list",
  many2many: "fa fa-tags",
  reference: "fa fa-external-link",
  priority: "fa fa-star-o",
  image: "fa fa-picture-o",
  sign: "fa fa-pencil-square-o",
  daterange: "fa fa-calendar-o",
  tags: "fa fa-tags",
  lines: "fa fa-table",
  related: "fa fa-share"
};
function iconForType(key, ttype) {
  return (key !== void 0 ? TYPE_ICONS[key] : void 0) ?? (ttype !== void 0 ? TYPE_ICONS[ttype] : void 0) ?? "fa fa-square-o";
}
const pendingFieldWidget = {
  component: PendingFieldWidget,
  extractProps: ({ options }) => ({
    name: options.name,
    label: options.label,
    ttype: options.ttype,
    resolved: options.resolved !== false
  })
};
registry.category("view_widgets").add("app_builder_pending", pendingFieldWidget);
export {
  PendingFieldWidget,
  TYPE_ICONS,
  iconForType,
  pendingFieldWidget
};

import { registry } from "@web/core/registry";
import { StudioConsole } from "./shell/shell";
import "./panes/views_pane";
import "./panes/home_pane";
import "./panes/changes_pane";
import "./record_pane/record_pane";
import "./flows/flow";
registry.category("actions").add("app_builder_console", StudioConsole);
registry.category("actions").add("app_builder_view_wysiwyg", StudioConsole);
export {
  StudioConsole
};

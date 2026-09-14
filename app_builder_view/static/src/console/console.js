/** @odoo-module **/
/**
 * The console's action: the shell (`shell/shell.js`) under the tag every
 * entry point sends, and the panes this module ships.
 *
 * Importing the panes here is what registers them: the Views pane with
 * the canvas, Home, Changes, and the record-pane and flow hosts that
 * data-only registrations from other addons resolve to.
 */

import { registry } from "@web/core/registry";
import { StudioConsole } from "./shell/shell";
import "./panes/views_pane";
import "./panes/home_pane";
import "./panes/changes_pane";
import "./record_pane/record_pane";
import "./flows/flow";

export { StudioConsole };

registry.category("actions").add("app_builder_console", StudioConsole);
// The tag the cog item and the report action sent before the console
// existed, kept so a bookmarked URL and an older caller still open it.
registry.category("actions").add("app_builder_view_wysiwyg", StudioConsole);

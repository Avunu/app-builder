/** @odoo-module **/
/**
 * The console's action: the shell (`shell/shell.ts`) under the tag every
 * entry point sends, and the panes this module ships.
 *
 * This is the entry of the console's own bundle
 * (`app_builder_view.assets_console`), which `console_loader.ts` fetches
 * the first time the action is opened.
 *
 * Importing the panes here is what registers them: the Views pane with
 * the canvas, Home, Changes, and the record-pane and flow hosts that
 * data-only registrations from other addons resolve to.
 */

import {registry} from "@web/core/registry";
import {CONSOLE_TAGS} from "./console_loader";
import {BuilderConsole} from "./shell/shell";
import "./panes/views_pane";
import "./panes/home_pane";
import "./panes/changes_pane";
import "./record_pane/record_pane";
import "./flows/flow";

export {BuilderConsole};

// Forced, because both tags are already held: `console_loader.ts`, in
// `web.assets_backend`, registers under each a function that fetches this
// bundle and runs the action again -- against what is registered here.
// The category's item type is `ActionsRegistryItemShape` (`odoo.ts`).
for (const tag of CONSOLE_TAGS) {
  registry.category("actions").add(tag, BuilderConsole, {force: true});
}

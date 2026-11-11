/** @odoo-module **/
/**
 * The console's action: the shell (`shell/shell.ts`) under the tag every
 * entry point sends, and the panes this module ships.
 *
 * Importing the panes here is what registers them: the Views pane with
 * the canvas, Home, Changes, and the record-pane and flow hosts that
 * data-only registrations from other addons resolve to.
 */

import {registry} from "@web/core/registry";
import {BuilderConsole} from "./shell/shell";
import "./panes/views_pane";
import "./panes/home_pane";
import "./panes/changes_pane";
import "./record_pane/record_pane";
import "./flows/flow";

export {BuilderConsole};

// `registry.category("actions")` is core Odoo's own category, already
// declared for real (`ActionsRegistryItemShape` -- a plain component
// class, the same shape `app_builder.field_editor`/`app_builder.canvas`/
// `cogMenu`/`systray` already give a registry that only ever stores
// component classes) via the ambient ActionRegistry augmentation
// `@web/webclient/actions/action_registry.js` supplies, which `allowJs`
// picks up transitively -- no local or `odoo.ts` `declare module` needed,
// unlike `cogMenu`/`systray`/`view_widgets`, which are core categories
// this repo had to transcribe by hand (TYPING.md, "Known traps") because
// their own vendor `.d.ts` sits outside `tsconfig.json`'s `include`.
// Confirmed by this file compiling clean with no augmentation added.
registry.category("actions").add("app_builder_console", BuilderConsole);
// The tag the cog item and the report action sent before the console
// existed, kept so a bookmarked URL and an older caller still open it.
registry.category("actions").add("app_builder_view_wysiwyg", BuilderConsole);

/** @odoo-module **/
/**
 * The console's client action, as far as `web.assets_backend` knows it:
 * a function that fetches the console's own bundle and runs the action
 * again.
 *
 * Only people in the builder group ever open the console, and every
 * internal user downloads `web.assets_backend`; so the console is not in
 * it. What is: the systray item, the cog item, and this file, which holds
 * the console's two tags until the bundle has been fetched. Loading the
 * bundle runs `console.ts`, which registers the real component over each
 * tag; the action handed back is then executed against that.
 *
 * The action service accepts a function in place of a component
 * (`_executeClientAction`: whatever it returns is run as the next action)
 * and reads `target` and `path` off whatever is registered, function or
 * class. Both are repeated here, so the console is full-screen and owns
 * `/odoo/builder` before its code has arrived: a reload of that URL finds
 * the tag by its path, comes through this function, and lands where it
 * left off.
 */

import {loadBundle} from "@web/core/assets";
import {cookie} from "@web/core/browser/cookie";
import {registry} from "@web/core/registry";
import type {ActionDescription, ActionsRegistryItemShape} from "./odoo";

/** The bundle `app_builder_view/__manifest__.py` declares, and the other
 * builder addons add their panes to. */
export const CONSOLE_BUNDLE = "app_builder_view.assets_console";

/** The same files for a dark web client. `web/views/view.js` picks
 * `web.assets_backend_lazy_dark` over `web.assets_backend_lazy` the same
 * way, so the dark variables a theme or dark-mode addon contributes reach
 * the console's stylesheets too. */
export const CONSOLE_BUNDLE_DARK = "app_builder_view.assets_console_dark";

/** The bundle to fetch for the colour scheme the web client was served in
 * (`web/views/webclient_templates.xml` reads the same cookie). */
export function consoleBundle(): string {
  return cookie.get("color_scheme") === "dark" ? CONSOLE_BUNDLE_DARK : CONSOLE_BUNDLE;
}

/** The console's tag, and the one the cog item and the report action sent
 * before the console existed (a bookmarked URL and an older caller still
 * open it). */
export const CONSOLE_TAGS = ["app_builder_console", "app_builder_view_wysiwyg"];

const actionRegistry = registry.category("actions");

/**
 * The stand-in for `tag`: fetch the bundle, then hand the same action back
 * for the action service to run against what the bundle registered.
 *
 * If the bundle arrived and the tag is still this function, the console
 * did not register itself -- a build without the compiled `.js`, say.
 * Handing the action back then would loop through here for ever, so that
 * is an error with a sentence to it.
 */
export function makeConsoleLoader(tag: string): ActionsRegistryItemShape {
  const loader: ActionsRegistryItemShape = async (
    _env: unknown,
    action: ActionDescription
  ): Promise<ActionDescription> => {
    const bundle = consoleBundle();
    await loadBundle(bundle);
    // `null` is the default `Registry.get` falls back to: its JSDoc makes
    // the second argument required, though the code does not.
    if (actionRegistry.get(tag, null) === loader) {
      throw new Error(
        `The builder console's assets (${bundle}) loaded without registering "${tag}".`
      );
    }
    return {...action};
  };
  loader.target = "fullscreen";
  loader.path = "builder";
  return loader;
}

/** What this module registers under each tag, exported so the tests can
 * read what the action service finds there before the console arrives. */
export const CONSOLE_LOADERS: ReadonlyArray<{
  tag: string;
  loader: ActionsRegistryItemShape;
}> = CONSOLE_TAGS.map((tag) => ({tag, loader: makeConsoleLoader(tag)}));

// `console.ts` imports this module, so this always runs first, and the
// console's forced registration replaces these once its bundle has loaded.
for (const {tag, loader} of CONSOLE_LOADERS) {
  actionRegistry.add(tag, loader);
}

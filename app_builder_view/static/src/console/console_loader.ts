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
import {registry} from "@web/core/registry";
import type {ActionDescription, ActionsRegistryItemShape} from "./odoo";

/** The bundle `app_builder_view/__manifest__.py` declares, and the other
 * builder addons add their panes to. */
export const CONSOLE_BUNDLE = "app_builder_view.assets_console";

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
    await loadBundle(CONSOLE_BUNDLE);
    // `null` is the default `Registry.get` falls back to: its JSDoc makes
    // the second argument required, though the code does not.
    if (actionRegistry.get(tag, null) === loader) {
      throw new Error(
        `The builder console's assets (${CONSOLE_BUNDLE}) loaded without registering "${tag}".`
      );
    }
    return {...action};
  };
  loader.target = "fullscreen";
  loader.path = "builder";
  return loader;
}

for (const tag of CONSOLE_TAGS) {
  // Not forced: where the console's bundle is already on the page (the
  // hoot runner includes it in its setup), `console.ts` may have run
  // first, and its registration is the one to keep.
  if (!actionRegistry.contains(tag)) {
    actionRegistry.add(tag, makeConsoleLoader(tag));
  }
}

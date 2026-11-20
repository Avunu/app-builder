/** @odoo-module **/
/**
 * The function that stands in for the console's action until its bundle
 * has been fetched (`console/console_loader.ts`).
 *
 * `web.assets_backend` holds this and not the console; so what is pinned
 * is what the action service needs of it before any of the console's code
 * has arrived -- that both tags are held, full-screen and on the console's
 * path -- and what it does when run: fetch the bundle, hand the action
 * back, and refuse to loop if the bundle registered nothing.
 */

import {expect, test} from "@odoo/hoot";
import {patchWithCleanup} from "@web/../tests/web_test_helpers";

import {assets} from "@web/core/assets";
import {registry} from "@web/core/registry";
import {
  CONSOLE_BUNDLE,
  CONSOLE_TAGS,
  makeConsoleLoader,
} from "@app_builder_view/console/console_loader";
import type {
  ActionDescription,
  ActionsRegistryItemShape,
} from "@app_builder_view/console/odoo";

const actionRegistry = registry.category("actions");

/** The loader, called the way the action service calls a function it
 * finds registered under a client action's tag. */
type Loader = (env: unknown, action: ActionDescription) => Promise<ActionDescription>;

const ACTION: ActionDescription = {
  type: "ir.actions.client",
  tag: "app_builder_test_console",
  params: {pane: "views"},
};

test("both tags are held, full-screen and on /odoo/builder, before the console loads", () => {
  for (const tag of CONSOLE_TAGS) {
    expect(actionRegistry.contains(tag)).toBe(true);
  }
  const loader = makeConsoleLoader("app_builder_test_console");
  // What the action service reads off whatever is registered, function
  // or class: without them a reload of the console's URL finds nothing.
  expect(loader.target).toBe("fullscreen");
  expect(loader.path).toBe("builder");
});

test("the loader fetches the console's bundle and hands the action back", async () => {
  const tag = "app_builder_test_console";
  const loaded: string[] = [];
  const loader = makeConsoleLoader(tag);
  actionRegistry.add(tag, loader, {force: true});
  patchWithCleanup(assets, {
    loadBundle(bundle: string) {
      loaded.push(bundle);
      // What `console.ts` does when the bundle runs: the real component
      // over the tag the loader held.
      const real: ActionsRegistryItemShape = () => undefined;
      actionRegistry.add(tag, real, {force: true});
      return Promise.resolve([]);
    },
  });
  const next = await (loader as Loader)({}, ACTION);
  expect(loaded).toEqual([CONSOLE_BUNDLE]);
  // The same action, to be run again -- as a copy, since the service
  // prepares whatever it is given.
  expect(next).toEqual(ACTION);
  expect(next).not.toBe(ACTION);
  actionRegistry.remove(tag);
});

test("a bundle that registers nothing is an error, not a loop", async () => {
  const tag = "app_builder_test_console";
  const loader = makeConsoleLoader(tag);
  actionRegistry.add(tag, loader, {force: true});
  patchWithCleanup(assets, {
    loadBundle: () => Promise.resolve([]),
  });
  await expect((loader as Loader)({}, ACTION)).rejects.toThrow(/without registering/);
  actionRegistry.remove(tag);
});

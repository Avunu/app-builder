import { expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
  getMockEnv,
  makeMockEnv,
  mockService,
  mountWithCleanup,
  onRpc,
  patchWithCleanup
} from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";
import { StudioSystrayItem } from "@app_builder_view/console/systray_item";
onRpc("has_group", () => true);
const FORM_CONTROLLER = {
  action: {
    id: 42,
    type: "ir.actions.act_window",
    res_model: "res.partner",
    views: [
      [false, "list"],
      [7, "form"]
    ]
  },
  props: { resModel: "res.partner", type: "form", resId: 3 },
  currentState: { resId: 5 }
};
const CONSOLE_CONTROLLER = {
  action: { type: "ir.actions.client", tag: "app_builder_console" },
  props: { action: { tag: "app_builder_console" } },
  currentState: {}
};
const mockActionService = mockService;
function stubActionService(controller) {
  const holder = { controller, actions: [] };
  mockActionService("action", () => ({
    get currentController() {
      return holder.controller ?? void 0;
    },
    doAction(action) {
      holder.actions.push(action);
      return Promise.resolve(true);
    },
    // Not exercised by any test here (`systray_item.ts` itself never
    // calls it) -- present only to satisfy `ActionService`'s shape.
    restore() {
      return Promise.resolve(void 0);
    }
  }));
  return holder;
}
async function mountItem() {
  if (!getMockEnv()) {
    await makeMockEnv();
  }
  return mountWithCleanup(StudioSystrayItem);
}
test("nothing is offered outside the studio group", async () => {
  patchWithCleanup(user, { hasGroup: async () => false });
  stubActionService(FORM_CONTROLLER);
  await mountItem();
  expect(".o_studio_systray_toggle").toHaveCount(0);
});
test("a window action gets the toggle; a client action and a placeholder do not", async () => {
  const holder = stubActionService(CONSOLE_CONTROLLER);
  const item = await mountItem();
  expect(".o_studio_systray_toggle").toHaveCount(0);
  holder.controller = FORM_CONTROLLER;
  item.env.bus.trigger("ACTION_MANAGER:UI-UPDATED", "current");
  await animationFrame();
  expect(".o_studio_systray_toggle").toHaveCount(1);
  expect(queryOne(".o_studio_systray_toggle")).toHaveAttribute(
    "data-tooltip",
    "Edit this form view in Studio"
  );
  holder.controller = { virtual: true, action: {}, props: {}, currentState: {} };
  item.env.bus.trigger("ACTION_MANAGER:UI-UPDATED", "current");
  await animationFrame();
  expect(".o_studio_systray_toggle").toHaveCount(0);
  holder.controller = null;
  item.env.bus.trigger("ACTION_MANAGER:UI-UPDATED", "current");
  await animationFrame();
  expect(".o_studio_systray_toggle").toHaveCount(0);
});
test("the toggle opens the console on what is on screen", async () => {
  const holder = stubActionService(FORM_CONTROLLER);
  await mountItem();
  await click(".o_studio_systray_toggle");
  await animationFrame();
  expect(holder.actions).toHaveLength(1);
  const action = holder.actions[0];
  expect(action.type).toBe("ir.actions.client");
  expect(action.tag).toBe("app_builder_console");
  expect(action.target).toBe("fullscreen");
  expect(action.params).toEqual({
    pane: "views",
    model: "res.partner",
    view_type: "form",
    // The id the action pins for this type; `false` when it pins none,
    // and the server resolves the default view.
    view_id: 7,
    action_id: 42,
    // The record the form is on now, not the one the action opened.
    res_id: 5
  });
  expect(action.context).toBe(void 0);
});
test("an unpinned view and a list send no view id and no record", async () => {
  const holder = stubActionService({
    action: { id: 42, type: "ir.actions.act_window", views: [[false, "list"]] },
    props: { resModel: "res.partner", type: "list" },
    currentState: { resId: false }
  });
  await mountItem();
  await click(".o_studio_systray_toggle");
  await animationFrame();
  expect(holder.actions[0].params).toEqual({
    pane: "views",
    model: "res.partner",
    view_type: "list",
    view_id: false,
    action_id: 42,
    res_id: false
  });
});

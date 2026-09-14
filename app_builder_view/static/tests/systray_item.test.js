/** @odoo-module **/
/**
 * The Studio toggle in the systray.
 *
 * Everything the item decides, it decides from `actionService
 * .currentController`, and everything it sends the console it derives from
 * that controller; so the action service is stubbed with a controller the
 * test controls and the item is mounted on its own. What is pinned: the
 * item is empty for someone outside the studio group, empty on a client
 * action and on a virtual placeholder, present on a window action, follows
 * navigation when the action manager announces a new controller, and opens
 * the console with the model, the view type, the pinned view id, the action
 * and the record on screen.
 */

import { expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    getMockEnv,
    makeMockEnv,
    mockService,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
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
            [7, "form"],
        ],
    },
    props: { resModel: "res.partner", type: "form", resId: 3 },
    currentState: { resId: 5 },
};

const CONSOLE_CONTROLLER = {
    action: { type: "ir.actions.client", tag: "app_builder_console" },
    props: { action: { tag: "app_builder_console" } },
    currentState: {},
};

/** Stub the action service with a controller the test can swap. */
function stubActionService(controller) {
    const holder = { controller, actions: [] };
    mockService("action", () => ({
        get currentController() {
            return holder.controller;
        },
        doAction(action) {
            holder.actions.push(action);
            return Promise.resolve(true);
        },
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

    // Navigation: the action manager announces the new controller once it
    // is mounted, and the item re-reads the stack.
    holder.controller = FORM_CONTROLLER;
    item.env.bus.trigger("ACTION_MANAGER:UI-UPDATED", "current");
    await animationFrame();
    expect(".o_studio_systray_toggle").toHaveCount(1);
    expect(queryOne(".o_studio_systray_toggle")).toHaveAttribute(
        "data-tooltip",
        "Edit this form view in Studio"
    );

    // A controller restored from the URL, not yet loaded.
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
    const [action] = holder.actions;
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
        res_id: 5,
    });
    // Nothing mirrored into the context: the console keeps what it needs
    // to come back after a reload in its own URL.
    expect(action.context).toBe(undefined);
});

test("an unpinned view and a list send no view id and no record", async () => {
    const holder = stubActionService({
        action: { id: 42, type: "ir.actions.act_window", views: [[false, "list"]] },
        props: { resModel: "res.partner", type: "list" },
        currentState: { resId: false },
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
        res_id: false,
    });
});

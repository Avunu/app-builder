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
import type {
    ActionController,
    ActionDescription,
    ActionService,
} from "@app_builder_view/console/odoo";
import { StudioSystrayItem } from "@app_builder_view/console/systray_item";

onRpc("has_group", () => true);

const FORM_CONTROLLER: ActionController = {
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

const CONSOLE_CONTROLLER: ActionController = {
    action: { type: "ir.actions.client", tag: "app_builder_console" },
    props: { action: { tag: "app_builder_console" } },
    currentState: {},
};

/** What `stubActionService` hands back: the controller the test can swap,
 * and every action the stubbed `doAction` was asked to run. `controller` is
 * `| null`, matching the real test's own `holder.controller = null` --
 * `ActionService.currentController` itself (`console/odoo.ts`) is
 * `| undefined`, not `| null`; the stub's own getter, below, converts at
 * the boundary rather than widening the shared type for one test file. */
interface ActionHolder {
    controller: ActionController | null;
    actions: ActionDescription[];
}

/**
 * `mockService`'s own real signature (`web_test_helpers.js`'s
 * `env_test_helpers.js`) types `serviceFactory` against the real, full
 * `ServiceFactories["action"]` shape -- `@types/services.d.ts`'s own
 * `typeof`-of-the-real-implementation cascade that TYPING.md's "Known
 * traps" already keeps out of this project's `tsconfig.json` `include` for
 * exactly this reason (it would pull the whole webclient into the program
 * to type one call). This stub only ever needs to satisfy
 * `systray_item.ts`'s own narrower `ActionService` facade
 * (`console/odoo.ts`) -- the same shape the component itself is written
 * against -- so `mockService` is re-typed locally to that shape instead,
 * the same "narrow, hand-traced escape hatch over a vendor boundary" move
 * already established for `queryFirst`/`useDragAndDrop`
 * (TYPING.md, "Known traps").
 */
const mockActionService = mockService as unknown as (
    name: "action",
    serviceFactory: () => ActionService,
) => void;

/** Stub the action service with a controller the test can swap. */
function stubActionService(controller: ActionController | null): ActionHolder {
    const holder: ActionHolder = { controller, actions: [] };
    mockActionService("action", () => ({
        get currentController() {
            return holder.controller ?? undefined;
        },
        doAction(action: ActionDescription) {
            holder.actions.push(action);
            return Promise.resolve(true);
        },
    }));
    return holder;
}

async function mountItem(): Promise<StudioSystrayItem> {
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
        "Edit this form view in Studio",
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
    // `toHaveLength(1)` above is this element's own guarantee that index 0
    // exists; `noUncheckedIndexedAccess` cannot see that, so asserted once
    // here rather than at every read below.
    const action = holder.actions[0]!;
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
    // to come back after a reload in its own URL. `ActionDescription`
    // (`console/odoo.ts`) has no `context` member at all -- no real caller
    // in this tree ever sends one -- so there is no typed member to read;
    // widened locally for this one assertion, whose whole point is that
    // absence.
    expect((action as ActionDescription & { context?: unknown }).context).toBe(undefined);
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
    expect(holder.actions[0]!.params).toEqual({
        pane: "views",
        model: "res.partner",
        view_type: "list",
        view_id: false,
        action_id: 42,
        res_id: false,
    });
});

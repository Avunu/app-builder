/** @odoo-module **/
/**
 * The version seam, and the hook contract behind it.
 *
 * `compat.js` is the one module allowed to know which Odoo it runs on, and
 * each of its answers is a claim about core that was checked by reading
 * three checkouts. These tests pin the claims that can be checked from a
 * test run: that the three lines are told apart by the numbers the servers
 * actually carry -- master says `19.5`, not `20` -- that each shim gives
 * each line its shape, and that the drag hook still lives where the console
 * imports it from, takes the params the console hands it, and refuses a
 * wrong one. A port to the next branch that moves the hook or renames a
 * param fails here, in one place, before any drag is attempted.
 */

import { expect, getFixture, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    getMockEnv,
    makeMockEnv,
    MockServer,
    models,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { rpcBus } from "@web/core/network/rpc";
import { session } from "@web/session";

import { useDragAndDrop } from "@html_editor/utils/drag_and_drop";
import { View } from "@web/views/view";
import * as compat from "@app_builder_view/console/compat";

/**
 * The one shape read off hoot's mock server here: `MockServer.env` is the
 * vendored Proxy-backed server environment (`mock_server.js:makeServerEnv`),
 * whose model handles come back through the vendor "error" type. A model's
 * `fields_get()` (`mock_model.js`) returns its field-definition map.
 */
interface MockModelHandle {
    fields_get(): Record<string, Record<string, unknown>>;
}

/**
 * Owl's `EventBus` (an `EventTarget` subclass, `@odoo/owl`) as this test
 * uses it. Both `env.bus` and `rpcBus` (`core/network/rpc.js`) reach us
 * through the vendor "error" type, so each is cast to this once.
 */
interface ListenableBus {
    addEventListener(type: string, listener: (ev: Event) => void): void;
    removeEventListener(type: string, listener: (ev: Event) => void): void;
}

class Partner extends models.Model {
    // `mock_fields.js`'s `makeFieldGenerator` returns `{ [name](props) {...} }
    // [name]` -- a self-indexing extraction, so its own type is an index
    // signature keyed by a plain (non-literal) `string`, and every one of
    // its named exports (`Char`, `Integer`, ...) reads back as
    // `(...) => FieldDefinition | undefined` under `noUncheckedIndexedAccess`.
    // The function always exists at runtime (that is the whole point of
    // the idiom); `!` says so at each call site rather than pretending the
    // vendor type is tighter than it is.
    name = fields.Char!();
    // `Model` (hoot's mock-server base class) already declares an instance
    // `_records` field of its own (`Partial<ModelRecord>[]`, read by the
    // static `_records` accessor pair) -- `override` is required under
    // `noImplicitOverride` the moment this class is type-checked as `.ts`,
    // even though nothing about this field's *runtime* behavior changes.
    override _records = [{ id: 1, name: "Ada" }];
}

defineModels([Partner]);

onRpc("has_group", () => true);

/**
 * The shape `session.server_version_info` takes on the wire: digit-bearing
 * parts (the major sometimes a `saas~xx` string, per `odoo/release.py`) in
 * an array of unspecified length, or `undefined` when the session carries
 * none at all. `compat.ts` keeps the same shape privately as its own
 * `VersionPart`/`VersionInfo` and does not export either -- this test keeps
 * its own copy rather than reaching into an unexported type.
 */
type ServerVersionInfo = readonly (string | number)[] | undefined;

/** Run `fn` with the server claiming to be `info`. */
function asServer<T>(info: ServerVersionInfo, fn: () => T): T {
    patchWithCleanup(session, { server_version_info: info });
    return fn();
}

const V18 = [18, 0, 0, "final", 0, ""];
const V19 = [19, 0, 0, "final", 0, ""];
// What master's `odoo/release.py:15` reads: the branch that becomes 20.
const MASTER = [19, 5, 0, "alpha", 1, ""];

test("the three lines are told apart by the numbers the servers carry", () => {
    asServer(V18, () => {
        expect(compat.serverVersion()).toEqual([18, 0]);
        expect(compat.versionAtLeast(18)).toBe(true);
        expect(compat.versionAtLeast(19)).toBe(false);
    });
    asServer(V19, () => {
        expect(compat.versionAtLeast(19)).toBe(true);
        expect(compat.versionAtLeast(19, 5)).toBe(false);
        expect(compat.versionAtLeast(20)).toBe(false);
    });
    asServer(MASTER, () => {
        expect(compat.serverVersion()).toEqual([19, 5]);
        expect(compat.versionAtLeast(19, 5)).toBe(true);
        expect(compat.versionAtLeast(19, 6)).toBe(false);
    });
    // A saas build spells its major `saas~NN` (`odoo/release.py` 19:14):
    // the digits name the line, not the prefix.
    asServer(["saas~19", 2, 0, "final", 0, ""], () => {
        expect(compat.serverVersion()).toEqual([19, 2]);
        expect(compat.versionAtLeast(19)).toBe(true);
        expect(compat.versionAtLeast(19, 5)).toBe(false);
    });
    // A session that does not say is read as 18, the branch this is written
    // on -- minor included, whatever it carried without a major.
    asServer(undefined, () => {
        expect(compat.serverVersion()).toEqual([18, 0]);
    });
    asServer(["saas", 3, 0, "final", 0, ""], () => {
        expect(compat.serverVersion()).toEqual([18, 0]);
    });
});

test("the drag ref is the object in 18 and 19, and a function on master", () => {
    const ref: compat.DragRef = { el: document.createElement("div") };
    asServer(V18, () => expect(compat.dragRef(ref)).toBe(ref));
    asServer(V19, () => expect(compat.dragRef(ref)).toBe(ref));
    asServer(MASTER, () => {
        const shimmed = compat.dragRef(ref);
        expect(typeof shimmed).toBe("function");
        // `expect(typeof shimmed).toBe("function")` above is the real
        // assertion; tsc's control flow analysis does not narrow a union
        // from a value handed to a test helper, so the call below is cast
        // back to the function half of `DragRef | (() => ...)` that the
        // assertion just confirmed it is.
        expect((shimmed as () => HTMLElement | null)()).toBe(ref.el);
    });
});

test("a form is told to render read-only by the prop its branch has", () => {
    asServer(V18, () => expect(compat.readonlyViewProps()).toEqual({ mode: "readonly" }));
    asServer(V19, () => expect(compat.readonlyViewProps()).toEqual({ readonly: true }));
    asServer(MASTER, () => expect(compat.readonlyViewProps()).toEqual({ readonly: true }));
});

test("the read-only props render this server's form read-only", async () => {
    if (!getMockEnv()) {
        await makeMockEnv();
    }
    // `MockServer.env`'s static getter is itself possibly `undefined`, and
    // its `[modelName: string]: Model` index signature reads as possibly
    // `undefined` again under `noUncheckedIndexedAccess` -- both `!`s are
    // asserting what `if (!getMockEnv()) { await makeMockEnv(); }` above
    // already guarantees at runtime. `.partner` (an index-signature member,
    // not a declared one) needs bracket notation under
    // `noPropertyAccessFromIndexSignature`.
    const modelFields = (MockServer.env as unknown as Record<string, MockModelHandle>)[
        "partner"
    ]!.fields_get();
    await mountWithCleanup(View, {
        props: {
            type: "form" as const,
            resModel: "partner",
            arch: `<form><field name="name"/></form>`,
            fields: modelFields,
            relatedModels: { partner: { fields: modelFields } },
            context: {},
            noBreadcrumbs: true,
            display: { controlPanel: false },
            resId: 1,
            ...compat.readonlyViewProps(),
        },
    });
    // The class the form compiler puts on the renderer when the record is
    // not in edition, in 18, 19 and master alike.
    expect(queryOne(".o_form_renderer")).toHaveClass("o_form_readonly");
    expect(queryOne(".o_form_renderer")).not.toHaveClass("o_form_editable");
});

test("a tab is found whether it is a link or a button", () => {
    // `getFixture()` (`hoot.js`) is `HTMLElement | null` before a fixture
    // exists; every test here runs after one is mounted, so `!` at each
    // declaration matches that guarantee rather than threading a null
    // check through code that can never actually see one.
    const fixture = getFixture()!;
    fixture.innerHTML = `
        <div class="o_notebook">
            <a class="nav-link" name="one" href="#">One</a>
            <button class="nav-link" name="two" type="button">Two</button>
        </div>
        <a class="nav-link" name="elsewhere" href="#">Not a tab</a>`;
    const tabs = [...fixture.querySelectorAll(compat.TAB_SELECTOR)];
    expect(tabs.map((tab) => tab.getAttribute("name"))).toEqual(["one", "two"]);
});

test("a field's row on master: sibling cells, and the inline wrapper of a boolean", () => {
    const fixture = getFixture()!;
    fixture.innerHTML = `
        <div class="o_inner_group" style="display:grid;grid-template-columns:100px 200px;width:300px">
            <div class="o_cell o_wrap_label"><label class="o_form_label">Name</label></div>
            <div class="o_cell o_wrap_input"><div class="o_field_widget" name="name">Ada</div></div>
            <div class="o_wrap_field_inline" style="display:contents">
                <div class="o_cell o_wrap_label"><label class="o_form_label">Active</label></div>
                <div class="o_cell o_no_box o_wrap_input"><div class="o_field_widget" name="active">x</div></div>
            </div>
        </div>`;
    const [name, active] = fixture.querySelectorAll(".o_field_widget");
    const [nameLabel, activeLabel] = fixture.querySelectorAll(".o_wrap_label");
    // The row is a DOM fact, not a version one: the same answer whatever
    // the server says it is.
    for (const info of [V18, V19, MASTER]) {
        asServer(info, () => {
            const nameRect = compat.rowRect(name!);
            expect(nameRect.left).toBe(nameLabel!.getBoundingClientRect().left);
            expect(nameRect.width).toBe(300);
            const activeRect = compat.rowRect(active!);
            expect(activeRect.left).toBe(activeLabel!.getBoundingClientRect().left);
            expect(activeRect.width).toBe(300);
            expect(activeRect.top).toBeGreaterThan(nameRect.top);
        });
    }
});

test("both view caches are told to clear, whichever bus this server listens on", async () => {
    if (!getMockEnv()) {
        await makeMockEnv();
    }
    // Same guarantee as above: `getMockEnv()` returns `OdooEnv | null`, and
    // the guard just above already ensures it is set.
    const env = getMockEnv()!;
    const envBus = env.bus as unknown as ListenableBus;
    const rpcEvents = rpcBus as unknown as ListenableBus;
    const heard: string[] = [];
    const onEnvBus = () => heard.push("env");
    // `EventTarget#addEventListener`'s callback is typed against `Event`,
    // not `CustomEvent` -- typing the parameter itself as `CustomEvent`
    // fails tsc's contravariant check on the listener parameter, so `ev`
    // stays `Event` and the `.detail` read is cast, matching what
    // `EventBus#trigger` (`@odoo/owl`) actually dispatches.
    const onRpcBus = (ev: Event) => heard.push(`rpc:${(ev as CustomEvent<string>).detail}`);
    envBus.addEventListener("CLEAR-CACHES", onEnvBus);
    rpcEvents.addEventListener("CLEAR-CACHES", onRpcBus);
    try {
        compat.clearViewCaches(env);
    } finally {
        envBus.removeEventListener("CLEAR-CACHES", onEnvBus);
        rpcEvents.removeEventListener("CLEAR-CACHES", onRpcBus);
    }
    expect(heard.sort()).toEqual(["env", "rpc:get_views"]);
});

test("a stale view and a confirmation are told apart by what the RPC layer keeps", () => {
    const stale = { data: { name: "odoo.addons.app_builder_view.exceptions.StudioStaleView" } };
    const confirm = {
        data: { name: "odoo.exceptions.UserError", context: { confirm_required: true, count: 4 } },
    };
    const plain = { data: { name: "odoo.exceptions.UserError", message: "no" } };
    expect(compat.isStaleError(stale)).toBe(true);
    expect(compat.isStaleError(confirm)).toBe(false);
    expect(compat.isStaleError(undefined)).toBe(false);
    expect(compat.isConfirmError(confirm)).toBe(true);
    expect(compat.isConfirmError(stale)).toBe(false);
    expect(compat.isConfirmError(plain)).toBe(false);
});

/** The params `drag.js` hands the hook, shaped for this server. */
function hookParams(rootEl: HTMLElement, overrides: Record<string, unknown> = {}) {
    return {
        ref: compat.dragRef({ el: rootEl }),
        elements: ".o_studio_tile",
        ignore: ".o_resize",
        preventDrag: () => false,
        tolerance: 5,
        delay: 0,
        cursor: "grabbing",
        scrollingElement: () => rootEl,
        edgeScrolling: { enabled: false },
        dropzones: () => [],
        helper: () => document.createElement("div"),
        onDragStart: () => {},
        onDrag: () => {},
        dropzoneOver: () => {},
        dropzoneOut: () => {},
        onDragEnd: () => {},
        ...compat.dragExtraParams(),
        ...overrides,
    };
}

test("the drag hook is where the console imports it from and takes what it is handed", () => {
    const fixture = getFixture()!;
    const rootEl = document.createElement("div");
    fixture.appendChild(rootEl);
    expect(typeof useDragAndDrop).toBe("function");

    // Created outside any component, the way `drag.js` does in `onMounted`:
    // the hook is Owl-free and validates its params on the spot.
    const hook = useDragAndDrop(hookParams(rootEl));
    try {
        expect(typeof hook.destroy).toBe("function");
        expect(typeof hook.update).toBe("function");
        expect(hook.state.dragging).toBe(false);
        expect(rootEl).toHaveClass("o_draggable");
    } finally {
        hook.destroy();
    }
    expect(rootEl).not.toHaveClass("o_draggable");
});

test("the hook's validator is real: a wrong-typed param throws at setup", () => {
    const fixture = getFixture()!;
    const rootEl = document.createElement("div");
    fixture.appendChild(rootEl);
    // `dropzones` is a function in 18, 19 and master; an array is refused
    // by the same check that would refuse a `ref` of the wrong shape.
    expect(() => useDragAndDrop(hookParams(rootEl, { dropzones: [] }))).toThrow();
    // A `helper` is what makes it the html_editor hook rather than the
    // plain draggable: an object is not one.
    expect(() => useDragAndDrop(hookParams(rootEl, { helper: {} }))).toThrow();
});

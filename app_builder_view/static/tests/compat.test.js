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

class Partner extends models.Model {
    name = fields.Char();
    _records = [{ id: 1, name: "Ada" }];
}

defineModels([Partner]);

onRpc("has_group", () => true);

/** Run `fn` with the server claiming to be `info`. */
function asServer(info, fn) {
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
    const ref = { el: document.createElement("div") };
    asServer(V18, () => expect(compat.dragRef(ref)).toBe(ref));
    asServer(V19, () => expect(compat.dragRef(ref)).toBe(ref));
    asServer(MASTER, () => {
        const shimmed = compat.dragRef(ref);
        expect(typeof shimmed).toBe("function");
        expect(shimmed()).toBe(ref.el);
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
    const modelFields = MockServer.env.partner.fields_get();
    await mountWithCleanup(View, {
        props: {
            type: "form",
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
    const fixture = getFixture();
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
    const fixture = getFixture();
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
            const nameRect = compat.rowRect(name);
            expect(nameRect.left).toBe(nameLabel.getBoundingClientRect().left);
            expect(nameRect.width).toBe(300);
            const activeRect = compat.rowRect(active);
            expect(activeRect.left).toBe(activeLabel.getBoundingClientRect().left);
            expect(activeRect.width).toBe(300);
            expect(activeRect.top).toBeGreaterThan(nameRect.top);
        });
    }
});

test("both view caches are told to clear, whichever bus this server listens on", async () => {
    if (!getMockEnv()) {
        await makeMockEnv();
    }
    const env = getMockEnv();
    const heard = [];
    const onEnvBus = () => heard.push("env");
    const onRpcBus = (ev) => heard.push(`rpc:${ev.detail}`);
    env.bus.addEventListener("CLEAR-CACHES", onEnvBus);
    rpcBus.addEventListener("CLEAR-CACHES", onRpcBus);
    try {
        compat.clearViewCaches(env);
    } finally {
        env.bus.removeEventListener("CLEAR-CACHES", onEnvBus);
        rpcBus.removeEventListener("CLEAR-CACHES", onRpcBus);
    }
    expect(heard.sort()).toEqual(["env", "rpc:get_views"]);
});

test("a stale view and a confirmation are told apart by what the RPC layer keeps", () => {
    const stale = { data: { name: "odoo.addons.app_builder_view.exceptions.StudioStaleView" } };
    const confirm = { data: { name: "odoo.exceptions.UserError", context: { confirm_required: true, count: 4 } } };
    const plain = { data: { name: "odoo.exceptions.UserError", message: "no" } };
    expect(compat.isStaleError(stale)).toBe(true);
    expect(compat.isStaleError(confirm)).toBe(false);
    expect(compat.isStaleError(undefined)).toBe(false);
    expect(compat.isConfirmError(confirm)).toBe(true);
    expect(compat.isConfirmError(stale)).toBe(false);
    expect(compat.isConfirmError(plain)).toBe(false);
});

/** The params `drag.js` hands the hook, shaped for this server. */
function hookParams(rootEl, overrides = {}) {
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
    const fixture = getFixture();
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
    const fixture = getFixture();
    const rootEl = document.createElement("div");
    fixture.appendChild(rootEl);
    // `dropzones` is a function in 18, 19 and master; an array is refused
    // by the same check that would refuse a `ref` of the wrong shape.
    expect(() => useDragAndDrop(hookParams(rootEl, { dropzones: [] }))).toThrow();
    // A `helper` is what makes it the html_editor hook rather than the
    // plain draggable: an object is not one.
    expect(() => useDragAndDrop(hookParams(rootEl, { helper: {} }))).toThrow();
});

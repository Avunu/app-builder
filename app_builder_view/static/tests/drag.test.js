/** @odoo-module **/
/**
 * Picking up and putting down, against the real drag hook.
 *
 * `drag.js` sits on `useDragAndDrop` and on a handful of things the hook
 * does not say: that five pixels of travel start the drag, that the
 * helper's box is what the zones are matched against, that any key ends
 * the drag with the last zone still set, that the body takes no pointer
 * events meanwhile. Each of those is pinned here on a form the real
 * compiler rendered, inside a console-shaped root with a palette beside
 * it, with a model that records what it is asked to drop and does not
 * talk to any server.
 */

import { after, expect, test } from "@odoo/hoot";
import {
    advanceTime,
    animationFrame,
    drag,
    hover,
    press,
    queryAll,
    queryFirst,
    queryOne,
} from "@odoo/hoot-dom";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    getMockEnv,
    makeMockEnv,
    MockServer,
    models,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";

import { View } from "@web/views/view";
import * as compat from "@app_builder_view/console/compat";
import { TAB_DWELL_MS, makeCanvasDrag } from "@app_builder_view/console/drag";
import { Overlay } from "@app_builder_view/console/overlay";

class Partner extends models.Model {
    name = fields.Char();
    city = fields.Char();
    sequence = fields.Integer();
    _records = [{ id: 1, name: "Ada", city: "London", sequence: 1 }];
}

defineModels([Partner]);

onRpc("has_group", () => true);

const ARCH = `
    <form class="o_studio_n_0">
        <sheet class="o_studio_n_1">
            <group class="o_studio_n_2">
                <group class="o_studio_n_3">
                    <field name="name" class="o_studio_n_4"/>
                    <field name="city" class="o_studio_n_5"/>
                </group>
                <group class="o_studio_n_6"/>
            </group>
            <notebook class="o_studio_n_7">
                <page name="one" string="One" class="o_studio_n_8">
                    <field name="sequence" class="o_studio_n_9"/>
                </page>
                <page name="two" string="Two" class="o_studio_n_10">
                    <group class="o_studio_n_11"/>
                </page>
            </notebook>
        </sheet>
    </form>`;

const ACCEPTS = {
    form: ["sheet", "group", "notebook", "field"],
    sheet: ["group", "notebook", "field"],
    group: ["field", "group"],
    notebook: ["page"],
    page: ["group", "notebook", "field"],
};

function node(kind, tag, name, parent, children, extra = {}) {
    const container = kind in ACCEPTS;
    return {
        kind,
        tag,
        name,
        parent,
        children,
        string: extra.string || null,
        container,
        orientation: extra.orientation || "column",
        accepts: container ? ACCEPTS[kind] : [],
        movable: !["root", "sheet", "notebook"].includes(kind),
        removable: true,
        selectable: true,
        hidden: null,
        field: null,
    };
}

const NODES = {
    o_studio_n_0: node("root", "form", null, null, ["o_studio_n_1"]),
    o_studio_n_1: node("sheet", "sheet", null, "o_studio_n_0", ["o_studio_n_2", "o_studio_n_7"]),
    o_studio_n_2: node("group", "group", null, "o_studio_n_1", ["o_studio_n_3", "o_studio_n_6"], {
        orientation: "row",
    }),
    o_studio_n_3: node("group", "group", null, "o_studio_n_2", ["o_studio_n_4", "o_studio_n_5"]),
    o_studio_n_4: node("field", "field", "name", "o_studio_n_3", [], { string: "Name" }),
    o_studio_n_5: node("field", "field", "city", "o_studio_n_3", [], { string: "City" }),
    o_studio_n_6: node("group", "group", "studio_group_aaaa", "o_studio_n_2", []),
    o_studio_n_7: node("notebook", "notebook", null, "o_studio_n_1", ["o_studio_n_8", "o_studio_n_10"], {
        orientation: "row",
    }),
    o_studio_n_8: node("page", "page", "one", "o_studio_n_7", ["o_studio_n_9"], { string: "One" }),
    o_studio_n_9: node("field", "field", "sequence", "o_studio_n_8", [], { string: "Sequence" }),
    o_studio_n_10: node("page", "page", "two", "o_studio_n_7", ["o_studio_n_11"], { string: "Two" }),
    o_studio_n_11: node("group", "group", "purchase", "o_studio_n_10", []),
};

/** What `drag.js` asks of the console model, and nothing else. */
function fakeModel() {
    return {
        nodes: NODES,
        canWrite: true,
        selection: null,
        selectedNode: null,
        drag: null,
        drops: [],
        beginDrag(label) {
            this.drag = { label, caption: "" };
        },
        setDragCaption(caption) {
            if (this.drag) {
                this.drag.caption = caption;
            }
        },
        endDrag() {
            this.drag = null;
        },
        async drop(token, position, payload) {
            this.drops.push({ token, position, payload });
            return undefined;
        },
    };
}

const TILE = "display:flex;gap:6px;width:160px;height:32px;align-items:center;";

class Harness extends Component {
    static template = xml`
        <div class="o_studio_console" style="display:flex;width:1000px">
            <div class="o_studio_sidebar" style="width:200px;flex:0 0 200px">
                <button type="button" class="o_studio_tile o_studio_tile_field o_studio_draggable"
                        data-kind="existing_field" data-key="sequence" data-name="sequence"
                        data-label="Sequence" style="${TILE}">
                    <i class="fa fa-hashtag"/><span>Sequence</span>
                </button>
                <button type="button" class="o_studio_tile o_studio_draggable"
                        data-kind="component" data-key="page" data-component="page"
                        data-label="Tabs" style="${TILE}">
                    <i class="fa fa-folder-o"/><span>Tabs</span>
                </button>
                <button type="button" class="o_studio_tile o_studio_draggable"
                        data-kind="existing_field" data-key="nope" data-label="Nope"
                        disabled="disabled" style="${TILE}">
                    <span>Nope</span>
                </button>
            </div>
            <div class="o_studio_canvas" style="position:relative;flex:1 1 auto;height:700px;overflow:auto">
                <div class="o_studio_canvas_ground">
                    <View t-props="props.viewProps"/>
                </div>
            </div>
        </div>`;
    static components = { View };
    static props = ["*"];
}

async function mountConsole() {
    if (!getMockEnv()) {
        await makeMockEnv();
    }
    const modelFields = MockServer.env.partner.fields_get();
    await mountWithCleanup(Harness, {
        props: {
            viewProps: {
                type: "form",
                resModel: "partner",
                arch: ARCH,
                fields: modelFields,
                relatedModels: { partner: { fields: modelFields } },
                context: {},
                noBreadcrumbs: true,
                display: { controlPanel: false },
                resId: 1,
                ...compat.readonlyViewProps(),
            },
        },
    });
    const rootEl = queryOne(".o_studio_console");
    const scrollEl = queryOne(".o_studio_canvas");
    const overlay = new Overlay(scrollEl);
    const model = fakeModel();
    const dragger = makeCanvasDrag({ rootEl, scrollEl, overlay, model });
    after(() => {
        dragger.destroy();
        overlay.destroy();
    });
    return { rootEl, scrollEl, overlay, model, dragger };
}

/**
 * Give the canvas a height of its own, so the view overflows it: the
 * console's stylesheet has it grow to fill the console.
 */
function shrink(scrollEl, height) {
    scrollEl.style.flex = "0 0 auto";
    scrollEl.style.height = `${height}px`;
}

/** Pick `el` up the way the tour helper does: down at its centre, twenty pixels of travel. */
async function pickUp(el) {
    const helpers = await drag(el);
    await animationFrame();
    await hover(el, { position: { top: 20, left: 20 }, relative: true });
    await animationFrame();
    return helpers;
}

test("twenty pixels of travel start the drag and lay out the zones", async () => {
    const { model, dragger } = await mountConsole();
    const tile = queryOne(".o_studio_tile[data-key='sequence']");
    expect(queryAll(".o_studio_dropzone")).toHaveLength(0);
    const { cancel } = await pickUp(tile);
    // The source is captured from the helper callback, never from the
    // hook's `element`, which is the helper itself in 18.
    expect(dragger.source).toBe(tile);
    expect(dragger.payload).toEqual({ kind: "existing_field", name: "sequence", label: "Sequence" });
    expect(dragger.dragging).toBe(true);
    expect(document.body).toHaveClass("o_studio_dragging");
    expect(model.drag).toEqual({ label: "Sequence", caption: "" });
    // The helper is a small box at the pointer with the chip hanging off it.
    // The helper hangs off the body, outside the fixture.
    const hit = document.body.querySelector(":scope > .o_studio_drag_hit");
    expect(hit).not.toBe(null);
    expect(hit.getBoundingClientRect().width).toBe(8);
    expect(hit.querySelector(".o_studio_chip_label")).toHaveText("Sequence");
    // Zones for a field: in the inner group, the empty group, the sheet
    // and the shown page -- never in the notebook, which takes pages only.
    const zones = queryAll(".o_studio_dropzone");
    expect(zones.length).toBeGreaterThan(0);
    expect(queryOne(".o_studio_dropzone[data-name='name'][data-position='after']")).toBeVisible();
    expect(queryOne(".o_studio_dropzone[data-name='studio_group_aaaa'][data-position='inside']")).toBeVisible();
    expect(queryAll(".o_studio_dropzone[data-container-kind='notebook']")).toHaveLength(0);
    expect(queryAll(".o_studio_dropzone[data-container-kind='page']").length).toBeGreaterThan(0);
    // Every zone has a real size, for a tour's `waitFor` to see it.
    for (const zone of zones) {
        const rect = zone.getBoundingClientRect();
        expect(rect.width).toBeGreaterThan(0);
        expect(rect.height).toBeGreaterThan(0);
    }
    // Nothing on the page is a native drag source.
    expect(queryAll("[draggable='true']")).toHaveLength(0);
    await cancel();
    await animationFrame();
});

test("Escape cancels: the zones go and nothing is dropped", async () => {
    const { model, dragger } = await mountConsole();
    const tile = queryOne(".o_studio_tile[data-key='sequence']");
    const { moveTo } = await pickUp(tile);
    const zone = queryOne(".o_studio_dropzone[data-name='name'][data-position='after']");
    await moveTo(zone, { position: "center" });
    await animationFrame();
    expect(zone).toHaveClass("o_studio_dz_active");
    expect(model.drag.caption).toBe("after Name");
    expect(document.body.querySelector(".o_studio_chip_caption")).toHaveText("after Name");
    await press("Escape");
    await animationFrame();
    expect(dragger.dragging).toBe(false);
    expect(queryAll(".o_studio_dropzone")).toHaveLength(0);
    expect(document.body.querySelectorAll(".o_studio_drag_hit")).toHaveLength(0);
    expect(document.body).not.toHaveClass("o_studio_dragging");
    expect(model.drag).toBe(null);
    expect(model.drops).toEqual([]);
});

test("a drop on a zone asks the model for exactly that drop", async () => {
    const { model } = await mountConsole();
    const tile = queryOne(".o_studio_tile[data-key='sequence']");
    const { moveTo, drop } = await pickUp(tile);
    const zone = queryOne(".o_studio_dropzone[data-name='city'][data-position='after']");
    await moveTo(zone, { position: "center" });
    await animationFrame();
    await drop();
    await animationFrame();
    expect(model.drops).toEqual([
        {
            token: "o_studio_n_5",
            position: "after",
            payload: { kind: "existing_field", name: "sequence" },
        },
    ]);
    expect(queryAll(".o_studio_dropzone")).toHaveLength(0);
    expect(model.drag).toBe(null);
});

test("a component tile lays out zones for its own tag", async () => {
    const { model } = await mountConsole();
    const tile = queryOne(".o_studio_tile[data-key='page']");
    const { moveTo, drop } = await pickUp(tile);
    // A tab goes in the notebook and nowhere else: bars between the tabs.
    const zones = queryAll(".o_studio_dropzone");
    expect(zones.every((el) => el.dataset.containerKind === "notebook")).toBe(true);
    expect(zones.every((el) => el.dataset.axis === "x")).toBe(true);
    const end = queryOne(".o_studio_dropzone[data-container-kind='notebook'][data-edge='end']");
    await moveTo(end, { position: "center" });
    await animationFrame();
    await drop();
    await animationFrame();
    expect(model.drops).toEqual([
        {
            token: "o_studio_n_10",
            position: "after",
            payload: { kind: "component", component: "page", values: {} },
        },
    ]);
});

test("a leaf of the view is picked up as a move; a container and a disabled tile are not", async () => {
    const { model, dragger } = await mountConsole();
    const widget = queryOne(".o_field_widget[name='name']");
    const { moveTo, drop } = await pickUp(widget);
    expect(dragger.dragging).toBe(true);
    expect(dragger.payload).toEqual({ kind: "move", token: "o_studio_n_4", label: "Name" });
    // Not beside itself: neither the gap before it nor the one after.
    expect(queryAll(".o_studio_dropzone[data-name='name']")).toHaveLength(0);
    // Not inside itself either -- a field has no inside -- but into the
    // empty group, yes.
    const inside = queryOne(".o_studio_dropzone[data-name='studio_group_aaaa'][data-position='inside']");
    await moveTo(inside, { position: "center" });
    await animationFrame();
    await drop();
    await animationFrame();
    expect(model.drops).toEqual([
        { token: "o_studio_n_6", position: "inside", payload: { kind: "move", token: "o_studio_n_4" } },
    ]);

    // A container is moved by its grip, not by pressing on it.
    const group = queryFirst(".o_inner_group");
    const first = await drag(group);
    await animationFrame();
    await hover(group, { position: { top: 20, left: 20 }, relative: true });
    await animationFrame();
    expect(dragger.dragging).toBe(false);
    expect(queryAll(".o_studio_dropzone")).toHaveLength(0);
    await first.cancel();

    // A disabled tile keeps its tooltip and is not picked up; a tile that
    // says nothing about what it is, neither.
    expect(dragger.isDraggable(queryOne(".o_studio_tile[data-key='nope']"))).toBe(false);
    expect(dragger.isDraggable(queryOne(".o_studio_tile[data-key='sequence']"))).toBe(true);
    expect(dragger.isDraggable(group)).toBe(false);
    expect(dragger.isDraggable(widget)).toBe(true);
    expect(model.drops).toHaveLength(1);
});

test("a container is picked up by the grip on its selection frame", async () => {
    const { model, overlay } = await mountConsole();
    // Select the inner group: the frame draws with a grip, since a group
    // is movable and a container.
    model.selection = { token: "o_studio_n_3" };
    model.selectedNode = NODES.o_studio_n_3;
    overlay.update({ hover: null, selection: "o_studio_n_3", nodes: NODES, tag: "Group", point: null });
    const grip = queryOne(".o_studio_overlay .o_studio_grip");
    expect(grip).not.toHaveAttribute("hidden");
    const { moveTo, drop } = await pickUp(grip);
    expect(model.drag.label).toBe("the group");
    // Nothing inside the group, and neither gap beside it in its parent;
    // the other column and the end of the sheet, yes.
    expect(queryAll(".o_studio_dropzone[data-container='o_studio_n_3']")).toHaveLength(0);
    expect(queryAll(".o_studio_dropzone[data-container='o_studio_n_2']").map((el) => [el.dataset.token, el.dataset.position])).toEqual([
        ["o_studio_n_6", "after"],
    ]);
    const end = queryOne(".o_studio_dropzone[data-container-kind='sheet'][data-edge='end']");
    await moveTo(end, { position: "center" });
    await animationFrame();
    await drop();
    await animationFrame();
    expect(model.drops).toEqual([
        { token: "o_studio_n_7", position: "after", payload: { kind: "move", token: "o_studio_n_3" } },
    ]);
});

test("resting on a tab switches the page and lays the zones out again", async () => {
    const { model } = await mountConsole();
    const tile = queryOne(".o_studio_tile[data-key='sequence']");
    const { moveTo, drop } = await pickUp(tile);
    expect(queryAll(".o_studio_dropzone[data-name='purchase']")).toHaveLength(0);
    const tab = queryOne(".o_notebook .nav-link[name='two']");
    expect(tab).not.toHaveClass("active");
    await moveTo(tab, { position: "center" });
    await animationFrame();
    expect(model.drag.caption).toBe("switching to Two…");
    await advanceTime(TAB_DWELL_MS + 10);
    await animationFrame();
    await animationFrame();
    expect(tab).toHaveClass("active");
    // The page has switched: the chip no longer says it is about to.
    expect(model.drag.caption).toBe("");
    const inside = queryOne(".o_studio_dropzone[data-name='purchase'][data-position='inside']");
    expect(inside).toBeVisible();
    await moveTo(inside, { position: "center" });
    await animationFrame();
    await drop();
    await animationFrame();
    expect(model.drops).toEqual([
        {
            token: "o_studio_n_11",
            position: "inside",
            payload: { kind: "existing_field", name: "sequence" },
        },
    ]);
});

test("a tab is found where it is after the canvas scrolled under the drag", async () => {
    const { model, scrollEl } = await mountConsole();
    // A short canvas, so the notebook is below the fold.
    shrink(scrollEl, 100);
    const tab = queryOne(".o_notebook .nav-link[name='two']");
    const box = scrollEl.getBoundingClientRect();
    expect(tab.getBoundingClientRect().top).toBeGreaterThan(box.bottom);
    const tile = queryOne(".o_studio_tile[data-key='sequence']");
    const { moveTo } = await pickUp(tile);
    // The canvas scrolls under the drag -- nothing in the DOM changes, so
    // the zones are not laid out again -- and the tab is now on screen, in
    // the middle of the canvas, clear of the bands at its edges that would
    // scroll it further.
    scrollEl.scrollTop = tab.getBoundingClientRect().top - box.top - 35;
    await animationFrame();
    const tabRect = tab.getBoundingClientRect();
    const centre = tabRect.top + tabRect.height / 2;
    expect(centre).toBeGreaterThan(box.top + 30);
    expect(centre).toBeLessThan(box.bottom - 30);
    await moveTo(tab, { position: "center" });
    await animationFrame();
    expect(model.drag.caption).toBe("switching to Two…");
    await advanceTime(TAB_DWELL_MS + 10);
    await animationFrame();
    await animationFrame();
    expect(tab).toHaveClass("active");
});

test("scrolling at the canvas's edge lets go of the zone that moved away", async () => {
    const { scrollEl } = await mountConsole();
    const tile = queryOne(".o_studio_tile[data-key='sequence']");
    const { moveTo } = await pickUp(tile);
    const zone = queryOne(".o_studio_dropzone[data-name='name'][data-position='after']");
    // Cut the canvas so this zone sits in the band at its bottom edge
    // where resting the pointer scrolls it.
    const box = scrollEl.getBoundingClientRect();
    const zoneRect = zone.getBoundingClientRect();
    shrink(scrollEl, zoneRect.top + zoneRect.height / 2 - box.top + 20);
    await moveTo(zone, { position: "center" });
    await animationFrame();
    expect(zone).toHaveClass("o_studio_dz_active");
    for (let frame = 0; frame < 12; frame++) {
        await animationFrame();
    }
    // The canvas scrolled and the zone went up with it; the pointer never
    // moved, and the hook was told anyway.
    expect(scrollEl.scrollTop).toBeGreaterThan(0);
    expect(zone).not.toHaveClass("o_studio_dz_active");
});

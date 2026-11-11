/** @odoo-module **/
/**
 * Picking up and putting down, against the real drag hook.
 *
 * `drag.ts` sits on `useDragAndDrop` and on a handful of things the hook
 * does not say: that five pixels of travel start the drag, that the
 * helper's box is what the zones are matched against, that any key ends
 * the drag with the last zone still set, that the body takes no pointer
 * events meanwhile. Each of those is pinned here on a form the real
 * compiler rendered, inside a console-shaped root with a palette beside
 * it, with a model that records what it is asked to drop and does not
 * talk to any server.
 */

import {after, expect, test} from "@odoo/hoot";
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
import {Component, xml} from "@odoo/owl";
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

import {View} from "@web/views/view";
import * as compat from "@app_builder_view/console/compat";
import type {
  CanvasDragModel,
  OutlineDragProvider,
} from "@app_builder_view/console/drag";
import {TAB_DWELL_MS, makeCanvasDrag} from "@app_builder_view/console/drag";
import {Overlay, ZoneLayer} from "@app_builder_view/console/overlay";
import {OUTLINE_INDENT, OUTLINE_PAD} from "@app_builder_view/console/sidebar/outline";
import type {
  DragPayload,
  BuilderNode,
  Token,
  ZonePosition,
} from "@app_builder_view/console/types";

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
 * `queryOne`/`queryAll`/`queryFirst` (`@odoo/hoot-dom`) all return the
 * DOM lib's own `Element`/`Element[]`, not the generic-parameterized
 * form their own JSDoc examples suggest (`queryOne\`iframe\`` reads as if
 * generic, but the real signatures -- `hoot-dom/helpers/dom.js` -- take
 * no type parameter at all; confirmed by a real `tsc` run rejecting
 * `queryOne<HTMLElement>(...)` outright). Every element this fixture's
 * own form/palette/outline ever produces genuinely is an `HTMLElement`
 * (inputs, buttons, tabs, rows -- no SVG anywhere in it), so narrowed
 * once here rather than at every one of this file's many call sites.
 *
 * `queryFirst`'s JSDoc marks its `options` parameter without `[brackets]`,
 * so TS infers it as required, but the real function reads
 * `arguments.length` itself and works fine with one argument -- the same
 * JSDoc-vs-runtime-arity gap `canvas_views.ts`'s own `Registry.get` cast
 * already established a fix for (TYPING.md, "Known traps").
 */
function queryOneEl(target: string): HTMLElement {
  return queryOne(target) as HTMLElement;
}
function queryAllEl(target: string): HTMLElement[] {
  return queryAll(target) as HTMLElement[];
}
function queryFirstEl(target: string): HTMLElement | null {
  return (queryFirst as (target: string) => Element | null)(
    target
  ) as HTMLElement | null;
}

class Partner extends models.Model {
  // `fields.Char`/`fields.Integer` etc. are each `makeFieldGenerator(...)`'s
  // return value (`mock_fields.js`); TS infers that function's own return
  // type with a self-indexing computed property, which reads as
  // `T | undefined` under `noUncheckedIndexedAccess` even though the
  // generator always exists at every real call -- the same fix already
  // established for this exact vendor file elsewhere in this migration.
  name = fields.Char!();
  city = fields.Char!();
  sequence = fields.Integer!();
  override _records = [{id: 1, name: "Ada", city: "London", sequence: 1}];
}

defineModels([Partner]);

onRpc("has_group", () => true);

const ARCH = `
    <form class="o_builder_n_0">
        <sheet class="o_builder_n_1">
            <group class="o_builder_n_2">
                <group class="o_builder_n_3">
                    <field name="name" class="o_builder_n_4"/>
                    <field name="city" class="o_builder_n_5"/>
                </group>
                <group class="o_builder_n_6"/>
            </group>
            <notebook class="o_builder_n_7">
                <page name="one" string="One" class="o_builder_n_8">
                    <field name="sequence" class="o_builder_n_9"/>
                </page>
                <page name="two" string="Two" class="o_builder_n_10">
                    <group class="o_builder_n_11"/>
                </page>
            </notebook>
        </sheet>
    </form>`;

const ACCEPTS: Record<string, string[]> = {
  form: ["sheet", "group", "notebook", "field"],
  sheet: ["group", "notebook", "field"],
  group: ["field", "group"],
  notebook: ["page"],
  page: ["group", "notebook", "field"],
};

/** A `BuilderNode` with inert defaults for the fields this fixture never
 * needs (`index`, `attrs`, `view_id`, `label`) -- the same builder-with-
 * defaults house pattern as `console_model.test.ts`'s own `node()`, and
 * for the same reason: a partial literal does not "sufficiently overlap"
 * the full interface on a bare `as`. */
function node(
  kind: string,
  tag: string,
  name: string | null,
  parent: Token | null,
  children: Token[],
  extra: {string?: string; orientation?: "row" | "column"} = {}
): BuilderNode {
  const container = kind in ACCEPTS;
  return {
    kind: kind as BuilderNode["kind"],
    tag,
    name,
    parent,
    children,
    index: 0,
    string: extra.string || null,
    container,
    orientation: extra.orientation || "column",
    accepts: container ? (ACCEPTS[kind] ?? []) : [],
    movable: !["root", "sheet", "notebook"].includes(kind),
    removable: true,
    selectable: true,
    hidden: null,
    attrs: {},
    dom: true,
    field: null,
    view_id: null,
    label: null,
  };
}

const NODES: Record<Token, BuilderNode> = {
  o_builder_n_0: node("root", "form", null, null, ["o_builder_n_1"]),
  o_builder_n_1: node("sheet", "sheet", null, "o_builder_n_0", [
    "o_builder_n_2",
    "o_builder_n_7",
  ]),
  o_builder_n_2: node(
    "group",
    "group",
    null,
    "o_builder_n_1",
    ["o_builder_n_3", "o_builder_n_6"],
    {
      orientation: "row",
    }
  ),
  o_builder_n_3: node("group", "group", null, "o_builder_n_2", [
    "o_builder_n_4",
    "o_builder_n_5",
  ]),
  o_builder_n_4: node("field", "field", "name", "o_builder_n_3", [], {string: "Name"}),
  o_builder_n_5: node("field", "field", "city", "o_builder_n_3", [], {string: "City"}),
  o_builder_n_6: node("group", "group", "builder_group_aaaa", "o_builder_n_2", []),
  o_builder_n_7: node(
    "notebook",
    "notebook",
    null,
    "o_builder_n_1",
    ["o_builder_n_8", "o_builder_n_10"],
    {orientation: "row"}
  ),
  o_builder_n_8: node("page", "page", "one", "o_builder_n_7", ["o_builder_n_9"], {
    string: "One",
  }),
  o_builder_n_9: node("field", "field", "sequence", "o_builder_n_8", [], {
    string: "Sequence",
  }),
  o_builder_n_10: node("page", "page", "two", "o_builder_n_7", ["o_builder_n_11"], {
    string: "Two",
  }),
  o_builder_n_11: node("group", "group", "purchase", "o_builder_n_10", []),
};

/** One drop `fakeModel()`'s own `drop()` recorded. */
interface RecordedDrop {
  token: Token | null;
  position: ZonePosition;
  payload: DragPayload;
}

/** `fakeModel()`'s own return: `CanvasDragModel` plus the two extra
 * fields this file's assertions read (`drag`, `drops`) that no real
 * `ConsoleModel` carries under those names. */
interface FakeModel extends CanvasDragModel {
  drag: {label: string; caption: string} | null;
  drops: RecordedDrop[];
}

/** What `drag.ts` asks of the console model, and nothing else. */
function fakeModel(): FakeModel {
  return {
    nodes: NODES,
    canWrite: true,
    selection: null,
    selectedNode: null,
    outlineDrag: null,
    drag: null,
    drops: [],
    beginDrag(label: string) {
      this.drag = {label, caption: ""};
    },
    setDragCaption(caption: string) {
      if (this.drag) {
        this.drag.caption = caption;
      }
    },
    endDrag() {
      this.drag = null;
    },
    async drop(
      token: Token | null,
      position: ZonePosition,
      payload: DragPayload
    ): Promise<undefined> {
      this.drops.push({token, position, payload});
      return undefined;
    },
  };
}

const TILE = "display:flex;gap:6px;width:160px;height:32px;align-items:center;";
const ROW = "display:block;height:24px;line-height:24px;font-size:12px;";

/** One row of `OUTLINE_ROWS`: `[token, depth]`, or `[token, depth,
 * extraClass]` for the one folded row. */
type OutlineRowFixture = [string, number] | [string, number, string];

// The outline's rows for the form above, as `sidebar/outline.js` lays
// them out: one per node, depth first, the second page folded.
const OUTLINE_ROWS: OutlineRowFixture[] = [
  ["o_builder_n_0", 0],
  ["o_builder_n_1", 1],
  ["o_builder_n_2", 2],
  ["o_builder_n_3", 3],
  ["o_builder_n_4", 4],
  ["o_builder_n_5", 4],
  ["o_builder_n_6", 3],
  ["o_builder_n_7", 2],
  ["o_builder_n_8", 3],
  ["o_builder_n_9", 4],
  ["o_builder_n_10", 3, "o_builder_outline_collapsed"],
];

interface HarnessProps {
  outline: OutlineRowFixture[] | null;
  viewProps: Record<string, unknown>;
}

class Harness extends Component<HarnessProps> {
  static override template = xml`
        <div class="o_builder_console" style="display:flex;flex-direction:row;align-items:flex-start;width:1000px;height:auto">
            <div class="o_builder_sidebar" style="width:200px;flex:0 0 200px">
                <div t-if="props.outline" class="o_builder_outline">
                    <ul class="o_builder_outline_list"
                        style="position:relative;height:300px;overflow:auto;margin:0;padding:0;list-style:none">
                        <li t-foreach="props.outline" t-as="row" t-key="row[0]"
                            class="o_builder_outline_row" t-att-class="row[2] || ''"
                            t-att-data-token="row[0]" t-att-data-depth="row[1]"
                            t-att-style="'${ROW}padding-left:' + (${OUTLINE_PAD} + row[1] * ${OUTLINE_INDENT}) + 'px'">
                            <span t-esc="row[0]"/>
                        </li>
                    </ul>
                </div>
                <button type="button" class="o_builder_tile o_builder_tile_field o_builder_draggable"
                        data-kind="existing_field" data-key="sequence" data-name="sequence"
                        data-label="Sequence" style="${TILE}">
                    <i class="fa fa-hashtag"/><span>Sequence</span>
                </button>
                <button type="button" class="o_builder_tile o_builder_draggable"
                        data-kind="component" data-key="page" data-component="page"
                        data-label="Tabs" style="${TILE}">
                    <i class="fa fa-folder-o"/><span>Tabs</span>
                </button>
                <button type="button" class="o_builder_tile o_builder_draggable"
                        data-kind="existing_field" data-key="nope" data-label="Nope"
                        disabled="disabled" style="${TILE}">
                    <span>Nope</span>
                </button>
            </div>
            <div class="o_builder_canvas" style="position:relative;flex:1 1 auto;height:700px;overflow:auto">
                <div class="o_builder_canvas_ground">
                    <View t-props="props.viewProps"/>
                </div>
            </div>
        </div>`;
  static components = {View};
  static override props = ["*"];
}

interface MountConsoleResult {
  rootEl: HTMLElement;
  scrollEl: HTMLElement;
  overlay: Overlay;
  model: FakeModel;
  dragger: ReturnType<typeof makeCanvasDrag>;
}

async function mountConsole({
  outline = false,
}: {outline?: boolean} = {}): Promise<MountConsoleResult> {
  if (!getMockEnv()) {
    await makeMockEnv();
  }
  // `MockServer.env` is only set once a mock env exists, which the
  // check above guarantees before this line ever runs -- a real
  // invariant `MockServer`'s own declared type does not encode.
  const modelFields = (MockServer.env as unknown as Record<string, MockModelHandle>)[
    "partner"
  ]!.fields_get();
  await mountWithCleanup(Harness as never, {
    props: {
      outline: outline ? OUTLINE_ROWS : null,
      viewProps: {
        type: "form",
        resModel: "partner",
        arch: ARCH,
        fields: modelFields,
        relatedModels: {partner: {fields: modelFields}},
        context: {},
        noBreadcrumbs: true,
        display: {controlPanel: false},
        resId: 1,
        ...compat.readonlyViewProps(),
      },
    },
  });
  const rootEl = queryOneEl(".o_builder_console");
  const scrollEl = queryOneEl(".o_builder_canvas");
  const overlay = new Overlay(scrollEl);
  const model = fakeModel();
  if (outline) {
    model.outlineDrag = fakeOutline(queryOneEl(".o_builder_outline_list"));
  }
  const dragger = makeCanvasDrag({rootEl, scrollEl, overlay, model});
  after(() => {
    dragger.destroy();
    overlay.destroy();
  });
  return {rootEl, scrollEl, overlay, model, dragger};
}

/** `fakeOutline()`'s own return: the real `OutlineDragProvider` contract
 * plus `expanded`, the one extra field this file's assertions read. */
interface FakeOutline extends OutlineDragProvider {
  expanded: Token[];
}

/**
 * What the outline leaves on the model for the drag, over a static list:
 * `expand` unfolds the second page by hand -- the row loses its fold and
 * its child row is appended -- which is what the component's re-render
 * comes to, and what the drag's observer sees.
 */
function fakeOutline(list: HTMLElement): FakeOutline {
  const layer = new ZoneLayer(list);
  const folded = new Set(["o_builder_n_10"]);
  const provider: FakeOutline = {
    el: list,
    layer,
    expanded: [],
    rows: () => [...list.querySelectorAll<HTMLElement>(".o_builder_outline_row")],
    indentOf: (depth: number) => OUTLINE_PAD + depth * OUTLINE_INDENT,
    isCollapsed: (token: Token) => folded.has(token),
    expand(token: Token) {
      this.expanded.push(token);
      if (!folded.delete(token)) {
        return;
      }
      const row = list.querySelector(`.o_builder_outline_row[data-token='${token}']`);
      if (!row) {
        return;
      }
      row.classList.remove("o_builder_outline_collapsed");
      const child = document.createElement("li");
      child.className = "o_builder_outline_row";
      child.dataset["token"] = "o_builder_n_11";
      child.dataset["depth"] = "4";
      child.setAttribute(
        "style",
        `${ROW}padding-left:${OUTLINE_PAD + 4 * OUTLINE_INDENT}px`
      );
      child.textContent = "o_builder_n_11";
      row.after(child);
    },
  };
  after(() => layer.destroy());
  return provider;
}

const OUTLINE_ZONE = ".o_builder_dropzone[data-layer='outline']";
const CANVAS_ZONE = ".o_builder_overlay .o_builder_dropzone";

function outlineRow(token: Token): HTMLElement {
  return queryOneEl(`.o_builder_outline_row[data-token='${token}']`);
}

/**
 * Give the canvas a height of its own, so the view overflows it: the
 * console's stylesheet has it grow to fill the console.
 */
function shrink(scrollEl: HTMLElement, height: number): void {
  scrollEl.style.flex = "0 0 auto";
  scrollEl.style.height = `${height}px`;
}

/**
 * `moveTo`'s real position union (`Side | "${Side}-${Side}" | Position`,
 * `hoot-dom/helpers/events.js`) does not list `"center"` as a value, but
 * the real implementation (`getPosition`) computes the exact visual
 * centre for any position string that names neither a horizontal
 * (`"left"`/`"right"`) nor a vertical (`"top"`/`"bottom"`) side -- a
 * real, working fallback the JSDoc under-documents, the same class of
 * gap `useDragAndDrop`/`Registry.get` already established a fix for
 * elsewhere in this migration. Widened once here, on `pickUp`'s own
 * return type, rather than cast at every one of this file's many
 * `moveTo(..., { position: "center" })` call sites.
 */
interface DragHelpersWithCenter {
  cancel: () => Promise<unknown>;
  drop: (to?: unknown, options?: unknown) => Promise<unknown>;
  moveTo: (
    to?: unknown,
    options?: {position?: string; relative?: boolean}
  ) => Promise<DragHelpersWithCenter>;
}

/** Pick `el` up the way the tour helper does: down at its centre, twenty pixels of travel. */
async function pickUp(el: HTMLElement): Promise<DragHelpersWithCenter> {
  const helpers = (await drag(el)) as unknown as DragHelpersWithCenter;
  await animationFrame();
  await hover(el, {position: {top: 20, left: 20}, relative: true});
  await animationFrame();
  return helpers;
}

test("twenty pixels of travel start the drag and lay out the zones", async () => {
  const {model, dragger} = await mountConsole();
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  expect(queryAll(".o_builder_dropzone")).toHaveLength(0);
  const {cancel} = await pickUp(tile);
  // The source is captured from the helper callback, never from the
  // hook's `element`, which is the helper itself in 18.
  expect(dragger.source).toBe(tile);
  expect(dragger.payload).toEqual({
    kind: "existing_field",
    name: "sequence",
    label: "Sequence",
  });
  expect(dragger.dragging).toBe(true);
  expect(document.body).toHaveClass("o_builder_dragging");
  expect(model.drag).toEqual({label: "Sequence", caption: ""});
  // The helper is a small box at the pointer with the chip hanging off it.
  // The helper hangs off the body, outside the fixture.
  const hit = document.body.querySelector(":scope > .o_builder_drag_hit");
  expect(hit).not.toBe(null);
  expect(hit!.getBoundingClientRect().width).toBe(8);
  expect(hit!.querySelector(".o_builder_chip_label")).toHaveText("Sequence");
  // Zones for a field: in the inner group, the empty group, the sheet
  // and the shown page -- never in the notebook, which takes pages only.
  const zones = queryAll(".o_builder_dropzone");
  expect(zones.length).toBeGreaterThan(0);
  expect(
    queryOne(".o_builder_dropzone[data-name='name'][data-position='after']")
  ).toBeVisible();
  expect(
    queryOne(
      ".o_builder_dropzone[data-name='builder_group_aaaa'][data-position='inside']"
    )
  ).toBeVisible();
  expect(queryAll(".o_builder_dropzone[data-container-kind='notebook']")).toHaveLength(
    0
  );
  expect(
    queryAll(".o_builder_dropzone[data-container-kind='page']").length
  ).toBeGreaterThan(0);
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
  const {model, dragger} = await mountConsole();
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo} = await pickUp(tile);
  const zone = queryOne(".o_builder_dropzone[data-name='name'][data-position='after']");
  await moveTo(zone, {position: "center"});
  await animationFrame();
  expect(zone).toHaveClass("o_builder_dz_active");
  expect(model.drag?.caption).toBe("after Name");
  expect(document.body.querySelector(".o_builder_chip_caption")).toHaveText(
    "after Name"
  );
  await press("Escape");
  await animationFrame();
  expect(dragger.dragging).toBe(false);
  expect(queryAll(".o_builder_dropzone")).toHaveLength(0);
  expect(document.body.querySelectorAll(".o_builder_drag_hit")).toHaveLength(0);
  expect(document.body).not.toHaveClass("o_builder_dragging");
  expect(model.drag).toBe(null);
  expect(model.drops).toEqual([]);
});

test("a drop on a zone asks the model for exactly that drop", async () => {
  const {model} = await mountConsole();
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo, drop} = await pickUp(tile);
  const zone = queryOne(".o_builder_dropzone[data-name='city'][data-position='after']");
  await moveTo(zone, {position: "center"});
  await animationFrame();
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_5",
      position: "after",
      payload: {kind: "existing_field", name: "sequence"},
    },
  ]);
  expect(queryAll(".o_builder_dropzone")).toHaveLength(0);
  expect(model.drag).toBe(null);
});

test("a component tile lays out zones for its own tag", async () => {
  const {model} = await mountConsole();
  const tile = queryOneEl(".o_builder_tile[data-key='page']");
  const {moveTo, drop} = await pickUp(tile);
  // A tab goes in the notebook and nowhere else: bars between the tabs.
  const zones = queryAllEl(".o_builder_dropzone");
  expect(zones.every((el) => el.dataset["containerKind"] === "notebook")).toBe(true);
  expect(zones.every((el) => el.dataset["axis"] === "x")).toBe(true);
  const end = queryOne(
    ".o_builder_dropzone[data-container-kind='notebook'][data-edge='end']"
  );
  await moveTo(end, {position: "center"});
  await animationFrame();
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_10",
      position: "after",
      payload: {kind: "component", component: "page", values: {}},
    },
  ]);
});

test("a leaf of the view is picked up as a move; a container and a disabled tile are not", async () => {
  const {model, dragger} = await mountConsole();
  const widget = queryOneEl(".o_field_widget[name='name']");
  const {moveTo, drop} = await pickUp(widget);
  expect(dragger.dragging).toBe(true);
  expect(dragger.payload).toEqual({
    kind: "move",
    token: "o_builder_n_4",
    label: "Name",
  });
  // Not beside itself: neither the gap before it nor the one after.
  expect(queryAll(".o_builder_dropzone[data-name='name']")).toHaveLength(0);
  // Not inside itself either -- a field has no inside -- but into the
  // empty group, yes.
  const inside = queryOne(
    ".o_builder_dropzone[data-name='builder_group_aaaa'][data-position='inside']"
  );
  await moveTo(inside, {position: "center"});
  await animationFrame();
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_6",
      position: "inside",
      payload: {kind: "move", token: "o_builder_n_4"},
    },
  ]);

  // A container is moved by its grip, not by pressing on it.
  const group = queryFirstEl(".o_inner_group")!;
  const first = await drag(group);
  await animationFrame();
  await hover(group, {position: {top: 20, left: 20}, relative: true});
  await animationFrame();
  expect(dragger.dragging).toBe(false);
  expect(queryAll(".o_builder_dropzone")).toHaveLength(0);
  await first.cancel();

  // A disabled tile keeps its tooltip and is not picked up; a tile that
  // says nothing about what it is, neither.
  expect(dragger.isDraggable(queryOneEl(".o_builder_tile[data-key='nope']"))).toBe(
    false
  );
  expect(dragger.isDraggable(queryOneEl(".o_builder_tile[data-key='sequence']"))).toBe(
    true
  );
  expect(dragger.isDraggable(group)).toBe(false);
  expect(dragger.isDraggable(widget)).toBe(true);
  expect(model.drops).toHaveLength(1);
});

test("a container is picked up by the grip on its selection frame", async () => {
  const {model, overlay} = await mountConsole();
  // Select the inner group: the frame draws with a grip, since a group
  // is movable and a container.
  model.selection = {token: "o_builder_n_3"};
  model.selectedNode = NODES["o_builder_n_3"] ?? null;
  overlay.update({
    hover: null,
    selection: "o_builder_n_3",
    nodes: NODES,
    tag: "Group",
    point: null,
  });
  const grip = queryOneEl(".o_builder_overlay .o_builder_grip");
  expect(grip).not.toHaveAttribute("hidden");
  const {moveTo, drop} = await pickUp(grip);
  expect(model.drag?.label).toBe("the group");
  // Nothing inside the group, and neither gap beside it in its parent;
  // the other column and the end of the sheet, yes.
  expect(queryAll(".o_builder_dropzone[data-container='o_builder_n_3']")).toHaveLength(
    0
  );
  expect(
    queryAllEl(".o_builder_dropzone[data-container='o_builder_n_2']").map((el) => [
      el.dataset["token"],
      el.dataset["position"],
    ])
  ).toEqual([["o_builder_n_6", "after"]]);
  const end = queryOne(
    ".o_builder_dropzone[data-container-kind='sheet'][data-edge='end']"
  );
  await moveTo(end, {position: "center"});
  await animationFrame();
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_7",
      position: "after",
      payload: {kind: "move", token: "o_builder_n_3"},
    },
  ]);
});

test("resting on a tab switches the page and lays the zones out again", async () => {
  const {model} = await mountConsole();
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo, drop} = await pickUp(tile);
  expect(queryAll(".o_builder_dropzone[data-name='purchase']")).toHaveLength(0);
  const tab = queryOne(".o_notebook .nav-link[name='two']");
  expect(tab).not.toHaveClass("active");
  await moveTo(tab, {position: "center"});
  await animationFrame();
  expect(model.drag?.caption).toBe("switching to Two…");
  await advanceTime(TAB_DWELL_MS + 10);
  await animationFrame();
  await animationFrame();
  expect(tab).toHaveClass("active");
  // The page has switched: the chip no longer says it is about to.
  expect(model.drag?.caption).toBe("");
  const inside = queryOne(
    ".o_builder_dropzone[data-name='purchase'][data-position='inside']"
  );
  expect(inside).toBeVisible();
  await moveTo(inside, {position: "center"});
  await animationFrame();
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_11",
      position: "inside",
      payload: {kind: "existing_field", name: "sequence"},
    },
  ]);
});

test("a tab is found where it is after the canvas scrolled under the drag", async () => {
  const {model, scrollEl} = await mountConsole();
  // A short canvas, so the notebook is below the fold.
  shrink(scrollEl, 100);
  const tab = queryOne(".o_notebook .nav-link[name='two']");
  const box = scrollEl.getBoundingClientRect();
  expect(tab.getBoundingClientRect().top).toBeGreaterThan(box.bottom);
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo} = await pickUp(tile);
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
  await moveTo(tab, {position: "center"});
  await animationFrame();
  expect(model.drag?.caption).toBe("switching to Two…");
  await advanceTime(TAB_DWELL_MS + 10);
  await animationFrame();
  await animationFrame();
  expect(tab).toHaveClass("active");
});

test("scrolling at the canvas's edge lets go of the zone that moved away", async () => {
  const {scrollEl} = await mountConsole();
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo} = await pickUp(tile);
  const zone = queryOne(".o_builder_dropzone[data-name='name'][data-position='after']");
  // Cut the canvas so this zone sits in the band at its bottom edge
  // where resting the pointer scrolls it.
  const box = scrollEl.getBoundingClientRect();
  const zoneRect = zone.getBoundingClientRect();
  shrink(scrollEl, zoneRect.top + zoneRect.height / 2 - box.top + 20);
  await moveTo(zone, {position: "center"});
  await animationFrame();
  expect(zone).toHaveClass("o_builder_dz_active");
  for (let frame = 0; frame < 12; frame++) {
    await animationFrame();
  }
  // The canvas scrolled and the zone went up with it; the pointer never
  // moved, and the hook was told anyway.
  expect(scrollEl.scrollTop).toBeGreaterThan(0);
  expect(zone).not.toHaveClass("o_builder_dz_active");
});

// -- the outline ------------------------------------------------------------------

test("a row of the outline is picked up as a move and dropped on a gap of the tree", async () => {
  const {model, dragger} = await mountConsole({outline: true});
  const row = outlineRow("o_builder_n_5");
  const {moveTo, drop} = await pickUp(row);
  expect(dragger.dragging).toBe(true);
  expect(dragger.payload).toEqual({
    kind: "move",
    token: "o_builder_n_5",
    label: "City",
  });
  expect(row).toHaveClass("o_dragged");
  // Zones in both layers: the canvas's in its overlay, the outline's in
  // its list, each saying which it is.
  expect(queryAll(CANVAS_ZONE).length).toBeGreaterThan(0);
  expect(queryAll(OUTLINE_ZONE).length).toBeGreaterThan(0);
  expect(queryAll(`.o_builder_outline_list ${OUTLINE_ZONE}`)).toHaveLength(
    queryAll(OUTLINE_ZONE).length
  );
  // Not beside itself in the tree either.
  expect(queryAll(`${OUTLINE_ZONE}[data-token='o_builder_n_5']`)).toHaveLength(0);
  expect(
    queryAll(`${OUTLINE_ZONE}[data-token='o_builder_n_4'][data-position='after']`)
  ).toHaveLength(0);
  // Below Sequence, the last row of the first page: after it, in the page.
  const zone = queryOneEl(
    `${OUTLINE_ZONE}[data-token='o_builder_n_9'][data-position='after']`
  );
  expect(zone.dataset["container"]).toBe("o_builder_n_8");
  await moveTo(zone, {position: "center"});
  await animationFrame();
  expect(zone).toHaveClass("o_builder_dz_active");
  expect(model.drag?.caption).toBe("at the end of One");
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_9",
      position: "after",
      payload: {kind: "move", token: "o_builder_n_5"},
    },
  ]);
  expect(queryAll(".o_builder_dropzone")).toHaveLength(0);
  expect(model.drag).toBe(null);
  expect(row).not.toHaveClass("o_dragged");
});

test("a container is picked up by its row, where a press on it means nothing else", async () => {
  const {dragger} = await mountConsole({outline: true});
  expect(dragger.isDraggable(outlineRow("o_builder_n_3"))).toBe(true);
  expect(dragger.isDraggable(queryFirstEl(".o_inner_group"))).toBe(false);
  // What stays put stays put in the tree too.
  expect(dragger.isDraggable(outlineRow("o_builder_n_1"))).toBe(false);
  expect(dragger.isDraggable(outlineRow("o_builder_n_7"))).toBe(false);
  const {cancel} = await pickUp(outlineRow("o_builder_n_3"));
  expect(dragger.payload).toEqual({
    kind: "move",
    token: "o_builder_n_3",
    label: "the group",
  });
  // Nothing inside the moved group, in either layer.
  expect(queryAll(".o_builder_dropzone[data-container='o_builder_n_3']")).toHaveLength(
    0
  );
  await cancel();
  await animationFrame();
});

test("a tile lands on a gap of the tree; the gap below a group's last row has two bands", async () => {
  const {model} = await mountConsole({outline: true});
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo, drop} = await pickUp(tile);
  // Below City, the last field of the inner group: after City in the
  // group, over the row's own text; after the group in its parent, at
  // the left edge.
  const deep = queryOne(
    `${OUTLINE_ZONE}[data-token='o_builder_n_5'][data-position='after']`
  );
  const shallow = queryOne(
    `${OUTLINE_ZONE}[data-token='o_builder_n_3'][data-position='after']`
  );
  const list = queryOne(".o_builder_outline_list").getBoundingClientRect();
  expect(deep.getBoundingClientRect().left).toBe(
    list.left + OUTLINE_PAD + 4 * OUTLINE_INDENT
  );
  expect(shallow.getBoundingClientRect().left).toBe(list.left);
  expect(shallow.getBoundingClientRect().width).toBe(OUTLINE_PAD + 4 * OUTLINE_INDENT);
  expect(deep.getBoundingClientRect().top).toBe(shallow.getBoundingClientRect().top);
  await moveTo(deep, {position: "center"});
  await animationFrame();
  expect(model.drag?.caption).toBe("after City");
  await moveTo(shallow, {position: "center"});
  await animationFrame();
  expect(model.drag?.caption).toBe("after the group");
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_3",
      position: "after",
      payload: {kind: "existing_field", name: "sequence"},
    },
  ]);
});

test("a node of the view is dropped into the tree, and Escape over the tree drops nothing", async () => {
  const {model, dragger} = await mountConsole({outline: true});
  const widget = queryOneEl(".o_field_widget[name='name']");
  let helpers = await pickUp(widget);
  const inside = queryOne(
    `${OUTLINE_ZONE}[data-token='o_builder_n_6'][data-position='inside']`
  );
  await helpers.moveTo(inside, {position: "center"});
  await animationFrame();
  expect(model.drag?.caption).toBe("into the group");
  await press("Escape");
  await animationFrame();
  expect(dragger.dragging).toBe(false);
  expect(model.drops).toEqual([]);
  expect(queryAll(".o_builder_dropzone")).toHaveLength(0);
  expect(queryAll(".o_builder_outline_list .o_builder_zones > *")).toHaveLength(0);

  helpers = await pickUp(widget);
  await helpers.moveTo(
    queryOne(`${OUTLINE_ZONE}[data-token='o_builder_n_6'][data-position='inside']`),
    {position: "center"}
  );
  await animationFrame();
  await helpers.drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_6",
      position: "inside",
      payload: {kind: "move", token: "o_builder_n_4"},
    },
  ]);
});

test("resting on a folded row unfolds it, and the zones follow", async () => {
  const {model} = await mountConsole({outline: true});
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo, drop} = await pickUp(tile);
  expect(
    queryAll(`${OUTLINE_ZONE}[data-container='o_builder_n_10'][data-position='before']`)
  ).toHaveLength(0);
  const folded = outlineRow("o_builder_n_10");
  // The folded page is itself a place: the chip says so while the
  // pointer rests, and keeps saying so.
  const into = queryOne(
    `${OUTLINE_ZONE}[data-token='o_builder_n_10'][data-position='inside']`
  );
  await moveTo(into, {position: "center"});
  await animationFrame();
  expect(model.drag?.caption).toBe("into Two");
  await advanceTime(TAB_DWELL_MS + 10);
  await animationFrame();
  await animationFrame();
  expect((model.outlineDrag as FakeOutline).expanded).toEqual(["o_builder_n_10"]);
  expect(folded).not.toHaveClass("o_builder_outline_collapsed");
  // The page's rows are on screen now, and so are the gaps between them.
  const before = queryOneEl(
    `${OUTLINE_ZONE}[data-container='o_builder_n_10'][data-position='before']`
  );
  expect(before.dataset["token"]).toBe("o_builder_n_11");
  // The unfolded page is no longer a box; its empty group is.
  expect(
    queryAll(`${OUTLINE_ZONE}[data-token='o_builder_n_10'][data-position='inside']`)
  ).toHaveLength(0);
  const group = queryOne(
    `${OUTLINE_ZONE}[data-token='o_builder_n_11'][data-position='inside']`
  );
  await moveTo(group, {position: "center"});
  await animationFrame();
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_11",
      position: "inside",
      payload: {kind: "existing_field", name: "sequence"},
    },
  ]);
});

test("a zone of the tree is found again after the zones were laid out again", async () => {
  const {model, dragger} = await mountConsole({outline: true});
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {moveTo, drop} = await pickUp(tile);
  const zone = queryOne(
    `${OUTLINE_ZONE}[data-token='o_builder_n_9'][data-position='after']`
  );
  await moveTo(zone, {position: "center"});
  await animationFrame();
  expect(zone).toHaveClass("o_builder_dz_active");
  // The canvas re-rendered under the drag: every zone element is new,
  // in both layers, and the same place in the tree is what counts --
  // not the canvas's own "after Sequence", which is elsewhere.
  dragger.onCanvasChanged();
  await animationFrame();
  expect(zone.isConnected).toBe(false);
  await drop();
  await animationFrame();
  expect(model.drops).toEqual([
    {
      token: "o_builder_n_9",
      position: "after",
      payload: {kind: "existing_field", name: "sequence"},
    },
  ]);
});

test("rows the list has scrolled away get no zone over what is below the list", async () => {
  const {model} = await mountConsole({outline: true});
  const list = queryOneEl(".o_builder_outline_list");
  list.style.height = "100px";
  const tile = queryOneEl(".o_builder_tile[data-key='sequence']");
  const {cancel} = await pickUp(tile);
  const box = list.getBoundingClientRect();
  const zones = queryAll(OUTLINE_ZONE);
  expect(zones.length).toBeGreaterThan(0);
  for (const zone of zones) {
    const rect = zone.getBoundingClientRect();
    expect(rect.top).toBeGreaterThan(box.top - 1);
    expect(rect.bottom).toBeLessThan(box.bottom + 1);
  }
  // The tiles below the list are under no zone.
  const tileRect = tile.getBoundingClientRect();
  expect(zones.some((zone) => zone.getBoundingClientRect().bottom > tileRect.top)).toBe(
    false
  );
  expect(model.drops).toEqual([]);
  await cancel();
  await animationFrame();
});

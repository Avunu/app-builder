import { expect, test } from "@odoo/hoot";
import { click, hover, press, queryAll, queryOne, rightClick } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { Outline } from "@app_builder_view/console/sidebar/outline";
function queryOneEl(target) {
  return queryOne(target);
}
function queryAllEl(target) {
  return queryAll(target);
}
function node(kind, tag, parent, children, extra = {}) {
  const {
    leaf = false,
    accepts = [],
    name = null,
    string = null,
    label = null,
    movable = kind !== "root" && kind !== "sheet"
  } = extra;
  return {
    kind,
    tag,
    parent,
    children,
    name,
    string,
    container: !leaf,
    index: 0,
    orientation: "column",
    accepts,
    movable,
    removable: movable,
    selectable: true,
    hidden: null,
    attrs: {},
    dom: true,
    field: null,
    view_id: null,
    label
  };
}
function makeNodes(prefix = "n") {
  const t = (n) => `${prefix}${n}`;
  const nodes = {
    [t(0)]: node("root", "form", null, [t(1)], { accepts: ["sheet", "field", "group"] }),
    [t(1)]: node("sheet", "sheet", t(0), [t(2), t(6), t(7)], {
      accepts: ["group", "notebook", "field"]
    }),
    [t(2)]: node("group", "group", t(1), [t(3), t(4), t(5)], {
      accepts: ["field", "group"],
      name: "left"
    }),
    [t(3)]: node("field", "field", t(2), [], { name: "street", string: "Street", leaf: true }),
    [t(4)]: node("field", "field", t(2), [], {
      name: "city",
      string: "City",
      leaf: true,
      label: { shown: true, by: "group", token: null, in_group: true }
    }),
    [t(5)]: node("field", "field", t(2), [], { name: "zip", string: "Zip", leaf: true }),
    [t(6)]: node("group", "group", t(1), [], {
      accepts: ["field", "group"],
      name: "studio_group_a1b2c3"
    }),
    [t(7)]: node("notebook", "notebook", t(1), [t(8), t(9)], {
      accepts: ["page"],
      movable: false
    }),
    [t(8)]: node("page", "page", t(7), [t(10)], {
      accepts: ["field", "group"],
      name: "one",
      string: "One"
    }),
    [t(9)]: node("page", "page", t(7), [], {
      accepts: ["field", "group"],
      name: "two",
      string: "Two"
    }),
    [t(10)]: node("field", "field", t(8), [], { name: "note", string: "Note", leaf: true })
  };
  return nodes;
}
function makeModel(calls, nodes = makeNodes()) {
  return reactive({
    nodes,
    root: "n0",
    canvas: { arch_version: "v1" },
    archVersion: "v1",
    editableAs: "canvas",
    viewId: 7,
    selection: null,
    selectionSerial: 0,
    hover: null,
    canWrite: true,
    outlineDrag: null,
    tagFor: (token) => `Node · ${token}`,
    hoverAt(token) {
      this.hover = token || null;
    },
    select(token) {
      this.selection = token ? { token, node: this.nodes[token] } : null;
      this.selectionSerial += 1;
    },
    reveal(token) {
      calls.push(["reveal", token]);
      this.select(token);
    },
    // Set by a test to stand in for the server's answer: the model
    // swaps the canvas in before `drop` resolves (`_mutate`).
    afterDrop: null,
    async drop(token, position, payload) {
      calls.push(["drop", token, position, payload]);
      if (this.afterDrop) {
        this.afterDrop();
      }
      return {};
    },
    async remove(token, force) {
      calls.push(["remove", token, force]);
      return {};
    },
    async setLabelShown(token, shown) {
      calls.push(["label", token, shown]);
      return {};
    }
  });
}
async function mountOutline(calls, nodes) {
  const model = makeModel(calls, nodes);
  await mountWithCleanup(Outline, { props: { model } });
  return model;
}
const ROW = ".o_studio_outline_row";
const tokens = () => queryAllEl(ROW).map((el) => el.dataset["token"]);
const row = (token) => queryOneEl(`${ROW}[data-token='${token}']`);
function readPrefs() {
  return JSON.parse(browser.localStorage.getItem("app_builder.outline") || "{}");
}
test("the rows are the tree, with the drag's provider left on the model", async () => {
  const calls = [];
  const model = await mountOutline(calls);
  expect(tokens()).toEqual(["n0", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8", "n10", "n9"]);
  expect(row("n3").dataset["depth"]).toBe("3");
  expect(row("n3").dataset["path"]).toBe("form:#0/sheet:#0/group:left/field:street");
  expect(row("n2")).toHaveAttribute("aria-expanded", "true");
  expect(row("n3")).not.toHaveAttribute("aria-expanded");
  expect(row("n1")).toHaveClass("o_studio_outline_fixed");
  expect(row("n0")).toHaveAttribute("tabindex", "0");
  expect(row("n3")).toHaveAttribute("tabindex", "-1");
  expect(model.outlineDrag).not.toBe(null);
  expect(model.outlineDrag.el).toBe(queryOneEl(".o_studio_outline_list"));
  expect(queryOne(".o_studio_outline_list .o_studio_zones")).not.toBe(null);
  expect(model.outlineDrag.indentOf(2)).toBe(8 + 32);
});
test("a click reveals, a hover outlines, and the canvas's hover is shown", async () => {
  const calls = [];
  const model = await mountOutline(calls);
  await click(row("n4"));
  await animationFrame();
  expect(calls).toEqual([["reveal", "n4"]]);
  expect(row("n4")).toHaveClass("o_studio_outline_selected");
  expect(row("n4")).toHaveAttribute("aria-selected", "true");
  await hover(row("n3"));
  expect(model.hover).toBe("n3");
  model.hover = "n5";
  await animationFrame();
  expect(row("n5")).toHaveClass("o_studio_outline_hover");
});
test("the canvas's selection opens the way to its row", async () => {
  const calls = [];
  const model = await mountOutline(calls);
  await click(queryOneEl(`${ROW}[data-token='n8'] .o_studio_outline_caret`));
  await animationFrame();
  expect(tokens()).not.toInclude("n10");
  expect(row("n8")).toHaveAttribute("aria-expanded", "false");
  expect(calls).toEqual([]);
  model.select("n10");
  await animationFrame();
  await animationFrame();
  expect(tokens()).toInclude("n10");
  expect(row("n10")).toHaveClass("o_studio_outline_selected");
  expect(row("n8")).toHaveAttribute("aria-expanded", "true");
});
test("the keyboard walks the rows, folds them, and reveals", async () => {
  const calls = [];
  await mountOutline(calls);
  row("n0").focus();
  await press("ArrowDown");
  await press("ArrowDown");
  expect(document.activeElement).toBe(row("n2"));
  await press("ArrowLeft");
  await animationFrame();
  expect(row("n2")).toHaveAttribute("aria-expanded", "false");
  expect(tokens()).not.toInclude("n3");
  await press("ArrowLeft");
  expect(document.activeElement).toBe(row("n1"));
  await press("ArrowDown");
  await press("ArrowRight");
  await animationFrame();
  expect(row("n2")).toHaveAttribute("aria-expanded", "true");
  expect(document.activeElement).toBe(row("n2"));
  await press("ArrowRight");
  expect(document.activeElement).toBe(row("n3"));
  await press("End");
  expect(document.activeElement).toBe(row("n9"));
  await press("Home");
  expect(document.activeElement).toBe(row("n0"));
  await press("ArrowDown");
  await press("ArrowDown");
  await press("ArrowDown");
  await press("Enter");
  expect(calls).toEqual([["reveal", "n3"]]);
});
test("Alt with an arrow asks the model for exactly one move, or none", async () => {
  const calls = [];
  await mountOutline(calls);
  row("n3").focus();
  await press(["Alt", "ArrowUp"]);
  await animationFrame();
  expect(calls).toEqual([]);
  await press(["Alt", "ArrowDown"]);
  await animationFrame();
  expect(calls).toEqual([["drop", "n4", "after", { kind: "move", token: "n3" }]]);
  calls.length = 0;
  await press(["Alt", "ArrowLeft"]);
  await animationFrame();
  expect(calls).toEqual([["drop", "n2", "after", { kind: "move", token: "n3" }]]);
  calls.length = 0;
  await press(["Alt", "ArrowRight"]);
  await animationFrame();
  expect(calls).toEqual([]);
  row("n1").focus();
  await press(["Alt", "ArrowDown"]);
  await animationFrame();
  expect(calls).toEqual([]);
});
test("a table minted anew keeps the folds and the focus by path", async () => {
  const calls = [];
  const model = await mountOutline(calls);
  await click(queryOneEl(`${ROW}[data-token='n8'] .o_studio_outline_caret`));
  await animationFrame();
  const swapped = makeNodes("x");
  swapped["x2"].children = ["x3", "x5", "x4"];
  model.afterDrop = () => {
    model.nodes = swapped;
    model.root = "x0";
    model.canvas = { arch_version: "v2" };
    model.archVersion = "v2";
    model.selection = { token: "x4", node: swapped["x4"] };
  };
  row("n4").focus();
  await press(["Alt", "ArrowDown"]);
  await animationFrame();
  await animationFrame();
  expect(calls).toEqual([["drop", "n5", "after", { kind: "move", token: "n4" }]]);
  expect(tokens()).toEqual(["x0", "x1", "x2", "x3", "x5", "x4", "x6", "x7", "x8", "x9"]);
  expect(row("x8")).toHaveAttribute("aria-expanded", "false");
  expect(document.activeElement).toBe(row("x4"));
  expect(row("x4")).toHaveAttribute("tabindex", "0");
  expect(row("x4")).toHaveClass("o_studio_outline_selected");
  const prefs = readPrefs();
  expect(prefs.collapsed["7"]).toEqual(["form:#0/sheet:#0/notebook:#2/page:one"]);
});
test("the right-click menu says what a row can do", async () => {
  const calls = [];
  await mountOutline(calls);
  await rightClick(row("n3"));
  await animationFrame();
  const menu = queryOne(".o_studio_outline_menu");
  expect(menu.querySelector("[data-item='move_up']")).toHaveAttribute("disabled");
  expect(menu.querySelector("[data-item='move_down']")).not.toHaveAttribute("disabled");
  expect(menu.querySelector("[data-item='move_out']")).not.toHaveAttribute("disabled");
  expect(menu.querySelector("[data-item='move_in']")).toHaveAttribute("disabled");
  expect(menu.querySelector("[data-item='remove']")).not.toBe(null);
  expect(menu.querySelector("[data-item='toggle_label']")).toBe(null);
  await click(menu.querySelector("[data-item='move_down']"));
  await animationFrame();
  expect(calls).toEqual([["drop", "n4", "after", { kind: "move", token: "n3" }]]);
  expect(queryAll(".o_studio_outline_menu")).toHaveLength(0);
  calls.length = 0;
  await rightClick(row("n4"));
  await animationFrame();
  const label = queryOne(".o_studio_outline_menu [data-item='toggle_label']");
  expect(label).toHaveText("Hide label");
  await click(label);
  await animationFrame();
  expect(calls).toEqual([["label", "n4", false]]);
  await rightClick(row("n1"));
  await animationFrame();
  expect(queryAll(".o_studio_outline_menu [data-item='remove']")).toHaveLength(0);
  expect(queryOne(".o_studio_outline_menu [data-item='move_out']")).toHaveAttribute("disabled");
  await click(queryOne(".o_studio_outline_menu [data-item='reveal']"));
  await animationFrame();
  expect(calls).toEqual([
    ["label", "n4", false],
    ["reveal", "n1"]
  ]);
});
test("Delete asks to remove what can be removed", async () => {
  const calls = [];
  await mountOutline(calls);
  row("n1").focus();
  await press("Delete");
  await animationFrame();
  expect(calls).toEqual([]);
  row("n5").focus();
  await press("Delete");
  await animationFrame();
  expect(calls).toEqual([["remove", "n5", false]]);
});
test("the filter keeps the matches and the way to them", async () => {
  const calls = [];
  await mountOutline(calls);
  const input = queryOne(".o_studio_outline_filter");
  input.value = "note";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await animationFrame();
  expect(tokens()).toEqual(["n0", "n1", "n7", "n8", "n10"]);
  input.focus();
  await press("Escape");
  await animationFrame();
  expect(tokens()).toHaveLength(11);
  expect(document.activeElement).toBe(row("n0"));
});
test("the panel folds shut and is remembered so", async () => {
  const calls = [];
  const model = await mountOutline(calls);
  expect(queryOneEl(".o_studio_outline").style.height).toBe("240px");
  await click(".o_studio_outline_toggle");
  await animationFrame();
  expect(queryAll(".o_studio_outline_list")).toHaveLength(0);
  expect(queryOne(".o_studio_outline")).toHaveClass("o_studio_outline_closed");
  expect(model.outlineDrag).toBe(null);
  expect(readPrefs().open).toBe(false);
  await click(".o_studio_outline_toggle");
  await animationFrame();
  expect(queryAll(ROW)).toHaveLength(11);
  expect(model.outlineDrag).not.toBe(null);
});

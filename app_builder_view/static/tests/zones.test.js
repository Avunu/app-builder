import { beforeEach, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/web_test_helpers";
import {
  BAR,
  GAP,
  MIN_BAR,
  MIN_INSIDE,
  buildZones,
  labelOf,
  payloadTag
} from "@app_builder_view/console/zones";
const NODES = {
  n0: node("root", "form", null, ["n1"], { accepts: ["sheet", "field", "group"] }),
  n1: node("sheet", "sheet", "n0", ["n2", "n6", "n7"], {
    accepts: ["group", "notebook", "field"]
  }),
  n2: node("group", "group", "n1", ["n3", "n4", "n5"], {
    accepts: ["field", "group"],
    name: "left"
  }),
  n3: node("field", "field", "n2", [], { name: "street", string: "Street", leaf: true }),
  n4: node("field", "field", "n2", [], { name: "city", string: "City", leaf: true }),
  n5: node("field", "field", "n2", [], { name: "zip", leaf: true }),
  n6: node("group", "group", "n1", [], {
    accepts: ["field", "group"],
    name: "studio_group_a1b2c3"
  }),
  n7: node("notebook", "notebook", "n1", ["n8", "n9"], {
    accepts: ["page"],
    orientation: "row"
  }),
  n8: node("page", "page", "n7", ["n10"], {
    accepts: ["field", "group"],
    name: "one",
    string: "One"
  }),
  n9: node("page", "page", "n7", [], { accepts: ["field", "group"], name: "two", string: "Two" }),
  n10: node("field", "field", "n8", [], { name: "note", string: "Note", leaf: true })
};
function node(kind, tag, parent, children, extra = {}) {
  const {
    leaf = false,
    accepts = [],
    orientation = "column",
    name = null,
    string = null
  } = extra;
  return {
    kind,
    tag,
    parent,
    children,
    name,
    string,
    container: !leaf,
    orientation,
    accepts,
    movable: kind !== "root" && kind !== "sheet",
    field: null,
    // The rest of `StudioNode` is real server data no test here reads
    // (buildZones/labelOf/payloadTag never touch it); filled with the
    // value an ordinary, un-hidden, un-pending node would carry rather
    // than left off, so the fixture is a real `StudioNode` and not a
    // cast pretending it is one.
    index: 0,
    removable: true,
    selectable: true,
    hidden: null,
    attrs: {},
    dom: true,
    view_id: null,
    label: null
  };
}
function rect(top, left, width, height) {
  return { top, left, width, height };
}
beforeEach(() => patchTranslations());
const RECTS = {
  n0: rect(0, 0, 400, 400),
  n1: rect(0, 0, 400, 400),
  n2: rect(20, 10, 380, 90),
  n3: rect(20, 10, 380, 30),
  n4: rect(50, 10, 380, 30),
  n5: rect(80, 10, 380, 30),
  n6: rect(120, 10, 380, 0),
  n7: rect(200, 10, 380, 130),
  n8: rect(200, 10, 80, 30),
  n9: rect(200, 90, 80, 30),
  n10: rect(240, 10, 380, 30)
};
const PANE = rect(230, 10, 380, 100);
function layout({ tag, moving = null, active = "n8" }) {
  const nodes = NODES;
  return buildZones({
    nodes,
    tag,
    moving,
    contentOf: (token) => {
      const found = nodes[token];
      return token === active && found && found.kind === "page" ? PANE : RECTS[token] ?? null;
    },
    childrenOf: (token) => {
      const found = nodes[token];
      if (!found) {
        return [];
      }
      return found.children.flatMap((child) => {
        const r = RECTS[child];
        return r ? [{ token: child, rect: r }] : [];
      });
    },
    isActive: (token) => token === active
  });
}
function find(zones, token, position) {
  return zones.find((zone) => zone.token === token && zone.position === position);
}
test("a column of fields gets a bar above the first and after each", () => {
  const { zones } = layout({ tag: "field" });
  const inGroup = zones.filter((zone) => zone.container === "n2");
  expect(inGroup.map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n3", "after"],
    ["n4", "after"],
    ["n5", "after"]
  ]);
  for (const zone of inGroup) {
    expect(zone.axis).toBe("y");
    expect(zone.rect.height).toBe(BAR);
    expect(zone.rect.width).toBe(380 - 16);
    expect(zone.containerKind).toBe("group");
  }
  const between = find(inGroup, "n3", "after");
  expect(between.rect.top).toBe(50 - BAR / 2);
  expect(find(inGroup, "n3", "before").rect.top).toBe(20);
  expect(find(inGroup, "n3", "before").edge).toBe("start");
  expect(find(inGroup, "n5", "after").edge).toBe("end");
  expect(find(inGroup, "n5", "after").rect.top + BAR).toBeLessThan(110 + 1);
});
test("captions name the neighbour by its label, or the end of the container", () => {
  const { zones } = layout({ tag: "field" });
  expect(find(zones, "n3", "before").caption).toBe("before Street");
  expect(find(zones, "n4", "after").caption).toBe("after City");
  expect(find(zones, "n5", "after").caption).toBe("after zip");
  expect(find(zones, "n7", "after").caption).toBe("at the end of the sheet");
  expect(find(zones, "n6", "inside").caption).toBe("into the group");
  expect(labelOf(NODES.n6)).toBe("the group");
});
test("an empty container offers one dashed zone of a real size", () => {
  const { zones, containers } = layout({ tag: "field" });
  const inside = find(zones, "n6", "inside");
  expect(inside.kind).toBe("group");
  expect(inside.name).toBe("studio_group_a1b2c3");
  expect(inside.rect.left).toBe(18);
  expect(inside.rect.width).toBe(380 - 16);
  expect(containers.some((c) => c.token === "n6")).toBe(true);
  const above = find(zones, "n2", "after");
  const below = find(zones, "n6", "after");
  expect(below).not.toBe(void 0);
  expect(inside.rect.top).toBe(above.rect.top + above.rect.height + GAP);
  expect(inside.rect.top + inside.rect.height).toBe(below.rect.top - GAP);
  expect(inside.rect.height).toBeGreaterThan(MIN_BAR);
});
const TAIL_NODES = {
  r: node("root", "form", null, ["s"], { accepts: ["sheet", "field", "group"] }),
  s: node("sheet", "sheet", "r", ["g", "e"], { accepts: ["group", "field"] }),
  g: node("group", "group", "s", ["f"], { accepts: ["field", "group"], name: "main" }),
  f: node("field", "field", "g", [], { name: "name", string: "Name", leaf: true }),
  e: node("group", "group", "s", [], { accepts: ["field", "group"], name: "studio_group_ffff" })
};
const TAIL_RECTS = {
  r: rect(0, 0, 400, 300),
  s: rect(0, 0, 400, 300),
  g: rect(20, 10, 380, 30),
  f: rect(20, 10, 380, 30),
  e: rect(66, 10, 380, 0)
};
test("an empty last child does not cost its parent the bar after it", () => {
  const { zones } = buildZones({
    nodes: TAIL_NODES,
    tag: "field",
    contentOf: (token) => TAIL_RECTS[token] ?? null,
    childrenOf: (token) => {
      const found = TAIL_NODES[token];
      if (!found) {
        return [];
      }
      return found.children.flatMap((child) => {
        const r = TAIL_RECTS[child];
        return r ? [{ token: child, rect: r }] : [];
      });
    },
    isActive: () => true
  });
  const end = find(zones, "e", "after");
  expect(end).not.toBe(void 0);
  expect(end.edge).toBe("end");
  expect(end.caption).toBe("at the end of the sheet");
  expect(end.rect.height).toBeGreaterThan(MIN_BAR);
  const inside = find(zones, "e", "inside");
  expect(inside).not.toBe(void 0);
  expect(inside.rect.top).toBeGreaterThan(end.rect.top + end.rect.height + GAP - 1);
  expect(inside.rect.height).toBeGreaterThan(MIN_INSIDE / 2 - 1);
  for (const a of zones) {
    for (const b of zones) {
      if (a !== b) {
        expect(overlapping(a.rect, b.rect)).toBe(false);
      }
    }
  }
});
test("a row container gets vertical bars", () => {
  const { zones } = layout({ tag: "page" });
  expect(zones.every((zone) => zone.container === "n7")).toBe(true);
  expect(zones.map((zone) => [zone.token, zone.position])).toEqual([
    ["n8", "before"],
    ["n8", "after"],
    ["n9", "after"]
  ]);
  for (const zone of zones) {
    expect(zone.axis).toBe("x");
    expect(zone.rect.width).toBe(BAR);
    expect(zone.rect.height).toBe(30 - 8);
  }
  expect(find(zones, "n9", "after").edge).toBe("end");
  expect(find(zones, "n9", "after").containerKind).toBe("notebook");
});
test("only the active page has zones; the sheet's root does not", () => {
  const { zones } = layout({ tag: "field" });
  expect(zones.some((zone) => zone.container === "n8")).toBe(true);
  expect(zones.some((zone) => zone.container === "n9")).toBe(false);
  expect(zones.some((zone) => zone.container === "n0")).toBe(false);
  const other = layout({ tag: "field", active: "n9" });
  expect(other.zones.some((zone) => zone.container === "n8")).toBe(false);
  expect(other.zones.some((zone) => zone.container === "n9")).toBe(true);
});
test("a move leaves out its own subtree and the gaps beside it", () => {
  const { zones } = layout({ tag: "field", moving: "n4" });
  const inGroup = zones.filter((zone) => zone.container === "n2");
  expect(inGroup.map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n5", "after"]
  ]);
  const moved = layout({ tag: "group", moving: "n2" });
  expect(moved.zones.some((zone) => zone.container === "n2")).toBe(false);
  expect(moved.zones.some((zone) => zone.token === "n2")).toBe(false);
});
test("a ghost is a neighbour like any other: the gaps beside it carry its token", () => {
  const nodes = {
    ...NODES,
    n2: { ...NODES.n2, children: ["n3", "n4", "p_weight", "n5"] },
    p_weight: {
      ...node("pending", "widget", "n2", [], {
        leaf: true,
        name: "weight",
        string: "Weight"
      }),
      pending: {
        draft_id: 0,
        name: "weight",
        ttype: "float",
        string: "Weight",
        resolved: false
      }
    }
  };
  const rects = {
    ...RECTS,
    n2: rect(20, 10, 380, 120),
    n5: rect(110, 10, 380, 30),
    p_weight: rect(80, 10, 380, 30)
  };
  const built = (moving) => buildZones({
    nodes,
    tag: "field",
    moving,
    contentOf: (token) => (rects[token] || RECTS[token]) ?? null,
    childrenOf: (token) => {
      const found = nodes[token];
      if (!found) {
        return [];
      }
      return found.children.flatMap((child) => {
        const r = rects[child];
        return r ? [{ token: child, rect: r }] : [];
      });
    },
    isActive: (token) => token === "n8"
  }).zones.filter((zone) => zone.container === "n2");
  expect(built(null).map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n3", "after"],
    ["n4", "after"],
    ["p_weight", "after"],
    ["n5", "after"]
  ]);
  expect(find(built(null), "p_weight", "after").caption).toBe("after Weight");
  expect(built("p_weight").map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n3", "after"],
    ["n5", "after"]
  ]);
});
function overlapping(a, b) {
  return !(a.left >= b.left + b.width + GAP || b.left >= a.left + a.width + GAP || a.top >= b.top + b.height + GAP || b.top >= a.top + a.height + GAP);
}
test("no two zones overlap, and the deeper one keeps its place", () => {
  const { zones } = layout({ tag: "field" });
  for (const a of zones) {
    for (const b of zones) {
      if (a !== b) {
        expect(overlapping(a.rect, b.rect)).toBe(false);
      }
    }
  }
  const last = find(zones, "n5", "after");
  const afterGroup = find(zones, "n2", "after");
  expect(last.rect.top).toBe(110 - BAR);
  expect(afterGroup.rect.top).toBeGreaterThan(last.rect.top + last.rect.height);
});
test("the tag of a payload", () => {
  expect(payloadTag({ kind: "existing_field", name: "x" })).toBe("field");
  expect(payloadTag({ kind: "new_field", values: {} })).toBe("field");
  expect(payloadTag({ kind: "component", component: "columns" })).toBe("group");
  expect(payloadTag({ kind: "component", component: "page" })).toBe("page");
  expect(payloadTag({ kind: "move", token: "n2" }, NODES)).toBe("group");
  expect(payloadTag({ kind: "move", token: "nope" }, NODES)).toBe(null);
  expect(payloadTag({ kind: "component", component: "nope" })).toBe(null);
  expect(payloadTag(null)).toBe(null);
});

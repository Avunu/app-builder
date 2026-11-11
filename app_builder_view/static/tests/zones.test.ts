/** @odoo-module **/
/**
 * The drop-zone layout, on rectangles alone.
 *
 * `zones.js` reaches the DOM only through callbacks, so what it decides --
 * which containers take the payload, where the bars go, what a move may
 * not land beside, that no two zones overlap -- is pinned here on plain
 * numbers, with no view mounted.
 */

import {beforeEach, expect, test} from "@odoo/hoot";
import {patchTranslations} from "@web/../tests/web_test_helpers";

import {
  BAR,
  GAP,
  MIN_BAR,
  MIN_INSIDE,
  buildZones,
  labelOf,
  payloadTag,
} from "@app_builder_view/console/zones";
import type {ZoneChild} from "@app_builder_view/console/zones";
import type {
  NodeKind,
  NodeTable,
  Orientation,
  PlainRect,
  BuilderNode,
  Token,
  Zone,
  ZoneContainer,
  ZonePosition,
} from "@app_builder_view/console/types";

// A form: a sheet holding one group of three fields, an empty group, and a
// notebook with two pages -- the first shown, the second not.
const NODES = {
  n0: node("root", "form", null, ["n1"], {accepts: ["sheet", "field", "group"]}),
  n1: node("sheet", "sheet", "n0", ["n2", "n6", "n7"], {
    accepts: ["group", "notebook", "field"],
  }),
  n2: node("group", "group", "n1", ["n3", "n4", "n5"], {
    accepts: ["field", "group"],
    name: "left",
  }),
  n3: node("field", "field", "n2", [], {name: "street", string: "Street", leaf: true}),
  n4: node("field", "field", "n2", [], {name: "city", string: "City", leaf: true}),
  n5: node("field", "field", "n2", [], {name: "zip", leaf: true}),
  n6: node("group", "group", "n1", [], {
    accepts: ["field", "group"],
    name: "builder_group_a1b2c3",
  }),
  n7: node("notebook", "notebook", "n1", ["n8", "n9"], {
    accepts: ["page"],
    orientation: "row",
  }),
  n8: node("page", "page", "n7", ["n10"], {
    accepts: ["field", "group"],
    name: "one",
    string: "One",
  }),
  n9: node("page", "page", "n7", [], {
    accepts: ["field", "group"],
    name: "two",
    string: "Two",
  }),
  n10: node("field", "field", "n8", [], {name: "note", string: "Note", leaf: true}),
};

/** The optional, named fields `node()`'s callers may set; anything left
 * out takes the default a plain, un-hidden, un-pending node would have. */
interface NodeExtra {
  leaf?: boolean;
  accepts?: readonly string[];
  orientation?: Orientation;
  name?: string | null;
  string?: string | null;
}

function node(
  kind: NodeKind,
  tag: string,
  parent: Token | null,
  children: Token[],
  extra: NodeExtra = {}
): BuilderNode {
  const {
    leaf = false,
    accepts = [],
    orientation = "column",
    name = null,
    string = null,
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
    // The rest of `BuilderNode` is real server data no test here reads
    // (buildZones/labelOf/payloadTag never touch it); filled with the
    // value an ordinary, un-hidden, un-pending node would carry rather
    // than left off, so the fixture is a real `BuilderNode` and not a
    // cast pretending it is one.
    index: 0,
    removable: true,
    selectable: true,
    hidden: null,
    attrs: {},
    dom: true,
    view_id: null,
    label: null,
  };
}

function rect(top: number, left: number, width: number, height: number): PlainRect {
  return {top, left, width, height};
}

// The captions are translated; with no env mounted, nothing has loaded
// the translations the lazy strings wait for.
beforeEach(() => patchTranslations());

// Where things are: the sheet from 0 to 400, the group's three rows of 30px
// from 20, the empty group at 120 with no height, the notebook from 200 --
// its tab strip 30px tall with two 80px tabs, its pane below -- and the
// first page's field in the pane.
const RECTS: Record<Token, PlainRect> = {
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
  n10: rect(240, 10, 380, 30),
};
const PANE: PlainRect = rect(230, 10, 380, 100);

interface LayoutOptions {
  tag: string | null;
  moving?: Token | null;
  active?: Token;
}

function layout({tag, moving = null, active = "n8"}: LayoutOptions): {
  zones: Zone[];
  containers: ZoneContainer[];
} {
  // A local, index-signature-typed view of `NODES`, for the dynamic
  // (bracket) lookups below -- `NODES` itself stays un-annotated so its
  // own known keys (`NODES.n6`, `NODES.n2`) keep reading by dot access.
  const nodes: NodeTable = NODES;
  return buildZones({
    nodes,
    tag,
    moving,
    contentOf: (token: Token): PlainRect | null => {
      const found = nodes[token];
      return token === active && found && found.kind === "page"
        ? PANE
        : (RECTS[token] ?? null);
    },
    childrenOf: (token: Token): ZoneChild[] => {
      const found = nodes[token];
      if (!found) {
        return [];
      }
      return found.children.flatMap((child) => {
        const r = RECTS[child];
        return r ? [{token: child, rect: r}] : [];
      });
    },
    isActive: (token: Token): boolean => token === active,
  });
}

function find(zones: Zone[], token: Token, position: ZonePosition): Zone | undefined {
  return zones.find((zone) => zone.token === token && zone.position === position);
}

test("a column of fields gets a bar above the first and after each", () => {
  const {zones} = layout({tag: "field"});
  const inGroup = zones.filter((zone) => zone.container === "n2");
  expect(inGroup.map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n3", "after"],
    ["n4", "after"],
    ["n5", "after"],
  ]);
  for (const zone of inGroup) {
    expect(zone.axis).toBe("y");
    expect(zone.rect.height).toBe(BAR);
    expect(zone.rect.width).toBe(380 - 16);
    expect(zone.containerKind).toBe("group");
  }
  // The gap between two rows is centred on their boundary.
  const between = find(inGroup, "n3", "after")!;
  expect(between.rect.top).toBe(50 - BAR / 2);
  // The edges stay inside the group's own box.
  expect(find(inGroup, "n3", "before")!.rect.top).toBe(20);
  expect(find(inGroup, "n3", "before")!.edge).toBe("start");
  expect(find(inGroup, "n5", "after")!.edge).toBe("end");
  expect(find(inGroup, "n5", "after")!.rect.top + BAR).toBeLessThan(110 + 1);
});

test("captions name the neighbour by its label, or the end of the container", () => {
  const {zones} = layout({tag: "field"});
  expect(find(zones, "n3", "before")!.caption).toBe("before Street");
  expect(find(zones, "n4", "after")!.caption).toBe("after City");
  // A field with no string is named by its technical name.
  expect(find(zones, "n5", "after")!.caption).toBe("after zip");
  // The last gap of the sheet is "the end of the sheet".
  expect(find(zones, "n7", "after")!.caption).toBe("at the end of the sheet");
  // An empty container reads as "into", and a generated name is not a name.
  expect(find(zones, "n6", "inside")!.caption).toBe("into the group");
  expect(labelOf(NODES.n6)).toBe("the group");
});

test("an empty container offers one dashed zone of a real size", () => {
  const {zones, containers} = layout({tag: "field"});
  const inside = find(zones, "n6", "inside")!;
  expect(inside.kind).toBe("group");
  expect(inside.name).toBe("builder_group_a1b2c3");
  expect(inside.rect.left).toBe(18);
  expect(inside.rect.width).toBe(380 - 16);
  expect(containers.some((c) => c.token === "n6")).toBe(true);
  // The group has no height, so its box is laid over the sheet below it
  // -- and yields to the sheet's own bars on either side of it, keeping
  // what is left between them rather than covering one of them up.
  const above = find(zones, "n2", "after")!;
  const below = find(zones, "n6", "after")!;
  // `below` is already narrowed to `Zone` by the `!` above;
  // `expect<R>`'s `R` then pins `.toBe`'s argument to `Zone` too, so
  // checking against `undefined` (still a real, meaningful assertion
  // -- `find`'s real return is `Zone | undefined`) needs this cast to
  // widen back to what `find` actually returns.
  expect(below as Zone | undefined).not.toBe(undefined);
  expect(inside.rect.top).toBe(above.rect.top + above.rect.height + GAP);
  expect(inside.rect.top + inside.rect.height).toBe(below.rect.top - GAP);
  expect(inside.rect.height).toBeGreaterThan(MIN_BAR);
});

// A sheet whose last child is an empty group with no height: what the Group
// and Columns tiles leave at the end of the sheet the moment they land.
const TAIL_NODES: NodeTable = {
  r: node("root", "form", null, ["s"], {accepts: ["sheet", "field", "group"]}),
  s: node("sheet", "sheet", "r", ["g", "e"], {accepts: ["group", "field"]}),
  g: node("group", "group", "s", ["f"], {accepts: ["field", "group"], name: "main"}),
  f: node("field", "field", "g", [], {name: "name", string: "Name", leaf: true}),
  e: node("group", "group", "s", [], {
    accepts: ["field", "group"],
    name: "builder_group_ffff",
  }),
};
const TAIL_RECTS: Record<Token, PlainRect> = {
  r: rect(0, 0, 400, 300),
  s: rect(0, 0, 400, 300),
  g: rect(20, 10, 380, 30),
  f: rect(20, 10, 380, 30),
  e: rect(66, 10, 380, 0),
};

test("an empty last child does not cost its parent the bar after it", () => {
  const {zones} = buildZones({
    nodes: TAIL_NODES,
    tag: "field",
    contentOf: (token: Token): PlainRect | null => TAIL_RECTS[token] ?? null,
    childrenOf: (token: Token): ZoneChild[] => {
      const found = TAIL_NODES[token];
      if (!found) {
        return [];
      }
      return found.children.flatMap((child) => {
        const r = TAIL_RECTS[child];
        return r ? [{token: child, rect: r}] : [];
      });
    },
    isActive: (): boolean => true,
  });
  // The end of the sheet is still on offer, right where the empty group
  // ends; the group's box sits below the bar, and is still a real box.
  const end = find(zones, "e", "after")!;
  expect(end as Zone | undefined).not.toBe(undefined);
  expect(end.edge).toBe("end");
  expect(end.caption).toBe("at the end of the sheet");
  expect(end.rect.height).toBeGreaterThan(MIN_BAR);
  const inside = find(zones, "e", "inside")!;
  expect(inside as Zone | undefined).not.toBe(undefined);
  expect(inside.rect.top).toBeGreaterThan(end.rect.top + end.rect.height + GAP - 1);
  expect(inside.rect.height).toBeGreaterThan(MIN_INSIDE / 2 - 1);
  // And, as always, nothing overlaps.
  for (const a of zones) {
    for (const b of zones) {
      if (a !== b) {
        expect(overlapping(a.rect, b.rect)).toBe(false);
      }
    }
  }
});

test("a row container gets vertical bars", () => {
  const {zones} = layout({tag: "page"});
  // Only the notebook takes a page.
  expect(zones.every((zone) => zone.container === "n7")).toBe(true);
  expect(zones.map((zone) => [zone.token, zone.position])).toEqual([
    ["n8", "before"],
    ["n8", "after"],
    ["n9", "after"],
  ]);
  for (const zone of zones) {
    expect(zone.axis).toBe("x");
    expect(zone.rect.width).toBe(BAR);
    expect(zone.rect.height).toBe(30 - 8);
  }
  expect(find(zones, "n9", "after")!.edge).toBe("end");
  expect(find(zones, "n9", "after")!.containerKind).toBe("notebook");
});

test("only the active page has zones; the sheet's root does not", () => {
  const {zones} = layout({tag: "field"});
  expect(zones.some((zone) => zone.container === "n8")).toBe(true);
  expect(zones.some((zone) => zone.container === "n9")).toBe(false);
  // The form has a sheet: nothing goes beside the sheet.
  expect(zones.some((zone) => zone.container === "n0")).toBe(false);
  const other = layout({tag: "field", active: "n9"});
  expect(other.zones.some((zone) => zone.container === "n8")).toBe(false);
  expect(other.zones.some((zone) => zone.container === "n9")).toBe(true);
});

test("a move leaves out its own subtree and the gaps beside it", () => {
  const {zones} = layout({tag: "field", moving: "n4"});
  const inGroup = zones.filter((zone) => zone.container === "n2");
  // Neither the gap before City nor the one after it: both are where it is.
  expect(inGroup.map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n5", "after"],
  ]);
  // Moving a container: nothing inside it is a target.
  const moved = layout({tag: "group", moving: "n2"});
  expect(moved.zones.some((zone) => zone.container === "n2")).toBe(false);
  expect(moved.zones.some((zone) => zone.token === "n2")).toBe(false);
});

test("a ghost is a neighbour like any other: the gaps beside it carry its token", () => {
  // The group with a pending field between City and Zip, as the canvas
  // splices one: the server addresses `p_<name>` in `drop_at`, so the
  // zones name the ghost itself and the drop keeps its side of it.
  const nodes: NodeTable = {
    ...NODES,
    n2: {...NODES.n2, children: ["n3", "n4", "p_weight", "n5"]},
    p_weight: {
      ...node("pending", "widget", "n2", [], {
        leaf: true,
        name: "weight",
        string: "Weight",
      }),
      pending: {
        draft_id: 0,
        name: "weight",
        ttype: "float",
        string: "Weight",
        resolved: false,
      },
    },
  };
  // The group grows by the ghost's row, and Zip moves down under it.
  const rects: Record<Token, PlainRect> = {
    ...RECTS,
    n2: rect(20, 10, 380, 120),
    n5: rect(110, 10, 380, 30),
    p_weight: rect(80, 10, 380, 30),
  };
  const built = (moving: Token | null): Zone[] =>
    buildZones({
      nodes,
      tag: "field",
      moving,
      contentOf: (token: Token): PlainRect | null =>
        (rects[token] || RECTS[token]) ?? null,
      childrenOf: (token: Token): ZoneChild[] => {
        const found = nodes[token];
        if (!found) {
          return [];
        }
        return found.children.flatMap((child) => {
          const r = rects[child];
          return r ? [{token: child, rect: r}] : [];
        });
      },
      isActive: (token: Token): boolean => token === "n8",
    }).zones.filter((zone) => zone.container === "n2");
  expect(built(null).map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n3", "after"],
    ["n4", "after"],
    ["p_weight", "after"],
    ["n5", "after"],
  ]);
  expect(find(built(null), "p_weight", "after")!.caption).toBe("after Weight");
  // Re-anchoring the ghost by dragging it: the two gaps it sits in are out.
  expect(built("p_weight").map((zone) => [zone.token, zone.position])).toEqual([
    ["n3", "before"],
    ["n3", "after"],
    ["n5", "after"],
  ]);
});

/** Whether two zone rectangles are closer than the gap the layout keeps. */
function overlapping(a: PlainRect, b: PlainRect): boolean {
  return !(
    a.left >= b.left + b.width + GAP ||
    b.left >= a.left + a.width + GAP ||
    a.top >= b.top + b.height + GAP ||
    b.top >= a.top + a.height + GAP
  );
}

test("no two zones overlap, and the deeper one keeps its place", () => {
  const {zones} = layout({tag: "field"});
  for (const a of zones) {
    for (const b of zones) {
      if (a !== b) {
        expect(overlapping(a.rect, b.rect)).toBe(false);
      }
    }
  }
  // The group's last bar sits at the group's bottom edge, untouched; the
  // sheet's bar after the group was pushed below it.
  const last = find(zones, "n5", "after")!;
  const afterGroup = find(zones, "n2", "after")!;
  expect(last.rect.top).toBe(110 - BAR);
  expect(afterGroup.rect.top).toBeGreaterThan(last.rect.top + last.rect.height);
});

test("the tag of a payload", () => {
  expect(payloadTag({kind: "existing_field", name: "x"})).toBe("field");
  expect(payloadTag({kind: "new_field", values: {}})).toBe("field");
  expect(payloadTag({kind: "component", component: "columns"})).toBe("group");
  expect(payloadTag({kind: "component", component: "page"})).toBe("page");
  expect(payloadTag({kind: "move", token: "n2"}, NODES)).toBe("group");
  expect(payloadTag({kind: "move", token: "nope"}, NODES)).toBe(null);
  expect(payloadTag({kind: "component", component: "nope"})).toBe(null);
  expect(payloadTag(null)).toBe(null);
});

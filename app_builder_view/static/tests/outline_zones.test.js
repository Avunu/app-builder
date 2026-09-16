/** @odoo-module **/
/**
 * The outline's drop-zone layout, on rectangles alone.
 *
 * `outline_zones.js` sees rows as `{token, depth, rect}` and nothing
 * else, so where a drop may land in the tree -- which gap means what,
 * how a gap that closes several containers is cut into bands, what a
 * move leaves out, what the list's edge clips -- is pinned here on
 * plain numbers.
 */

import { beforeEach, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/web_test_helpers";

import { END_EXT, outlineZones } from "@app_builder_view/console/outline_zones";
import { MIN_BAR } from "@app_builder_view/console/zones";

// The form of zones.test.js: a sheet holding a group of three fields, an
// empty group and a notebook of two pages, the first with one field.
const NODES = {
    n0: node("root", "form", null, ["n1"], { accepts: ["sheet", "field", "group"] }),
    n1: node("sheet", "sheet", "n0", ["n2", "n6", "n7"], {
        accepts: ["group", "notebook", "field"],
    }),
    n2: node("group", "group", "n1", ["n3", "n4", "n5"], {
        accepts: ["field", "group"],
        name: "left",
    }),
    n3: node("field", "field", "n2", [], { name: "street", string: "Street", leaf: true }),
    n4: node("field", "field", "n2", [], { name: "city", string: "City", leaf: true }),
    n5: node("field", "field", "n2", [], { name: "zip", leaf: true }),
    n6: node("group", "group", "n1", [], { accepts: ["field", "group"], name: "studio_group_a1b2c3" }),
    n7: node("notebook", "notebook", "n1", ["n8", "n9"], { accepts: ["page"] }),
    n8: node("page", "page", "n7", ["n10"], { accepts: ["field", "group"], name: "one", string: "One" }),
    n9: node("page", "page", "n7", [], { accepts: ["field", "group"], name: "two", string: "Two" }),
    n10: node("field", "field", "n8", [], { name: "note", string: "Note", leaf: true }),
};

function node(kind, tag, parent, children, extra = {}) {
    const { leaf = false, accepts = [], name = null, string = null } = extra;
    return {
        kind,
        tag,
        parent,
        children,
        name,
        string,
        container: !leaf,
        accepts,
        movable: kind !== "root" && kind !== "sheet",
        selectable: true,
        field: null,
        label: null,
    };
}

const ROW = 24;
const WIDTH = 240;
const indentOf = (depth) => 8 + 16 * depth;

/** Rows of 24px from the top of a 240px-wide list, in the order given. */
function rowsOf(entries, top = 0) {
    return entries.map(([token, depth], index) => ({
        token,
        depth,
        rect: { top: top + index * ROW, left: 0, width: WIDTH, height: ROW },
    }));
}

const ALL = rowsOf([
    ["n0", 0],
    ["n1", 1],
    ["n2", 2],
    ["n3", 3],
    ["n4", 3],
    ["n5", 3],
    ["n6", 2],
    ["n7", 2],
    ["n8", 3],
    ["n10", 4],
    ["n9", 3],
]);

function layout({ tag, moving = null, rows = ALL, box = { top: 0, left: 0, width: WIDTH, height: 400 } }) {
    return outlineZones({ nodes: NODES, tag, moving, rows, indentOf, box }).zones;
}

function find(zones, token, position, depth = null) {
    return zones.find(
        (zone) =>
            zone.token === token &&
            zone.position === position &&
            (depth === null || zone.depth === depth)
    );
}

beforeEach(() => patchTranslations());

test("a gap between two siblings is one full-width place", () => {
    const zones = layout({ tag: "field" });
    const between = find(zones, "n3", "after");
    expect(between.container).toBe("n2");
    expect(between.layer).toBe("outline");
    expect(between.axis).toBe("y");
    expect(between.rect.left).toBe(0);
    expect(between.rect.width).toBe(WIDTH);
    // From the middle of Street to the middle of City, drawn on the line
    // between them.
    expect(between.rect.top).toBe(3 * ROW + ROW / 2);
    expect(between.rect.height).toBe(ROW);
    expect(between.line).toBe(4 * ROW);
    expect(between.caption).toBe("after Street");
    expect(between.edge).toBe(null);
    // Above the first child: before it, in its container.
    const first = find(zones, "n3", "before");
    expect(first.container).toBe("n2");
    expect(first.edge).toBe("start");
    expect(first.caption).toBe("before Street");
});

test("a gap that closes a container is cut into bands, deepest over the text", () => {
    const zones = layout({ tag: "field" });
    // Below Zip: after Zip in the group, or after the group in the sheet.
    const inGroup = find(zones, "n5", "after", 3);
    const inSheet = find(zones, "n2", "after", 2);
    expect(inGroup).not.toBe(undefined);
    expect(inSheet).not.toBe(undefined);
    expect(inGroup.rect.left).toBe(indentOf(3));
    expect(inGroup.rect.left + inGroup.rect.width).toBe(WIDTH);
    expect(inSheet.rect.left).toBe(0);
    expect(inSheet.rect.width).toBe(indentOf(3));
    expect(inGroup.line).toBe(inSheet.line);
    expect(inGroup.line).toBe(6 * ROW);
    expect(inGroup.rect.top).toBe(inSheet.rect.top);
    expect(inGroup.edge).toBe("end");
    expect(inSheet.edge).toBe(null);
    expect(inGroup.caption).toBe("after zip");
    expect(inSheet.caption).toBe("after left");
    // The row below is an empty group, a place of its own: the gap stops
    // at its upper quarter.
    expect(inGroup.rect.top + inGroup.rect.height).toBe(6 * ROW + ROW / 4);
});

test("an empty container is a box on its own row, between the gaps", () => {
    const zones = layout({ tag: "field" });
    const inside = find(zones, "n6", "inside");
    expect(inside.rect.top).toBe(6 * ROW + ROW / 4);
    expect(inside.rect.height).toBe(ROW / 2);
    expect(inside.rect.width).toBe(WIDTH);
    expect(inside.line).toBe(null);
    expect(inside.caption).toBe("into the group");
    const after = find(zones, "n6", "after");
    expect(after.rect.top).toBe(6 * ROW + (3 * ROW) / 4);
    // An expanded container is not a box: its first gap is the way in.
    expect(find(zones, "n2", "inside")).toBe(undefined);
    expect(find(zones, "n8", "inside")).toBe(undefined);
    expect(find(zones, "n9", "inside").caption).toBe("into Two");
});

test("a form with a sheet takes nothing beside the sheet; a container takes what it accepts", () => {
    const zones = layout({ tag: "field" });
    expect(zones.some((zone) => zone.container === "n0")).toBe(false);
    // The notebook takes no field: nothing before its first page, and
    // the gap below the page's field offers the page's end only.
    expect(find(zones, "n8", "before")).toBe(undefined);
    expect(find(zones, "n8", "after")).toBe(undefined);
    const endOfPage = find(zones, "n10", "after");
    expect(endOfPage.caption).toBe("at the end of One");
    expect(endOfPage.rect.width).toBe(WIDTH);
    // Below the last row: after the notebook, at the end of the sheet.
    const end = find(zones, "n7", "after");
    expect(end.edge).toBe("end");
    expect(end.caption).toBe("at the end of the sheet");
    expect(end.rect.top).toBe(10 * ROW + (3 * ROW) / 4);
    expect(end.rect.height).toBe(ROW / 4 + END_EXT);
    expect(find(zones, "n1", "after")).toBe(undefined);
    // A page goes only into the notebook.
    const pages = layout({ tag: "page" });
    expect(pages.every((zone) => zone.container === "n7")).toBe(true);
    expect(pages.map((zone) => [zone.token, zone.position])).toEqual([
        ["n8", "before"],
        ["n8", "after"],
        ["n9", "after"],
    ]);
    expect(find(pages, "n9", "after").caption).toBe("after Two");
});

test("a move leaves out its own subtree and the gaps beside it", () => {
    const zones = layout({ tag: "field", moving: "n4" });
    expect(find(zones, "n3", "after")).toBe(undefined);
    expect(find(zones, "n4", "after")).toBe(undefined);
    expect(find(zones, "n3", "before")).not.toBe(undefined);
    expect(find(zones, "n5", "after")).not.toBe(undefined);
    // A container on the move: nothing in it, nothing beside it, and the
    // band that would put it after itself is gone too.
    const group = layout({ tag: "group", moving: "n2" });
    expect(group.some((zone) => zone.container === "n2")).toBe(false);
    expect(find(group, "n2", "before")).toBe(undefined);
    expect(find(group, "n2", "after")).toBe(undefined);
    expect(find(group, "n6", "after")).not.toBe(undefined);
    expect(find(group, "n6", "inside")).not.toBe(undefined);
});

test("a folded container is a box, and the gap below it is its parent's", () => {
    const rows = rowsOf([
        ["n0", 0],
        ["n1", 1],
        ["n2", 2],
        ["n6", 2],
        ["n7", 2],
        ["n8", 3],
        ["n10", 4],
        ["n9", 3],
    ]);
    const zones = layout({ tag: "field", rows });
    const inside = find(zones, "n2", "inside");
    expect(inside.rect.top).toBe(2 * ROW + ROW / 4);
    const before = find(zones, "n2", "before");
    expect(before.rect.top).toBe(ROW + ROW / 2);
    expect(before.rect.top + before.rect.height).toBe(2 * ROW + ROW / 4);
    const after = find(zones, "n2", "after");
    expect(after.container).toBe("n1");
    expect(after.depth).toBe(2);
    expect(after.rect.width).toBe(WIDTH);
    expect(zones.some((zone) => zone.container === "n2" && zone.position !== "inside")).toBe(false);
});

test("nothing is laid out beyond the list's own box", () => {
    const box = { top: 0, left: 0, width: WIDTH, height: 100 };
    const zones = layout({ tag: "field", box });
    expect(zones.length).toBeGreaterThan(0);
    for (const zone of zones) {
        expect(zone.rect.top).toBeGreaterThan(-1);
        expect(zone.rect.top + zone.rect.height).toBeLessThan(101);
        expect(zone.rect.height).toBeGreaterThan(MIN_BAR - 1);
    }
    // A row scrolled out of view above the box has no gap of its own.
    const scrolled = layout({ tag: "field", rows: rowsOf(ALL.map((r) => [r.token, r.depth]), -200), box });
    expect(find(scrolled, "n3", "after")).toBe(undefined);
    expect(find(scrolled, "n10", "after")).not.toBe(undefined);
});

test("no two zones overlap", () => {
    for (const tag of ["field", "group", "page"]) {
        const zones = layout({ tag });
        for (const a of zones) {
            for (const b of zones) {
                if (a !== b) {
                    expect(overlapping(a.rect, b.rect)).toBe(false);
                }
            }
        }
    }
});

function overlapping(a, b) {
    return !(
        a.left >= b.left + b.width ||
        b.left >= a.left + a.width ||
        a.top >= b.top + b.height ||
        b.top >= a.top + a.height
    );
}

test("nothing to lay out without a tag, rows or a box", () => {
    expect(layout({ tag: null })).toEqual([]);
    expect(layout({ tag: "field", rows: [] })).toEqual([]);
    expect(outlineZones({ nodes: NODES, tag: "field", rows: ALL, indentOf, box: null }).zones).toEqual(
        []
    );
});

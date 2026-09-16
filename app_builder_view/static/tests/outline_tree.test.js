/** @odoo-module **/
/**
 * The outline's rows and moves, on a node table alone.
 *
 * `outline_tree.js` reads nothing but the table, so what it lists, in
 * what order, what it leaves out, what a path names across a re-stamp,
 * and what a key press asks for are pinned here with no view mounted.
 */

import { beforeEach, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/web_test_helpers";

import {
    beforeAnchor,
    canDrop,
    flatten,
    isOwnedLabel,
    moveTarget,
    nextFocus,
    pathAfterMove,
    pathKey,
    tokenAtPath,
    visibleChildren,
} from "@app_builder_view/console/outline_tree";

// A form: a sheet holding a group of three fields -- the first with its
// own <label for> just before it, the last invisible -- an empty group,
// a notebook with two pages, and a ghost staged in the first group. And
// one field the kanban declared at the root, shown nowhere.
const NODES = {
    n0: node("root", "form", null, ["n1", "n99"], { accepts: ["sheet", "field", "group"] }),
    n1: node("sheet", "sheet", "n0", ["n2", "n6", "n7"], {
        accepts: ["group", "notebook", "field"],
    }),
    n2: node("group", "group", "n1", ["n11", "n3", "n4", "p_weight", "n5"], {
        accepts: ["field", "group"],
        name: "left",
    }),
    n11: node("label", "label", "n2", [], { leaf: true, string: "Street" }),
    n3: node("field", "field", "n2", [], {
        name: "street",
        string: "Street",
        leaf: true,
        label: { shown: true, by: "label", token: "n11", in_group: false },
        field: { name: "street", type: "char", string: "Street" },
    }),
    n4: node("field", "field", "n2", [], {
        name: "city",
        string: "City",
        leaf: true,
        attrs: { required: "1" },
        field: { name: "city", type: "char", string: "City" },
    }),
    p_weight: {
        ...node("pending", "widget", "n2", [], { leaf: true, name: "weight" }),
        pending: { name: "weight", string: "Weight", ttype: "float" },
    },
    n5: node("field", "field", "n2", [], {
        name: "zip",
        leaf: true,
        hidden: "invisible",
        field: { name: "zip", type: "char", string: "Zip" },
    }),
    n6: node("group", "group", "n1", [], { accepts: ["field", "group"], name: "studio_group_a1b2c3" }),
    n7: node("notebook", "notebook", "n1", ["n8", "n9"], { accepts: ["page"], movable: false }),
    n8: node("page", "page", "n7", ["n10"], { accepts: ["field", "group"], name: "one", string: "One" }),
    n9: node("page", "page", "n7", [], { accepts: ["field", "group"], name: "two", string: "Two" }),
    n10: node("field", "field", "n8", [], {
        name: "note",
        string: "Note",
        leaf: true,
        field: { name: "note", type: "text", string: "Note" },
    }),
    n99: node("field", "field", "n0", [], { name: "color", leaf: true, selectable: false }),
};

function node(kind, tag, parent, children, extra = {}) {
    const {
        leaf = false,
        accepts = [],
        name = null,
        string = null,
        label = null,
        field = null,
        attrs = {},
        hidden = null,
        selectable = true,
        movable = kind !== "root" && kind !== "sheet",
    } = extra;
    return {
        kind,
        tag,
        parent,
        children,
        name,
        string,
        container: !leaf,
        accepts,
        movable,
        removable: movable,
        selectable,
        hidden,
        attrs,
        field,
        label,
    };
}

beforeEach(() => patchTranslations());

test("rows follow the document, and a label a field owns is not one", () => {
    const rows = flatten(NODES, "n0");
    expect(rows.map((row) => [row.token, row.depth])).toEqual([
        ["n0", 0],
        ["n1", 1],
        ["n2", 2],
        ["n3", 3],
        ["n4", 3],
        ["p_weight", 3],
        ["n5", 3],
        ["n6", 2],
        ["n7", 2],
        ["n8", 3],
        ["n10", 4],
        ["n9", 3],
    ]);
    expect(isOwnedLabel(NODES, "n11")).toBe(true);
    expect(visibleChildren(NODES, "n2")).toEqual(["n3", "n4", "p_weight", "n5"]);
    // The kanban's root-declared field is on no card: not a row.
    expect(rows.some((row) => row.token === "n99")).toBe(false);
});

test("a row says what it is: label, icon, badges, and whether it stays put", () => {
    const rows = flatten(NODES, "n0");
    const by = Object.fromEntries(rows.map((row) => [row.token, row]));
    expect(by.n0.label).toBe("View");
    expect(by.n3.label).toBe("Street");
    expect(by.n3.icon).toBe("fa fa-font");
    expect(by.n10.icon).toBe("fa fa-align-left");
    expect(by.n6.label).toBe("the group");
    expect(by.n6.icon).toBe("fa fa-object-group");
    expect(by.p_weight.label).toBe("Weight");
    expect(by.p_weight.icon).toBe("fa fa-superscript");
    expect(by.p_weight.badges.pending).toBe(true);
    expect(by.n4.badges.required).toBe(true);
    expect(by.n3.badges.required).toBe(false);
    expect(by.n5.badges.hidden).toBe("invisible");
    expect(by.n4.badges.hidden).toBe(null);
    expect(by.n1.fixed).toBe(true);
    expect(by.n7.fixed).toBe(true);
    expect(by.n4.fixed).toBe(false);
    expect(by.n2.hasChildren).toBe(true);
    expect(by.n2.expanded).toBe(true);
    expect(by.n6.hasChildren).toBe(false);
    expect(by.n4.hasChildren).toBe(false);
});

test("a folded container keeps its rows to itself", () => {
    const key = pathKey(NODES, "n2");
    expect(key).toBe("form:#0/sheet:#0/group:left");
    const rows = flatten(NODES, "n0", { collapsed: new Set([key]) });
    expect(rows.map((row) => row.token)).toEqual(["n0", "n1", "n2", "n6", "n7", "n8", "n10", "n9"]);
    expect(rows.find((row) => row.token === "n2").expanded).toBe(false);
});

test("a filter keeps what matches and the way down to it, open", () => {
    const rows = flatten(NODES, "n0", { collapsed: new Set([pathKey(NODES, "n8")]), filter: "note" });
    expect(rows.map((row) => row.token)).toEqual(["n0", "n1", "n7", "n8", "n10"]);
    expect(rows.find((row) => row.token === "n8").expanded).toBe(true);
    // The technical name and the kind count too.
    expect(flatten(NODES, "n0", { filter: "zip" }).map((row) => row.token)).toEqual([
        "n0",
        "n1",
        "n2",
        "n5",
    ]);
    expect(flatten(NODES, "n0", { filter: "notebook" }).map((row) => row.token)).toEqual([
        "n0",
        "n1",
        "n7",
    ]);
    expect(flatten(NODES, "n0", { filter: "nothing like it" })).toEqual([]);
});

test("a path names the same row on any table of the view", () => {
    for (const row of flatten(NODES, "n0")) {
        expect(tokenAtPath(NODES, "n0", row.key)).toBe(row.token);
    }
    // Unnamed siblings are told apart by their place among the rows.
    expect(pathKey(NODES, "n6")).toBe("form:#0/sheet:#0/group:studio_group_a1b2c3");
    expect(pathKey(NODES, "n10")).toBe("form:#0/sheet:#0/notebook:#2/page:one/field:note");
    // The same view stamped again, with every token one slot over.
    const shifted = {};
    const rename = (token) => (token && NODES[token] ? `x${token}` : token);
    for (const [token, entry] of Object.entries(NODES)) {
        shifted[rename(token)] = {
            ...entry,
            parent: rename(entry.parent),
            children: entry.children.map(rename),
            label: entry.label ? { ...entry.label, token: rename(entry.label.token) } : null,
        };
    }
    expect(tokenAtPath(shifted, "xn0", pathKey(NODES, "n10"))).toBe("xn10");
    expect(tokenAtPath(shifted, "xn0", pathKey(NODES, "n6"))).toBe("xn6");
    expect(tokenAtPath(shifted, "xn0", "form:#0/sheet:#0/group:gone")).toBe(null);
    expect(tokenAtPath(NODES, "n0", "")).toBe(null);
});

test("before a field with its own label just before it means before the label", () => {
    expect(beforeAnchor(NODES, "n3")).toBe("n11");
    expect(beforeAnchor(NODES, "n4")).toBe("n4");
    // A label that stands elsewhere is not in the way.
    const apart = {
        ...NODES,
        n2: { ...NODES.n2, children: ["n3", "n4", "n11", "p_weight", "n5"] },
    };
    expect(beforeAnchor(apart, "n3")).toBe("n3");
});

test("what a key press asks for, and what it does not", () => {
    // Up from the first child: nowhere. Up onto a labelled field: its label.
    expect(moveTarget(NODES, "n3", "up")).toBe(null);
    expect(moveTarget(NODES, "n4", "up")).toEqual({ target: "n11", position: "before" });
    expect(moveTarget(NODES, "n5", "up")).toEqual({ target: "p_weight", position: "before" });
    expect(moveTarget(NODES, "n4", "down")).toEqual({ target: "p_weight", position: "after" });
    expect(moveTarget(NODES, "n5", "down")).toBe(null);
    // Out of the group: after it, in the sheet, which takes a field.
    expect(moveTarget(NODES, "n4", "out")).toEqual({ target: "n2", position: "after" });
    // Out of the notebook: the sheet takes no page.
    expect(moveTarget(NODES, "n8", "out")).toBe(null);
    // Into the sibling above when it is a container that takes the tag.
    expect(moveTarget(NODES, "n7", "in")).toBe(null); // the notebook is not movable
    const withField = {
        ...NODES,
        n1: { ...NODES.n1, children: ["n2", "n6", "n12", "n7"] },
        n12: node("field", "field", "n1", [], { name: "email", string: "Email", leaf: true }),
    };
    expect(moveTarget(withField, "n12", "in")).toEqual({ target: "n6", position: "inside" });
    expect(moveTarget(withField, "n7", "in")).toBe(null);
    // A field whose sibling above is a field: nothing to go into.
    expect(moveTarget(NODES, "n4", "in")).toBe(null);
    // What stays put goes nowhere.
    for (const direction of ["up", "down", "out", "in"]) {
        expect(moveTarget(NODES, "n1", direction)).toBe(null);
        expect(moveTarget(NODES, "n0", direction)).toBe(null);
    }
});

test("a drop is refused into itself, into what does not take it, and for what stays put", () => {
    expect(canDrop(NODES, "n4", "n3", "before")).toBe(true);
    expect(canDrop(NODES, "n4", "n6", "inside")).toBe(true);
    expect(canDrop(NODES, "n2", "n2", "inside")).toBe(false);
    expect(canDrop(NODES, "n2", "n4", "after")).toBe(false); // into its own subtree
    expect(canDrop(NODES, "n8", "n2", "inside")).toBe(false); // a group takes no page
    expect(canDrop(NODES, "n1", "n6", "after")).toBe(false); // the sheet is not movable
    expect(canDrop(NODES, "n4", "n0", "after")).toBe(false); // nothing beside the root
    expect(canDrop(NODES, "n4", "n0", "inside")).toBe(false); // the root has a sheet
    expect(canDrop(NODES, "n4", "nope", "after")).toBe(false);
});

test("the path a moved row will have is the one the next table answers to", () => {
    const down = pathAfterMove(NODES, "n4", moveTarget(NODES, "n4", "down"));
    expect(down).toBe("form:#0/sheet:#0/group:left/field:city");
    const out = pathAfterMove(NODES, "n4", moveTarget(NODES, "n4", "out"));
    expect(out).toBe("form:#0/sheet:#0/field:city");
    // An unnamed node is known by where it lands: the empty group moved
    // up before the first group sits at index 0 of the sheet.
    const unnamed = { ...NODES, n6: { ...NODES.n6, name: null } };
    expect(pathAfterMove(unnamed, "n6", { target: "n2", position: "before" })).toBe(
        "form:#0/sheet:#0/group:#0"
    );
    expect(pathAfterMove(unnamed, "n6", { target: "n7", position: "after" })).toBe(
        "form:#0/sheet:#0/group:#2"
    );
    expect(pathAfterMove(unnamed, "n6", { target: "n8", position: "inside" })).toBe(
        "form:#0/sheet:#0/notebook:#2/page:one/group:#1"
    );
    // A move before a labelled field counts from the field, not the label.
    expect(pathAfterMove(unnamed, "n6", { target: "n11", position: "before" })).toBe(
        "form:#0/sheet:#0/group:left/group:#0"
    );
});

test("the focus walks the rows", () => {
    const rows = flatten(NODES, "n0");
    expect(nextFocus(rows, 0, "ArrowUp")).toBe(0);
    expect(nextFocus(rows, 3, "ArrowUp")).toBe(2);
    expect(nextFocus(rows, 3, "ArrowDown")).toBe(4);
    expect(nextFocus(rows, rows.length - 1, "ArrowDown")).toBe(rows.length - 1);
    expect(nextFocus(rows, 5, "Home")).toBe(0);
    expect(nextFocus(rows, 5, "End")).toBe(rows.length - 1);
    expect(nextFocus(rows, 5, "Enter")).toBe(5);
    expect(nextFocus([], 0, "ArrowDown")).toBe(-1);
});

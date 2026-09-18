/** @odoo-module **/
/**
 * The outline, mounted on a model that records what it is asked.
 *
 * What the rows show is `outline_tree.ts`'s and pinned there; what is
 * pinned here is the component's side: that the canvas's selection
 * opens the way to its row, that a click reveals and a hover outlines,
 * that the keyboard walks, folds and moves, that the right-click menu
 * says what can be done, and that a table minted anew under the tree
 * keeps its folds and its focus by path.
 */

import { expect, test } from "@odoo/hoot";
import { click, hover, press, queryAll, queryOne, rightClick } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import type { ConsoleModel } from "@app_builder_view/console/console_model";
import type { OutlineDragProvider } from "@app_builder_view/console/drag";
import { Outline } from "@app_builder_view/console/sidebar/outline";
import type { OutlinePrefs } from "@app_builder_view/console/sidebar/outline";
import type {
    DragPayload,
    FieldLabel,
    NodeTable,
    StudioNode,
    Token,
    ZonePosition,
} from "@app_builder_view/console/types";

/**
 * `queryOne`/`queryAll` (`@odoo/hoot-dom`) return the DOM lib's own
 * `Element`/`Element[]`, not a generic-parameterized form their own
 * JSDoc examples suggest -- confirmed by a real `tsc` run rejecting
 * `queryOne<HTMLElement>(...)` outright (TYPING.md, "Known traps"; the
 * same real signature `drag.test.ts`'s own `queryOneEl`/`queryAllEl`
 * wrap). Every element this fixture's own rows/filter/menu ever produce
 * genuinely is an `HTMLElement`, so narrowed once here rather than at
 * every one of this file's many call sites.
 */
function queryOneEl(target: string): HTMLElement {
    return queryOne(target) as HTMLElement;
}
function queryAllEl(target: string): HTMLElement[] {
    return queryAll(target) as HTMLElement[];
}

/** Extra construction options `node()` accepts, mirroring the original
 * JS helper's own destructured defaults one for one. */
interface NodeExtra {
    leaf?: boolean;
    accepts?: string[];
    name?: string | null;
    string?: string | null;
    label?: FieldLabel | null;
    movable?: boolean;
}

/**
 * A `StudioNode` with inert defaults for the fields this fixture never
 * reads (`index`, `orientation`, `dom`, `view_id`) -- the same
 * builder-with-defaults house pattern `drag.test.ts`'s own `node()` (and
 * `console_model.test.ts`'s) already use, and for the same reason: a
 * partial literal does not "sufficiently overlap" the full `StudioNode`
 * interface on a bare `as` (TYPING.md, "Implemented so far",
 * `identity.test.ts`'s own finding).
 */
function node(
    kind: string,
    tag: string,
    parent: Token | null,
    children: Token[],
    extra: NodeExtra = {},
): StudioNode {
    const {
        leaf = false,
        accepts = [],
        name = null,
        string = null,
        label = null,
        movable = kind !== "root" && kind !== "sheet",
    } = extra;
    return {
        kind: kind as StudioNode["kind"],
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
        label,
    };
}

// A form: a sheet holding a group of three fields, an empty group and a
// notebook of two pages, the first with one field.
function makeNodes(prefix: string = "n"): NodeTable {
    const t = (n: number): string => `${prefix}${n}`;
    const nodes: Record<Token, StudioNode> = {
        [t(0)]: node("root", "form", null, [t(1)], { accepts: ["sheet", "field", "group"] }),
        [t(1)]: node("sheet", "sheet", t(0), [t(2), t(6), t(7)], {
            accepts: ["group", "notebook", "field"],
        }),
        [t(2)]: node("group", "group", t(1), [t(3), t(4), t(5)], {
            accepts: ["field", "group"],
            name: "left",
        }),
        [t(3)]: node("field", "field", t(2), [], { name: "street", string: "Street", leaf: true }),
        [t(4)]: node("field", "field", t(2), [], {
            name: "city",
            string: "City",
            leaf: true,
            label: { shown: true, by: "group", token: null, in_group: true },
        }),
        [t(5)]: node("field", "field", t(2), [], { name: "zip", string: "Zip", leaf: true }),
        [t(6)]: node("group", "group", t(1), [], {
            accepts: ["field", "group"],
            name: "studio_group_a1b2c3",
        }),
        [t(7)]: node("notebook", "notebook", t(1), [t(8), t(9)], {
            accepts: ["page"],
            movable: false,
        }),
        [t(8)]: node("page", "page", t(7), [t(10)], {
            accepts: ["field", "group"],
            name: "one",
            string: "One",
        }),
        [t(9)]: node("page", "page", t(7), [], {
            accepts: ["field", "group"],
            name: "two",
            string: "Two",
        }),
        [t(10)]: node("field", "field", t(8), [], { name: "note", string: "Note", leaf: true }),
    };
    return nodes;
}

/** One call `makeModel()`'s fake pushes onto `calls`, one variant per
 * method the outline asks of the model -- what a test's own
 * `expect(calls).toEqual([...])` checks against. */
type Call =
    | ["reveal", Token | null]
    | ["drop", Token | null, ZonePosition, DragPayload]
    | ["remove", Token, boolean]
    | ["label", Token, boolean];

/** The current selection: a token plus the node it named -- the same
 * shape `console_model.ts`'s own private `Selection` interface holds,
 * not exported from there, so named again here rather than imported. */
interface FakeSelection {
    token: Token;
    node: StudioNode;
}

/**
 * What the outline asks of the console model, recorded -- the same
 * narrow-fake house pattern `drag.test.ts`'s own `fakeModel()` and
 * `console_model.test.ts`'s own `FakeShell` already use, except
 * `Outline`'s own `Props.model` is typed to the real `ConsoleModel`
 * class itself, not a narrow interface `Outline`'s own constructor could
 * be changed to accept the way `CanvasDrag`'s was (out of this
 * conversion's own scope, which is this test file alone) -- `mountOutline`
 * below bridges that with the same `as unknown as X` cast
 * `console_model.test.ts`'s own `draft: null as unknown as DraftModel`
 * already uses for the identical situation. `nodes`/`root` are plain,
 * writable fields here -- unlike the real `ConsoleModel`, where both are
 * get-only accessors computed off `canvas` -- since several tests below
 * reassign them directly to stand in for a fresh canvas the server sent
 * back after a drop.
 */
interface FakeModel {
    nodes: NodeTable;
    root: Token | null;
    canvas: Record<string, unknown> | null;
    archVersion: string;
    editableAs: string;
    viewId: number | false;
    selection: FakeSelection | null;
    selectionSerial: number;
    hover: Token | null;
    canWrite: boolean;
    outlineDrag: OutlineDragProvider | null;
    tagFor(token: Token): string;
    hoverAt(token: Token | null): void;
    select(token: Token | null): void;
    reveal(token: Token | null): void;
    /** Set by a test to stand in for the server's answer: the model
     * swaps the canvas in before `drop` resolves (`_mutate`). */
    afterDrop: (() => void) | null;
    drop(
        token: Token | null,
        position: ZonePosition,
        payload: DragPayload,
    ): Promise<Record<string, never>>;
    remove(token: Token, force: boolean): Promise<Record<string, never>>;
    setLabelShown(token: Token, shown: boolean): Promise<Record<string, never>>;
}

function makeModel(calls: Call[], nodes: NodeTable = makeNodes()): FakeModel {
    return reactive<FakeModel>({
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
        tagFor: (token: Token) => `Node · ${token}`,
        hoverAt(this: FakeModel, token: Token | null) {
            this.hover = token || null;
        },
        select(this: FakeModel, token: Token | null) {
            // `this.nodes[token]` is only read once `token` is truthy
            // (`noUncheckedIndexedAccess` still answers `StudioNode |
            // undefined`, but a node of this fixture's own table is
            // always there for a token the test itself picked).
            this.selection = token ? { token, node: this.nodes[token]! } : null;
            this.selectionSerial += 1;
        },
        reveal(this: FakeModel, token: Token | null) {
            calls.push(["reveal", token]);
            this.select(token);
        },
        // Set by a test to stand in for the server's answer: the model
        // swaps the canvas in before `drop` resolves (`_mutate`).
        afterDrop: null,
        async drop(
            this: FakeModel,
            token: Token | null,
            position: ZonePosition,
            payload: DragPayload,
        ): Promise<Record<string, never>> {
            calls.push(["drop", token, position, payload]);
            if (this.afterDrop) {
                this.afterDrop();
            }
            return {};
        },
        async remove(token: Token, force: boolean): Promise<Record<string, never>> {
            calls.push(["remove", token, force]);
            return {};
        },
        async setLabelShown(token: Token, shown: boolean): Promise<Record<string, never>> {
            calls.push(["label", token, shown]);
            return {};
        },
    });
}

async function mountOutline(calls: Call[], nodes?: NodeTable): Promise<FakeModel> {
    const model = makeModel(calls, nodes);
    // `Outline`'s own `Props.model` is the real `ConsoleModel` class --
    // this fake only ever satisfies the dozen members `outline.ts`
    // itself reads off `this.model` (see `FakeModel`'s own comment
    // above), so the bridge is the same `as unknown as X` cast already
    // established for this exact situation (`console_model.test.ts`).
    await mountWithCleanup(Outline, { props: { model: model as unknown as ConsoleModel } });
    return model;
}

const ROW = ".o_studio_outline_row";
const tokens = (): (string | undefined)[] => queryAllEl(ROW).map((el) => el.dataset["token"]);
const row = (token: string): HTMLElement => queryOneEl(`${ROW}[data-token='${token}']`);

/** What this browser remembers of the outline, read back the same way
 * `outline.ts`'s own `loadPrefs()` does (`|| "{}"`): `Storage.getItem`'s
 * real signature answers `string | null`, not just `string`, which
 * `JSON.parse` does not accept directly. */
function readPrefs(): OutlinePrefs {
    return JSON.parse(browser.localStorage.getItem("app_builder.outline") || "{}") as OutlinePrefs;
}

test("the rows are the tree, with the drag's provider left on the model", async () => {
    const calls: Call[] = [];
    const model = await mountOutline(calls);
    expect(tokens()).toEqual(["n0", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8", "n10", "n9"]);
    expect(row("n3").dataset["depth"]).toBe("3");
    expect(row("n3").dataset["path"]).toBe("form:#0/sheet:#0/group:left/field:street");
    expect(row("n2")).toHaveAttribute("aria-expanded", "true");
    expect(row("n3")).not.toHaveAttribute("aria-expanded");
    expect(row("n1")).toHaveClass("o_studio_outline_fixed");
    // The first row takes the Tab key; the rest are reached with the arrows.
    expect(row("n0")).toHaveAttribute("tabindex", "0");
    expect(row("n3")).toHaveAttribute("tabindex", "-1");
    expect(model.outlineDrag).not.toBe(null);
    expect(model.outlineDrag!.el).toBe(queryOneEl(".o_studio_outline_list"));
    // `queryOne`'s own real signature always answers a real `Element`
    // (it throws rather than returning `null`), unlike native
    // `Element.querySelector` elsewhere in this file -- widened once
    // here to let this redundant-but-harmless assertion through, the
    // same shape `canvas_views.test.ts`'s own `renderer`/`.not.toBe(null)`
    // needs a nullable-typed receiver for.
    expect(queryOne(".o_studio_outline_list .o_studio_zones") as Element | null).not.toBe(null);
    expect(model.outlineDrag!.indentOf(2)).toBe(8 + 32);
});

test("a click reveals, a hover outlines, and the canvas's hover is shown", async () => {
    const calls: Call[] = [];
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
    const calls: Call[] = [];
    const model = await mountOutline(calls);
    await click(queryOneEl(`${ROW}[data-token='n8'] .o_studio_outline_caret`));
    await animationFrame();
    expect(tokens()).not.toInclude("n10");
    expect(row("n8")).toHaveAttribute("aria-expanded", "false");
    // Folding is not selecting.
    expect(calls).toEqual([]);
    model.select("n10");
    // One frame draws the selection, and the effect that opens the way
    // to it asks for the next.
    await animationFrame();
    await animationFrame();
    expect(tokens()).toInclude("n10");
    expect(row("n10")).toHaveClass("o_studio_outline_selected");
    expect(row("n8")).toHaveAttribute("aria-expanded", "true");
});

test("the keyboard walks the rows, folds them, and reveals", async () => {
    const calls: Call[] = [];
    await mountOutline(calls);
    row("n0").focus();
    await press("ArrowDown");
    await press("ArrowDown");
    expect(document.activeElement).toBe(row("n2"));
    await press("ArrowLeft");
    await animationFrame();
    expect(row("n2")).toHaveAttribute("aria-expanded", "false");
    expect(tokens()).not.toInclude("n3");
    // Left on a folded row goes to its parent; Right unfolds.
    await press("ArrowLeft");
    expect(document.activeElement).toBe(row("n1"));
    await press("ArrowDown");
    await press("ArrowRight");
    await animationFrame();
    expect(row("n2")).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(row("n2"));
    // Right on an open row goes to its first child.
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
    const calls: Call[] = [];
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
    // Into the one above: Street has a field above it, which takes nothing.
    await press(["Alt", "ArrowRight"]);
    await animationFrame();
    expect(calls).toEqual([]);
    // The sheet stays put, whatever the key.
    row("n1").focus();
    await press(["Alt", "ArrowDown"]);
    await animationFrame();
    expect(calls).toEqual([]);
});

test("a table minted anew keeps the folds and the focus by path", async () => {
    const calls: Call[] = [];
    const model = await mountOutline(calls);
    await click(queryOneEl(`${ROW}[data-token='n8'] .o_studio_outline_caret`));
    await animationFrame();
    // The server answers with the view as it is now -- City after Zip --
    // and every token one slot over.
    const swapped = makeNodes("x");
    // Bracket notation, not `swapped.x2`: `NodeTable` carries an index
    // signature (`Record<Token, StudioNode>`), and
    // `noPropertyAccessFromIndexSignature` disallows dot access against
    // one -- the same rule `outline.ts` itself already follows
    // everywhere it reads a node table. `!`: this fixture's own table
    // always has these two tokens.
    swapped["x2"]!.children = ["x3", "x5", "x4"];
    model.afterDrop = () => {
        model.nodes = swapped;
        model.root = "x0";
        model.canvas = { arch_version: "v2" };
        model.archVersion = "v2";
        model.selection = { token: "x4", node: swapped["x4"]! };
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
    // What is folded is remembered for the view, in this browser.
    const prefs = readPrefs();
    expect(prefs.collapsed!["7"]).toEqual(["form:#0/sheet:#0/notebook:#2/page:one"]);
});

test("the right-click menu says what a row can do", async () => {
    const calls: Call[] = [];
    await mountOutline(calls);
    await rightClick(row("n3"));
    await animationFrame();
    const menu = queryOne(".o_studio_outline_menu");
    expect(menu.querySelector("[data-item='move_up']")).toHaveAttribute("disabled");
    expect(menu.querySelector("[data-item='move_down']")).not.toHaveAttribute("disabled");
    expect(menu.querySelector("[data-item='move_out']")).not.toHaveAttribute("disabled");
    expect(menu.querySelector("[data-item='move_in']")).toHaveAttribute("disabled");
    expect(menu.querySelector("[data-item='remove']")).not.toBe(null);
    // Street is in a group with no label switch of its own; City has one.
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
    // The sheet neither moves nor goes: only Reveal is left to it.
    expect(queryAll(".o_studio_outline_menu [data-item='remove']")).toHaveLength(0);
    expect(queryOne(".o_studio_outline_menu [data-item='move_out']")).toHaveAttribute("disabled");
    await click(queryOne(".o_studio_outline_menu [data-item='reveal']"));
    await animationFrame();
    expect(calls).toEqual([
        ["label", "n4", false],
        ["reveal", "n1"],
    ]);
});

test("Delete asks to remove what can be removed", async () => {
    const calls: Call[] = [];
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
    const calls: Call[] = [];
    await mountOutline(calls);
    const input = queryOne(".o_studio_outline_filter") as HTMLInputElement;
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
    const calls: Call[] = [];
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

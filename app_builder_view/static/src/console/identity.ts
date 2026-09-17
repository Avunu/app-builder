/** @odoo-module **/
/**
 * Which node of the view is this element?
 *
 * The server names every node of the arch with a class token,
 * `o_studio_n_<ordinal>` (`tools/canvas_stamp.py`), and the view compiler
 * carries `class` through to the rendered DOM for every tag that renders
 * one. So the question "what did the user click" is answered by walking up
 * to the nearest element carrying a token -- and never by inferring a
 * locator from the DOM, which is a per-user projection of the view.
 *
 * Three places the token does not land, and this module knows them all. A
 * list column's class reaches its cells but never its heading -- `th` is
 * built from the column's name alone -- so a heading is mapped through
 * `data-name` and the node table. The label a form group generates for a
 * field carries the group's classes, not the field's, so a click on it is
 * a click on the widget beside it. A kanban card renders its template once
 * per record, so one token is many elements; the *instance* under the
 * pointer is the one outlined, and the server edits the template once.
 *
 * The kanban case has a second half. The parts of one card -- its body,
 * its side panel, the fields in them -- are asked about one at a time,
 * and each has to answer from the *same* card, or the drop zones of the
 * body would be laid out in one card and those of the side panel in the
 * next. So a point resolves first to the card it is in, and an instance
 * that does not contain the point itself is taken from that card; the
 * one card the pointer is over is what every part answers from.
 *
 * Pure functions over the DOM and the node table; no Owl, no services.
 */

import * as compat from "./compat";
import type { BoxRect, NodeTable, Point, StudioNode, Token } from "./types";

// An ordinal for a node of the arch, whose token is the whole class; or
// `p_<name>` for the ghost of a field staged on a draft, which the server
// splices into the canvas under that token and stamps as
// `o_studio_n_p_<name>` -- the class carries the prefix, the table does not.
const TOKEN_RE = /\bo_studio_n_(p_[A-Za-z0-9_]+|\d+)\b/;
const HEADING = "th[data-name]";
// A rendered kanban card. The renderer pads the last row of an ungrouped
// board with empty `.o_kanban_ghost` records, which render no template
// and are no card to point at.
const CARD = ".o_kanban_record:not(.o_kanban_ghost)";

/** An element or click target the way the console hands one around: never
 * synthesized, always something that was actually in the DOM. */
type MaybeElement = Element | null | undefined;

/** The token an element carries in its class list, or `null`. */
export function ownToken(el: MaybeElement): Token | null {
    if (!el || !el.classList) {
        return null;
    }
    const match = TOKEN_RE.exec(el.className || "");
    if (!match) {
        return null;
    }
    const captured = match[1];
    if (captured === undefined) {
        return null;
    }
    return captured.startsWith("p_") ? captured : `o_studio_n_${captured}`;
}

/** The class a token is stamped as. */
export function classOf(token: Token): string {
    return token.startsWith("p_") ? `o_studio_n_${token}` : token;
}

/** What `tokenOf` resolves a click to. */
export interface TokenHit {
    token: Token;
    el: Element;
}

/**
 * The token of the innermost stamped node around `el`, with the element
 * that carries it, or `null` for a click on nothing addressable.
 *
 * `nodes` is the canvas's node table, needed for the list heading case: a
 * heading names a column and the table knows which column node that is. A
 * heading that names no column -- the child list of an x2many field in a
 * form -- is an ordinary click, resolved by walking up to that field.
 */
export function tokenOf(el: MaybeElement, nodes: NodeTable | null | undefined): TokenHit | null {
    if (!el || !el.closest) {
        return null;
    }
    const heading = el.closest<HTMLElement>(HEADING);
    if (heading && heading.dataset["name"]) {
        const token = columnToken(heading.dataset["name"], nodes);
        if (token) {
            return { token, el: heading };
        }
    }
    let cursor: Element | null = el.nodeType === Node.ELEMENT_NODE ? el : el.parentElement;
    // A generated label is stamped with its group, not its field: the
    // widget it labels is what was meant. Unless something between the
    // click and the label cell is a node of its own -- an explicit
    // `<label for>` -- in which case the walk below finds it first.
    const wrap = cursor && cursor.closest<HTMLLabelElement>("label.o_form_label, .o_wrap_label");
    if (wrap && !stampedBetween(cursor, wrap)) {
        const widget = compat.labelWidget(wrap);
        if (widget) {
            cursor = widget;
        }
    }
    while (cursor) {
        const token = ownToken(cursor);
        if (token) {
            return { token, el: cursor };
        }
        cursor = cursor.parentElement;
    }
    return null;
}

/** Whether any element from `from` up to and including `until` is stamped. */
function stampedBetween(from: MaybeElement, until: Element): boolean {
    let cursor = from;
    while (cursor) {
        if (ownToken(cursor)) {
            return true;
        }
        if (cursor === until) {
            return false;
        }
        cursor = cursor.parentElement;
    }
    return false;
}

/** The column node called `name`, for a list heading. */
export function columnToken(name: string, nodes: NodeTable | null | undefined): Token | null {
    for (const [token, node] of Object.entries(nodes ?? {})) {
        if (node.kind === "column" && node.name === name) {
            return token;
        }
    }
    return null;
}

/**
 * Every rendered instance of a node, in document order.
 *
 * One element for almost everything; many for a kanban card's parts; the
 * heading for a list column, whose class never reaches `th`.
 */
export function elementsFor(
    token: Token,
    root: Element | null,
    nodes: NodeTable | null | undefined,
): Element[] {
    if (!root || !token) {
        return [];
    }
    const node = nodes && nodes[token];
    if (node && node.kind === "column" && node.name) {
        const heading = root.querySelector(`th[data-name="${cssEscape(node.name)}"]`);
        return heading ? [heading] : [];
    }
    return [...root.querySelectorAll(`.${classOf(token)}`)];
}

/**
 * The rectangle to outline for a node instance, in viewport coordinates.
 *
 * What the token lands on is not always what the user thinks of as the
 * thing: a form field's element is the input half of its row, a sheet's
 * class lands on the background that also holds the header, a page's only
 * DOM is its tab. Each is widened or narrowed to the shape a person would
 * point at.
 */
export function rectFor(
    node: StudioNode | null | undefined,
    instance: Element | null,
): BoxRect | null {
    if (!instance) {
        return null;
    }
    const kind = node ? node.kind : null;
    if (kind === "field" && instance.matches(".o_field_widget, .o_form_label")) {
        return compat.rowRect(instance);
    }
    if (kind === "label" && instance.matches(".o_form_label")) {
        return compat.rowRect(instance);
    }
    if (kind === "sheet") {
        const inner = instance.querySelector(":scope > .o_form_sheet");
        return (inner || instance).getBoundingClientRect();
    }
    if (kind === "card") {
        const card = instance.closest(".o_kanban_record");
        return (card || instance).getBoundingClientRect();
    }
    return instance.getBoundingClientRect();
}

/**
 * The instance of `token` nearest to a viewport point, for the kanban case
 * where one node is many elements: the one under the point, else the one
 * in the card under the point, else the first.
 *
 * The second answer is what keeps a card's parts together. The body of a
 * card is asked about with a point that is over the card's side panel,
 * and the body that counts is the one beside that side panel -- not the
 * first body on the board.
 */
export function instanceAt(
    token: Token,
    root: Element | null,
    nodes: NodeTable | null | undefined,
    point: Point | null,
): Element | null {
    const instances = elementsFor(token, root, nodes);
    if (!point || instances.length <= 1) {
        return instances[0] || null;
    }
    const under = instances.find((el) => within(el.getBoundingClientRect(), point));
    if (under) {
        return under;
    }
    const card = cardAt(root, point);
    if (card) {
        const inCard = instances.find((el) => card.contains(el));
        if (inCard) {
            return inCard;
        }
    }
    return instances[0] ?? null;
}

/** Every rendered kanban card under `root`, in document order. */
export function cardsOf(root: Element | null): Element[] {
    return root ? [...root.querySelectorAll(CARD)] : [];
}

/** The rendered kanban card a viewport point is over, or `null`. */
export function cardAt(root: Element | null, point: Point | null): Element | null {
    if (!root || !point) {
        return null;
    }
    return cardsOf(root).find((card) => within(card.getBoundingClientRect(), point)) || null;
}

/** The card an element is part of, or `null` outside any. */
export function cardOf(el: MaybeElement): Element | null {
    return el && el.closest ? el.closest(CARD) : null;
}

/**
 * The first card a person can see: the first whose box meets the scroll
 * container's, else the first there is. What a drag from the palette
 * lays its zones out on, since the pointer has not been over any card.
 */
export function firstVisibleCard(
    root: Element | null,
    scrollEl: Element | null = root,
): Element | null {
    const cards = cardsOf(root);
    if (!cards.length) {
        return null;
    }
    const view = scrollEl ? scrollEl.getBoundingClientRect() : null;
    if (!view) {
        return cards[0] ?? null;
    }
    return (
        cards.find((card) => {
            const r = card.getBoundingClientRect();
            return (
                (r.width || r.height) &&
                r.bottom > view.top &&
                r.top < view.bottom &&
                r.right > view.left &&
                r.left < view.right
            );
        }) ??
        cards[0] ??
        null
    );
}

/** The viewport centre of an element, a point every part of it answers to. */
export function centreOf(el: Element): Point {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

function within(r: BoxRect, point: Point): boolean {
    return point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom;
}

/** The `.nav-link` of a notebook page node, if that page is rendered. */
export function tabFor(token: Token, root: Element | null): Element | null {
    if (!root || !token) {
        return null;
    }
    return root.querySelector(`${compat.TAB_SELECTOR}.${token}`);
}

/** What a tab click means for remembering the active page. */
export interface TabMemory {
    name: string | null;
    index: number;
}

/** What a tab click means for remembering the active page. */
export function describeTab(tab: Element): TabMemory {
    const name = tab.getAttribute("name") || null;
    const strip = tab.closest(".nav");
    const tabs = strip ? [...strip.querySelectorAll(".nav-link")] : [tab];
    return { name, index: tabs.indexOf(tab) };
}

/** The rendered tab a remembered page maps to now, or `null`. */
export function findTab(root: Element | null, page: TabMemory | null): Element | null {
    if (!root || !page) {
        return null;
    }
    if (page.name) {
        const byName = root.querySelector(`${compat.TAB_SELECTOR}[name="${cssEscape(page.name)}"]`);
        if (byName) {
            return byName;
        }
    }
    const tabs = root.querySelectorAll(compat.TAB_SELECTOR);
    return tabs[page.index] || null;
}

function cssEscape(value: string): string {
    return window.CSS && window.CSS.escape
        ? window.CSS.escape(value)
        : String(value).replace(/["\\]/g, "\\$&");
}

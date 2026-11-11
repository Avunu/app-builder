/** @odoo-module **/
/**
 * Where a node is on the canvas, and where its children are.
 *
 * The token names a node; the DOM says where it is rendered. The two do
 * not line up as neatly as a class on an element suggests: a form field's
 * element is the input half of its row and the outline the user expects
 * covers the label too; a sheet's class lands on the background that also
 * holds the header; a page's only DOM is its tab, while what it *contains*
 * is drawn in the pane beside it; a list column's class never reaches its
 * heading. Every one of those is answered here, so that the overlay and
 * the drop zones ask "where is this node" and get the rectangle a person
 * would point at.
 *
 * Two shapes of question. `outlineRect` is the node as a thing -- what
 * hover and selection draw around. `contentRect` is the node as a place
 * -- the area its children sit in, which is what a drop zone is laid out
 * in. `childEntries` are the rendered children of a container, in DOM
 * order, each with its outline. All rectangles are in viewport
 * coordinates until `toContent` puts them into the scroll container's,
 * where the overlay draws.
 *
 * Pure functions over the DOM and the node table; no Owl, no services.
 */

import * as compat from "./compat";
import {cardAt, cardsOf, elementsFor, instanceAt, rectFor, tabFor} from "./identity";
import type {NodeTable, PlainRect, Point, Token} from "./types";

/**
 * The rendered instance of a node, or `null`.
 *
 * A page is its tab; a kanban card whose template has no class of its
 * own -- the legacy `kanban-box` -- is the record under `point`, else the
 * first; everything else is the element carrying the token nearest
 * `point`, for the kanban case where one node is many.
 */
export function instanceOf(
  token: Token,
  root: Element | null,
  nodes: NodeTable,
  point: Point | null = null
): Element | null {
  const node = nodes[token];
  if (!node || !root) {
    return null;
  }
  let instance =
    node.kind === "page" ? tabFor(token, root) : instanceAt(token, root, nodes, point);
  if (!instance && node.kind === "card") {
    instance = cardAt(root, point) || cardsOf(root)[0] || null;
  }
  return instance && instance.isConnected ? instance : null;
}

/**
 * The viewport rectangle a node is outlined with, or `null` when it is
 * not rendered or has no size.
 */
export function outlineRect(
  token: Token,
  root: Element | null,
  nodes: NodeTable,
  point: Point | null = null
): PlainRect | null {
  const instance = instanceOf(token, root, nodes, point);
  if (!instance) {
    return null;
  }
  const rect = rectFor(nodes[token], instance);
  return rect && (rect.width || rect.height) ? plain(rect) : null;
}

/**
 * The element a container's children are laid out in, or `null`.
 *
 * The sheet's children live in the inner sheet, not in the background
 * that carries the token; a notebook's children are its tabs, laid out
 * in the header strip; a page's children are in the active pane -- and
 * only when the page *is* the active one, since the pane shows one page
 * at a time and an inactive page's children are nowhere.
 */
export function contentElement(
  token: Token,
  root: Element | null,
  nodes: NodeTable,
  point: Point | null = null
): Element | null {
  const node = nodes[token];
  const instance = instanceOf(token, root, nodes, point);
  if (!node || !instance) {
    return null;
  }
  if (node.kind === "sheet") {
    return instance.querySelector(":scope > .o_form_sheet") || instance;
  }
  if (node.kind === "notebook") {
    return instance.querySelector(":scope > .o_notebook_headers") || instance;
  }
  if (node.kind === "page") {
    if (!instance.classList.contains("active")) {
      return null;
    }
    const notebook = instance.closest(".o_notebook");
    return notebook
      ? notebook.querySelector(":scope > .o_notebook_content > .tab-pane")
      : null;
  }
  if (node.kind === "card") {
    return instance.closest(".o_kanban_record") || instance;
  }
  return instance;
}

/** The viewport rectangle of `contentElement`, or `null`. */
export function contentRect(
  token: Token,
  root: Element | null,
  nodes: NodeTable,
  point: Point | null = null
): PlainRect | null {
  const el = contentElement(token, root, nodes, point);
  if (!el) {
    return null;
  }
  const rect = el.getBoundingClientRect();
  return rect.width || rect.height ? plain(rect) : null;
}

/**
 * How an element lays its children out, by its computed style: `"row"`
 * when they sit side by side, `"column"` when they stack, `null` when
 * the style does not say -- a block, whose children stack but whose
 * node may know better.
 *
 * The node table says which way a container flows from the arch alone,
 * and for a kanban card that is not enough: `<t t-name="card"
 * class="flex-row">` -- most of the core's cards -- puts its side panel
 * beside its body, and the bars between the two have to stand up. The
 * card's own flex direction is what says so.
 */
export function flowOf(el: Element | null): "row" | "column" | null {
  if (!el || !el.isConnected) {
    return null;
  }
  const style = window.getComputedStyle(el);
  if (!["flex", "inline-flex"].includes(style.display)) {
    return null;
  }
  return style.flexDirection.startsWith("column") ? "column" : "row";
}

/** Whether a page node is the one its notebook currently shows. */
export function isActivePage(
  token: Token,
  root: Element | null,
  nodes: NodeTable
): boolean {
  const node = nodes[token];
  if (!node || node.kind !== "page") {
    return true;
  }
  const tab = tabFor(token, root);
  return Boolean(tab && tab.classList.contains("active"));
}

/** One rendered child of a container, as `childEntries` reports it. */
export interface ChildEntry {
  token: Token;
  el: Element;
  rect: PlainRect;
}

/**
 * The rendered children of a container, in DOM order: `[{token, el,
 * rect}]`, one entry per child that has an instance inside `container`
 * (the element `contentElement` names) with a size.
 *
 * Children are taken from the node table, never from the DOM, so a
 * subview's rows or a widget's inner markup are never mistaken for
 * children. A child rendered somewhere else -- the button box, which a
 * form draws in its control panel -- is left out: a drop next to it would
 * be a drop nowhere the user can see. A hidden child the canvas was asked
 * to show anyway *is* rendered, and counts.
 */
export function childEntries(
  token: Token,
  root: Element | null,
  nodes: NodeTable,
  container: Element | null
): ChildEntry[] {
  const node = nodes[token];
  if (!node || !container) {
    return [];
  }
  const entries: ChildEntry[] = [];
  for (const child of node.children) {
    const childNode = nodes[child];
    if (!childNode) {
      continue;
    }
    let el: Element | null | undefined = null;
    if (childNode.kind === "page") {
      el = tabFor(child, root);
    } else {
      el = elementsFor(child, root, nodes).find((candidate) =>
        container.contains(candidate)
      );
    }
    if (!el || !container.contains(el)) {
      continue;
    }
    const rect = rectFor(childNode, el);
    if (!rect || (!rect.width && !rect.height)) {
      continue;
    }
    entries.push({token: child, el, rect: plain(rect)});
  }
  entries.sort((a, b) => domOrder(a.el, b.el));
  return entries;
}

/**
 * The notebook tabs on the canvas, for a drag that has to know which tab
 * the pointer is resting on without the DOM's help: the body takes no
 * pointer events while something is dragged. The elements, not their
 * rectangles: the canvas scrolls under a drag, and a tab is measured
 * when it is asked about.
 */
export function tabsOf(root: Element | null): Element[] {
  return root ? [...root.querySelectorAll(compat.TAB_SELECTOR)] : [];
}

/** Viewport coordinates to coordinates inside the scroll container. */
export function toContent(rect: PlainRect, scrollEl: Element): PlainRect {
  const base = scrollEl.getBoundingClientRect();
  return {
    top: rect.top - base.top + scrollEl.scrollTop,
    left: rect.left - base.left + scrollEl.scrollLeft,
    width: rect.width,
    height: rect.height,
  };
}

/** Whether a viewport point is inside a rectangle, widened by `slack`. */
export function contains(rect: PlainRect, point: Point, slack = 0): boolean {
  return (
    point.x >= rect.left - slack &&
    point.x <= rect.left + rect.width + slack &&
    point.y >= rect.top - slack &&
    point.y <= rect.top + rect.height + slack
  );
}

/** A DOMRect-like as a plain `{top, left, width, height}`. */
export function plain(rect: PlainRect): PlainRect {
  return {top: rect.top, left: rect.left, width: rect.width, height: rect.height};
}

function domOrder(a: Element, b: Element): number {
  if (a === b) {
    return 0;
  }
  const position = a.compareDocumentPosition(b);
  if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
    return -1;
  }
  if (position & Node.DOCUMENT_POSITION_PRECEDING) {
    return 1;
  }
  return 0;
}

/** @odoo-module **/
/**
 * Where a drop can land, as rectangles.
 *
 * A drop is "before this node", "after this node" or "inside this empty
 * container" -- the three positions the server takes -- and a zone is one
 * of those with a place on screen: a thin bar in the gap between two
 * children, above the first, below the last, or a dashed box filling a
 * container that has nothing in it yet. The bars are laid across the
 * container's flow: horizontal in a column of fields, vertical between
 * the columns of an outer group, the tabs of a notebook or the headings
 * of a list.
 *
 * Which containers get zones is the server's word, not the DOM's: each
 * node says what it `accepts`, and the payload's tag is checked against
 * that here so a tab is never offered a place in a group. Which way a
 * container flows is the server's word too, unless the caller can read
 * it off the rendering -- a kanban card laid out as a row has its side
 * panel beside its body, whatever the arch says of a card. For a move,
 * the moving node's own subtree is out -- nothing goes inside what is
 * being moved -- and so are the two gaps beside it, where dropping would
 * change nothing. Only what is rendered gets a zone: an inactive page's
 * children are nowhere on screen, and the tab dwell is how one gets
 * there.
 *
 * Nested containers put their zones close together -- the last gap of a
 * group and the gap after the group in its sheet are a few pixels apart
 * -- and two zones that overlap would make the drop a coin toss. So the
 * last pass keeps them apart. Among bars, the deeper container's wins the
 * space and the shallower one is trimmed to what is left beside it, or
 * dropped when nothing is. An empty container's box yields to every bar:
 * a bar is a precise place that has no other, while the box is mostly
 * slack -- an empty group has no height of its own, and its box would
 * otherwise sit on the bar after it, the one drop the group's parent has
 * left to offer.
 *
 * Pure: the DOM is reached only through the callbacks the caller binds,
 * so the layout can be tested on plain rectangles. No Owl, no services.
 */

import {_t} from "./l10n";
import type {Translated} from "./l10n";
import type {
  DragPayload,
  NodeKind,
  NodeTable,
  Orientation,
  PlainRect,
  BuilderNode,
  Token,
  Zone,
  ZoneAxis,
  ZoneContainer,
} from "./types";

/** How thick a bar is, in pixels: the hit area, wider than what is drawn. */
export const BAR = 14;
/** How far a bar stops short of the ends of what it spans. */
export const INSET = 8;
/** The shortest a bar may be. */
export const MIN_LENGTH = 16;
/** How tall an empty container's zone is at the least. */
export const MIN_INSIDE = 40;
/** The gap kept between two zones, so neither is a hair from the other. */
export const GAP = 2;
/** The thinnest a trimmed zone may be and still be offered. */
export const MIN_BAR = 6;

/** The tag a palette component puts in the arch (`canvas_stamp.COMPONENT_TAGS`). */
export const COMPONENT_TAGS: Record<string, string> = {
  group: "group",
  columns: "group",
  page: "page",
  notebook: "notebook",
  separator: "separator",
  label: "label",
  button: "button",
};

/**
 * The tag a payload will put in the arch, or `null`.
 *
 * `nodes` is needed for a move, whose tag is that of the node moved.
 */
export function payloadTag(
  payload: DragPayload | null,
  nodes: NodeTable = {}
): string | null {
  if (!payload) {
    return null;
  }
  if (["existing_field", "new_field", "move_pending"].includes(payload.kind)) {
    return "field";
  }
  if (payload.kind === "component") {
    return (payload.component && COMPONENT_TAGS[payload.component]) || null;
  }
  if (payload.kind === "move") {
    const node = payload.token ? nodes[payload.token] : undefined;
    return node ? node.tag : null;
  }
  return null;
}

/** A rendered child, as `buildZones`'s caller reports one
 * (`geometry.ts:ChildEntry` minus `el`, which layout never needs). */
export interface ZoneChild {
  token: Token;
  rect: PlainRect;
}

/** What `buildZones` lays zones out from. */
export interface BuildZonesParams {
  /** the canvas's node table */
  nodes: NodeTable;
  /** the tag the payload puts in the arch */
  tag: string | null;
  /** the token being moved, if any */
  moving?: Token | null;
  /** the area a container's children sit in, in viewport coordinates */
  contentOf: (token: Token) => PlainRect | null;
  /** the rendered children of a container in DOM order */
  childrenOf: (token: Token) => ZoneChild[];
  /** whether a page is the one shown */
  isActive: (token: Token) => boolean;
  /** how the rendering lays a container's children out, when it can
   * tell; the node's own `orientation` otherwise */
  flowOf?: (token: Token) => Orientation | null;
}

/** Lay out the zones for one payload. `layer` is `"canvas"`; the outline
 * lays its own (`outline_zones.js`). */
export function buildZones({
  nodes,
  tag,
  moving = null,
  contentOf,
  childrenOf,
  isActive,
  flowOf = () => null,
}: BuildZonesParams): {zones: Zone[]; containers: ZoneContainer[]} {
  const zones: Zone[] = [];
  const containers: ZoneContainer[] = [];
  if (!tag) {
    return {zones, containers};
  }
  const excluded = moving ? subtree(nodes, moving) : new Set<Token>();
  for (const [token, node] of Object.entries(nodes)) {
    if (!takesTag(nodes, token, tag) || excluded.has(token)) {
      continue;
    }
    if (node.kind === "page" && !isActive(token)) {
      continue;
    }
    const content = contentOf(token);
    if (!content) {
      continue;
    }
    const children = childrenOf(token);
    const flow = flowOf(token) || node.orientation;
    const axis: ZoneAxis = flow === "row" ? "x" : "y";
    const depth = depthOf(nodes, token);
    const base = {
      layer: "canvas" as const,
      container: token,
      containerKind: node.kind,
      containerLabel: labelOf(node),
      depth,
      axis,
    };
    if (!children.length) {
      const rect = insideRect(content);
      containers.push({token, rect});
      zones.push({
        ...base,
        token,
        position: "inside",
        kind: node.kind,
        name: node.name || "",
        edge: null,
        rect,
        caption: String(_t("into %s", labelOf(node))),
      });
      continue;
    }
    containers.push({token, rect: content});
    const movingIndex = moving ? children.findIndex((c) => c.token === moving) : -1;
    const span = spanOf(children, content, axis);
    for (let gap = 0; gap <= children.length; gap++) {
      if (movingIndex >= 0 && (gap === movingIndex || gap === movingIndex + 1)) {
        continue;
      }
      const anchor = gap === 0 ? children[0] : children[gap - 1];
      if (!anchor) {
        continue;
      }
      const anchorNode = nodes[anchor.token];
      if (!anchorNode) {
        continue;
      }
      const position = gap === 0 ? "before" : "after";
      const edge = gap === 0 ? "start" : gap === children.length ? "end" : null;
      const rect = barRect(children, gap, content, span, axis);
      if (!rect) {
        continue;
      }
      zones.push({
        ...base,
        token: anchor.token,
        position,
        kind: anchorNode.kind,
        name: anchorNode.name || "",
        edge,
        rect,
        caption: captionFor(position, edge, anchorNode, node),
      });
    }
  }
  return {zones: separate(zones), containers};
}

/**
 * Whether the container at `token` takes a child of `tag`: the server's
 * word on what it accepts, less the one case the rendering decides -- a
 * form with a sheet takes nothing beside the sheet, since a field there
 * would land outside the paper.
 */
export function takesTag(nodes: NodeTable, token: Token, tag: string | null): boolean {
  const node = nodes[token];
  if (!node || !node.container || !tag || !node.accepts.includes(tag)) {
    return false;
  }
  if (node.kind === "root") {
    return !node.children.some((c) => nodes[c]?.kind === "sheet");
  }
  return true;
}

/** The label a node is spoken of by: its string, its field's, its name. */
export function labelOf(node: BuilderNode | null | undefined): string {
  if (!node) {
    return "";
  }
  if (node.string && node.string !== node.name) {
    return node.string;
  }
  if (node.field && node.field.string) {
    return node.field.string;
  }
  if (node.name && !/^builder_[a-z]+_[0-9a-f]+$/.test(node.name)) {
    return node.name;
  }
  return String(KIND_LABELS[node.kind] || _t("element"));
}

/** Each label is a `_t(...)` (`Translated`, see `l10n.ts`); `labelOf` wraps
 * the lookup in `String(...)`, which is what resolves it to a plain string. */
const KIND_LABELS: Partial<Record<NodeKind, Translated>> = {
  root: _t("the view"),
  sheet: _t("the sheet"),
  group: _t("the group"),
  page: _t("the tab"),
  notebook: _t("the notebook"),
  header: _t("the header"),
  button_box: _t("the button box"),
  html: _t("the block"),
  card: _t("the card"),
  main: _t("the card body"),
  aside: _t("the card side panel"),
  footer: _t("the card footer"),
  // Not a real NodeKind (canvas_stamp.py never emits it) -- kept from
  // the original table as-is rather than dropped, since a defensive
  // fallback for a value the type system rules out is exactly what
  // `Partial<Record<NodeKind, ...>>` cannot express without widening
  // the key type for one entry. See TYPING.md if this is ever revisited.
  ["list" as NodeKind]: _t("the list"),
};

/**
 * What the chip says over a zone. Plain strings: the captions travel into
 * datasets and comparisons, where a lazily translated one would not read.
 */
export function captionFor(
  position: "before" | "after",
  edge: "start" | "end" | null,
  anchor: BuilderNode,
  container: BuilderNode
): string {
  const ends: NodeKind[] = ["sheet", "page", "root", "card", "main", "aside", "footer"];
  if (edge === "end" && ends.includes(container.kind)) {
    return String(_t("at the end of %s", labelOf(container)));
  }
  return String(
    position === "before"
      ? _t("before %s", labelOf(anchor))
      : _t("after %s", labelOf(anchor))
  );
}

/** The token and every token listed under it. */
export function subtree(nodes: NodeTable, token: Token): Set<Token> {
  const out = new Set<Token>([token]);
  const pending = [token];
  while (pending.length) {
    const current = pending.pop();
    const node = current ? nodes[current] : undefined;
    for (const child of node?.children ?? []) {
      out.add(child);
      pending.push(child);
    }
  }
  return out;
}

/** How many ancestors a node has: 0 for the root. */
export function depthOf(nodes: NodeTable, token: Token): number {
  let depth = 0;
  let cursor = nodes[token] ? nodes[token].parent : null;
  let node = cursor ? nodes[cursor] : undefined;
  while (cursor && node) {
    depth += 1;
    cursor = node.parent;
    node = cursor ? nodes[cursor] : undefined;
  }
  return depth;
}

/** The box an empty container offers: inset, and never too short to hit. */
function insideRect(content: PlainRect): PlainRect {
  const left = content.left + INSET;
  const width = Math.max(content.width - 2 * INSET, MIN_LENGTH);
  const top = content.top + Math.min(INSET, content.height / 2);
  const height = Math.max(content.height - 2 * INSET, MIN_INSIDE);
  return {top, left, width, height};
}

interface Span {
  start: number;
  end: number;
}

/**
 * How far the bars of a container reach across its flow: the extent of
 * its children, inset, and no shorter than a bar can be.
 */
function spanOf(children: ZoneChild[], content: PlainRect, axis: ZoneAxis): Span {
  let start = Infinity;
  let end = -Infinity;
  for (const {rect} of children) {
    if (axis === "y") {
      start = Math.min(start, rect.left);
      end = Math.max(end, rect.left + rect.width);
    } else {
      start = Math.min(start, rect.top);
      end = Math.max(end, rect.top + rect.height);
    }
  }
  const inset = axis === "y" ? INSET : INSET / 2;
  start += inset;
  end -= inset;
  if (end - start < MIN_LENGTH) {
    const contentStart = axis === "y" ? content.left : content.top;
    const contentEnd =
      axis === "y" ? content.left + content.width : content.top + content.height;
    start = Math.max(contentStart, start);
    end = Math.max(start + MIN_LENGTH, Math.min(contentEnd, end));
  }
  return {start, end};
}

/**
 * The bar for gap `gap` of a container: above the first child, between
 * two, below the last -- and kept inside the container's own box, so a
 * bar at its edge sits on the child rather than on the neighbour outside.
 */
function barRect(
  children: ZoneChild[],
  gap: number,
  content: PlainRect,
  span: Span,
  axis: ZoneAxis
): PlainRect | null {
  const along = (rect: PlainRect): Span =>
    axis === "y"
      ? {start: rect.top, end: rect.top + rect.height}
      : {start: rect.left, end: rect.left + rect.width};
  const box = along(content);
  let start: number;
  if (gap === 0) {
    const first = children[0];
    if (!first) {
      return null;
    }
    start = along(first.rect).start - BAR;
  } else if (gap === children.length) {
    const last = children[children.length - 1];
    if (!last) {
      return null;
    }
    start = along(last.rect).end;
  } else {
    const before = children[gap - 1];
    const after = children[gap];
    if (!before || !after) {
      return null;
    }
    start = (along(before.rect).end + along(after.rect).start) / 2 - BAR / 2;
  }
  if (box.end - box.start >= BAR) {
    start = Math.min(Math.max(start, box.start), box.end - BAR);
  }
  if (axis === "y") {
    return {top: start, left: span.start, width: span.end - span.start, height: BAR};
  }
  return {top: span.start, left: start, width: BAR, height: span.end - span.start};
}

/**
 * Keep zones from overlapping: bars before boxes, deeper containers
 * first, each later zone trimmed to clear what is already placed and
 * dropped when too little of it is left. A bar is trimmed along its own
 * thickness; a box, which has no thin side of its own, along that of the
 * bar it clears.
 */
function separate(zones: Zone[]): Zone[] {
  const rank = (zone: Zone) => (zone.position === "inside" ? 1 : 0);
  const ordered = zones
    .map((zone, index) => ({zone, index}))
    .sort(
      (a, b) =>
        rank(a.zone) - rank(b.zone) || b.zone.depth - a.zone.depth || a.index - b.index
    )
    .map((entry) => entry.zone);
  const placed: Zone[] = [];
  for (const zone of ordered) {
    let rect: PlainRect | null = zone.rect;
    for (const other of placed) {
      if (!rect || !overlaps(rect, other.rect)) {
        continue;
      }
      rect = trim(
        rect,
        other.rect,
        zone.position === "inside" ? other.axis : zone.axis
      );
    }
    if (rect) {
      placed.push({...zone, rect});
    }
  }
  return placed;
}

function overlaps(a: PlainRect, b: PlainRect): boolean {
  return (
    a.left < b.left + b.width + GAP &&
    a.left + a.width + GAP > b.left &&
    a.top < b.top + b.height + GAP &&
    a.top + a.height + GAP > b.top
  );
}

/**
 * What is left of `rect` once `other` (widened by the gap) is taken out
 * of it along `axis` -- `y` for a horizontal bar, `x` for a vertical one
 * -- keeping the larger remainder, or `null` when it is too thin to
 * offer.
 */
function trim(rect: PlainRect, other: PlainRect, cutAxis: ZoneAxis): PlainRect | null {
  const [start, size, otherStart, otherSize]: [number, number, number, number] =
    cutAxis === "y"
      ? [rect.top, rect.height, other.top, other.height]
      : [rect.left, rect.width, other.left, other.width];
  const blockedStart = otherStart - GAP;
  const blockedEnd = otherStart + otherSize + GAP;
  const before = {start, size: Math.min(start + size, blockedStart) - start};
  const afterStart = Math.max(start, blockedEnd);
  const after = {start: afterStart, size: start + size - afterStart};
  const best = before.size >= after.size ? before : after;
  if (best.size < MIN_BAR) {
    return null;
  }
  return cutAxis === "y"
    ? {...rect, top: best.start, height: best.size}
    : {...rect, left: best.start, width: best.size};
}

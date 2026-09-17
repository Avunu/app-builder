import { _t } from "@web/core/l10n/translation";
const BAR = 14;
const INSET = 8;
const MIN_LENGTH = 16;
const MIN_INSIDE = 40;
const GAP = 2;
const MIN_BAR = 6;
const COMPONENT_TAGS = {
  group: "group",
  columns: "group",
  page: "page",
  notebook: "notebook",
  separator: "separator",
  label: "label",
  button: "button"
};
function payloadTag(payload, nodes = {}) {
  if (!payload) {
    return null;
  }
  if (["existing_field", "new_field", "move_pending"].includes(payload.kind)) {
    return "field";
  }
  if (payload.kind === "component") {
    return payload.component && COMPONENT_TAGS[payload.component] || null;
  }
  if (payload.kind === "move") {
    const node = payload.token ? nodes[payload.token] : void 0;
    return node ? node.tag : null;
  }
  return null;
}
function buildZones({
  nodes,
  tag,
  moving = null,
  contentOf,
  childrenOf,
  isActive,
  flowOf = () => null
}) {
  const zones = [];
  const containers = [];
  if (!tag) {
    return { zones, containers };
  }
  const excluded = moving ? subtree(nodes, moving) : /* @__PURE__ */ new Set();
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
    const axis = flow === "row" ? "x" : "y";
    const depth = depthOf(nodes, token);
    const base = {
      layer: "canvas",
      container: token,
      containerKind: node.kind,
      containerLabel: labelOf(node),
      depth,
      axis
    };
    if (!children.length) {
      const rect = insideRect(content);
      containers.push({ token, rect });
      zones.push({
        ...base,
        token,
        position: "inside",
        kind: node.kind,
        name: node.name || "",
        edge: null,
        rect,
        caption: String(_t("into %s", labelOf(node)))
      });
      continue;
    }
    containers.push({ token, rect: content });
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
        caption: captionFor(position, edge, anchorNode, node)
      });
    }
  }
  return { zones: separate(zones), containers };
}
function takesTag(nodes, token, tag) {
  const node = nodes[token];
  if (!node || !node.container || !tag || !node.accepts.includes(tag)) {
    return false;
  }
  if (node.kind === "root") {
    return !node.children.some((c) => nodes[c]?.kind === "sheet");
  }
  return true;
}
function labelOf(node) {
  if (!node) {
    return "";
  }
  if (node.string && node.string !== node.name) {
    return node.string;
  }
  if (node.field && node.field.string) {
    return node.field.string;
  }
  if (node.name && !/^studio_[a-z]+_[0-9a-f]+$/.test(node.name)) {
    return node.name;
  }
  return String(KIND_LABELS[node.kind] || _t("element"));
}
const KIND_LABELS = {
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
  ["list"]: _t("the list")
};
function captionFor(position, edge, anchor, container) {
  const ends = ["sheet", "page", "root", "card", "main", "aside", "footer"];
  if (edge === "end" && ends.includes(container.kind)) {
    return String(_t("at the end of %s", labelOf(container)));
  }
  return String(
    position === "before" ? _t("before %s", labelOf(anchor)) : _t("after %s", labelOf(anchor))
  );
}
function subtree(nodes, token) {
  const out = /* @__PURE__ */ new Set([token]);
  const pending = [token];
  while (pending.length) {
    const current = pending.pop();
    const node = current ? nodes[current] : void 0;
    for (const child of node?.children ?? []) {
      out.add(child);
      pending.push(child);
    }
  }
  return out;
}
function depthOf(nodes, token) {
  let depth = 0;
  let cursor = nodes[token] ? nodes[token].parent : null;
  let node = cursor ? nodes[cursor] : void 0;
  while (cursor && node) {
    depth += 1;
    cursor = node.parent;
    node = cursor ? nodes[cursor] : void 0;
  }
  return depth;
}
function insideRect(content) {
  const left = content.left + INSET;
  const width = Math.max(content.width - 2 * INSET, MIN_LENGTH);
  const top = content.top + Math.min(INSET, content.height / 2);
  const height = Math.max(content.height - 2 * INSET, MIN_INSIDE);
  return { top, left, width, height };
}
function spanOf(children, content, axis) {
  let start = Infinity;
  let end = -Infinity;
  for (const { rect } of children) {
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
    const contentEnd = axis === "y" ? content.left + content.width : content.top + content.height;
    start = Math.max(contentStart, start);
    end = Math.max(start + MIN_LENGTH, Math.min(contentEnd, end));
  }
  return { start, end };
}
function barRect(children, gap, content, span, axis) {
  const along = (rect) => axis === "y" ? { start: rect.top, end: rect.top + rect.height } : { start: rect.left, end: rect.left + rect.width };
  const box = along(content);
  let start;
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
    return { top: start, left: span.start, width: span.end - span.start, height: BAR };
  }
  return { top: span.start, left: start, width: BAR, height: span.end - span.start };
}
function separate(zones) {
  const rank = (zone) => zone.position === "inside" ? 1 : 0;
  const ordered = zones.map((zone, index) => ({ zone, index })).sort(
    (a, b) => rank(a.zone) - rank(b.zone) || b.zone.depth - a.zone.depth || a.index - b.index
  ).map((entry) => entry.zone);
  const placed = [];
  for (const zone of ordered) {
    let rect = zone.rect;
    for (const other of placed) {
      if (!rect || !overlaps(rect, other.rect)) {
        continue;
      }
      rect = trim(rect, other.rect, zone.position === "inside" ? other.axis : zone.axis);
    }
    if (rect) {
      placed.push({ ...zone, rect });
    }
  }
  return placed;
}
function overlaps(a, b) {
  return a.left < b.left + b.width + GAP && a.left + a.width + GAP > b.left && a.top < b.top + b.height + GAP && a.top + a.height + GAP > b.top;
}
function trim(rect, other, cutAxis) {
  const [start, size, otherStart, otherSize] = cutAxis === "y" ? [rect.top, rect.height, other.top, other.height] : [rect.left, rect.width, other.left, other.width];
  const blockedStart = otherStart - GAP;
  const blockedEnd = otherStart + otherSize + GAP;
  const before = { start, size: Math.min(start + size, blockedStart) - start };
  const afterStart = Math.max(start, blockedEnd);
  const after = { start: afterStart, size: start + size - afterStart };
  const best = before.size >= after.size ? before : after;
  if (best.size < MIN_BAR) {
    return null;
  }
  return cutAxis === "y" ? { ...rect, top: best.start, height: best.size } : { ...rect, left: best.start, width: best.size };
}
export {
  BAR,
  COMPONENT_TAGS,
  GAP,
  INSET,
  MIN_BAR,
  MIN_INSIDE,
  MIN_LENGTH,
  buildZones,
  captionFor,
  depthOf,
  labelOf,
  payloadTag,
  subtree,
  takesTag
};

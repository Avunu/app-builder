import { _t } from "./l10n";
import { TYPE_ICONS } from "./pending_widget";
import { labelOf, subtree, takesTag } from "./zones";
const KIND_ICONS = {
  root: "fa fa-th-large",
  sheet: "fa fa-file-o",
  group: "fa fa-object-group",
  page: "fa fa-folder-o",
  notebook: "fa fa-folder",
  separator: "fa fa-minus",
  button: "fa fa-hand-pointer-o",
  header: "fa fa-flag-o",
  button_box: "fa fa-th",
  chatter: "fa fa-comments-o",
  label: "fa fa-tag",
  widget: "fa fa-puzzle-piece",
  card: "fa fa-id-card-o",
  main: "fa fa-id-card-o",
  aside: "fa fa-id-card-o",
  footer: "fa fa-id-card-o",
  html: "fa fa-code",
  pending: "fa fa-clock-o",
  list: "fa fa-list",
  column: "fa fa-columns"
};
const TRUE_LITERALS = /* @__PURE__ */ new Set(["1", "true", "True"]);
function ownedLabels(nodes) {
  const owned = /* @__PURE__ */ new Set();
  for (const node of Object.values(nodes)) {
    if (node.label && node.label.token) {
      owned.add(node.label.token);
    }
  }
  return owned;
}
function isOwnedLabel(nodes, token) {
  const node = nodes[token];
  return Boolean(node && node.kind === "label" && ownedLabels(nodes).has(token));
}
function visibleChildren(nodes, token, owned = ownedLabels(nodes)) {
  const node = nodes[token];
  if (!node) {
    return [];
  }
  return (node.children || []).filter((child) => {
    const entry = nodes[child];
    return Boolean(entry && entry.selectable !== false && !owned.has(child));
  });
}
function labelFor(node) {
  if (!node) {
    return "";
  }
  if (node.kind === "root") {
    return String(_t("View"));
  }
  if (node.kind === "pending" && node.pending) {
    return node.pending.string || node.pending.name || labelOf(node);
  }
  return labelOf(node);
}
const typeIcons = TYPE_ICONS;
function iconFor(node) {
  if (!node) {
    return "fa fa-square-o";
  }
  const fieldIcon = node.field && typeIcons[node.field.type];
  if (fieldIcon) {
    return fieldIcon;
  }
  const pendingIcon = node.kind === "pending" && node.pending && typeIcons[node.pending.ttype];
  if (pendingIcon) {
    return pendingIcon;
  }
  return KIND_ICONS[node.kind] || "fa fa-square-o";
}
function segmentOf(nodes, token, owned) {
  const node = nodes[token];
  if (!node) {
    return `:${token}`;
  }
  if (node.name) {
    return `${node.tag}:${node.name}`;
  }
  if (node.string) {
    return `${node.tag}:${node.string}`;
  }
  const siblings = node.parent ? visibleChildren(nodes, node.parent, owned) : [token];
  return `${node.tag}:#${siblings.indexOf(token)}`;
}
function pathKey(nodes, token, owned = ownedLabels(nodes)) {
  const segments = [];
  let cursor = token;
  let node = cursor ? nodes[cursor] : void 0;
  while (cursor && node) {
    segments.unshift(segmentOf(nodes, cursor, owned));
    cursor = node.parent;
    node = cursor ? nodes[cursor] : void 0;
  }
  return segments.join("/");
}
function tokenAtPath(nodes, root, path) {
  if (!path || !nodes[root]) {
    return null;
  }
  const owned = ownedLabels(nodes);
  const segments = path.split("/");
  if (segments[0] !== segmentOf(nodes, root, owned)) {
    return null;
  }
  let cursor = root;
  for (const segment of segments.slice(1)) {
    const next = visibleChildren(nodes, cursor, owned).find(
      (child) => segmentOf(nodes, child, owned) === segment
    );
    if (!next) {
      return null;
    }
    cursor = next;
  }
  return cursor;
}
function flatten(nodes, root, { collapsed = /* @__PURE__ */ new Set(), filter = "" } = {}) {
  const rows = [];
  if (!nodes[root]) {
    return rows;
  }
  const owned = ownedLabels(nodes);
  const needle = (filter || "").trim().toLowerCase();
  const matches = needle ? matching(nodes, root, needle, owned) : null;
  const walk = (token, depth) => {
    const node = nodes[token];
    if (!node || matches && !matches.has(token)) {
      return;
    }
    const key = pathKey(nodes, token, owned);
    const children = visibleChildren(nodes, token, owned);
    const hasChildren = children.length > 0;
    const expanded = hasChildren && (matches ? true : !collapsed.has(key));
    rows.push({
      token,
      node,
      depth,
      key,
      hasChildren,
      expanded,
      label: labelFor(node),
      icon: iconFor(node),
      badges: {
        hidden: node.hidden || null,
        pending: node.kind === "pending",
        required: Boolean(node.attrs && TRUE_LITERALS.has(String(node.attrs["required"])))
      },
      fixed: !node.movable
    });
    if (expanded) {
      for (const child of children) {
        walk(child, depth + 1);
      }
    }
  };
  walk(root, 0);
  return rows;
}
function matching(nodes, root, needle, owned) {
  const kept = /* @__PURE__ */ new Set();
  const walk = (token) => {
    const node = nodes[token];
    let hit = false;
    for (const child of visibleChildren(nodes, token, owned)) {
      hit = walk(child) || hit;
    }
    const own = [labelFor(node), node && node.name || "", node && node.kind || ""].join(" ").toLowerCase().includes(needle);
    if (hit || own) {
      kept.add(token);
      return true;
    }
    return false;
  };
  walk(root);
  return kept;
}
function beforeAnchor(nodes, token) {
  const node = nodes[token];
  if (!node || !node.label || node.label.by !== "label" || !node.label.token) {
    return token;
  }
  const label = nodes[node.label.token];
  if (!label || label.parent !== node.parent) {
    return token;
  }
  const parent = node.parent ? nodes[node.parent] : void 0;
  const siblings = parent ? parent.children : [];
  const at = siblings.indexOf(token);
  const before = at > 0 ? siblings[at - 1] : void 0;
  return before === node.label.token ? node.label.token : token;
}
function canDrop(nodes, src, target, position) {
  const node = nodes[src];
  const anchor = nodes[target];
  if (!node || !anchor || !node.movable || src === target) {
    return false;
  }
  if (position !== "inside" && !anchor.parent) {
    return false;
  }
  const container = position === "inside" ? target : anchor.parent;
  if (!container || !takesTag(nodes, container, node.tag)) {
    return false;
  }
  return !subtree(nodes, src).has(target);
}
function moveTarget(nodes, token, direction) {
  const node = nodes[token];
  if (!node || !node.parent) {
    return null;
  }
  const siblings = visibleChildren(nodes, node.parent);
  const at = siblings.indexOf(token);
  let move = null;
  if (direction === "up" && at > 0) {
    const above = siblings[at - 1];
    if (above) {
      move = { target: beforeAnchor(nodes, above), position: "before" };
    }
  } else if (direction === "down" && at >= 0 && at < siblings.length - 1) {
    const below = siblings[at + 1];
    if (below) {
      move = { target: below, position: "after" };
    }
  } else if (direction === "out") {
    move = { target: node.parent, position: "after" };
  } else if (direction === "in" && at > 0) {
    const above = siblings[at - 1];
    if (above) {
      move = { target: above, position: "inside" };
    }
  }
  if (!move || !canDrop(nodes, token, move.target, move.position)) {
    return null;
  }
  return move;
}
function pathAfterMove(nodes, token, { target, position }) {
  const owned = ownedLabels(nodes);
  const node = nodes[token];
  const targetNode = nodes[target];
  const container = position === "inside" ? target : targetNode && targetNode.parent;
  if (!node || !container) {
    return "";
  }
  const parentPath = pathKey(nodes, container, owned);
  let segment;
  if (node.name) {
    segment = `${node.tag}:${node.name}`;
  } else if (node.string) {
    segment = `${node.tag}:${node.string}`;
  } else {
    const children = visibleChildren(nodes, container, owned).filter((c) => c !== token);
    let index;
    if (position === "inside") {
      index = children.length;
    } else {
      const anchor = children.includes(target) ? target : ownerOf(nodes, target);
      index = children.indexOf(anchor) + (position === "after" ? 1 : 0);
    }
    segment = `${node.tag}:#${index}`;
  }
  return `${parentPath}/${segment}`;
}
function ownerOf(nodes, token) {
  for (const [other, node] of Object.entries(nodes)) {
    if (node.label && node.label.token === token) {
      return other;
    }
  }
  return token;
}
function nextFocus(rows, index, key) {
  if (!rows.length) {
    return -1;
  }
  switch (key) {
    case "ArrowUp":
      return Math.max(0, index - 1);
    case "ArrowDown":
      return Math.min(rows.length - 1, index + 1);
    case "Home":
      return 0;
    case "End":
      return rows.length - 1;
    default:
      return index;
  }
}
export {
  KIND_ICONS,
  beforeAnchor,
  canDrop,
  flatten,
  iconFor,
  isOwnedLabel,
  labelFor,
  moveTarget,
  nextFocus,
  ownedLabels,
  pathAfterMove,
  pathKey,
  tokenAtPath,
  visibleChildren
};

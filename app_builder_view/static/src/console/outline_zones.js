import { _t } from "@web/core/l10n/translation";
import { beforeAnchor } from "./outline_tree";
import { MIN_BAR, captionFor, labelOf, subtree, takesTag } from "./zones";
const END_EXT = 12;
function outlineZones({
  nodes,
  tag,
  moving = null,
  rows,
  indentOf,
  box
}) {
  const zones = [];
  if (!tag || !rows.length || !box) {
    return { zones, containers: [] };
  }
  const excluded = moving ? subtree(nodes, moving) : /* @__PURE__ */ new Set();
  const count = rows.length;
  const right = box.left + box.width;
  const showsChildren = (i) => {
    const next = rows[i + 1];
    const current = rows[i];
    return i + 1 < count && Boolean(next && current && next.depth > current.depth);
  };
  const intoRow = (i) => {
    const row = rows[i];
    return Boolean(
      row && !excluded.has(row.token) && takesTag(nodes, row.token, tag) && !showsChildren(i)
    );
  };
  const lower = (i) => {
    const row = rows[i];
    return row ? row.rect.top + row.rect.height * (intoRow(i) ? 0.75 : 0.5) : 0;
  };
  const upper = (i) => {
    const row = rows[i];
    return row ? row.rect.top + row.rect.height * (intoRow(i) ? 0.25 : 0.5) : 0;
  };
  const push = (zone) => {
    const rect = clip(zone.rect, box);
    if (rect && rect.height >= MIN_BAR && rect.width >= MIN_BAR) {
      zones.push({ ...zone, rect });
    }
  };
  for (let i = 0; i < count; i++) {
    const row = rows[i];
    if (!row) {
      continue;
    }
    if (intoRow(i)) {
      const node = nodes[row.token];
      if (node) {
        push({
          layer: "outline",
          token: row.token,
          position: "inside",
          kind: node.kind,
          name: node.name || "",
          container: row.token,
          containerKind: node.kind,
          containerLabel: labelOf(node),
          depth: row.depth,
          axis: "y",
          edge: null,
          line: null,
          rect: {
            top: row.rect.top + row.rect.height / 4,
            left: box.left,
            width: box.width,
            height: row.rect.height / 2
          },
          caption: String(_t("into %s", labelOf(node)))
        });
      }
    }
    const next = i + 1 < count ? rows[i + 1] ?? null : null;
    const top = lower(i);
    const bottom = next ? upper(i + 1) : row.rect.top + row.rect.height + END_EXT;
    const line = next ? next.rect.top : row.rect.top + row.rect.height;
    const candidates = gapCandidates({ nodes, tag, moving, excluded, row, next });
    if (!candidates.length || bottom <= top) {
      continue;
    }
    candidates.sort((a, b) => b.depth - a.depth);
    const deepest = candidates[0]?.depth ?? 0;
    const shallowest = candidates[candidates.length - 1]?.depth ?? 0;
    for (const candidate of candidates) {
      let left;
      let end;
      if (candidates.length === 1) {
        left = box.left;
        end = right;
      } else if (candidate.depth === deepest) {
        left = box.left + indentOf(candidate.depth);
        end = right;
      } else {
        left = box.left + indentOf(candidate.depth);
        end = box.left + indentOf(candidate.depth + 1);
      }
      if (candidate.depth === shallowest) {
        left = box.left;
      }
      const anchor = nodes[candidate.anchor];
      const container = nodes[candidate.container];
      if (!anchor || !container) {
        continue;
      }
      push({
        layer: "outline",
        token: candidate.token,
        position: candidate.position,
        kind: anchor.kind,
        name: anchor.name || "",
        container: candidate.container,
        containerKind: container.kind,
        containerLabel: labelOf(container),
        depth: candidate.depth,
        axis: "y",
        edge: candidate.edge,
        line,
        rect: { top, left, width: end - left, height: bottom - top },
        caption: captionFor(candidate.position, candidate.edge, anchor, container)
      });
    }
  }
  return { zones, containers: [] };
}
function gapCandidates({
  nodes,
  tag,
  moving,
  excluded,
  row,
  next
}) {
  const out = [];
  const fits = (container) => Boolean(container && !excluded.has(container) && takesTag(nodes, container, tag));
  if (next && next.depth > row.depth) {
    if (next.token !== moving && fits(row.token)) {
      out.push({
        token: beforeAnchor(nodes, next.token),
        anchor: next.token,
        position: "before",
        container: row.token,
        depth: next.depth,
        edge: "start"
      });
    }
    return out;
  }
  const floor = next ? next.depth : 1;
  let ancestor = row.token;
  for (let depth = row.depth; depth >= floor && ancestor; depth--) {
    const node = nodes[ancestor];
    const beside = ancestor === moving || depth === floor && next && next.token === moving;
    if (node && node.parent && !excluded.has(ancestor) && !beside && fits(node.parent)) {
      out.push({
        token: ancestor,
        anchor: ancestor,
        position: "after",
        container: node.parent,
        depth,
        edge: !next || depth > next.depth ? "end" : null
      });
    }
    ancestor = node ? node.parent : null;
  }
  return out;
}
function clip(rect, box) {
  const top = Math.max(rect.top, box.top);
  const left = Math.max(rect.left, box.left);
  const bottom = Math.min(rect.top + rect.height, box.top + box.height);
  const right = Math.min(rect.left + rect.width, box.left + box.width);
  if (bottom <= top || right <= left) {
    return null;
  }
  return { top, left, width: right - left, height: bottom - top };
}
export {
  END_EXT,
  outlineZones
};

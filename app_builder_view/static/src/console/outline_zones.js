/** @odoo-module **/
/**
 * Where a drop can land on the outline, as rectangles.
 *
 * The tree is a column of rows, so every drop is a horizontal line
 * between two of them -- or the row itself, for a container that shows
 * nothing under it and takes what is dragged. The same three positions
 * the canvas offers (`zones.js`), laid out over rows instead of the
 * rendering, and sent the same way: one token, one position.
 *
 * A gap between two rows can mean more than one thing. Below the last
 * field of a group, "after that field, in the group" and "after the
 * group, in the sheet" are the same line on screen; below the last row
 * of a page inside a notebook inside a sheet, three places share it.
 * Tree editors settle this by where the pointer is across the row: the
 * gap is cut into bands, one per container the line closes, each
 * starting at that container's indent, so the deepest place takes the
 * pointer over the row's own text and the shallowest takes it at the
 * left edge. No two zones overlap, so the drag hook's nearest-zone pick
 * never has to break a tie.
 *
 * The rows a drag can reach are the ones on screen: the list scrolls,
 * and a zone laid out for a row scrolled out of view would sit, as far
 * as the hook can measure, over whatever is below the list. So every
 * zone is clipped to the list's own box and the layout is done again
 * when the list scrolls.
 *
 * Pure: rows come in as `{token, depth, rect, collapsed}` and nothing
 * here touches the DOM. No Owl, no services.
 */

import { _t } from "@web/core/l10n/translation";
import { beforeAnchor } from "./outline_tree";
import { MIN_BAR, captionFor, labelOf, subtree, takesTag } from "./zones";

/** How far below the last row its gap still reaches, in pixels. */
export const END_EXT = 12;

/**
 * Lay the outline's zones out for one payload.
 *
 * @param {Object} params
 * @param {Object} params.nodes the node table
 * @param {string} params.tag the tag the payload puts in the arch
 * @param {string|null} [params.moving] the token being moved, if any
 * @param {Object[]} params.rows the rows on screen, in order:
 *   `{token, depth, rect}` with `rect` in viewport coordinates
 * @param {Function} params.indentOf `(depth) => px`, where a row of that
 *   depth starts, from the list's left edge
 * @param {Object} params.box the list's visible box, viewport coordinates
 * @returns {{zones: Object[], containers: Object[]}} the zones in the
 *   canvas's shape, each with `layer: "outline"` and `line` -- the
 *   viewport y of the boundary a bar is drawn on, `null` for a box
 */
export function outlineZones({ nodes, tag, moving = null, rows, indentOf, box }) {
    const zones = [];
    if (!tag || !rows.length || !box) {
        return { zones, containers: [] };
    }
    const excluded = moving ? subtree(nodes, moving) : new Set();
    const count = rows.length;
    const right = box.left + box.width;
    const showsChildren = (i) => i + 1 < count && rows[i + 1].depth > rows[i].depth;
    const intoRow = (i) =>
        !excluded.has(rows[i].token) && takesTag(nodes, rows[i].token, tag) && !showsChildren(i);
    // The gap takes the halves of the rows on either side, or a quarter
    // beside a row that is itself a place to drop into.
    const lower = (i) => rows[i].rect.top + rows[i].rect.height * (intoRow(i) ? 0.75 : 0.5);
    const upper = (i) => rows[i].rect.top + rows[i].rect.height * (intoRow(i) ? 0.25 : 0.5);
    const push = (zone) => {
        const rect = clip(zone.rect, box);
        if (rect && rect.height >= MIN_BAR && rect.width >= MIN_BAR) {
            zones.push({ ...zone, rect });
        }
    };

    for (let i = 0; i < count; i++) {
        const row = rows[i];
        if (intoRow(i)) {
            const node = nodes[row.token];
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
                    height: row.rect.height / 2,
                },
                caption: String(_t("into %s", labelOf(node))),
            });
        }
        const next = i + 1 < count ? rows[i + 1] : null;
        const top = lower(i);
        const bottom = next ? upper(i + 1) : row.rect.top + row.rect.height + END_EXT;
        const line = next ? next.rect.top : row.rect.top + row.rect.height;
        const candidates = gapCandidates({ nodes, tag, moving, excluded, row, next });
        if (!candidates.length || bottom <= top) {
            continue;
        }
        // Deepest first: the band over the row's own text is the nearest
        // place, and each shallower place takes the indent to its left.
        candidates.sort((a, b) => b.depth - a.depth);
        const deepest = candidates[0].depth;
        const shallowest = candidates[candidates.length - 1].depth;
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
                caption: captionFor(candidate.position, candidate.edge, anchor, container),
            });
        }
    }
    return { zones, containers: [] };
}

/**
 * What the gap below `row` can mean, one entry per container whose
 * boundary the gap is: `{token, anchor, position, container, depth,
 * edge}` -- `token` is what is sent, `anchor` the row it names (they
 * differ when the row is a field whose own label stands before it).
 */
function gapCandidates({ nodes, tag, moving, excluded, row, next }) {
    const out = [];
    const fits = (container) => container && !excluded.has(container) && takesTag(nodes, container, tag);
    if (next && next.depth > row.depth) {
        // The first child: before it, in the row's own container.
        if (next.token !== moving && fits(row.token)) {
            out.push({
                token: beforeAnchor(nodes, next.token),
                anchor: next.token,
                position: "before",
                container: row.token,
                depth: next.depth,
                edge: "start",
            });
        }
        return out;
    }
    // The row closes every container between its depth and the next
    // row's -- all of them, below the last row -- and each is a place.
    const floor = next ? next.depth : 1;
    let ancestor = row.token;
    for (let depth = row.depth; depth >= floor && ancestor; depth--) {
        const node = nodes[ancestor];
        const beside = ancestor === moving || (depth === floor && next && next.token === moving);
        if (node && node.parent && !excluded.has(ancestor) && !beside && fits(node.parent)) {
            out.push({
                token: ancestor,
                anchor: ancestor,
                position: "after",
                container: node.parent,
                depth,
                edge: !next || depth > next.depth ? "end" : null,
            });
        }
        ancestor = node ? node.parent : null;
    }
    return out;
}

/** The part of `rect` inside `box`, or `null` when none is. */
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

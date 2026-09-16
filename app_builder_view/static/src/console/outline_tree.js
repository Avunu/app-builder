/** @odoo-module **/
/**
 * The view as a tree of rows: what the outline lists, in what order, at
 * what depth, and what a key press on a row asks the server for.
 *
 * Everything here is read off the node table the canvas payload carries
 * (`tools/canvas_stamp.py`): a node's `children` are in document order,
 * `parent` walks up, `accepts` says what a container takes. So the tree
 * is the arch, seen from the same table the drop zones are laid out
 * from, and nothing is asked of the DOM. Two nodes are left out. A
 * `<label for>` a field owns is not a row of its own: it follows its
 * field wherever the field goes (DESIGN.md, discovery 22), and listing
 * it would offer a drop between a label and its field that the eye
 * cannot see. A node the table marks unselectable -- a field a kanban
 * declares at its root and shows on no card -- is not on the document
 * as a person reads it; the Add tab lists those.
 *
 * Tokens are ordinals, minted anew on every edit, so nothing a person
 * did to the tree -- fold a group, put the cursor on a row -- can be
 * remembered by token. A row's *path* is its name and its ancestors'
 * (`pathKey`), which survives a re-stamp; `tokenAtPath` finds the row
 * again on the next table.
 *
 * A keyboard move is the same request a drag makes: one target, one
 * position, checked here against what the container accepts and what
 * is inside what, then sent through `model.drop` for the server to
 * check again. `beforeAnchor` is the one place the tree knows more than
 * the canvas: a drop "before a field" whose own label stands just
 * before it lands between the two, and the label is not a row here, so
 * the anchor is the label.
 *
 * Pure: no Owl, no services, no DOM.
 */

import { _t } from "@web/core/l10n/translation";
import { TYPE_ICONS } from "./pending_widget";
import { labelOf, subtree, takesTag } from "./zones";

/** The icon a row shows for a kind that is not a field. */
export const KIND_ICONS = {
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
    column: "fa fa-columns",
};

/** Attribute values the arch means as true. */
const TRUE_LITERALS = new Set(["1", "true", "True"]);

/** The tokens of every `<label for>` a field of the table owns. */
export function ownedLabels(nodes) {
    const owned = new Set();
    for (const node of Object.values(nodes)) {
        if (node.label && node.label.token) {
            owned.add(node.label.token);
        }
    }
    return owned;
}

/** Whether `token` is a label some field of the table owns. */
export function isOwnedLabel(nodes, token) {
    const node = nodes[token];
    return Boolean(node && node.kind === "label" && ownedLabels(nodes).has(token));
}

/**
 * The children of `token` the tree lists, in document order: what the
 * table marks selectable, less the labels fields own. `owned` may be
 * passed when the caller already has it.
 */
export function visibleChildren(nodes, token, owned = ownedLabels(nodes)) {
    const node = nodes[token];
    if (!node) {
        return [];
    }
    return (node.children || []).filter((child) => {
        const entry = nodes[child];
        return Boolean(entry && entry.selectable !== false && !owned.has(child));
    });
}

/** The label a row shows: the node's own, its field's, or its kind's. */
export function labelFor(node) {
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

/** The icon a row shows: a field's type, else its kind's. */
export function iconFor(node) {
    if (!node) {
        return "fa fa-square-o";
    }
    if (node.field && TYPE_ICONS[node.field.type]) {
        return TYPE_ICONS[node.field.type];
    }
    if (node.kind === "pending" && node.pending && TYPE_ICONS[node.pending.ttype]) {
        return TYPE_ICONS[node.pending.ttype];
    }
    return KIND_ICONS[node.kind] || "fa fa-square-o";
}

/**
 * One segment of a path: the tag and what tells the node from its
 * siblings -- its name, else its string, else its place among the
 * children the tree lists.
 */
function segmentOf(nodes, token, owned) {
    const node = nodes[token];
    if (node.name) {
        return `${node.tag}:${node.name}`;
    }
    if (node.string) {
        return `${node.tag}:${node.string}`;
    }
    const siblings = node.parent ? visibleChildren(nodes, node.parent, owned) : [token];
    return `${node.tag}:#${siblings.indexOf(token)}`;
}

/**
 * The path of a node: its segment and its ancestors', root first, joined
 * by `/`. Two tables of the same view give the same path to the same
 * node, whatever the tokens say.
 */
export function pathKey(nodes, token, owned = ownedLabels(nodes)) {
    const segments = [];
    let cursor = token;
    while (cursor && nodes[cursor]) {
        segments.unshift(segmentOf(nodes, cursor, owned));
        cursor = nodes[cursor].parent;
    }
    return segments.join("/");
}

/** The token at `path` on this table, or `null` when nothing is there. */
export function tokenAtPath(nodes, root, path) {
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

/**
 * Lay the tree out as rows.
 *
 * @param {Object} nodes the node table
 * @param {string} root the root token
 * @param {Object} [options]
 * @param {Set<string>} [options.collapsed] the paths of the containers
 *   folded shut
 * @param {string} [options.filter] text a row -- or one below it -- has to
 *   match to be listed; the ancestors of a match are shown open
 * @returns {Object[]} `{token, node, depth, key, hasChildren, expanded,
 *   label, icon, badges: {hidden, pending, required}, fixed}`, in
 *   document order
 */
export function flatten(nodes, root, { collapsed = new Set(), filter = "" } = {}) {
    const rows = [];
    if (!nodes[root]) {
        return rows;
    }
    const owned = ownedLabels(nodes);
    const needle = (filter || "").trim().toLowerCase();
    const matches = needle ? matching(nodes, root, needle, owned) : null;
    const walk = (token, depth) => {
        const node = nodes[token];
        if (matches && !matches.has(token)) {
            return;
        }
        const key = pathKey(nodes, token, owned);
        const children = visibleChildren(nodes, token, owned);
        const hasChildren = children.length > 0;
        // A filter opens the way to what it found; a fold is remembered
        // for when it is cleared.
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
                required: Boolean(node.attrs && TRUE_LITERALS.has(String(node.attrs.required))),
            },
            fixed: !node.movable,
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

/**
 * The tokens a filter keeps: every node whose label, name or kind holds
 * the needle, and every ancestor of one.
 */
function matching(nodes, root, needle, owned) {
    const kept = new Set();
    const walk = (token) => {
        const node = nodes[token];
        let hit = false;
        for (const child of visibleChildren(nodes, token, owned)) {
            hit = walk(child) || hit;
        }
        const own = [labelFor(node), node.name || "", node.kind || ""]
            .join(" ")
            .toLowerCase()
            .includes(needle);
        if (hit || own) {
            kept.add(token);
            return true;
        }
        return false;
    };
    walk(root);
    return kept;
}

/**
 * The anchor for a drop "before `token`": the field's own `<label for>`
 * when it stands just before the field, else the field itself. The
 * server follows the label of what is *moved*, not of what is dropped
 * beside, so "before the field" would land between its label and it.
 */
export function beforeAnchor(nodes, token) {
    const node = nodes[token];
    if (!node || !node.label || node.label.by !== "label" || !node.label.token) {
        return token;
    }
    const label = nodes[node.label.token];
    if (!label || label.parent !== node.parent) {
        return token;
    }
    const siblings = (nodes[node.parent] && nodes[node.parent].children) || [];
    const at = siblings.indexOf(token);
    return at > 0 && siblings[at - 1] === node.label.token ? node.label.token : token;
}

/**
 * Whether the server would take `src` put `position` `target`: `src` is
 * movable, the container the position names takes its tag, and nothing
 * is dropped into itself. The server checks all of this again.
 */
export function canDrop(nodes, src, target, position) {
    const node = nodes[src];
    const anchor = nodes[target];
    if (!node || !anchor || !node.movable || src === target) {
        return false;
    }
    if (position !== "inside" && !anchor.parent) {
        return false;
    }
    const container = position === "inside" ? target : anchor.parent;
    if (!takesTag(nodes, container, node.tag)) {
        return false;
    }
    return !subtree(nodes, src).has(target);
}

/**
 * Where a key press moves `token`: `up` before the sibling above, `down`
 * after the one below, `out` after its container, `in` into the sibling
 * above when that takes it. `{target, position}`, or `null` when the
 * move is not one the server would take.
 */
export function moveTarget(nodes, token, direction) {
    const node = nodes[token];
    if (!node || !node.parent) {
        return null;
    }
    const siblings = visibleChildren(nodes, node.parent);
    const at = siblings.indexOf(token);
    let move = null;
    if (direction === "up" && at > 0) {
        move = { target: beforeAnchor(nodes, siblings[at - 1]), position: "before" };
    } else if (direction === "down" && at >= 0 && at < siblings.length - 1) {
        move = { target: siblings[at + 1], position: "after" };
    } else if (direction === "out") {
        move = { target: node.parent, position: "after" };
    } else if (direction === "in" && at > 0) {
        move = { target: siblings[at - 1], position: "inside" };
    }
    if (!move || !canDrop(nodes, token, move.target, move.position)) {
        return null;
    }
    return move;
}

/**
 * The path `token` will have once `move` is made, so the row can be
 * found again on the table the server sends back.
 */
export function pathAfterMove(nodes, token, { target, position }) {
    const owned = ownedLabels(nodes);
    const node = nodes[token];
    const container = position === "inside" ? target : nodes[target].parent;
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
            // The anchor may be a label the tree does not list: the row
            // it stands for is the field that owns it.
            const anchor = children.includes(target) ? target : ownerOf(nodes, target);
            index = children.indexOf(anchor) + (position === "after" ? 1 : 0);
        }
        segment = `${node.tag}:#${index}`;
    }
    return `${parentPath}/${segment}`;
}

/** The field whose `<label for>` is `token`, or `token` itself. */
function ownerOf(nodes, token) {
    for (const [other, node] of Object.entries(nodes)) {
        if (node.label && node.label.token === token) {
            return other;
        }
    }
    return token;
}

/**
 * The row the focus goes to from row `index` on `key`: the previous or
 * next, the first or the last. `index` itself when the key is none of
 * those.
 */
export function nextFocus(rows, index, key) {
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

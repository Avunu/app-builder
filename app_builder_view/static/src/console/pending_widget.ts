/** @odoo-module **/
/**
 * The ghost of a field that does not exist yet.
 *
 * On a model a package defines in Python, a new field is a class attribute
 * waiting for an Apply, and the view cannot render what the registry has
 * never loaded. So the server splices a `<widget name="app_builder_pending">`
 * into the canvas arch where the field will land, and this is what draws
 * it: a dashed box with the type and the label, in the flow of the form,
 * where a real field would be. A `<widget>` because that is the one tag
 * that renders in a form group, as a list column and in a kanban card
 * alike; a `<div>` would not.
 *
 * Only the drawing lives here. The ghost is stamped like any node -- its
 * class carries `o_builder_n_p_<name>` -- so the canvas selects it, the
 * properties show its staged definition and a drag re-anchors it, all
 * without this component knowing: it draws a box, and the console's
 * overlay and drag do the rest by the token. A ghost whose anchor no
 * longer resolves is still listed by the server but not spliced; the one
 * drawn here always has a place, and says so.
 */

import {Component} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {standardWidgetProps} from "@web/views/widgets/standard_widget_props";
import type {StaticWidgetInfo, ViewWidgetsRegistryItemShape} from "./odoo";

/**
 * What `this.props.xxx` this component's own getters actually read.
 * `standardWidgetProps` (`@web/views/widgets/standard_widget_props.js`,
 * spread into `static props` below unchanged) also hands this component a
 * `record`/`readonly` pair -- real, Owl-validated props -- but nothing in
 * this file's own TS code reads either, so they are left off this
 * interface rather than typed for a reader that does not exist yet, the
 * same rule this migration has applied to every wire shape so far. All
 * four fields below are optional to match the component's own (defensive)
 * `static props` schema, even though the one real producer of this
 * widget -- `_splice_ghost` in `builder_view_canvas.py` -- always sets
 * every one of them (see `PendingWidgetOptions` below).
 */
interface Props {
  name?: string;
  label?: string;
  ttype?: string;
  resolved?: boolean;
}

export class PendingFieldWidget extends Component<Props> {
  static override template = "app_builder_view.PendingFieldWidget";
  static override props = {
    ...standardWidgetProps,
    name: {type: String, optional: true},
    label: {type: String, optional: true},
    ttype: {type: String, optional: true},
    resolved: {type: Boolean, optional: true},
  };

  get label() {
    return this.props.label || this.props.name || "";
  }

  get icon() {
    return iconForType(this.props.ttype, this.props.ttype);
  }
}

/**
 * The icon the palette shows for a field type, shared with the ghost.
 * Keyed by field type and, below the line, by the picker keys that are a
 * type with a preset -- an Image is a binary, but not the File icon.
 *
 * Annotated as the open dictionary it always was used as -- both here and
 * in `drag.ts`, which indexes it with an arbitrary runtime `node.field.type:
 * string` -- rather than left to infer a closed literal-key type from the
 * object literal below. `drag.ts` currently re-binds its own import with a
 * local `TYPE_ICONS as Record<string, string>` cast to work around exactly
 * that inference (see its own comment above `const ICONS = ...`); now that
 * the export itself carries the right type, that cast is no longer needed
 * there (not changed here -- see findings).
 */
export const TYPE_ICONS: Record<string, string> = {
  char: "fa fa-font",
  text: "fa fa-align-left",
  html: "fa fa-file-text-o",
  boolean: "fa fa-check-square-o",
  integer: "fa fa-hashtag",
  float: "fa fa-superscript",
  monetary: "fa fa-money",
  date: "fa fa-calendar",
  datetime: "fa fa-clock-o",
  selection: "fa fa-list-ul",
  binary: "fa fa-file-o",
  many2one: "fa fa-link",
  one2many: "fa fa-list",
  many2many: "fa fa-tags",
  reference: "fa fa-external-link",
  priority: "fa fa-star-o",
  image: "fa fa-picture-o",
  sign: "fa fa-pencil-square-o",
  daterange: "fa fa-calendar-o",
  tags: "fa fa-tags",
  lines: "fa fa-table",
  related: "fa fa-share",
};

/**
 * The icon for a picker entry: its key's when that has one, else its
 * type's. `key`/`ttype` are `string | undefined` (every real caller so far
 * passes a value that can genuinely be missing -- this file's own `icon`
 * getter included, before a ghost's staged type has resolved), so each
 * lookup is guarded rather than indexed directly: `noUncheckedIndexedAccess`
 * adds `| undefined` to a `Record` read regardless, and a bracket index
 * read on a possibly-`undefined` key does not compile at all. Written as a
 * `??` chain that reads `TYPE_ICONS[...]` exactly once per key -- reading
 * the same computed index a second time does not re-narrow away the
 * `undefined` a first read already excluded (TYPING.md's own
 * "repeated-bracket-index" trap) -- rather than the original's `||` chain,
 * which is behaviorally identical (every real icon string is non-empty,
 * so `||` and `??` agree here) but relies on subtler truthy-narrowing of a
 * plain `string | undefined` that is easy to get wrong under strict mode.
 */
export function iconForType(
  key: string | undefined,
  ttype: string | undefined
): string {
  return (
    (key !== undefined ? TYPE_ICONS[key] : undefined) ??
    (ttype !== undefined ? TYPE_ICONS[ttype] : undefined) ??
    "fa fa-square-o"
  );
}

/**
 * `options="{...}"` on the spliced `<widget>` node, exactly as
 * `_splice_ghost` (`builder_view_canvas.py`) always builds it --
 * `repr()`'d from a plain dict literal with exactly these four keys, every
 * one of them always set (`resolved` via `bool(info.get("resolved",
 * True))`, never omitted). Narrower than `StaticWidgetInfo.options`'s own
 * bare `object` (necessarily -- different widgets put wildly different
 * things there), so this widget's own `extractProps` types its `options`
 * as this shape rather than the vendor's generic one.
 */
interface PendingWidgetOptions {
  name: string;
  label: string;
  ttype: string;
  resolved: boolean;
}

/**
 * `StaticWidgetInfo` with `options` narrowed to this widget's own real
 * shape -- legal narrowing on an interface member (TYPING.md's own rule:
 * an overriding property must be narrower than, or equal to, what it
 * overrides, and any object shape is narrower than bare `object`).
 */
interface PendingWidgetInfo extends StaticWidgetInfo {
  options: PendingWidgetOptions;
}

export const pendingFieldWidget: ViewWidgetsRegistryItemShape = {
  component: PendingFieldWidget,
  extractProps: ({options}: PendingWidgetInfo) => ({
    name: options.name,
    label: options.label,
    ttype: options.ttype,
    resolved: options.resolved !== false,
  }),
};

registry.category("view_widgets").add("app_builder_pending", pendingFieldWidget);

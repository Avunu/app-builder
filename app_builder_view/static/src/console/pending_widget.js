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
 * class carries `o_studio_n_p_<name>` -- so the canvas selects it, the
 * properties show its staged definition and a drag re-anchors it, all
 * without this component knowing: it draws a box, and the console's
 * overlay and drag do the rest by the token. A ghost whose anchor no
 * longer resolves is still listed by the server but not spliced; the one
 * drawn here always has a place, and says so.
 */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class PendingFieldWidget extends Component {
    static template = "app_builder_view.PendingFieldWidget";
    static props = {
        ...standardWidgetProps,
        name: { type: String, optional: true },
        label: { type: String, optional: true },
        ttype: { type: String, optional: true },
        resolved: { type: Boolean, optional: true },
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
 */
export const TYPE_ICONS = {
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

/** The icon for a picker entry: its key's when that has one, else its type's. */
export function iconForType(key, ttype) {
    return TYPE_ICONS[key] || TYPE_ICONS[ttype] || "fa fa-square-o";
}

export const pendingFieldWidget = {
    component: PendingFieldWidget,
    extractProps: ({ options }) => ({
        name: options.name,
        label: options.label,
        ttype: options.ttype,
        resolved: options.resolved !== false,
    }),
};

registry.category("view_widgets").add("app_builder_pending", pendingFieldWidget);

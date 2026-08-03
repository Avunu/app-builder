/** @odoo-module **/
/**
 * What you can change about the thing you selected.
 *
 * Shaped after two things already in this codebase and one in core:
 *
 *  - the field-type catalogue in `app_builder_base/tools/modelspec.py`, whose
 *    `params` decide which rows a field editor shows -- same idea, so the model
 *    composer and the view editor feel like one product rather than two;
 *  - master's `html_builder`, where options are a registry matched against the
 *    selected element rather than a component per case.
 *
 * Every row is data. Adding "kanban card options" later is an entry here, not a
 * new component, and each row produces the same `set_attributes` operation the
 * view editor has always had -- no new server plumbing per option.
 *
 * `null` means *remove the attribute*, which is different from the empty
 * string: it restores Odoo's own default rather than pinning a blank value.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

export const viewOptions = registry.category("app_builder.view_options");

const NUMERIC = ["integer", "float", "monetary"];

// Curated per type rather than "every widget Odoo has". A widget that does not
// apply to the field renders as an error in the user's face, and a list of
// eighty is not a choice anybody can make.
const WIDGETS = {
    char: [
        ["email", _t("Email")],
        ["phone", _t("Phone")],
        ["url", _t("Link")],
        ["badge", _t("Badge")],
    ],
    text: [["text", _t("Plain text")]],
    integer: [["progressbar", _t("Progress bar")], ["handle", _t("Drag handle")]],
    float: [["percentage", _t("Percentage")], ["float_time", _t("Duration")]],
    monetary: [["monetary", _t("Amount")]],
    boolean: [["boolean_toggle", _t("Toggle")]],
    date: [["remaining_days", _t("Remaining days")]],
    datetime: [["remaining_days", _t("Remaining days")]],
    selection: [["badge", _t("Badge")], ["priority", _t("Stars")]],
    many2one: [["many2one_avatar", _t("Avatar")]],
    many2many: [["many2many_tags", _t("Tags")]],
    binary: [["image", _t("Image")]],
};

function widgetChoices(target) {
    const type = target.field && target.field.type;
    return [["", _t("Default")], ...(WIDGETS[type] || [])];
}

// -- list ---------------------------------------------------------------

viewOptions.add("list_column", {
    id: "list_column",
    viewTypes: ["list"],
    match: (target) => target.kind === "column",
    title: (target) => (target.field && target.field.string) || target.name,
    rows: [
        {
            name: "string",
            label: _t("Column heading"),
            type: "text",
            placeholder: (target) => (target.field && target.field.string) || "",
            help: _t("Leave empty to use the field's own label."),
        },
        { name: "widget", label: _t("Shown as"), type: "select", choices: widgetChoices },
        {
            name: "optional",
            label: _t("Optional column"),
            type: "select",
            choices: () => [
                ["", _t("Always shown")],
                ["show", _t("Optional, on by default")],
                ["hide", _t("Optional, off by default")],
            ],
            help: _t(
                "Optional columns can be turned on and off by each user from " +
                    "the toggle at the right of the header row."
            ),
        },
        {
            name: "sum",
            label: _t("Column total"),
            type: "text",
            when: (target) => NUMERIC.includes(target.field && target.field.type),
            help: _t("The label shown beside the total, e.g. “Total”."),
        },
        {
            name: "column_invisible",
            label: _t("Hide this column"),
            type: "toggle",
            help: _t(
                "Hides the column without removing it, so nothing that depends " +
                    "on the field breaks."
            ),
        },
    ],
});

viewOptions.add("list_root", {
    id: "list_root",
    viewTypes: ["list"],
    match: (target) => target.kind === "root",
    title: () => _t("This list"),
    rows: [
        { name: "string", label: _t("Title"), type: "text" },
        {
            name: "editable",
            label: _t("Edit rows inline"),
            type: "select",
            choices: () => [
                ["", _t("Open the form")],
                ["top", _t("Inline, new rows on top")],
                ["bottom", _t("Inline, new rows at the bottom")],
            ],
        },
        {
            name: "multi_edit",
            label: _t("Edit many records at once"),
            type: "toggle",
            help: _t("Lets a user select rows and change a value on all of them."),
        },
        {
            name: "default_order",
            label: _t("Default sort"),
            type: "text",
            help: _t("A field name, optionally followed by desc — e.g. date desc."),
        },
        { name: "create", label: _t("Allow creating"), type: "toggle", invert: true },
        { name: "delete", label: _t("Allow deleting"), type: "toggle", invert: true },
    ],
});

// -- form ---------------------------------------------------------------

viewOptions.add("form_field", {
    id: "form_field",
    viewTypes: ["form"],
    match: (target) => target.kind === "field",
    title: (target) => (target.field && target.field.string) || target.name,
    rows: [
        {
            name: "string",
            label: _t("Label"),
            type: "text",
            placeholder: (target) => (target.field && target.field.string) || "",
            help: _t("Leave empty to use the field's own label."),
        },
        { name: "widget", label: _t("Shown as"), type: "select", choices: widgetChoices },
        {
            name: "placeholder",
            label: _t("Placeholder"),
            type: "text",
            help: _t("Grey hint text shown while the field is empty."),
        },
        {
            name: "help",
            label: _t("Tooltip"),
            type: "text",
            help: _t("Shown when the user hovers the label."),
        },
        {
            name: "required",
            label: _t("Required"),
            type: "toggle",
            help: _t(
                "Required on this form only. The field itself stays optional, " +
                    "so other screens and imports are unaffected."
            ),
        },
        { name: "readonly", label: _t("Read-only"), type: "toggle" },
        {
            name: "invisible",
            label: _t("Hidden"),
            type: "toggle",
            help: _t(
                "Hides the field without removing it, so anything depending on " +
                    "it keeps working."
            ),
        },
    ],
});

viewOptions.add("form_page", {
    id: "form_page",
    viewTypes: ["form"],
    match: (target) => target.kind === "page",
    title: () => _t("This tab"),
    rows: [{ name: "string", label: _t("Tab name"), type: "text" }],
});

viewOptions.add("form_root", {
    id: "form_root",
    viewTypes: ["form"],
    match: (target) => target.kind === "root",
    title: () => _t("This form"),
    rows: [
        { name: "string", label: _t("Title"), type: "text" },
        { name: "create", label: _t("Allow creating"), type: "toggle", invert: true },
        { name: "edit", label: _t("Allow editing"), type: "toggle", invert: true },
        { name: "delete", label: _t("Allow deleting"), type: "toggle", invert: true },
    ],
});

// -- kanban -------------------------------------------------------------

viewOptions.add("kanban_field", {
    id: "kanban_field",
    viewTypes: ["kanban"],
    match: (target) => target.kind === "field",
    title: (target) => (target.field && target.field.string) || target.name,
    rows: [
        { name: "widget", label: _t("Shown as"), type: "select", choices: widgetChoices },
        {
            name: "invisible",
            label: _t("Hidden"),
            type: "toggle",
            help: _t("Hides it on the card without removing it."),
        },
    ],
});

viewOptions.add("kanban_root", {
    id: "kanban_root",
    viewTypes: ["kanban"],
    match: (target) => target.kind === "root",
    title: () => _t("This kanban"),
    rows: [
        {
            name: "default_group_by",
            label: _t("Group by"),
            type: "text",
            help: _t("The field whose values become the columns, e.g. state."),
        },
        {
            name: "quick_create",
            label: _t("Quick create"),
            type: "toggle",
            invert: true,
            help: _t("Lets a user add a card from the column without a form."),
        },
        {
            name: "records_draggable",
            label: _t("Cards can be dragged"),
            type: "toggle",
            invert: true,
        },
        { name: "group_create", label: _t("Columns can be added"), type: "toggle", invert: true },
        { name: "archivable", label: _t("Columns can be archived"), type: "toggle", invert: true },
        {
            name: "default_order",
            label: _t("Default sort"),
            type: "text",
            help: _t("A field name, optionally followed by desc."),
        },
    ],
});

/**
 * Every option group that applies to the current selection.
 *
 * More than one may match, and they render in registry order, so a general
 * group can be declared once and a specific one added beside it later.
 */
export function optionsFor(viewType, target) {
    if (!target) {
        return [];
    }
    return viewOptions
        .getAll()
        .filter(
            (option) =>
                option.viewTypes.includes(viewType) && option.match(target)
        );
}

/**
 * Rows of an option group that apply to this target, with their current value
 * read from the node's real attributes.
 */
export function visibleRows(option, target) {
    return option.rows
        .filter((row) => !row.when || row.when(target))
        .map((row) => ({
            ...row,
            choices: typeof row.choices === "function" ? row.choices(target) : row.choices,
            placeholder:
                typeof row.placeholder === "function"
                    ? row.placeholder(target)
                    : row.placeholder,
            value: readValue(row, target),
        }));
}

function readValue(row, target) {
    const raw = (target.attrs || {})[row.name];
    if (row.type === "toggle") {
        // `invert` covers attributes that exist to switch something *off*:
        // create="0" means "no creating", so the checkbox reads the other way
        // round and an unset attribute means allowed.
        const on = raw === undefined ? row.invert : !["0", "false", "False"].includes(raw);
        return row.invert ? on : raw !== undefined && on;
    }
    return raw === undefined ? "" : raw;
}

/**
 * The attribute value an edited row should write. `null` removes the attribute.
 */
export function writeValue(row, value) {
    if (row.type === "toggle") {
        if (row.invert) {
            return value ? null : "0";
        }
        return value ? "1" : null;
    }
    return value === "" ? null : value;
}

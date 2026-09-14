/** @odoo-module **/
/**
 * Resolving the server's option catalogue against what this browser has.
 *
 * The rows themselves used to be declared here. They are declared in
 * `app_builder_view/tools/view_options.py` now, beside the field-type catalogue
 * the field editor reads, because two files describing one product drift and
 * nothing compares them. What is left here is the half that genuinely belongs
 * on the client:
 *
 *  - **the widget list**, because only the browser knows what is registered.
 *    The server *proposes* a curated set; `registry.category("fields")`
 *    disposes. A widget the server names but this database has not installed
 *    is dropped rather than offered, and one whose `supportedTypes` disagree
 *    with the field is dropped too — a widget that does not apply renders an
 *    error where the field should be.
 *  - **the `options="{...}"` merge**, because a row targeting an option is
 *    editing one key of a JSON blob the node already carries, and the node's
 *    current value is here.
 *
 * `null` means *remove the attribute*, which is different from the empty
 * string: it restores Odoo's own default rather than pinning a blank value.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const fieldRegistry = registry.category("fields");

/**
 * Widgets the server offers for this field that actually exist here.
 *
 * `supportedTypes` is core's own declaration on each field descriptor, so this
 * agrees with what the view would really accept rather than with what we
 * believed when the catalogue was written.
 */
function widgetChoices(target, context) {
    const type = target.field && target.field.type;
    const proposed = (context.catalogue && context.catalogue.widgets) || [];
    const usable = proposed.filter((entry) => {
        const descriptor = fieldRegistry.get(entry.value, null);
        if (!descriptor) {
            return false;
        }
        const supported = descriptor.supportedTypes;
        // A descriptor that declares nothing supports whatever it is given;
        // fall back to what the server transcribed from core.
        return supported ? supported.includes(type) : entry.types.includes(type);
    });
    return [["", _t("Default")], ...usable.map((entry) => [entry.value, entry.label])];
}

function fieldChoices(row, context) {
    const types = row.field_types || [];
    const fields = (context && context.fields) || [];
    const matching = fields
        .filter((f) => !types.length || types.includes(f.type))
        .map((f) => [f.name, `${f.string} (${f.name})`]);
    return row.allow_empty
        ? [["", row.empty_label || _t("None")], ...matching]
        : matching;
}

function choicesFor(row, target, context) {
    switch (row.source) {
        case "widgets":
            return widgetChoices(target, context);
        case "fields":
            return fieldChoices(row, context);
        case "image_size":
            return [
                ["", _t("Default")],
                ...((context.catalogue && context.catalogue.image_sizes) || []),
            ];
        case "comodel_fields":
            // Fields of the model this relation points at, not of the model
            // being edited -- a tag colour lives on the tag.
            return fieldChoices(row, {
                fields: (target.field && target.field.comodel_fields) || [],
            });
        default:
            return row.choices || [];
    }
}

/** Every option group the server sent that matches this selection. */
export function optionsFor(context, target) {
    if (!target || !context || !context.options) {
        return [];
    }
    return context.options.filter((group) => group.kinds.includes(target.kind));
}

/**
 * The rows of a group that apply to this target, with their current values.
 *
 * A row whose widget brings extra configuration of its own contributes those
 * rows immediately after it, so choosing "Image" makes its size row appear
 * without a round trip.
 */
export function visibleRows(group, target, context = {}) {
    const out = [];
    for (const row of group.rows) {
        if (!applies(row, target)) {
            continue;
        }
        out.push(resolve(row, target, context));
        if (row.source === "widgets") {
            out.push(...widgetOwnRows(target, context));
        }
    }
    return out;
}

function applies(row, target) {
    if (!row.only_for || !row.only_for.length) {
        return true;
    }
    return row.only_for.includes(target.field && target.field.type);
}

/** The rows the currently chosen widget brings with it. */
function widgetOwnRows(target, context) {
    const current = (target.attrs || {}).widget;
    if (!current) {
        return [];
    }
    const entry = ((context.catalogue && context.catalogue.widgets) || []).find(
        (w) => w.value === current
    );
    return (entry ? entry.rows : []).map((row) => resolve(row, target, context));
}

function resolve(row, target, context) {
    return {
        ...row,
        // Not the name: one attribute can have two rows. `invisible` is both a
        // checkbox ("hidden") and a condition ("hidden when"), and two rows
        // sharing a t-key makes Owl reuse one element for both.
        key: `${row.name}:${row.type}`,
        choices: choicesFor(row, target, context),
        placeholder:
            row.placeholder_from === "field.string"
                ? (target.field && target.field.string) || ""
                : row.placeholder || "",
        value: readValue(row, target),
    };
}

/** The `options="{...}"` blob a node currently carries. */
function readOptions(target) {
    const raw = (target.attrs || {}).options;
    if (!raw) {
        return {};
    }
    try {
        // Odoo writes this with Python's repr, so single quotes and True/False.
        return JSON.parse(
            raw.replace(/'/g, '"').replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false")
        );
    } catch {
        return {};
    }
}

function readValue(row, target) {
    const raw =
        row.target === "option"
            ? readOptions(target)[row.name]
            : (target.attrs || {})[row.name];
    if (row.type === "groups") {
        // A comma-separated list of xmlids, which is what the arch carries and
        // what survives being loaded into another database.
        return raw ? raw.split(",").map((x) => x.trim()).filter(Boolean) : [];
    }
    if (row.type === "toggle") {
        // `invert` covers attributes that exist to switch something *off*:
        // create="0" means "no creating", so the checkbox reads the other way
        // round and an unset attribute means allowed.
        if (row.target === "option") {
            return row.invert ? raw !== false : raw === true;
        }
        const on =
            raw === undefined ? row.invert : !["0", "false", "False"].includes(raw);
        return row.invert ? on : raw !== undefined && on;
    }
    if (raw === undefined || raw === null) {
        return "";
    }
    return typeof raw === "string" ? raw : JSON.stringify(raw);
}

/**
 * The attributes an edited row should write.
 *
 * Returns a whole `{attribute: value}` map rather than a single value, because
 * a row targeting an option is editing one key of a blob and has to hand back
 * the blob. `null` removes the attribute.
 */
export function writeValue(row, value, target) {
    if (row.target === "option") {
        const options = readOptions(target);
        const next = row.type === "toggle" ? Boolean(value) : value;
        if (next === "" || next === false) {
            delete options[row.name];
        } else {
            options[row.name] = next;
        }
        return {
            options: Object.keys(options).length ? JSON.stringify(options) : null,
        };
    }
    if (row.type === "toggle") {
        if (row.invert) {
            return { [row.name]: value ? null : "0" };
        }
        return { [row.name]: value ? "1" : null };
    }
    if (row.type === "groups") {
        const chosen = (value || []).filter(Boolean);
        return { [row.name]: chosen.length ? chosen.join(",") : null };
    }
    return { [row.name]: value === "" ? null : value };
}

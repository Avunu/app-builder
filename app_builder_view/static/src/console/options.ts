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

import {_t} from "./l10n";
import {registry} from "@web/core/registry";
import type {DescribedTarget, BuilderModelFieldEntry} from "./types";
import type {CatalogueJSON, OptionGroupJSON, RowJSON, WidgetJSON} from "./wire";

const fieldRegistry = registry.category("fields");

/** What `context.catalogue`/`.fields`/`.options` carry, wherever this
 * module is handed a context (`console_model.js`'s own `context`, or a
 * narrower ad hoc object built just for `fieldChoices`'s comodel case). */
export interface OptionsContext {
  catalogue?: CatalogueJSON;
  fields?: BuilderModelFieldEntry[];
  options?: OptionGroupJSON[];
}

/** A resolved row's `value`, shaped by `row.type` -- see `readValue`. */
export type RowValue = string | string[] | boolean;

/** A catalogue row with its choices resolved and its current value read,
 * as `visibleRows` hands one to the sidebar (`resolve`). */
export interface ResolvedRow extends Omit<RowJSON, "choices"> {
  key: string;
  choices: [string, string][];
  placeholder: string;
  value: RowValue;
}

/**
 * Widgets the server offers for this field that actually exist here.
 *
 * `supportedTypes` is core's own declaration on each field descriptor, so this
 * agrees with what the view would really accept rather than with what we
 * believed when the catalogue was written.
 */
function widgetChoices(
  target: DescribedTarget,
  context: OptionsContext
): [string, string][] {
  const type = target.field && target.field.type;
  const proposed = (context.catalogue && context.catalogue.widgets) || [];
  const usable = proposed.filter((entry) => {
    const descriptor = fieldRegistry.get(entry.value, null);
    if (!descriptor) {
      return false;
    }
    const supported = descriptor.supportedTypes;
    // A descriptor that declares nothing supports whatever it is given;
    // fall back to what the server transcribed from core. `supported`
    // is typed as the enumerated `FieldType` union, but `type` is a
    // plain `string` from the server (a builder field type not in
    // that union -- `widget`, `chatter` -- is a real possibility,
    // not a type error); cast to how the array actually behaves at
    // runtime rather than narrowing `type` to a union it may not fit.
    return supported
      ? (supported as string[]).includes(type ?? "")
      : entry.types.includes(type ?? "");
  });
  return [
    ["", String(_t("Default"))],
    ...usable.map((entry): [string, string] => [entry.value, entry.label]),
  ];
}

function fieldChoices(
  row: RowJSON,
  context: {fields?: BuilderModelFieldEntry[]} | undefined
): [string, string][] {
  const types = row.field_types || [];
  const fields = (context && context.fields) || [];
  const matching: [string, string][] = fields
    .filter((f) => !types.length || types.includes(f.type))
    .map((f) => [f.name, `${f.string} (${f.name})`]);
  return row.allow_empty
    ? [["", row.empty_label || String(_t("None"))], ...matching]
    : matching;
}

function choicesFor(
  row: RowJSON,
  target: DescribedTarget,
  context: OptionsContext
): [string, string][] {
  switch (row.source) {
    case "widgets":
      return widgetChoices(target, context);
    case "fields":
      return fieldChoices(row, context);
    case "image_size":
      return [
        ["", String(_t("Default"))],
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
export function optionsFor(
  context: OptionsContext,
  target: DescribedTarget | null
): OptionGroupJSON[] {
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
export function visibleRows(
  group: OptionGroupJSON,
  target: DescribedTarget,
  context: OptionsContext = {}
): ResolvedRow[] {
  const out: ResolvedRow[] = [];
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

function applies(row: RowJSON, target: DescribedTarget): boolean {
  if (!row.only_for || !row.only_for.length) {
    return true;
  }
  return row.only_for.includes((target.field && target.field.type) ?? "");
}

/** The rows the currently chosen widget brings with it. */
function widgetOwnRows(
  target: DescribedTarget,
  context: OptionsContext
): ResolvedRow[] {
  const current = (target.attrs || {})["widget"];
  if (!current) {
    return [];
  }
  const entry: WidgetJSON | undefined = (
    (context.catalogue && context.catalogue.widgets) ||
    []
  ).find((w) => w.value === current);
  return (entry ? entry.rows : []).map((row) => resolve(row, target, context));
}

function resolve(
  row: RowJSON,
  target: DescribedTarget,
  context: OptionsContext
): ResolvedRow {
  return {
    ...row,
    // Not the name: one attribute can have two rows. `invisible` is both a
    // checkbox ("hidden") and a condition ("hidden when"), and two rows
    // sharing a t-key makes Owl reuse one element for both.
    key: `${row.name}:${row.type}`,
    choices: choicesFor(row, target, context),
    // `row.placeholder` was never a real field of `RowJSON`/the Python
    // `Row` dataclass (only `placeholder_from` is) -- pre-existing,
    // not introduced here, so every row that is not `field.string`
    // has always resolved to "" regardless. Kept as-is rather than
    // silently changing behavior; flagged for a follow-up.
    placeholder:
      row.placeholder_from === "field.string"
        ? (target.field && target.field.string) || ""
        : "",
    value: readValue(row, target),
  };
}

/** A value the `options="{...}"` blob holds. Every row that targets an
 * option is `toggle`/`text`/`select`/`image_size` (`catalogue.py`'s
 * curated `Row.type`s) -- always a flat primitive, never nested JSON --
 * so this is narrower than `unknown` on purpose, not loosened for one. */
export type OptionValue = string | number | boolean | null;

/** The `options="{...}"` blob a node currently carries. */
function readOptions(target: DescribedTarget): Record<string, OptionValue> {
  const raw = (target.attrs || {})["options"];
  if (!raw) {
    return {};
  }
  try {
    // Odoo writes this with Python's repr, so single quotes and True/False.
    return JSON.parse(
      raw
        .replace(/'/g, '"')
        .replace(/\bTrue\b/g, "true")
        .replace(/\bFalse\b/g, "false")
    ) as Record<string, OptionValue>;
  } catch {
    return {};
  }
}

function readValue(row: RowJSON, target: DescribedTarget): RowValue {
  const raw =
    row.target === "option"
      ? readOptions(target)[row.name]
      : (target.attrs || {})[row.name];
  if (row.type === "groups") {
    // A comma-separated list of xmlids, which is what the arch carries and
    // what survives being loaded into another database.
    return typeof raw === "string"
      ? raw
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean)
      : [];
  }
  if (row.type === "toggle") {
    // `invert` covers attributes that exist to switch something *off*:
    // create="0" means "no creating", so the checkbox reads the other way
    // round and an unset attribute means allowed.
    if (row.target === "option") {
      return row.invert ? raw !== false : raw === true;
    }
    const on =
      raw === undefined ? row.invert : !["0", "false", "False"].includes(String(raw));
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
export function writeValue(
  row: RowJSON,
  value: unknown,
  target: DescribedTarget
): Record<string, unknown> {
  if (row.target === "option") {
    const options = readOptions(target);
    // `value` is whatever the UI just edited -- text input, checkbox,
    // select, tags -- so genuinely `unknown` here, unlike the values
    // `readOptions` itself reads back (always a flat primitive,
    // `OptionValue`). An `options`-targeted row is never `groups` in
    // this catalogue (`RELATIONAL_ROWS` -- the only `option`-targeted
    // rows -- are both `toggle`), but the array case is handled the
    // same way the attribute-target `groups` branch below handles
    // it, rather than assumed away.
    const next: OptionValue =
      row.type === "toggle"
        ? Boolean(value)
        : Array.isArray(value)
          ? value.join(",")
          : (value as OptionValue);
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
      return {[row.name]: value ? null : "0"};
    }
    return {[row.name]: value ? "1" : null};
  }
  if (row.type === "groups") {
    const chosen = (Array.isArray(value) ? value : []).filter(Boolean);
    return {[row.name]: chosen.length ? chosen.join(",") : null};
  }
  return {[row.name]: value === "" ? null : value};
}

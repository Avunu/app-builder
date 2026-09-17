import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
const fieldRegistry = registry.category("fields");
function widgetChoices(target, context) {
  const type = target.field && target.field.type;
  const proposed = context.catalogue && context.catalogue.widgets || [];
  const usable = proposed.filter((entry) => {
    const descriptor = fieldRegistry.get(entry.value, null);
    if (!descriptor) {
      return false;
    }
    const supported = descriptor.supportedTypes;
    return supported ? supported.includes(type ?? "") : entry.types.includes(type ?? "");
  });
  return [
    ["", _t("Default")],
    ...usable.map((entry) => [entry.value, entry.label])
  ];
}
function fieldChoices(row, context) {
  const types = row.field_types || [];
  const fields = context && context.fields || [];
  const matching = fields.filter((f) => !types.length || types.includes(f.type)).map((f) => [f.name, `${f.string} (${f.name})`]);
  return row.allow_empty ? [["", row.empty_label || _t("None")], ...matching] : matching;
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
        ...context.catalogue && context.catalogue.image_sizes || []
      ];
    case "comodel_fields":
      return fieldChoices(row, {
        fields: target.field && target.field.comodel_fields || []
      });
    default:
      return row.choices || [];
  }
}
function optionsFor(context, target) {
  if (!target || !context || !context.options) {
    return [];
  }
  return context.options.filter((group) => group.kinds.includes(target.kind));
}
function visibleRows(group, target, context = {}) {
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
  return row.only_for.includes((target.field && target.field.type) ?? "");
}
function widgetOwnRows(target, context) {
  const current = (target.attrs || {})["widget"];
  if (!current) {
    return [];
  }
  const entry = (context.catalogue && context.catalogue.widgets || []).find((w) => w.value === current);
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
    // `row.placeholder` was never a real field of `RowJSON`/the Python
    // `Row` dataclass (only `placeholder_from` is) -- pre-existing,
    // not introduced here, so every row that is not `field.string`
    // has always resolved to "" regardless. Kept as-is rather than
    // silently changing behavior; flagged for a follow-up.
    placeholder: row.placeholder_from === "field.string" ? target.field && target.field.string || "" : "",
    value: readValue(row, target)
  };
}
function readOptions(target) {
  const raw = (target.attrs || {})["options"];
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(
      raw.replace(/'/g, '"').replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false")
    );
  } catch {
    return {};
  }
}
function readValue(row, target) {
  const raw = row.target === "option" ? readOptions(target)[row.name] : (target.attrs || {})[row.name];
  if (row.type === "groups") {
    return typeof raw === "string" ? raw.split(",").map((x) => x.trim()).filter(Boolean) : [];
  }
  if (row.type === "toggle") {
    if (row.target === "option") {
      return row.invert ? raw !== false : raw === true;
    }
    const on = raw === void 0 ? row.invert : !["0", "false", "False"].includes(String(raw));
    return row.invert ? on : raw !== void 0 && on;
  }
  if (raw === void 0 || raw === null) {
    return "";
  }
  return typeof raw === "string" ? raw : JSON.stringify(raw);
}
function writeValue(row, value, target) {
  if (row.target === "option") {
    const options = readOptions(target);
    const next = row.type === "toggle" ? Boolean(value) : Array.isArray(value) ? value.join(",") : value;
    if (next === "" || next === false) {
      delete options[row.name];
    } else {
      options[row.name] = next;
    }
    return {
      options: Object.keys(options).length ? JSON.stringify(options) : null
    };
  }
  if (row.type === "toggle") {
    if (row.invert) {
      return { [row.name]: value ? null : "0" };
    }
    return { [row.name]: value ? "1" : null };
  }
  if (row.type === "groups") {
    const chosen = (Array.isArray(value) ? value : []).filter(Boolean);
    return { [row.name]: chosen.length ? chosen.join(",") : null };
  }
  return { [row.name]: value === "" ? null : value };
}
export {
  optionsFor,
  visibleRows,
  writeValue
};

import { _t } from "../l10n";
import { registry } from "@web/core/registry";
const paneRegistry = registry.category("app_builder.panes");
const legacyTabs = registry.category("app_builder.console_tabs");
let warnedLegacy = false;
function warnLegacyTabs() {
  if (warnedLegacy) {
    return;
  }
  warnedLegacy = true;
  const keys = legacyTabs.getEntries().map(([key]) => key);
  if (keys.length) {
    console.warn(
      "app_builder.console_tabs is no longer read by the console; register a pane in app_builder.panes instead: " + keys.join(", ")
    );
  }
}
const resolvers = {
  record: null,
  flow: null
};
function setPaneResolver(kind, resolve) {
  resolvers[kind] = resolve;
}
function resolvePane(key) {
  if (!paneRegistry.contains(key)) {
    throw new Error(`app_builder.panes has no "${key}"`);
  }
  const registered = paneRegistry.get.call(
    paneRegistry,
    key
  );
  const entry = { key, ...registered };
  if (entry.Component) {
    return {
      ...entry,
      sidebar: entry.sidebar ?? null,
      makeModel: entry.makeModel ?? null
    };
  }
  if (entry.surface) {
    if (!resolvers.record) {
      throw new Error(`no record pane to render "${key}"`);
    }
    return { ...entry, ...resolvers.record(entry) };
  }
  if (entry.flow) {
    if (!resolvers.flow) {
      throw new Error(`no flow host to render "${key}"`);
    }
    return { ...entry, tab: false, ...resolvers.flow(entry) };
  }
  throw new Error(`app_builder.panes["${key}"] declares neither Component, surface nor flow`);
}
function paneAvailable(entry, ctx) {
  if (entry.isAvailable) {
    return Boolean(entry.isAvailable(ctx));
  }
  if (entry.scope === "model" && !ctx.modelName) {
    return false;
  }
  if (entry.scope === "view" && !(ctx.view && ctx.view.view_id)) {
    return false;
  }
  return true;
}
function paneTabs(ctx) {
  return paneRegistry.getEntries().map(([key, entry]) => ({ key, ...entry })).filter((entry) => entry.tab !== false && !entry.flow).map((entry) => {
    const available = paneAvailable(entry, ctx);
    let reason = "";
    if (!available && entry.scope === "model" && !ctx.modelName) {
      reason = String(
        _t("Choose a model first — from the crumb, or open any view with Studio.")
      );
    } else if (!available && entry.scope === "view") {
      reason = String(_t("Open a view first."));
    } else if (!available) {
      reason = String(_t("Not available here."));
    }
    return { ...entry, available, reason };
  });
}
function paneFlows(ctx) {
  return paneRegistry.getEntries().map(([key, entry]) => ({ key, ...entry })).filter((entry) => entry.tab === false || entry.flow).filter((entry) => paneAvailable(entry, ctx));
}
export {
  paneAvailable,
  paneFlows,
  paneRegistry,
  paneTabs,
  resolvePane,
  setPaneResolver,
  warnLegacyTabs
};

/** @odoo-module **/
/**
 * The panes the console can show, and what each needs to be shown.
 *
 * A pane is one thing in the content slot with, optionally, one thing in
 * the sidebar: the Views pane is the canvas beside Add | View |
 * Properties, a record pane is the model's automations beside their
 * properties, the Home pane is the package's workspace with no sidebar.
 * Every top-bar tab is a pane; not every pane is a tab (a flow is opened
 * by a tile and has no tab).
 *
 * Registered in `app_builder.panes` by whichever addon owns the thing. An
 * addon that does not depend on this one registers a *data-only* entry --
 * a surface name and a few strings -- and the console renders it with
 * its own record pane; only an addon that may import from here brings a
 * component of its own. Entries:
 *
 *   label, icon, sequence (add() option)
 *   scope        "package" | "model" | "view" -- what must be in hand
 *   isAvailable  (ctx) => boolean, optional, on top of scope
 *   tab          false for a pane the bar does not list (a flow)
 *
 *   a custom pane:   Component, sidebar (component or null), makeModel(shell)
 *   a record pane:   surface, surfaceArgs, rowActions, newFlow
 *   a flow pane:     flow: {title, steps: [{key, label, Component, validate}],
 *                          onDone(shell, flow), onCancel(shell)}
 *
 * Every pane component and sidebar takes `{shell, model}` and nothing
 * else, and reads both through `useState`, the way every console
 * component reads the console model today.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

export const paneRegistry = registry.category("app_builder.panes");

// The tab registry the panes replace. Its only verb was `open(env, ctx)`,
// a `doAction` out of the console, which is exactly what a pane is not;
// an entry still registered there is a contributor that has not moved,
// and is told so once rather than silently ignored.
const legacyTabs = registry.category("app_builder.console_tabs");
let warnedLegacy = false;

export function warnLegacyTabs() {
    if (warnedLegacy) {
        return;
    }
    warnedLegacy = true;
    const keys = legacyTabs.getEntries().map(([key]) => key);
    if (keys.length) {
        console.warn(
            "app_builder.console_tabs is no longer read by the console; register a pane in " +
                "app_builder.panes instead: " +
                keys.join(", ")
        );
    }
}

/** The resolvers a data-only entry needs: set by the modules that own them. */
const resolvers = {
    record: null, // (entry) => {Component, sidebar, makeModel}
    flow: null, // (entry) => {Component, sidebar, makeModel}
};

export function setPaneResolver(kind, resolve) {
    resolvers[kind] = resolve;
}

/** The entry with its component, sidebar and model factory filled in. */
export function resolvePane(key) {
    if (!paneRegistry.contains(key)) {
        throw new Error(`app_builder.panes has no "${key}"`);
    }
    const entry = { key, ...paneRegistry.get(key) };
    if (entry.Component) {
        return { sidebar: null, makeModel: null, ...entry };
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

/**
 * Whether `entry` can be shown with what the shell has in hand. An
 * entry's own `isAvailable` decides entirely when it has one; the scope
 * rule is the default.
 */
export function paneAvailable(entry, ctx) {
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

/**
 * The tabs the bar lists, in sequence, each with `available` and the
 * reason it is dimmed: a tab that needs a model is shown and disabled,
 * not hidden, so the bar reads the same on every pane.
 */
export function paneTabs(ctx) {
    return paneRegistry
        .getEntries()
        .map(([key, entry]) => ({ key, ...entry }))
        .filter((entry) => entry.tab !== false && !entry.flow)
        .map((entry) => {
            const available = paneAvailable(entry, ctx);
            let reason = "";
            if (!available && entry.scope === "model" && !ctx.modelName) {
                reason = _t("Choose a model first — from the crumb, or open any view with Studio.");
            } else if (!available && entry.scope === "view") {
                reason = _t("Open a view first.");
            } else if (!available) {
                reason = _t("Not available here.");
            }
            return { ...entry, available, reason };
        });
}

/** The flows on offer as tiles: panes with no tab, that apply here. */
export function paneFlows(ctx) {
    return paneRegistry
        .getEntries()
        .map(([key, entry]) => ({ key, ...entry }))
        .filter((entry) => entry.tab === false || entry.flow)
        .filter((entry) => paneAvailable(entry, ctx));
}

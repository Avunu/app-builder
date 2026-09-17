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

import type { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import type { PaneContext, PaneEntry, PaneModel, PaneRegistration } from "../types";

// `registry.category()`'s own signature (`web/static/src/core/registry.js`)
// is `category<K extends keyof GetRegistryCategories<T> & string>(subcategory:
// K): Registry<GetRegistryCategories<T>[K]>` -- a category name that is not a
// key of `GlobalRegistryCategories` (`registries.d.ts`) cannot be passed at
// all, let alone typed on the far side. Odoo's own `views`/`fields`
// categories get this via `views_registry.d.ts`/`fields_registry.d.ts`
// (both in `tsconfig.json`'s `include`); `app_builder.panes` and
// `app_builder.console_tabs` are ours, declared nowhere yet -- Phase 2c's
// planned `console/odoo.ts` facade is where TYPING.md says this
// declaration eventually belongs, but that file does not exist yet, and
// this is the one file that creates both categories, so it is declared
// here for now rather than leaving `registry.category("app_builder.panes")`
// unable to compile at all. `PaneRegistration` (not `PaneEntry`): this
// names the *stored* shape, before `resolvePane` merges in `key`.
declare module "registries" {
    interface GlobalRegistryCategories {
        "app_builder.panes": PaneRegistration;
        // Nothing registers here any more (`warnLegacyTabs` below exists
        // to say so) -- no real shape to name, and nothing here reads
        // more than an entry's own key.
        "app_builder.console_tabs": unknown;
    }
}

export const paneRegistry = registry.category("app_builder.panes");

// The tab registry the panes replace. Its only verb was `open(env, ctx)`,
// a `doAction` out of the console, which is exactly what a pane is not;
// an entry still registered there is a contributor that has not moved,
// and is told so once rather than silently ignored.
const legacyTabs = registry.category("app_builder.console_tabs");
let warnedLegacy = false;

export function warnLegacyTabs(): void {
    if (warnedLegacy) {
        return;
    }
    warnedLegacy = true;
    const keys = legacyTabs.getEntries().map(([key]) => key);
    if (keys.length) {
        console.warn(
            "app_builder.console_tabs is no longer read by the console; register a pane in " +
                "app_builder.panes instead: " +
                keys.join(", "),
        );
    }
}

/**
 * What a resolver (`setPaneResolver("record" | "flow", ...)`) must add to
 * turn a data-only entry into a renderable one. Traced from both real
 * resolvers (`record_pane.js`, `flow.js`), which each return exactly
 * these three keys and nothing else -- a concrete triad, not the vaguer
 * `Partial<PaneEntry>` the module docstring's own shorthand above ("a
 * custom pane: Component, sidebar ..., makeModel(shell)") might suggest
 * on its own.
 */
export interface PaneResolverResult {
    Component: typeof Component;
    sidebar: typeof Component | null;
    makeModel: (shell: unknown) => PaneModel;
}

/**
 * A resolver: given the raw registered entry (`surface`/`flow` and
 * whatever else the addon that owns it put there, plus `key`), returns
 * the Component/sidebar/model triad `resolvePane` merges on top of it.
 */
export type PaneResolver = (entry: PaneEntry) => PaneResolverResult;

/** The two kinds of data-only entry a resolver exists for. */
export type PaneResolverKind = "record" | "flow";

/** The resolvers a data-only entry needs: set by the modules that own them. */
const resolvers: Record<PaneResolverKind, PaneResolver | null> = {
    record: null,
    flow: null,
};

export function setPaneResolver(kind: PaneResolverKind, resolve: PaneResolver): void {
    resolvers[kind] = resolve;
}

/** The entry with its component, sidebar and model factory filled in. */
export function resolvePane(key: string): PaneEntry {
    if (!paneRegistry.contains(key)) {
        throw new Error(`app_builder.panes has no "${key}"`);
    }
    // `Registry.get`'s JSDoc leaves `defaultValue` undocumented (so TS
    // infers it as required) -- the same trap `canvas_views.ts`'s own
    // `Registry.get` call hit first, and the same fix: `key` is already
    // known to exist (`contains`, just above), so this keeps the call at
    // one argument rather than passing an explicit `undefined` that
    // would suppress the real "missing key" throw, and `.call(paneRegistry,
    // key)` rather than a bare reference, since `get` reads
    // `this.content` internally and an unbound reference would call it
    // with no `this` at all.
    const registered = (paneRegistry.get as (key: string) => PaneRegistration).call(
        paneRegistry,
        key,
    );
    const entry: PaneEntry = { key, ...registered };
    if (entry.Component) {
        // A custom pane may have no sidebar or no model of its own; the
        // pre-conversion JS filled both in with a single
        // `{ sidebar: null, makeModel: null, ...entry }` spread. Written
        // here as two `??` fills on a *single* source instead: spreading
        // two objects that disagree on whether `null` belongs to a
        // key's type (the literal default says yes, `entry`'s own
        // optional `sidebar`/`makeModel` say "maybe, if present") would
        // leave the result's type to however TS resolves that
        // ambiguity, which could not be checked against a real compiler
        // here (drafting is read-only). `entry.sidebar ?? null` and
        // `entry.makeModel ?? null` are each a single, unambiguous
        // expression instead, giving the exact same value on both keys
        // for every real entry without depending on that inference.
        return {
            ...entry,
            sidebar: entry.sidebar ?? null,
            makeModel: entry.makeModel ?? null,
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

/**
 * Whether `entry` can be shown with what the shell has in hand. An
 * entry's own `isAvailable` decides entirely when it has one; the scope
 * rule is the default.
 */
export function paneAvailable(entry: PaneEntry, ctx: PaneContext): boolean {
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

/** A tab the bar lists: a resolved entry plus whether it can be opened
 * right now and, when it cannot, the sentence that says why (`top_bar.js`'s
 * own reads: `tab.key`, `tab.available`, `tab.active`, `tab.label`,
 * `tab.icon`). */
export interface PaneTab extends PaneEntry {
    available: boolean;
    reason: string;
}

/**
 * The tabs the bar lists, in sequence, each with `available` and the
 * reason it is dimmed: a tab that needs a model is shown and disabled,
 * not hidden, so the bar reads the same on every pane.
 */
export function paneTabs(ctx: PaneContext): PaneTab[] {
    return paneRegistry
        .getEntries()
        .map(([key, entry]): PaneEntry => ({ key, ...entry }))
        .filter((entry) => entry.tab !== false && !entry.flow)
        .map((entry): PaneTab => {
            const available = paneAvailable(entry, ctx);
            let reason = "";
            if (!available && entry.scope === "model" && !ctx.modelName) {
                // `_t()` (`@web/core/l10n/translation.js`) returns
                // `string | Markup | LazyTranslatedString`, never a bare
                // `string` -- the same reason `outline_tree.ts`/
                // `outline_zones.ts` wrap it in `String(...)` rather than
                // assigning it straight into a `string`-typed variable.
                reason = String(
                    _t("Choose a model first — from the crumb, or open any view with Studio."),
                );
            } else if (!available && entry.scope === "view") {
                reason = String(_t("Open a view first."));
            } else if (!available) {
                reason = String(_t("Not available here."));
            }
            return { ...entry, available, reason };
        });
}

/** The flows on offer as tiles: panes with no tab, that apply here. */
export function paneFlows(ctx: PaneContext): PaneEntry[] {
    return paneRegistry
        .getEntries()
        .map(([key, entry]): PaneEntry => ({ key, ...entry }))
        .filter((entry) => entry.tab === false || entry.flow)
        .filter((entry) => paneAvailable(entry, ctx));
}

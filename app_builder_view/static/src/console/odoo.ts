/** @odoo-module **/
/**
 * The framework boundary, fenced in one place (TYPING.md, Phase 2c).
 *
 * Every service the console reads through `useService`, typed once here
 * rather than through Odoo's own auto-generated `@types/services.d.ts` --
 * that file exists specifically to `import` real service *implementation*
 * modules and take their type with `typeof`, which pulls the entire
 * webclient into the program just to type one service (TYPING.md's own
 * "Known traps" has the full account). Each interface below names only
 * what a real file in this tree calls on that service -- grep the whole
 * tree for `useService("...")` before adding a fifth service here, and
 * grep every real call site of a method before widening one that already
 * is.
 *
 * Also the one place `app_builder.panes`/`app_builder.console_tabs` are
 * declared into Odoo's own `GlobalRegistryCategories` (`registries.d.ts`,
 * the same mechanism `views_registry.d.ts`/`fields_registry.d.ts` use for
 * core's own categories) -- moved here from `shell/pane_registry.ts`,
 * which carried the identical declaration only because this file did not
 * exist yet when it needed `registry.category("app_builder.panes")` to
 * compile at all.
 *
 * Not here, and deliberately so:
 *  - `rpc` (`@web/core/network/rpc`): no real file in this tree calls it
 *    directly -- every server round trip goes through `orm.call`
 *    (`OrmService`, below) instead, and `compat.ts`'s own mention of
 *    `core/network/rpc.js` is about that module's cache-invalidation bus,
 *    not a call site. Typing a facade nothing calls would be typing
 *    ahead of a reader this migration has consistently avoided elsewhere;
 *    add it here the day a real file needs it.
 *  - A stringifying wrapper around `_t`. Every already-converted file
 *    that needs a plain `string` already writes `String(_t(...))` at the
 *    point it is needed (`console_model.ts`, `draft_model.ts`,
 *    `shell_model.ts`, `outline_tree.ts`, `zones.ts`, `pane_registry.ts`,
 *    and more) -- a real, working, established pattern. A facade that
 *    eagerly stringified by default would be the wrong default for a
 *    file that instead wants to hand a *lazy* translated value to a
 *    component prop, so Owl's own reactivity can re-render it on a
 *    language change; nothing in this tree does that yet, but inventing
 *    an eager-only wrapper now would quietly foreclose it. Import `_t`
 *    from `@web/core/l10n/translation` directly, same as every file so
 *    far, and reach for `String(...)` at the point a plain string is
 *    actually needed.
 */

import type { Component } from "@odoo/owl";
import { useService as useServiceUntyped } from "@web/core/utils/hooks";
import type { NotificationService, OrmService, PaneRegistration } from "./types";

declare module "registries" {
    interface GlobalRegistryCategories {
        "app_builder.panes": PaneRegistration;
        // Nothing registers here any more (`pane_registry.ts`'s own
        // `warnLegacyTabs` exists to say so) -- no real shape to name,
        // and nothing here reads more than an entry's own key.
        "app_builder.console_tabs": unknown;
    }
}

// -- dialog -----------------------------------------------------------
//
// `@web/core/dialog/dialog_service.js` (the service, `useService("dialog")`,
// called in nine real files so far -- `apply_dialog.js`, `top_bar.js`,
// `views_pane.js`, `changes_pane.js`, `record_pane.js`,
// `sidebar/{view_tab,properties_tab,outline}.js`) and
// `@web/core/dialog/dialog.js` (the component every one of them renders
// or wraps).

/** `DialogServiceInterfaceAddOptions`, transcribed from the vendor's own
 * JSDoc typedef (`dialog_service.js`). */
export interface DialogServiceAddOptions {
    onClose?(): void;
}

/**
 * `dialog_service.js`'s own `DialogServiceInterface` typedef names `add`'s
 * `props` parameter as a bare `{}` -- any object, uncorrelated with
 * whichever `Component` is passed. Widened here to a generic that ties
 * the two together instead: `Component<P>`'s own constructor takes
 * `props: P`, so passing a props object that does not match the dialog
 * class actually given is now a real compile error, not just at runtime
 * (Owl's own prop validation, which still runs regardless). Confirmed
 * with a standalone probe before relying on it -- a real improvement
 * over the vendor's own looser typing, not a guess.
 */
export interface DialogService {
    // `...args: unknown[]` looks like the obvious constructor signature
    // here, but does not actually work: TS cannot unify a rest parameter
    // typed `unknown[]` with a real constructor's own specific first
    // parameter (`props: P`) the way it can with `any[]`, which turns
    // this check off for the constructor's *parameter list* specifically
    // while still fully checking `props` against `P` at the call site --
    // confirmed by testing both forms for real: `unknown[]` rejects the
    // valid call this type exists to accept.
    add<P extends object>(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        dialogClass: new (...args: any[]) => Component<P>,
        props: P,
        options?: DialogServiceAddOptions,
    ): () => void;
    closeAll(): void;
}

/**
 * `@web/core/dialog/dialog.js`'s own `static props` schema, transcribed
 * directly from the real, stable vendor component rather than guessed --
 * unlike this addon's own wire shapes, a fixed vendor component's props
 * carry none of the "guessed wrong" risk typing ahead of a reader
 * otherwise has here, and nine real files render or wrap this one
 * component, so one shared shape is worth having before the first of
 * them converts rather than re-derived nine times.
 */
export interface DialogProps {
    contentClass?: string;
    bodyClass?: string;
    fullscreen?: boolean;
    footer?: boolean;
    header?: boolean;
    size?: "sm" | "md" | "lg" | "xl" | "fs" | "fullscreen";
    technical?: boolean;
    title?: string;
    modalRef?: (el: HTMLElement | null) => void;
    slots: {
        default: unknown;
        header?: unknown;
        footer?: unknown;
    };
    withBodyPadding?: boolean;
    onExpand?(): void;
}

// -- action -------------------------------------------------------------
//
// `@web/core/actions/action_service.js`, `useService("action")`, called
// in two real files (`cog_menu_item.js`, `systray_item.js`).

/**
 * As much of `doAction`'s real target shape (`action_service.js`'s own
 * `ActionRequest`/`ActionDescription`) as both real callers construct: a
 * plain `ir.actions.client` descriptor, never a numeric id, an xml id or
 * a tag string on its own (`ActionRequest`'s other members). Narrow it
 * further, or add the other `ActionRequest` variants, the day a file
 * needs one.
 */
export interface ActionDescription {
    type: string;
    tag?: string;
    name?: string;
    target?: string;
    params?: Record<string, unknown>;
}

/** The one field both real callers read off `currentController`'s real,
 * much larger shape (`action_service.js`'s internal `Controller`):
 * `.action.res_model` and `.currentState.resId`. */
export interface ActionController {
    action: { res_model?: string; [key: string]: unknown };
    currentState?: { resId?: number | false };
}

export interface ActionService {
    doAction(action: ActionDescription, options?: Record<string, unknown>): Promise<unknown>;
    readonly currentController: ActionController | undefined;
}

// -- useService -----------------------------------------------------------

/**
 * Odoo's own `useService` (`@web/core/utils/hooks.js`) is generic over
 * `keyof import("services").ServiceFactories` -- the same
 * `@types/services.d.ts` cascade this file's own docstring explains this
 * whole module exists to avoid pulling in. Overloaded here instead, one
 * signature per service this tree's real files actually call by name;
 * `orm`/`notification` reuse the facades `types.ts` already carries for
 * `DraftModel`/`ConsoleModel`/every pane model, so a component and the
 * model it hands services to agree on the same shape.
 */
export function useService(name: "orm"): OrmService;
export function useService(name: "notification"): NotificationService;
export function useService(name: "dialog"): DialogService;
export function useService(name: "action"): ActionService;
export function useService(name: string): unknown {
    return useServiceUntyped(name);
}

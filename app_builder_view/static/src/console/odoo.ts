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
 *  - `_t`. It has its own module, `l10n.ts` (typed, not stringifying),
 *    so the Owl-free modules can import it without pulling in this
 *    file's Owl hooks and dialog component. `String(_t(...))` where a
 *    primitive is needed -- but never while a module body is running:
 *    translations are not loaded yet, and `String()` of a lazy value
 *    then throws out of `odoo.define`, aborting the whole asset bundle.
 */

import type { Component } from "@odoo/owl";
import { user as userUntyped } from "@web/core/user";
import { useService as useServiceUntyped } from "@web/core/utils/hooks";
import type { NotificationService, OrmService, PaneRegistration } from "./types";

declare module "registries" {
    interface GlobalRegistryCategories {
        "app_builder.panes": PaneRegistration;
        // Nothing registers here any more (`pane_registry.ts`'s own
        // `warnLegacyTabs` exists to say so) -- no real shape to name,
        // and nothing here reads more than an entry's own key.
        "app_builder.console_tabs": unknown;
        /** `field_editor_fallback.ts`'s own fallback, and
         * `app_builder_model`'s full popover (`console_items.js`) --
         * whichever registers first wins (`fieldEditorComponent()`'s own
         * `entries[0]`). Every registrant is a plain component class
         * taking `FieldEditorProps` (`types.ts`); typed as the bare
         * class (never instantiated or read for its own `Props` by this
         * registry itself, only passed on to `usePopover`), the same way
         * core's own `DialogsRegistryItemShape` types a category that
         * only ever stores component classes. */
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "app_builder.field_editor": typeof Component<any, any>;
        /** The component the Views pane renders for a view's
         * `editable_as` (`panes/views_pane.ts`'s own `canvasComponent`) --
         * registered into by `canvas.ts` (`"canvas"`),
         * `canvases/search_lists_canvas.ts` (`"search_lists"`) and
         * `app_builder_report`'s own `report_canvas.ts` (`"report"`). A
         * plain component-class registry, taken only for
         * identity (`canvasRegistry.contains`/`.get`, compared against a
         * known class) and handed straight to the template's
         * `t-component`, the same shape as `app_builder.field_editor`/
         * `cogMenu`/`systray`. */
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        "app_builder.canvas": typeof Component<any, any>;
        cogMenu: CogMenuItem;
        systray: SystrayRegistryItemShape;
        // Odoo's own category, not ours -- see the "-- view widgets --"
        // section below for why it is transcribed here instead of
        // imported from the real vendor `.d.ts`.
        view_widgets: ViewWidgetsRegistryItemShape;
        // Odoo's own category (`console.ts` is the first real registrant
        // in this tree) -- see the "-- actions registry --" section below.
        actions: ActionsRegistryItemShape;
        // Odoo's own category, registered into by every tour file under
        // `static/tests/tours/` -- see the "-- tours --" section below.
        "web_tour.tours": ToursRegistryShape;
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

// -- confirmation dialog ----------------------------------------------------
//
// `@web/core/confirmation_dialog/confirmation_dialog.js`, rendered via
// `DialogService.add` by two real files (`apply_dialog.ts`, `sidebar/
// remove_flow.ts`). Re-exported here, typed, rather than imported directly
// from the vendor module: this project builds with `checkJs: false`
// (`tsconfig.json`'s own comment on why), and a plain, untyped `.js` class
// extending a generic TS class with no `@extends {Component<Props>}`
// JSDoc does not carry its base class's members into TS's inferred type
// under that setting -- confirmed with a standalone probe (`inst.render()`/
// `inst.props` both fail to resolve on `InstanceType<typeof
// ConfirmationDialog>` the same way they do not on an identical class
// declared directly in a `.ts` file). `DialogService.add`'s own generic
// constructor check then reports the vendor class as "missing props, env,
// __owl__, render" against *any* `Component<P>` instantiation, `P = any`
// included -- not fixable by widening `P`, since the vendor class itself
// is what fails the check. Cast once here instead of at every call site,
// the same "narrow, hand-traced facade over a vendor boundary" move this
// file already makes for `OrmService`/`NotificationService`/`ActionService`.

import { ConfirmationDialog as ConfirmationDialogImpl } from "@web/core/confirmation_dialog/confirmation_dialog";

/** What a real caller supplies to `dialog.add(ConfirmationDialog, {...})`
 * -- `close` is not among them: the dialog service injects it itself
 * before constructing (`dialog_service.js`), never supplied by a caller
 * of `DialogService.add`. `title`/`body`/`confirmLabel`/`cancelLabel` are
 * `_t(...)`'s own lazy return type: the vendor's own `title` validator
 * accepts `typeof m === "string" || typeof m.toString === "function"`
 * (a lazy translated value), and both real callers pass `_t(...)` for
 * `body` too despite its schema's plainer-looking `{ type: String }` --
 * Owl's own prop validation does not enforce that distinction at
 * runtime. */
export interface ConfirmationDialogProps {
    title?: unknown;
    body?: unknown;
    confirm?: () => void;
    confirmLabel?: unknown;
    confirmClass?: string;
    cancel?: () => void;
    cancelLabel?: unknown;
    dismiss?: () => void;
}

export const ConfirmationDialog = ConfirmationDialogImpl as unknown as new (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ...args: any[]
) => Component<ConfirmationDialogProps>;

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

/**
 * `currentController`'s real shape (`action_service.js`'s own `Controller`,
 * built by `_makeController` from whichever `_execute*` function ran --
 * far larger than what any one file here reads). Widened past the
 * original Phase 2c cut -- which named only `.action.res_model` and
 * `.currentState.resId`, the two fields `cog_menu_item.js` reads -- to
 * also cover `systray_item.ts`'s own reads, traced against the same real
 * file: `.virtual` (`_controllersFromState`, a restored-from-router
 * placeholder whose `action`/`props` may still be empty objects) and
 * `.props.resModel`/`.props.type`/`.props.resId` plus `.action.type`/
 * `.action.views`/`.action.id` (`_getViewInfo`, called from
 * `_createController` for every `ir.actions.act_window` controller: the
 * loaded action record is assigned whole onto `controller.action`, not
 * copied, and `resModel`/`type` are written onto `controller.props`
 * unconditionally for a real window-action controller). `action.views`
 * is the action's own `[view_id, view_type]` pair list, the same shape
 * `_getViewInfo`'s own `action.views.some(...)` reads it as elsewhere in
 * that file.
 */
export interface ActionController {
    /** Set only on a restored-from-router placeholder
     * (`_controllersFromState`), whose `action`/`props` may still be
     * empty objects -- every real caller bails out on this before
     * reading anything else off the controller. */
    virtual?: boolean;
    action: {
        type?: string;
        id?: number | false;
        views?: Array<[number | false, string]>;
        res_model?: string;
        [key: string]: unknown;
    };
    props?: {
        resModel?: string;
        type?: string;
        resId?: number | false;
        [key: string]: unknown;
    };
    currentState?: { resId?: number | false };
}

export interface ActionService {
    /** `action_service.js`'s own real first-parameter type is `ActionId
     * | ActionXMLId | ActionTag | ActionDescription` (its own
     * `ActionRequest` typedef); widened here from `ActionDescription`
     * alone to also cover `number` (a plain action id) once `shell.ts`
     * needed it (`_loadAction`'s own `typeof actionRequest === "number"`
     * branch) -- the `string` variants stay unadded until a real caller
     * needs one, per this interface's own original note. */
    doAction(
        action: ActionDescription | number,
        options?: Record<string, unknown>,
    ): Promise<unknown>;
    /** `action_service.js`'s own `restore(jsId)` -- `jsId` genuinely
     * optional (`if (!jsId) { ... }` falls back to the previous
     * controller in the stack), confirmed against the real source
     * rather than guessed. */
    restore(jsId?: string): Promise<unknown>;
    readonly currentController: ActionController | undefined;
}

// -- cog menu -------------------------------------------------------------
//
// `registry.category("cogMenu")`, Odoo's own category (`cog_menu_item.ts`).

/**
 * The slice of Odoo's own per-view `env.config` this addon actually reads
 * (`cog_menu_item.ts`, `app_builder_ui/static/src/automations_menu_item.js`).
 * Traced to the real construction (`@web/views/view.js:148`) rather than
 * guessed: `actionId` is the one member of that file's own `Config`
 * typedef this addon touches, always present (`getDefaultConfig()`
 * defaults it to `false`). `viewId`/`viewType` are **not** part of the
 * formal `Config` typedef at all -- `View#loadView` adds both
 * dynamically, via `Object.assign(this.env.config, {..., viewId:
 * viewDescription.id, viewType: type, ...})`, inside `onWillStart`. Typed
 * as always-present (not optional) because Owl always resolves a
 * parent's `onWillStart` before any child -- a cog menu item included --
 * starts rendering, so by the time either `isDisplayed` or a real click
 * handler runs, that assignment has already happened. `resModel` is the
 * one genuinely optional member: grepping every `config.resModel =`/
 * `config = {...resModel...}` site under `web/static/src` turns up none
 * -- `view.js` never writes it onto `config` itself; `cog_menu_item.ts`'s
 * own `onEdit` falls back to the current controller's action for exactly
 * this reason. */
export interface ViewEnvConfig {
    resModel?: string;
    viewId: number | false;
    viewType: string;
    actionId: number | false;
}

export interface ViewEnv {
    config: ViewEnvConfig;
}

/**
 * `registry.category("cogMenu")`'s real item shape. Declared here (rather
 * than reused from OCB's own `@types/registries/registries.d.ts`) because
 * that file is deliberately outside this repo's `tsconfig.json` `include`
 * (cherry-picked, not a blanket glob), and because its
 * `isDisplayed?: (env: OdooEnv) => boolean` does not match how every real
 * registration in this tree actually implements it: an `async` function,
 * so really `Promise<boolean>` -- the same class of JSDoc-vs-runtime gap
 * TYPING.md's "Known traps" already tracks for
 * `Registry.get`/`queryFirst`/`useDragAndDrop`/`moveTo`.
 */
export interface CogMenuItem {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Component: typeof Component<any, any>;
    groupNumber: number;
    isDisplayed?: (env: ViewEnv) => boolean | Promise<boolean>;
}

// -- systray ----------------------------------------------------------------
//
// `registry.category("systray")`, Odoo's own category (`systray_item.ts`).

export interface SystrayRegistryItemShape {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Component: typeof Component<any, any>;
    isDisplayed?: (env: unknown) => boolean;
}

// -- view widgets ---------------------------------------------------------
//
// `@web/core/registry`'s `"view_widgets"` category (registered into by
// `pending_widget.ts`'s own `<widget name="app_builder_pending">`), and the
// per-node info `Widget` (`views/widgets/widget.js`) hands a registered
// widget's `extractProps`. Transcribed from the real vendor
// `@types/registries/view_widgets_registry.d.ts` -- not in tsconfig.json's
// `include` (unlike its `fields_registry.d.ts`/`views_registry.d.ts`
// siblings) -- with one correction to that vendor file's own imprecise
// `extractProps` parameter naming: the real runtime call
// (`views/widgets/widget.js`'s `widgetProps` getter,
// `this.widget.extractProps(widgetInfo, dynamicInfo)`) passes the *full*
// per-node info object, not its `options` sub-field alone as the vendor
// `.d.ts`'s own parameter name ("options") implies.

/** The second argument every registered widget's `extractProps` receives:
 * only `readonly`, resolved from the node's own modifiers, unlike
 * `StaticWidgetInfo`'s raw, unevaluated `attrs.readonly`. */
export interface DynamicWidgetInfo {
    readonly: boolean;
}

/** One `<widget>` arch node, as `Widget.parseWidgetNode` (`widget.js`)
 * always builds it: `options` is that node's own `options="{...}"`
 * attribute, evaluated -- a plain `object`, since its real shape is
 * entirely up to whichever widget declares it (a caller narrows it, the
 * way `pending_widget.ts`'s own `PendingWidgetInfo` does). */
export interface StaticWidgetInfo {
    attrs: Record<string, string>;
    name: string;
    options: object;
    widget: ViewWidgetsRegistryItemShape;
}

/** A `"view_widgets"` registry entry. */
export interface ViewWidgetsRegistryItemShape {
    additionalClasses?: string[];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: typeof Component<any, any>;
    extractProps?(options: StaticWidgetInfo, dynamicInfo: DynamicWidgetInfo): object;
    fieldDependencies?:
        Partial<StaticWidgetInfo>[] | ((baseInfo: StaticWidgetInfo) => Partial<StaticWidgetInfo>[]);
}

// -- actions registry -------------------------------------------------------
//
// `registry.category("actions")` -- core Odoo's own category, registered
// into by `console.ts` (`StudioConsole`, under two tags: the console's
// own and a legacy one kept for old bookmarks/callers). Transcribed from
// the real vendor `@types/registries/registries.d.ts` -- not in
// `tsconfig.json`'s `include` (unlike its `fields_registry.d.ts`/
// `views_registry.d.ts` siblings; the same reason `cogMenu`/`systray`/
// `view_widgets` are transcribed here rather than imported). A real
// registrant is either a plain handler function or a component class
// (`StudioConsole` is the latter); `target`/`path`/`displayName` are the
// action-framework's own convention, read off the registered class/
// function by `action_service.js`, matching `shell.ts`'s own doc comment
// on why `static target`/`static path` need no `override` (neither is a
// `Component` class-body member). `target`'s own vendor type (`ActionMode`)
// could not be found declared anywhere in the vendor's own `@types` tree
// (a loose reference in the vendor `.d.ts` itself); typed as the plain
// `string` `shell.ts`'s own `static target = "fullscreen"` actually is,
// rather than a vendor type this repo cannot locate to transcribe.

/** A registrant is either a plain handler function (given the console's
 * `env` and an `ActionDescription`) or a component class -- no real
 * registration in this tree uses the function arm (`StudioConsole` is a
 * component), but the vendor category accepts both, so both are named
 * here rather than narrowed to just this addon's own usage, the same
 * "transcribe the whole real shape" choice already made for `cogMenu`/
 * `systray`/`view_widgets`. */
export type ActionsRegistryItemShape = (
    | ((env: unknown, action: ActionDescription) => void)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    | typeof Component<any, any>
) & {
    displayName?: string;
    path?: string;
    target?: string;
};

// -- tours --------------------------------------------------------------
//
// `registry.category("web_tour.tours")` -- core Odoo's own category,
// registered into by every tour file under this addon suite's own
// `static/tests/tours/`. Transcribed from the real vendor
// `web_tour/static/src/@types/registries.d.ts` -- not in `tsconfig.json`'s
// `include` (the same reason `cogMenu`/`systray`/`view_widgets`/`actions`
// are transcribed here too) -- with two corrections to that file's own
// account, confirmed against the real running tour service rather than
// guessed:
//
//  - `url` is declared required (`url: string`) there, but every tour in
//    this addon suite omits it (`console_tour.js`'s own comment:
//    "Deliberately no `url`: ... a url here would override the one
//    `start_tour` passes"), and the real consumer
//    (`tour_service.js`'s own `if (tour.url && tourConfig.startUrl !=
//    tour.url && tourConfig.redirect)`) treats it as genuinely optional --
//    the same class of JSDoc-vs-runtime gap already tracked for
//    `Registry.get`/`queryFirst`/`Domain.toList`.
//  - `run`'s function arm is typed `() => void | Promise<void>` there,
//    with no `this` and no parameter -- but the real call site
//    (`tour_step_automatic.js`'s own `this.run.call({anchor:
//    this.element}, actionHelper)`) binds `this` to `{anchor: Element}`
//    and passes one argument (a real `TourHelpers` instance, left
//    `unknown` here: no tour in this tree reads it). Several real tours
//    read `this.anchor` inside a `run` function.
//  - `run` is declared required there too, but a step that is only a
//    wait-for-trigger (no action of its own -- just confirming something
//    is on screen before the next step) omits it entirely in real tours
//    in this tree; widened to optional. `content` stays required: every
//    real step in this tree sets one.

export interface TourStep {
    content: string;
    trigger: string;
    run?: string | ((this: { anchor: Element }, helpers: unknown) => void | Promise<void>);
}

export interface ToursRegistryShape {
    test?: boolean;
    url?: string;
    steps(): TourStep[];
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
    // `useService` is untyped vendor JS whose generic JSDoc collapses to the
    // `error` type; assigning it to `unknown` is the honest boundary.
    const service: unknown = useServiceUntyped(name);
    return service;
}

// -- user -----------------------------------------------------------------

/**
 * `user` (`@web/core/user`), narrowly: what this tree calls on it.
 * `hasGroup` is `groupCache.read(group, this.context)` in `user.js`, and
 * `Cache.read` (`core/utils/cache.js`) is untyped JS returning whatever
 * `getGroupCacheValue` produced -- an `rpc` promise resolving to a
 * boolean (`user.js`'s `groupCache`, pre-seeded with
 * `Promise.resolve(isInternalUser)`) -- so `Promise<boolean>`, which the
 * checker cannot see through `Cache`'s untyped `read`.
 */
export interface UserFacade {
    hasGroup(group: string): Promise<boolean>;
}

/** The same `user` object, typed. Nothing changes at runtime. */
export const user: UserFacade = userUntyped;

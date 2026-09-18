/** @odoo-module **/
/**
 * The studio console: one bar across the top, and under it whichever
 * pane is on -- its content on the right and, when it has one, its
 * sidebar on the left.
 *
 * Full-screen, because building a screen is not something done in the
 * corner of another one: `static target = "fullscreen"` hides the navbar
 * in 18, 19 and master however the action was launched. `static path`
 * gives it a URL of its own, `/odoo/studio`, and what the shell holds --
 * the package, the model, the pane, the view, a record -- rides on that
 * URL through `updateActionState`, so a reload lands where it left off.
 *
 * Every RPC and every piece of state lives in `shell_model.ts` and the
 * panes' own models; this component wires the parts together and answers
 * Close.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ResizablePanel } from "@web/core/resizable_panel/resizable_panel";
import * as compat from "../compat";
import { TopBar } from "../top_bar";
import type {
    FieldService,
    NotificationService,
    OdooRpcError,
    OrmService,
    PaneEntry,
    PaneModel,
} from "../types";
import { useService } from "../odoo";
import type { ActionController, ActionService } from "../odoo";
import { StudioShell } from "./shell_model";
import type { ShellUrlState } from "./shell_model";

/**
 * What Odoo's action framework hands every `ir.actions.client` component
 * (`action_service.js`'s own `_getViewInfo`/`_createController`, the same
 * real construction `odoo.ts`'s own `ActionController` traces). Real
 * action objects carry far more (`id`, `tag`, `target`, `res_model`, ...);
 * `context`/`params` are the only two this file reads (`get params()`,
 * below), so nothing else is named.
 */
interface ActionProps {
    context?: Record<string, unknown>;
    params?: Record<string, unknown>;
}

/**
 * `{action, updateActionState}`, as `static props` below validates it
 * (`"*": true`, the widest schema Owl has -- every real caller of an
 * `ir.actions.client` component hands over far more than this file reads,
 * and there is no fixed shape to name for the rest). `updateActionState`
 * is the action service's own per-controller state pusher
 * (`action_service.js`), handed to every registered action component so
 * a reload of the console's own URL comes back through `action.params`
 * (`StudioShell`'s own docstring, and `get params()` below).
 */
export interface Props {
    action?: ActionProps;
    updateActionState?: (state: ShellUrlState) => void;
}

/** The one piece of the action framework's own `env.config` this file
 * touches (`action_service.js:_updateUI`, `controller.config.setDisplayName`/
 * `.breadcrumbs`) -- distinct from `odoo.ts`'s own `ViewEnvConfig`, which
 * is a *view's* `env.config` (`view.js`'s own, narrower slice), not an
 * action component's. `setDisplayName`'s own real signature takes the
 * plain `string` it assigns straight to `controller.displayName` and
 * hands to `title.setParts({action: ...})`. */
interface ConsoleEnvConfig {
    breadcrumbs?: unknown[];
    setDisplayName?: (title: string) => void;
}

/** The slice of Owl's `env` this component reads or hands onward: the
 * three services `StudioShell`'s own constructor needs (`shell_model.ts`'s
 * `ShellEnv`), `bus.trigger` (`compat.clearViewCaches`), and `config`
 * (above). */
interface ConsoleEnv {
    services: {
        orm: OrmService;
        notification: NotificationService;
        field: FieldService;
    };
    bus: { trigger: (name: string) => void };
    config?: ConsoleEnvConfig;
}

/** `useState({ready: false, error: ""})`'s own shape. `error` stays
 * `string | undefined`, not plain `string`: `onWillStart`'s own catch
 * branch (below) sets it straight from an RPC error's own `data.message`,
 * which is itself optional (`OdooRpcError`, `../types.ts`) -- the original
 * JS already relied on that possibly being `undefined` at runtime rather
 * than falling back to an empty string, and this keeps that behavior
 * rather than quietly changing it. */
interface ConsoleState {
    ready: boolean;
    error: string | undefined;
}

export class StudioConsole extends Component<Props, ConsoleEnv> {
    // `template`/`props` both live on Owl's own `Component` class body, so
    // `noImplicitOverride` requires `override` here; `components`/`target`/
    // `path` do not (TYPING.md's own "Known traps" -- `components` is not
    // a `Component` instance/static member at all, and `target`/`path` are
    // this addon's/the action framework's own convention, read off the
    // registered class by `action_service.js`, never declared on `Component`
    // itself).
    static override template = "app_builder_view.StudioConsole";
    static components = { ResizablePanel, TopBar };
    // `as const`, not a plain object literal: without it TS widens `true`
    // to `boolean`, which is not assignable to `BaseType` (`true | "*" |
    // {new (...): any}`, `validation.d.ts`) -- the literal `true` itself
    // is a valid `BaseType`, only the widened type is not. Purely a type
    // annotation; the emitted `.js` for an object literal is identical
    // either way.
    static override props = { "*": true } as const;
    static target = "fullscreen";
    static path = "studio";

    // Assigned in `setup()`, not a field initializer or a constructor this
    // class writes its own -- `declare` adds a compile-time type only, so
    // the emitted `.js` is unchanged and `strictPropertyInitialization`
    // does not ask for an assignment it cannot see (the same pattern
    // `top_bar.ts`/`apply_dialog.ts` already use).
    declare action: ActionService;
    declare shell: StudioShell;
    declare state: ConsoleState;

    override setup(): void {
        this.action = useService("action");
        this.shell = useState(
            new StudioShell(this.env, StudioShell.fromParams(this.params), {
                pushState: (state) => this.pushState(state),
                setTitle: (title) => this.setTitle(title),
            }),
        );
        this.state = useState<ConsoleState>({ ready: false, error: "" });

        onWillStart(async () => {
            try {
                await this.shell.load();
            } catch (err) {
                // Captured once, right after the cast, rather than reading
                // `err.data`/`.message` off a re-cast `err` a second time --
                // the repeated-cast form is what this migration's own
                // "Known traps" flags as losing its narrowing once another
                // expression runs in between.
                const rpcErr = err as OdooRpcError | undefined;
                if (!rpcErr?.data) {
                    throw err;
                }
                this.state.error = rpcErr.data.message;
                this.state.ready = true;
                return;
            }
            await this.shell.openPane(this.shell.pane, this.shell.paneState);
            this.state.ready = true;
        });
    }

    /**
     * What to open: the console's own params, the legacy editor's
     * (`view_id, res_model, view_type`), and on a reload the router's
     * state, which the action service hands back as params.
     */
    get params(): Record<string, unknown> {
        const action = this.props.action || {};
        return { ...(action.context || {}), ...(action.params || {}) };
    }

    pushState(state: ShellUrlState): void {
        if (this.props.updateActionState) {
            this.props.updateActionState(state);
        }
    }

    setTitle(title: string): void {
        const config = this.env.config;
        if (config && config.setDisplayName) {
            config.setDisplayName(title);
        }
    }

    // -- the pane on screen ----------------------------------------------------

    get pane(): PaneEntry | null {
        return this.shell.activePane;
    }

    /** The active pane's own component -- always present once the console
     * is `ready` (every real `app_builder.panes` registration resolves to
     * one, `shell/pane_registry.ts`'s own `resolvePane`), but
     * `PaneRegistration.Component` stays optional on the shared type since
     * it is also the shape of an unresolved, data-only entry -- so this
     * getter's own return type carries that same optionality rather than
     * asserting an invariant `pane_registry.ts` itself does not promise
     * statically. */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    get content(): typeof Component<any, any> | null | undefined {
        return this.pane ? this.pane.Component : null;
    }

    /** The active pane's own sidebar, `null` for a pane that has none
     * (`home_pane.ts`), or `undefined` when no pane is resolved at all --
     * see `content`, just above, for why the optionality is not narrowed
     * away here either. */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    get sidebar(): typeof Component<any, any> | null | undefined {
        return this.pane ? this.pane.sidebar : null;
    }

    get paneProps(): { shell: StudioShell; model: PaneModel | undefined } {
        return { shell: this.shell, model: this.shell.activeModel || undefined };
    }

    get sidebarWidth(): number {
        return this.shell.sidebarWidth || 360;
    }

    onSidebarResize(width: number): void {
        this.shell.sidebarWidth = width;
    }

    get readOnly(): boolean {
        return Boolean(this.shell.package) && !this.shell.packageWritable;
    }

    get readOnlyNote(): string {
        const info = this.shell.package;
        return String(
            _t(
                "%s is read-only: its directory cannot be written. This is normal on a deployment — build where the files are writable and ship the result through git.",
                info ? info.name : "",
            ),
        );
    }

    /**
     * Leave the console. Back to where the user came from when there is
     * somewhere to go back to; else to the action they named; else to the
     * model's first window action. The real views load through a cache
     * the canvas never touched, so it is dropped first for them to show
     * the edits.
     *
     * Back to a list or a kanban is not a restore. A restored controller
     * comes back with the model state it exported on leaving -- the
     * fields it was reading records with -- so it renders the new arch
     * and reads the old field set, and every card or row shows a field
     * dropped meanwhile as blank until the next reload. A form builds
     * its model afresh and is restored as it is. So for those two the
     * action the cog item handed over is run again in the previous
     * action's place: the same evaluated context and domain, the same
     * search state (it travels on the action object), and a model that
     * reads what the arch now shows. The search view it carries is
     * dropped first, since the action service adds it back on the way in
     * and would otherwise list it twice.
     */
    async close(): Promise<unknown> {
        compat.clearViewCaches(this.env);
        const entry = this.shell.entry || {};
        const breadcrumbs = this.env.config?.breadcrumbs || [];
        if (breadcrumbs.length > 1) {
            // `ShellEntry.previous_action` (`shell_model.ts`) is still
            // typed `unknown` there -- nothing converted before this file
            // read it. Cast to what the only real writer ever puts there
            // (`cog_menu_item.ts`'s own `previous_action: controller ?
            // controller.action : null`, itself `ActionController["action"]`)
            // rather than widening the shared field here; flagged in this
            // file's own findings, since this pass only touches `shell.ts`.
            const previous = entry.previous_action as ActionController["action"] | null | undefined;
            const previousType = previous?.type;
            if (previous && previousType === "ir.actions.act_window" && this.rerunsOnClose) {
                const action = {
                    ...previous,
                    type: previousType,
                    views: (previous.views || []).filter((view) => view[1] !== "search"),
                };
                // What the service fills in on the way in, and what it
                // could not serialise from a copy that still held them.
                // Deleted through a `Record<string, unknown>` view of the
                // same object rather than off `action` directly: whether
                // object-spreading a type with its own index signature
                // (`ActionController["action"]`'s own `[key: string]:
                // unknown`) keeps that index signature on the spread
                // result was not something this pass could confirm against
                // a real compiler (drafting is read-only) -- this sidesteps
                // the question entirely rather than assume either answer,
                // at no runtime cost (the same object, just a different
                // compile-time view of it).
                const raw = action as unknown as Record<string, unknown>;
                delete raw["_originalAction"];
                delete raw["controllers"];
                return this.action.doAction(action, {
                    stackPosition: "replacePreviousAction",
                    viewType: this.previousViewType,
                });
            }
            return this.action.restore();
        }
        if (entry.action_id) {
            return this.action.doAction(entry.action_id);
        }
        const modelName = this.shell.modelName;
        if (modelName) {
            const actions = await this.env.services.orm.searchRead<{ id: number }>(
                "ir.actions.act_window",
                [["res_model", "=", modelName]],
                ["id"],
                { limit: 1, order: "id" },
            );
            // `actions.length` being truthy does not, to
            // `noUncheckedIndexedAccess`, prove `actions[0]` exists --
            // asserted the same way this migration already does for other
            // length-guarded first-element reads (`field_editor_fallback.ts`'s
            // own `fieldEditorComponent()`).
            const first = actions[0];
            if (first) {
                return this.action.doAction(first.id);
            }
        }
        // Nowhere in particular to go back to: the default app.
        this.env.bus.trigger("WEBCLIENT:LOAD_DEFAULT_APP");
        return undefined;
    }

    /**
     * The type of the view the console was opened from: the one the cog
     * was on, kept across a switch inside the console.
     */
    get previousViewType(): string | false {
        const entry = this.shell.entry || {};
        return (
            entry.previous_view_type ||
            (this.params["view_type"] as string | false | undefined) ||
            false
        );
    }

    /** Whether Close re-runs the previous action rather than restoring it. */
    get rerunsOnClose(): boolean {
        // `Array<string>.includes` only takes a `string` -- widened to
        // accept `previousViewType`'s own `string | false` rather than
        // narrowing that getter, the same "the array, not the value, gets
        // the wider type" move used wherever this migration hands a
        // possibly-`false` value to a stock `string`-only API.
        return (["list", "kanban"] as Array<string | false>).includes(this.previousViewType);
    }
}

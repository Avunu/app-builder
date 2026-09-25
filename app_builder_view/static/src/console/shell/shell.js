import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { ResizablePanel } from "@web/core/resizable_panel/resizable_panel";
import * as compat from "../compat";
import { TopBar } from "../top_bar";
import { useService } from "../odoo";
import { StudioShell } from "./shell_model";
class StudioConsole extends Component {
  // `template`/`props` both live on Owl's own `Component` class body, so
  // `noImplicitOverride` requires `override` here; `components`/`target`/
  // `path` do not (TYPING.md's own "Known traps" -- `components` is not
  // a `Component` instance/static member at all, and `target`/`path` are
  // this addon's/the action framework's own convention, read off the
  // registered class by `action_service.js`, never declared on `Component`
  // itself).
  static template = "app_builder_view.StudioConsole";
  static components = { ResizablePanel, TopBar };
  // `as const`, not a plain object literal: without it TS widens `true`
  // to `boolean`, which is not assignable to `BaseType` (`true | "*" |
  // {new (...): any}`, `validation.d.ts`) -- the literal `true` itself
  // is a valid `BaseType`, only the widened type is not. Purely a type
  // annotation; the emitted `.js` for an object literal is identical
  // either way.
  static props = { "*": true };
  static target = "fullscreen";
  static path = "studio";
  setup() {
    this.action = useService("action");
    this.shell = useState(
      new StudioShell(this.env, StudioShell.fromParams(this.params), {
        pushState: (state) => this.pushState(state),
        setTitle: (title) => this.setTitle(title)
      })
    );
    this.state = useState({ ready: false, error: "" });
    onWillStart(async () => {
      try {
        await this.shell.load();
      } catch (err) {
        const rpcErr = err;
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
  get params() {
    const action = this.props.action || {};
    return { ...action.context || {}, ...action.params || {} };
  }
  pushState(state) {
    if (this.props.updateActionState) {
      this.props.updateActionState(state);
    }
  }
  setTitle(title) {
    const config = this.env.config;
    if (config && config.setDisplayName) {
      config.setDisplayName(title);
    }
  }
  // -- the pane on screen ----------------------------------------------------
  get pane() {
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
  get content() {
    return this.pane ? this.pane.Component : null;
  }
  /** The active pane's own sidebar, `null` for a pane that has none
   * (`home_pane.ts`), or `undefined` when no pane is resolved at all --
   * see `content`, just above, for why the optionality is not narrowed
   * away here either. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  get sidebar() {
    return this.pane ? this.pane.sidebar : null;
  }
  get paneProps() {
    return { shell: this.shell, model: this.shell.activeModel || void 0 };
  }
  get sidebarWidth() {
    return this.shell.sidebarWidth || 360;
  }
  onSidebarResize(width) {
    this.shell.sidebarWidth = width;
  }
  get readOnly() {
    return Boolean(this.shell.package) && !this.shell.packageWritable;
  }
  get readOnlyNote() {
    const info = this.shell.package;
    return String(
      _t(
        "%s is read-only: its directory cannot be written. This is normal on a deployment — build where the files are writable and ship the result through git.",
        info ? info.name : ""
      )
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
  async close() {
    compat.clearViewCaches(this.env);
    const entry = this.shell.entry || {};
    const breadcrumbs = this.env.config?.breadcrumbs || [];
    if (breadcrumbs.length > 1) {
      const previous = entry.previous_action;
      const previousType = previous?.type;
      if (previous && previousType === "ir.actions.act_window" && this.rerunsOnClose) {
        const action = {
          ...previous,
          type: previousType,
          views: (previous.views || []).filter((view) => view[1] !== "search")
        };
        const raw = action;
        delete raw["_originalAction"];
        delete raw["controllers"];
        return this.action.doAction(action, {
          stackPosition: "replacePreviousAction",
          viewType: this.previousViewType
        });
      }
      return this.action.restore();
    }
    if (entry.action_id) {
      return this.action.doAction(entry.action_id);
    }
    const modelName = this.shell.modelName;
    if (modelName) {
      const actions = await this.env.services.orm.searchRead(
        "ir.actions.act_window",
        [["res_model", "=", modelName]],
        ["id"],
        { limit: 1, order: "id" }
      );
      const first = actions[0];
      if (first) {
        return this.action.doAction(first.id);
      }
    }
    this.env.bus.trigger("WEBCLIENT:LOAD_DEFAULT_APP");
    return void 0;
  }
  /**
   * The type of the view the console was opened from: the one the cog
   * was on, kept across a switch inside the console.
   */
  get previousViewType() {
    const entry = this.shell.entry || {};
    return entry.previous_view_type || this.params["view_type"] || false;
  }
  /** Whether Close re-runs the previous action rather than restoring it. */
  get rerunsOnClose() {
    return ["list", "kanban"].includes(this.previousViewType);
  }
}
export {
  StudioConsole
};

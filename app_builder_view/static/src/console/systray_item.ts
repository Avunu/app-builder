/** @odoo-module **/
/**
 * "Builder" in the systray -- the way into the console from any screen.
 *
 * The cog item reaches the console from inside a view's control panel; this
 * one sits in the navbar, where Enterprise puts its toggle, and is there
 * whatever the screen shows. It offers itself only when the screen is a
 * window action -- a list, a form, a kanban of some model -- because that is
 * the only thing the console has a canvas for: a dashboard, a settings page
 * or the console itself gets nothing.
 *
 * What the console is told comes from `actionService.currentController`,
 * and nothing else is reachable from here: the navbar is a sibling of the
 * action container, so `env.config` -- where the cog item reads the view
 * id -- is not set on it, and the id the View resolved lives in a copy of
 * the config that never leaves the View. So the model and the view type
 * travel, the view id only when the action pins one, and the server
 * resolves the default view from the rest, the way it already does for
 * the cog item on an ordinary `view_mode="list,form"` action.
 *
 * The navbar re-renders its systray on registry changes and app changes
 * only, never on navigation; so this item listens for the action manager's
 * own "a controller is mounted" event and re-renders itself.
 */

import {Component, onWillStart, useState} from "@odoo/owl";
import {_t} from "./l10n";
import {registry} from "@web/core/registry";
import {useBus} from "@web/core/utils/hooks";
import type {EventBus} from "@odoo/owl";
import type {EnvWithBus} from "./compat";
import type {ActionController, ActionService} from "./odoo";
import {useService, user} from "./odoo";

// `registry.category("systray")`'s item shape (`SystrayRegistryItemShape`)
// and its `declare module "registries"` augmentation both live in
// `odoo.ts` now -- "the framework boundary, fenced in one place"
// (TYPING.md, Phase 2c) -- alongside `app_builder.panes`/`console_tabs`.

/** `BuilderSystrayItem` takes no props of its own -- `static props = {}`
 * below, and the systray mounts every entry with none. `Record<string,
 * never>` rather than a bare `{}`: TypeScript treats an empty *interface*
 * as accepting almost any value structurally, which is not what is meant
 * here -- this component genuinely takes nothing. */
type Props = Record<string, never>;

/** What `open()` sends the console: the model on screen, the view type
 * showing it, the view id if the current action pins one for that type,
 * the action id (so the console's own Close can restore it) and the
 * record on screen, if any. Not a shape any other file needs --
 * `cog_menu_item.js`'s own `params` object (still unconverted) names an
 * overlapping but not identical set of keys (`res_model` *and* `model`,
 * `previous_action`), so this stays local rather than joining
 * `types.ts`. */
interface SystrayTarget {
  model: string;
  view_type: string | undefined;
  view_id: number | false;
  action_id: number | false;
  res_id: number | false;
}

export class BuilderSystrayItem extends Component<Props, EnvWithBus> {
  static override template = "app_builder_view.BuilderSystrayItem";
  static override props = {};

  // Assigned in `setup()`, not the constructor -- Owl's own idiom, and
  // the constructor here is entirely framework-driven -- so declared
  // with the definite-assignment assertion rather than given an
  // initializer or an `| undefined` that would make every read below
  // narrow for nothing.
  action!: ActionService;
  state!: {allowed: boolean};

  override setup(): void {
    this.action = useService("action");
    this.state = useState({allowed: false});
    // Gated on the builder group the way the cog item is: the server
    // guards the writes, this only keeps the button out of the way of
    // people it would do nothing for.
    onWillStart(async () => {
      this.state.allowed = await user.hasGroup("app_builder_base.group_builder_user");
    });
    // Fired after the new controller is mounted and the stack committed
    // (18, 19 and master alike), so what is read below is current.
    useBus(this.env.bus as unknown as EventBus, "ACTION_MANAGER:UI-UPDATED", () =>
      this.render()
    );
  }

  /**
   * What the console would be opened on, or `null` when the screen is
   * not a view of a model.
   *
   * A controller restored from the URL may be a `virtual` placeholder
   * with an empty action and no props; a client action -- the console
   * among them -- has a tag and no `resModel`. Both are refused by the
   * one check on the action's type, the placeholder by its own flag too.
   */
  get target(): SystrayTarget | null {
    if (!this.state.allowed) {
      return null;
    }
    const ctrl = this.action.currentController;
    if (!ctrl || ctrl.virtual || !ctrl.action || !ctrl.props) {
      return null;
    }
    if (ctrl.action.type !== "ir.actions.act_window" || !ctrl.props.resModel) {
      return null;
    }
    const viewType = ctrl.props.type;
    const views = ctrl.action.views || [];
    const pinned = views.find((view) => view[1] === viewType);
    // Contextually typed against `ActionController["currentState"]`
    // itself (minus the `| undefined` the fallback exists to clear):
    // an un-annotated `ctrl.currentState || {}` infers a bare `{}`
    // for the fallback branch, and `state.resId` below would then
    // fail against that branch of the union -- the same "widen the
    // fallback to the field's own optional shape" move TYPING.md's
    // other clusters already use for a `||` default that must keep
    // an optional key reachable.
    const state: NonNullable<ActionController["currentState"]> =
      ctrl.currentState || {};
    return {
      model: ctrl.props.resModel,
      view_type: viewType,
      view_id: (pinned && pinned[0]) || false,
      action_id: ctrl.action.id || false,
      res_id: state.resId || ctrl.props.resId || false,
    };
  }

  get label(): string {
    return String(_t("Builder"));
  }

  get tooltip(): string {
    const target = this.target;
    return target
      ? String(_t("Edit this %s view in Builder", target.view_type))
      : String(_t("Open Builder"));
  }

  /**
   * Open the console on the screen, on its Views pane. What the console
   * needs to come back to this screen after a reload it keeps in its
   * own URL, so nothing is mirrored into the context.
   */
  open(): void {
    const target = this.target;
    if (!target) {
      return;
    }
    void this.action.doAction({
      type: "ir.actions.client",
      tag: "app_builder_console",
      target: "fullscreen",
      name: String(_t("Builder")),
      params: {...target, pane: "views"},
    });
  }
}

registry.category("systray").add(
  "app_builder.toggle",
  {Component: BuilderSystrayItem, isDisplayed: () => true},
  {
    sequence: 5,
  }
);

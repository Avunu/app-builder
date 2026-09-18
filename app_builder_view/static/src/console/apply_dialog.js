import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog, useService } from "./odoo";
class ApplyDialog extends Component {
  // `template`/`props` are both declared on Owl's own `Component` base
  // class (`template: string`, `props?: Schema`), so `noImplicitOverride`
  // requires `override` here; `components` is not a static member of
  // `Component` itself (only of the unrelated `StaticComponentProperties`
  // helper type `ComponentConstructor` uses), so `override` on it is a
  // real `tsc` error ("not declared in the base class") -- confirmed
  // against `node_modules/@odoo/owl/dist/types/runtime/component.d.ts`
  // directly, not guessed.
  static template = "app_builder_view.ApplyDialog";
  static components = { Dialog };
  static props = {
    shell: Object,
    close: Function
  };
  setup() {
    this.shell = useState(this.props.shell);
    this.dialog = useService("dialog");
    this.state = useState({
      allowDestructive: false,
      showDiff: false,
      diff: null,
      loadingDiff: false,
      error: "",
      refusedAsDestructive: false
    });
  }
  get title() {
    return String(_t("Apply %s pending change(s)", this.draft.pendingCount));
  }
  /** The shell's draft on the model in hand. */
  get draft() {
    return this.shell.draft;
  }
  /**
   * The Views pane's own model, when the console is on a canvas.
   * `shell.activeModel` is typed to the generic `PaneModel` contract
   * every pane satisfies (`shell_model.ts`); the real object it holds
   * whenever `pane === "views"` is always a `ConsoleModel`
   * (`views_pane.js`'s own registration is the one thing that ever puts
   * something there under that key), so the downcast asserts an
   * invariant the caller below already relies on (`.pending`/`.viewId`,
   * neither part of the generic `PaneModel` contract) rather than
   * guessing a shape -- `ConsoleModel implements PaneModel`, so the two
   * are related types and the assertion is a real narrowing.
   */
  get views() {
    return this.shell.pane === "views" ? this.shell.activeModel : null;
  }
  get changes() {
    return this.draft.pendingChanges;
  }
  /**
   * For an added field the canvas does not draw, where it will land:
   * anchored on another view of the model, or placed by the balanced
   * fallback. `""` for a field with a ghost, or a change that is not
   * an addition.
   *
   * An anchor on *this* view whose ghost could not be spliced -- the
   * neighbour is gone and the view has no fallback spot to draw at, as
   * a kanban has not -- is the fallback case too: the field was dropped
   * here, and it is the balanced placement that will put it here.
   */
  whereabouts(change) {
    const views = this.views;
    if (change.kind !== "added" || !views) {
      return "";
    }
    const entry = views.pending.find((p) => p.name === change.name);
    if (!entry || entry.placed) {
      return "";
    }
    if (entry.view_id && entry.view_id !== views.viewId) {
      return String(_t("Not on this canvas: it was dropped on another view of this model."));
    }
    return String(_t("Not on this canvas: it will be placed automatically after Apply."));
  }
  get errors() {
    return this.draft.errors;
  }
  /** Whether anything here would lose data, so "Apply anyway" is offered. */
  get hasDestructive() {
    return this.state.refusedAsDestructive || this.changes.some((change) => change.destructive);
  }
  get reloadMode() {
    return this.draft.reloadMode;
  }
  get reloadNotice() {
    if (this.reloadMode === "manual") {
      return String(
        _t(
          "This server runs several workers, so it cannot reload in place. The files are written and the package is marked for upgrade; restart the server and Odoo loads it on the way up. Until then the fields are in the file, not in the database."
        )
      );
    }
    return String(_t("Applying reloads this package in place. It takes a moment."));
  }
  /** What the primary button says: a write under workers, an apply otherwise. */
  get applyLabel() {
    return this.reloadMode === "manual" ? String(_t("Write files")) : String(_t("Apply"));
  }
  /** Why Apply cannot be pressed, or `""`. */
  get blocker() {
    const blocker = this.draft.applyBlocker;
    if (blocker) {
      return blocker;
    }
    if (this.hasDestructive && !this.state.allowDestructive) {
      return String(_t('Tick "Apply anyway" to accept the data that would be kept aside.'));
    }
    return "";
  }
  get canApply() {
    return !this.draft.applying && !this.blocker;
  }
  get applying() {
    return this.draft.applying;
  }
  async toggleDiff() {
    this.state.showDiff = !this.state.showDiff;
    if (this.state.showDiff && this.state.diff === null) {
      this.state.loadingDiff = true;
      try {
        this.state.diff = await this.draft.previewDiff();
      } finally {
        this.state.loadingDiff = false;
      }
    }
  }
  async onApply() {
    if (!this.canApply) {
      return;
    }
    this.state.error = "";
    const result = await this.shell.apply(this.state.allowDestructive);
    if (result.ok) {
      this.props.close();
      return;
    }
    this.state.error = result.message;
    if (result.destructive) {
      this.state.refusedAsDestructive = true;
    }
  }
  onDiscard() {
    if (this.applying || this.shell.activity.busy) {
      return;
    }
    this.dialog.add(ConfirmationDialog, {
      title: _t("Discard pending changes"),
      body: _t(
        "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
        this.draft.pendingCount
      ),
      confirmLabel: _t("Discard"),
      confirm: () => {
        this.props.close();
        void this.shell.discard();
      },
      cancel: () => {
      }
    });
  }
}
export {
  ApplyDialog
};

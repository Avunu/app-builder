import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { messageOf } from "../shell/draft_model";
import { setPaneResolver } from "../shell/pane_registry";
class FlowModel {
  shell;
  spec;
  values;
  index;
  error;
  busy;
  done;
  result;
  opened;
  /** Set by `open()`; whatever the pane host's own target for this key
   * is (`shell_model.ts:openTarget`) -- opaque here, the same as
   * `PaneModel.open`'s own parameter. */
  target;
  constructor(shell, spec) {
    this.shell = shell;
    this.spec = spec;
    this.values = { ...spec.initial || {} };
    this.index = 0;
    this.error = "";
    this.busy = false;
    this.done = false;
    this.result = null;
    this.opened = false;
  }
  get activity() {
    return { busy: this.busy, status: "saved", error: "", drag: null, applying: false };
  }
  get history() {
    return null;
  }
  get steps() {
    return this.spec.steps;
  }
  get step() {
    return this.steps[this.index];
  }
  get isLast() {
    return this.index === this.steps.length - 1;
  }
  async open(target) {
    this.target = target;
    if (this.spec.onOpen) {
      await this.spec.onOpen(this.shell, this);
    }
  }
  reactivate() {
    return void 0;
  }
  /** Whether the current step lets the flow go on: its own check. */
  check() {
    this.error = this.step.validate?.(this.values, this.shell) || "";
    return !this.error;
  }
  async next() {
    if (!this.check()) {
      return;
    }
    if (this.isLast) {
      await this.finish();
      return;
    }
    this.index += 1;
    const step = this.step;
    if (step.onEnter) {
      await step.onEnter(this.values, this.shell, this);
    }
  }
  back() {
    this.error = "";
    if (this.index > 0) {
      this.index -= 1;
    }
  }
  async finish() {
    this.busy = true;
    this.error = "";
    try {
      this.result = await this.spec.onDone(this.shell, this);
      this.done = true;
    } catch (err) {
      if (!err?.data) {
        throw err;
      }
      this.error = messageOf(err);
    } finally {
      this.busy = false;
    }
  }
  async cancel() {
    if (this.spec.onCancel) {
      await this.spec.onCancel(this.shell, this);
    } else {
      await this.shell.openPane("home");
    }
  }
}
class Flow extends Component {
  static template = "app_builder_view.Flow";
  static props = { shell: Object, model: { type: Object, optional: true } };
  /** Assigned in `setup()`, which Owl calls synchronously right after
   * construction and before the first render -- always set by the
   * time any getter or template read runs. */
  shell;
  flow;
  setup() {
    this.shell = useState(this.props.shell);
    this.flow = useState(this.props.model);
  }
  get title() {
    return this.flow.spec.title;
  }
  get stepProps() {
    return { shell: this.shell, flow: this.flow };
  }
  get nextLabel() {
    if (this.flow.isLast) {
      return this.flow.spec.doneLabel || _t("Done");
    }
    return _t("Next");
  }
}
setPaneResolver("flow", (entry) => ({
  Component: Flow,
  sidebar: null,
  // `resolvePane` (`shell/pane_registry.ts`) only ever calls the "flow"
  // resolver from its own `if (entry.flow)` branch, so `entry.flow` is
  // always a real `FlowSpec` by the time this runs -- not an invariant
  // `tsc` can see across that module boundary, hence the cast rather
  // than a redundant guard (and a plain cast rather than `!`, so this
  // keeps compiling however precisely `PaneRegistration.flow` itself
  // ends up typed in `types.ts`).
  makeModel: (shell) => new FlowModel(shell, entry.flow)
}));
export {
  Flow,
  FlowModel
};

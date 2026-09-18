/** @odoo-module **/
/**
 * A flow: a few steps in the content slot, with a rail across the top.
 *
 * Creating a package, building an app, adopting a model: each asks two
 * or three things before it writes anything, and writes on the last
 * step's button and not before. A flow is a pane with no tab -- a tile
 * or a picker opens it -- registered with `flow: {title, steps, onDone,
 * onCancel}`; each step is a component taking `{shell, flow}` that reads
 * and writes `flow.values`, and may say what is wrong with them
 * (`validate(values, shell) -> string`).
 *
 * In the content slot rather than a dialog: reload-safe (the URL names
 * the pane, and the flow starts again at its first step), with room for
 * a preview, and with nothing modal under the "Advanced" dialog a record
 * pane may open.
 */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { messageOf } from "../shell/draft_model";
import { setPaneResolver } from "../shell/pane_registry";
import type { StudioShell } from "../shell/shell_model";
import type {
    FlowSpec,
    FlowStep,
    FlowValues,
    OdooRpcError,
    PaneActivity,
    PaneModel,
} from "../types";

export class FlowModel implements PaneModel {
    shell: StudioShell;
    spec: FlowSpec;
    values: FlowValues;
    index: number;
    error: string;
    busy: boolean;
    done: boolean;
    result: unknown;
    opened: boolean;
    /** Set by `open()`; whatever the pane host's own target for this key
     * is (`shell_model.ts:openTarget`) -- opaque here, the same as
     * `PaneModel.open`'s own parameter. */
    target?: unknown;

    constructor(shell: StudioShell, spec: FlowSpec) {
        this.shell = shell;
        this.spec = spec;
        this.values = { ...(spec.initial || {}) };
        this.index = 0;
        this.error = "";
        this.busy = false;
        this.done = false;
        this.result = null;
        this.opened = false;
    }

    get activity(): PaneActivity {
        return { busy: this.busy, status: "saved", error: "", drag: null, applying: false };
    }

    get history(): null {
        return null;
    }

    get steps(): FlowStep[] {
        return this.spec.steps;
    }

    get step(): FlowStep {
        // `index` only ever moves within `[0, steps.length)` (`next()`
        // and `back()` both bound it), so this read is always in range --
        // an invariant `noUncheckedIndexedAccess` cannot see on its own.
        return this.steps[this.index]!;
    }

    get isLast(): boolean {
        return this.index === this.steps.length - 1;
    }

    async open(target: unknown): Promise<void> {
        this.target = target;
        if (this.spec.onOpen) {
            await this.spec.onOpen(this.shell, this);
        }
    }

    reactivate(): void {
        return undefined;
    }

    /** Whether the current step lets the flow go on: its own check. */
    check(): boolean {
        this.error = this.step.validate?.(this.values, this.shell) || "";
        return !this.error;
    }

    async next(): Promise<void> {
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

    back(): void {
        this.error = "";
        if (this.index > 0) {
            this.index -= 1;
        }
    }

    async finish(): Promise<void> {
        this.busy = true;
        this.error = "";
        try {
            this.result = await this.spec.onDone(this.shell, this);
            this.done = true;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.error = messageOf(err);
        } finally {
            this.busy = false;
        }
    }

    async cancel(): Promise<void> {
        if (this.spec.onCancel) {
            await this.spec.onCancel(this.shell, this);
        } else {
            await this.shell.openPane("home");
        }
    }
}

interface Props {
    shell: StudioShell;
    model: FlowModel;
}

export class Flow extends Component<Props> {
    static override template = "app_builder_view.Flow";
    static override props = { shell: Object, model: { type: Object, optional: true } };

    /** Assigned in `setup()`, which Owl calls synchronously right after
     * construction and before the first render -- always set by the
     * time any getter or template read runs. */
    shell!: StudioShell;
    flow!: FlowModel;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.flow = useState(this.props.model);
    }

    get title(): unknown {
        return this.flow.spec.title;
    }

    get stepProps(): { shell: StudioShell; flow: FlowModel } {
        return { shell: this.shell, flow: this.flow };
    }

    get nextLabel(): unknown {
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
    makeModel: (shell) => new FlowModel(shell as StudioShell, entry.flow as FlowSpec),
}));

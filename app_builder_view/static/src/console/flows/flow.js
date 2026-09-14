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

export class FlowModel {
    constructor(shell, spec) {
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

    async reactivate() {
        return undefined;
    }

    /** Whether the current step lets the flow go on: its own check. */
    check() {
        const validate = this.step.validate;
        this.error = validate ? validate(this.values, this.shell) || "" : "";
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
            if (!(err && err.data)) {
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

export class Flow extends Component {
    static template = "app_builder_view.Flow";
    static props = { shell: Object, model: { type: Object, optional: true } };

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
    makeModel: (shell) => new FlowModel(shell, entry.flow),
}));

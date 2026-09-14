/** @odoo-module **/
/**
 * Adopt a model: bring a hand-made `x_` model under Python, in the package.
 *
 * Choose which, see the class the studio will write, review, and one call
 * (`adopt`) writes it, retires the manual metadata it replaces and reloads
 * the package. One model at a time is recommended: the class is reviewed
 * as a whole, and a mistake in one is easier to see alone.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import * as compat from "@app_builder_view/console/compat";
import { paneRegistry } from "@app_builder_view/console/shell/pane_registry";

class ChooseStep extends Component {
    static template = "app_builder_model.AdoptChoose";
    static props = { shell: Object, flow: Object };

    setup() {
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState({ models: [], loading: true });
        onWillStart(async () => {
            this.state.models = await this.orm.call("studio.app.builder", "adoptable_models", []);
            this.state.loading = false;
            // Opened on a model from Home: it is the one chosen.
            const preset = this.flow.target && this.flow.target.model;
            if (preset && !this.flow.values.models) {
                this.flow.values.models = this.state.models.some((m) => m.model === preset)
                    ? [preset]
                    : [];
            }
            this.flow.values.models = this.flow.values.models || [];
            this.flow.values.previews = Object.fromEntries(
                this.state.models.map((m) => [m.model, m.preview])
            );
        });
    }

    isOn(name) {
        return (this.flow.values.models || []).includes(name);
    }

    toggle(name) {
        const current = new Set(this.flow.values.models || []);
        if (current.has(name)) {
            current.delete(name);
        } else {
            current.add(name);
        }
        this.flow.values.models = [...current];
    }

    /** Where the model came from, in a phrase. */
    origin(entry) {
        if (entry.owner_package) {
            return _t("Made by the studio in %s, as records", entry.owner_package.name);
        }
        return _t("Made by hand in Settings › Technical");
    }
}

class PreviewStep extends Component {
    static template = "app_builder_model.AdoptPreview";
    static props = { shell: Object, flow: Object };

    setup() {
        this.flow = useState(this.props.flow);
    }

    get previews() {
        const previews = this.flow.values.previews || {};
        return (this.flow.values.models || []).map((name) => ({
            name,
            code: previews[name] || "",
        }));
    }
}

class ReviewStep extends Component {
    static template = "app_builder_model.AdoptReview";
    static props = { shell: Object, flow: Object };

    setup() {
        this.flow = useState(this.props.flow);
        this.shell = useState(this.props.shell);
    }

    get files() {
        return (this.flow.values.models || []).map((name) => `models/${name.replace(/\./g, "_")}.py`);
    }

    get manual() {
        return Boolean(this.shell.package && this.shell.package.reload_mode === "manual");
    }
}

paneRegistry.add("adopt_model", {
    label: _t("Adopt a model"),
    icon: "fa fa-download",
    scope: "package",
    tab: false,
    flow: {
        key: "adopt_model",
        title: _t("Adopt a model"),
        doneLabel: _t("Adopt"),
        steps: [
            {
                key: "choose",
                label: _t("Choose"),
                Component: ChooseStep,
                validate: (values) =>
                    (values.models || []).length ? "" : _t("Choose at least one model."),
            },
            { key: "preview", label: _t("Preview"), Component: PreviewStep },
            { key: "review", label: _t("Review"), Component: ReviewStep },
        ],
        onDone: async (shell, flow) => {
            const names = flow.values.models || [];
            const answer = await shell.orm.call("studio.app.builder", "adopt", [
                shell.packageId,
                names,
            ]);
            compat.clearViewCaches(shell.env);
            await shell.refreshPackages();
            shell.inventory = null;
            await shell.openView({ model: names[0], view_type: "form" });
            shell.callout = {
                key: "adopted",
                title: answer.restart_required
                    ? _t("%s is written; restart to make it Python", names.join(", "))
                    : _t("%s is Python now", names.join(", ")),
                lines: [
                    _t("Its fields live in models/ as a class; the studio keeps the marked block in sync and leaves the rest to you."),
                    _t("New fields on it are staged and applied with one reload."),
                ],
                model: names[0],
            };
            return answer;
        },
    },
});

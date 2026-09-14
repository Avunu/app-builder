/** @odoo-module **/
/**
 * Home: the package as a workspace.
 *
 * What the package is and how it is doing -- writable, drifted,
 * uncommitted, a failed apply with a rollback on offer -- then the five
 * things to do from here (build an app, adopt a model, open a view, edit
 * the menus, look at the changes), then the models the package defines
 * and the ones it touches, and the getting-started list until it is
 * dismissed. With no package yet, the create-package flow is the page.
 */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { messageOf } from "../shell/draft_model";
import { paneFlows, paneRegistry } from "../shell/pane_registry";
import { healthDot } from "../top_bar";
import { Flow, FlowModel } from "../flows/flow";
import "../flows/create_package_flow";

export class HomeModel {
    constructor(shell) {
        this.shell = shell;
        this.orm = shell.orm;
        this.checklist = null;
        this.busy = false;
        this.error = "";
        this.opened = false;
        // The create-package flow, hosted here on a first run.
        this.createFlow = null;
    }

    get activity() {
        return { busy: this.busy, status: "saved", error: "", drag: null, applying: false };
    }

    get history() {
        return null;
    }

    async open() {
        await this.reactivate();
    }

    async reactivate() {
        this.error = "";
        await this.shell.refreshPackages();
        if (!this.shell.packageId) {
            this.shell.inventory = null;
            this.checklist = null;
            return;
        }
        this.busy = true;
        try {
            const [, checklist] = await Promise.all([
                this.shell.loadInventory(),
                this.orm.call("studio.workspace", "checklist", [this.shell.packageId]),
                this.loadFeatures(),
            ]);
            this.checklist = checklist;
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.error = messageOf(err);
        } finally {
            this.busy = false;
        }
    }

    /**
     * The features a Python model of the package can still take on
     * (`studio.app.builder.features`), when the app builder is installed
     * -- it registers the build_app flow, which is how this addon, which
     * does not depend on it, knows.
     */
    async loadFeatures() {
        if (this.features !== undefined) {
            return;
        }
        const builder = paneRegistry.contains("build_app");
        if (!builder) {
            this.features = [];
            return;
        }
        const answer = await this.orm.call("studio.app.builder", "features", []);
        this.features = answer.features.filter((f) => f.offered);
    }

    /**
     * Stage a feature on a model the package defines in Python: fields and
     * model options on the draft, applied like any other change.
     */
    async addFeature(modelName, key) {
        this.busy = true;
        this.error = "";
        try {
            const added = await this.orm.call("studio.app.builder", "add_feature", [
                this.shell.packageId,
                modelName,
                key,
            ]);
            return added;
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.shell.notification.add(messageOf(err), { type: "warning" });
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /** One call on the workspace about the package, then everything read again. */
    async act(method, ...args) {
        this.busy = true;
        this.error = "";
        try {
            const result = await this.orm.call("studio.workspace", method, [
                this.shell.packageId,
                ...args,
            ]);
            await this.reactivate();
            return result;
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.error = messageOf(err);
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /** The create-package flow, made once. */
    get firstRun() {
        if (!this.createFlow) {
            const entry = paneRegistry.get("create_package");
            this.createFlow = new FlowModel(this.shell, entry.flow);
        }
        return this.createFlow;
    }
}

const HEALTH_LINES = {
    read_only: () => _t("Read-only · the directory cannot be written"),
    missing: () => _t("Files missing on disk"),
    not_installed: () => _t("Not installed · Odoo has not loaded this module yet"),
    failed_apply: () => _t("Last apply failed · a rollback is available"),
    restart_required: () => _t("Restart to load · files were written that only a restart can load"),
    drifted: () => _t("Files edited on disk"),
    pending: () => _t("Changes pending on a model"),
    pending_write: () => _t("Pending write"),
    uncommitted: () => _t("Uncommitted changes"),
    no_git: () => _t("Not a git repository"),
    manual_reload: () => _t("Restart to apply · this server runs workers"),
};

const HEALTH_ACTIONS = {
    not_installed: { label: _t("Install it"), pane: null, method: "reload" },
    failed_apply: { label: _t("Roll back…"), pane: "changes" },
    restart_required: { label: _t("See what is waiting"), pane: "changes" },
    drifted: { label: _t("Review"), pane: "changes" },
    missing: { label: _t("Write to disk"), method: "write_files" },
    pending_write: { label: _t("Write to disk"), method: "write_files" },
    pending: { label: _t("Apply…"), pane: "changes" },
    uncommitted: { label: _t("Commit"), pane: "changes" },
    no_git: { label: _t("Initialise git…"), method: "git_init" },
};

const FLAG_DOT = {
    read_only: "grey",
    no_git: "grey",
    manual_reload: "grey",
    missing: "red",
    failed_apply: "red",
    drifted: "red",
};

const CHECKLIST = [
    { key: "package", label: _t("Create a package") },
    { key: "app", label: _t("Build an app") },
    { key: "field", label: _t("Add a field") },
    { key: "automation", label: _t("Automate something") },
    { key: "commit", label: _t("Commit") },
];

export class HomePane extends Component {
    static template = "app_builder_view.HomePane";
    static components = { Flow };
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.orm = useService("orm");
        this.state = useState({ modelSearch: "" });
    }

    get package() {
        return this.shell.package;
    }

    get packages() {
        return this.shell.packages.map((info) => ({
            ...info,
            dot: healthDot(info),
            active: info.id === this.shell.packageId,
            summaryLine: this.summaryOf(info),
        }));
    }

    summaryOf(info) {
        const flags = info.health || [];
        const worst = ["read_only", "missing", "failed_apply", "drifted", "restart_required", "pending", "uncommitted"].find(
            (f) => flags.includes(f)
        );
        if (worst) {
            return HEALTH_LINES[worst]();
        }
        return _t("in sync");
    }

    get firstRun() {
        return !this.shell.packages.length;
    }

    get noneWritable() {
        return this.shell.packages.length > 0 && !this.shell.packages.some((p) => p.writable);
    }

    /** The health line: the worst things first, each with what to do. */
    get health() {
        const info = this.package;
        if (!info) {
            return [];
        }
        const order = Object.keys(HEALTH_LINES);
        return (info.health || [])
            .slice()
            .sort((a, b) => order.indexOf(a) - order.indexOf(b))
            .map((flag) => ({
                flag,
                label: HEALTH_LINES[flag] ? HEALTH_LINES[flag]() : flag,
                action: HEALTH_ACTIONS[flag] || null,
                dot: FLAG_DOT[flag] || "amber",
            }));
    }

    get healthy() {
        const info = this.package;
        return Boolean(info) && !this.health.some((h) => h.flag !== "no_git" && h.flag !== "manual_reload");
    }

    get gitLine() {
        const info = this.package;
        if (!info || !info.git.is_git) {
            return "";
        }
        const dirty = info.git.dirty + info.git.untracked;
        return dirty
            ? _t("⎇ %s · %s uncommitted", info.git.branch, dirty)
            : _t("⎇ %s · nothing to commit", info.git.branch);
    }

    async onHealthAction(entry) {
        const action = entry.action;
        if (!action) {
            return;
        }
        if (action.pane) {
            await this.shell.openPane(action.pane);
            return;
        }
        if (action.method) {
            await this.model.act(action.method);
        }
    }

    // -- tiles ---------------------------------------------------------------

    get tiles() {
        const flows = paneFlows(this.shell.paneContext);
        const writable = this.shell.packageWritable;
        const has = (key) => flows.some((f) => f.key === key);
        return [
            {
                key: "build_app",
                label: _t("Build an app"),
                icon: "fa fa-cubes",
                hint: _t("A model, its views, menu and access"),
                enabled: writable && has("build_app"),
                reason: !writable ? _t("The package is read-only.") : "",
                run: () => this.shell.openPane("build_app"),
            },
            {
                key: "adopt_model",
                label: _t("Adopt a model"),
                icon: "fa fa-download",
                hint: _t("Bring a hand-made x_ model under Python"),
                enabled: writable && has("adopt_model"),
                reason: !writable ? _t("The package is read-only.") : "",
                run: () => this.shell.openPane("adopt_model"),
            },
            {
                key: "open_view",
                label: _t("Open a view"),
                icon: "fa fa-pencil-square-o",
                hint: _t("Any model, any view"),
                enabled: true,
                reason: "",
                run: () => this.shell.openPane("open_view"),
            },
            {
                key: "menu",
                label: _t("Edit menus"),
                icon: "fa fa-bars",
                hint: _t("The apps this package owns"),
                enabled: paneRegistry.contains("menu"),
                reason: paneRegistry.contains("menu") ? "" : _t("Install app_builder_ui."),
                run: () => this.shell.openPane("menu"),
            },
            {
                key: "changes",
                label: _t("Changes"),
                icon: "fa fa-code-fork",
                hint: this.shell.changesCount
                    ? _t("%s to look at", this.shell.changesCount)
                    : _t("Nothing pending"),
                enabled: true,
                reason: "",
                run: () => this.shell.openPane("changes"),
            },
        ];
    }

    // -- models ---------------------------------------------------------------

    get models() {
        const inventory = this.shell.inventory;
        const term = this.state.modelSearch.toLowerCase();
        const rows = ((inventory && inventory.models) || []).filter(
            (m) => !term || m.model.includes(term) || m.display_name.toLowerCase().includes(term)
        );
        return rows.map((m) => ({
            ...m,
            sourceLabel: {
                python: _t("Python"),
                frozen: _t("Python (code-owned)"),
                extends: _t("Extends"),
                xml: _t("data records"),
            }[m.source],
            adoptable: m.source === "xml",
        }));
    }

    /** Models the package touches without defining: from the picker's lists. */
    get extended() {
        const inventory = this.shell.inventory;
        if (!inventory) {
            return [];
        }
        const defined = new Set(inventory.models.map((m) => m.model));
        const touched = {};
        for (const [key, entries] of Object.entries(inventory)) {
            if (key === "models") {
                continue;
            }
            for (const entry of entries) {
                if (entry.subject && !defined.has(entry.subject)) {
                    touched[entry.subject] = touched[entry.subject] || { model: entry.subject, counts: {} };
                    touched[entry.subject].counts[key] = (touched[entry.subject].counts[key] || 0) + 1;
                }
            }
        }
        return Object.values(touched).sort((a, b) => a.model.localeCompare(b.model));
    }

    countsLine(counts) {
        const parts = [];
        const labels = {
            fields: _t("field"),
            views: _t("view"),
            automations: _t("automation"),
            rules: _t("rule"),
            reports: _t("report"),
            approvals: _t("approval"),
            menus: _t("menu"),
            access: _t("access line"),
        };
        for (const [key, label] of Object.entries(labels)) {
            const n = counts[key] || 0;
            if (n) {
                parts.push(n === 1 ? `1 ${label}` : `${n} ${label}s`);
            }
        }
        return parts.join(" · ");
    }

    async onOpenModel(entry) {
        await this.shell.openView({ model: entry.model });
    }

    async onModelFields(entry) {
        await this.shell.openView({ model: entry.model, view_type: "form" });
    }

    async onAdopt(entry) {
        await this.shell.setModel(entry.model, { open: false });
        await this.shell.openPane("adopt_model", { model: entry.model });
    }

    /** The features a row offers: the builder's, on a model written in Python. */
    featuresFor(entry) {
        if (entry.source !== "python" || !this.shell.packageWritable) {
            return [];
        }
        return this.model.features || [];
    }

    /** A feature chosen on a model row: staged, then the form shows the ghosts. */
    async onAddFeature(entry, ev) {
        const key = ev.target.value;
        ev.target.value = "";
        if (!key) {
            return;
        }
        const added = await this.model.addFeature(entry.model, key);
        if (!added) {
            return;
        }
        const count = (added.added || []).length;
        this.shell.notification.add(
            count
                ? _t("%s staged on %s: apply from the Views pane.", count, entry.display_name)
                : _t("%s already has that.", entry.display_name),
            { type: "info" }
        );
        // The Views pane learns the draft from the editing context it
        // loads on open; the form then shows the staged fields as ghosts.
        await this.shell.openView({ model: entry.model, view_type: "form" });
    }

    // -- checklist ------------------------------------------------------------

    get checklist() {
        const done = this.model.checklist;
        if (!done || this.shell.prefs.checklist_dismissed) {
            return [];
        }
        return CHECKLIST.map((item) => ({ ...item, done: Boolean(done[item.key]) }));
    }

    dismissChecklist() {
        this.shell.rememberPref("checklist_dismissed", true);
    }
}

paneRegistry.add(
    "home",
    {
        label: _t("Home"),
        icon: "fa fa-home",
        scope: "package",
        Component: HomePane,
        sidebar: null,
        makeModel: (shell) => new HomeModel(shell),
    },
    { sequence: 0 }
);

// Open a view: a model, then the Views pane on it.
class OpenViewStep extends Component {
    static template = "app_builder_view.OpenViewStep";
    static props = { shell: Object, flow: Object };

    setup() {
        this.shell = useState(this.props.shell);
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState({ term: "", matches: [] });
    }

    get suggestions() {
        const inventory = this.shell.inventory;
        return ((inventory && inventory.models) || []).map((m) => ({
            model: m.model,
            display_name: m.display_name,
        }));
    }

    async onSearch(ev) {
        const term = (ev.target.value || "").trim();
        this.state.term = term;
        if (term.length < 2) {
            this.state.matches = [];
            return;
        }
        const rows = await this.orm.searchRead(
            "ir.model",
            ["|", ["name", "ilike", term], ["model", "ilike", term], ["transient", "=", false]],
            ["model", "name"],
            { limit: 12 }
        );
        if (this.state.term === term) {
            this.state.matches = rows.map((r) => ({ model: r.model, display_name: r.name }));
        }
    }

    pick(entry) {
        this.flow.values.model = entry.model;
        this.flow.values.label = entry.display_name;
    }
}

paneRegistry.add("open_view", {
    label: _t("Open a view"),
    icon: "fa fa-pencil-square-o",
    scope: "package",
    tab: false,
    flow: {
        key: "open_view",
        title: _t("Open a view"),
        doneLabel: _t("Open"),
        steps: [
            {
                key: "model",
                label: _t("Model"),
                Component: OpenViewStep,
                validate: (values) => (values.model ? "" : _t("Pick a model.")),
            },
        ],
        onDone: async (shell, flow) => {
            await shell.openView({ model: flow.values.model });
        },
    },
});

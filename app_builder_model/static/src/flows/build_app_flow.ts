/** @odoo-module **/
/**
 * Build an app: a name, the features, who can use it, where it goes.
 *
 * Four questions and a review, then one call (`create_app_rpc`) that
 * writes the model as Python, reloads the package, builds the views,
 * the menu and the access lines, and reloads once more. Nothing is
 * written before the last button. Tags and Lines build a second model
 * each and are decided now: adding them later means building another
 * app, and the tile says so.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@app_builder_view/console/odoo";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import * as compat from "@app_builder_view/console/compat";
import { paneRegistry } from "@app_builder_view/console/shell/pane_registry";
import type { OrmService } from "@app_builder_view/console/types";
import type { PackageEntryJSON } from "@app_builder_view/console/wire";
import type { OpenViewTarget } from "@app_builder_view/console/shell/shell_model";

/**
 * This flow's own `flow.values` bag, the same "built up one field at a
 * time" contract `create_package_flow.ts`'s `CreatePackageValues` already
 * documents -- every field optional on its own terms, not just
 * defensively.
 */
interface BuildAppValues {
    label?: string;
    model_name?: string;
    nameTouched?: boolean;
    features?: string[];
    groups?: number[];
    menu_kind?: "new_root" | "under";
    parent_menu_id?: number | false;
}

/**
 * What `NameStep` (`suggest()`) and `ReviewStep` (`manual`) read directly
 * off `props.shell` -- the real `StudioShell` (`shell/shell_model.ts`) the
 * flow host hands every step (`flows/flow.ts`'s own `stepProps`), narrowed
 * to exactly those two reads the same way `FlowShell` below narrows what
 * `onDone` needs. `FeaturesStep`/`WhoStep`/`MenuStep` never read
 * `props.shell` at all, so their own `Props` leave it at
 * `FlowStepProps`'s own `unknown` default -- the identical reasoning
 * `create_package_flow.ts`'s `FlowStepProps.shell: unknown` already used
 * for every one of its own steps.
 */
interface FlowStepShell {
    packageId: number | false;
    package: PackageEntryJSON | null;
}

/**
 * What every step of this flow receives (`flows/flow.ts`'s own contract:
 * a step component takes `{shell, flow}`). `flow` is the reactive
 * `FlowModel` instance narrowed to the one member every step reads and
 * writes -- its own per-flow `values` bag, the same shape
 * `create_package_flow.ts`'s `FlowStepProps` already uses.
 */
interface FlowStepProps<S = unknown> {
    shell: S;
    flow: { values: BuildAppValues };
}

/** `Workshop Job` -> `workshop_job`, the way the server will spell it.
 * Dead code, confirmed pre-existing (defined, never called, in the
 * original `.js` too) -- not this migration's job to remove. */
function slug(text: string): string {
    return (text || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
}

/**
 * `suggest_name`'s answer (`studio_app_builder.py:suggest_name`): the
 * technical name a label would get, and whether it is already taken.
 */
interface SuggestNameAnswer {
    model: string;
    taken: boolean;
}

/**
 * One entry of `features()`'s own `features` list
 * (`studio_app_builder.py:features`, spreading `scaffold.features_json()`'s
 * `{key, label, help, default, views}` with `implies`/`companion`/
 * `offered` added). `companion` is always a string on the wire -- the
 * Python side falls back to `""` when a feature has none -- and `offered`
 * is what decides whether a tile shows it at all (`FeaturesStep.offered`
 * below): a feature another one `implies` is not offered separately.
 */
interface BuildAppFeatureEntry {
    key: string;
    label: string;
    help: string;
    default: boolean;
    views: string[];
    implies: string[];
    companion: string;
    offered: boolean;
}

/** `features()`'s whole return (`studio_app_builder.py:features`). */
interface FeaturesAnswer {
    features: BuildAppFeatureEntry[];
    defaults: string[];
}

class NameStep extends Component<FlowStepProps<FlowStepShell>> {
    static override template = "app_builder_model.BuildAppName";
    static override props = { shell: Object, flow: Object };

    flow!: { values: BuildAppValues };
    orm!: OrmService;
    state!: { suggested: string; taken: boolean; checking: boolean };

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState({ suggested: "", taken: false, checking: false });
        if (this.flow.values.label) {
            void this.suggest();
        }
    }

    onLabel(ev: InputEvent): void {
        this.flow.values.label = (ev.target as HTMLInputElement).value;
        if (!this.flow.values.nameTouched) {
            this.flow.values.model_name = "";
        }
        void this.suggest();
    }

    onName(ev: InputEvent): void {
        this.flow.values.model_name = (ev.target as HTMLInputElement).value.trim();
        this.flow.values.nameTouched = true;
    }

    async suggest(): Promise<void> {
        const label = (this.flow.values.label || "").trim();
        if (!label || !this.props.shell.packageId) {
            this.state.suggested = "";
            this.state.taken = false;
            return;
        }
        this.state.checking = true;
        try {
            const answer = await this.orm.call<SuggestNameAnswer>(
                "studio.app.builder",
                "suggest_name",
                [label, this.props.shell.packageId],
            );
            // Only the latest answer counts: the person keeps typing.
            if ((this.flow.values.label || "").trim() === label) {
                this.state.suggested = answer.model;
                this.state.taken = answer.taken;
                if (!this.flow.values.nameTouched) {
                    this.flow.values.model_name = answer.model;
                }
            }
        } finally {
            this.state.checking = false;
        }
    }

    get modelName(): string {
        return this.flow.values.model_name || this.state.suggested || "";
    }
}

class FeaturesStep extends Component<FlowStepProps> {
    static override template = "app_builder_model.BuildAppFeatures";
    static override props = { shell: Object, flow: Object };

    flow!: { values: BuildAppValues };
    orm!: OrmService;
    state!: { features: BuildAppFeatureEntry[]; defaults: string[] };

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState<{ features: BuildAppFeatureEntry[]; defaults: string[] }>({
            features: [],
            defaults: [],
        });
        onWillStart(async () => {
            const answer = await this.orm.call<FeaturesAnswer>(
                "studio.app.builder",
                "features",
                [],
            );
            this.state.features = answer.features;
            this.state.defaults = answer.defaults;
            if (!this.flow.values.features) {
                this.flow.values.features = [...answer.defaults];
            }
        });
    }

    /** What the tiles offer: a feature another one implies is not a tile. */
    get offered(): BuildAppFeatureEntry[] {
        return this.state.features.filter((f) => f.offered);
    }

    isOn(key: string): boolean {
        return (this.flow.values.features || []).includes(key);
    }

    toggle(key: string): void {
        const current = new Set(this.flow.values.features || []);
        if (current.has(key)) {
            current.delete(key);
        } else {
            current.add(key);
        }
        this.flow.values.features = [...current];
    }

    /** The one sentence a tile carries: what it builds, and its cost. */
    consequence(feature: BuildAppFeatureEntry): string {
        const parts: string[] = [];
        if (feature.help) {
            parts.push(feature.help);
        }
        if (feature.views && feature.views.length) {
            parts.push(String(_t("Adds: %s", feature.views.map((v) => "+ " + v).join(" "))));
        }
        if (feature.companion) {
            parts.push(
                String(
                    _t(
                        "Builds a second model (%s). Decided now: adding it later means building another app.",
                        feature.companion,
                    ),
                ),
            );
        }
        return parts.join(" ");
    }
}

class WhoStep extends Component<FlowStepProps> {
    static override template = "app_builder_model.BuildAppWho";
    static components = { MultiRecordSelector };
    static override props = { shell: Object, flow: Object };

    flow!: { values: BuildAppValues };
    orm!: OrmService;

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        onWillStart(async () => {
            if (!this.flow.values.groups) {
                // Internal User, by its xmlid: the default every app starts with.
                const ids = await this.orm.call<{ res_id: number }[]>(
                    "ir.model.data",
                    "search_read",
                    [
                        [
                            ["module", "=", "base"],
                            ["name", "=", "group_user"],
                        ],
                        ["res_id"],
                    ],
                );
                // A single bracket read of `ids[0]` right after the `.length`
                // guard is not narrowed by it under `noUncheckedIndexedAccess`
                // (the check is a different expression) -- captured into a
                // local first, the fix used throughout this migration for the
                // identical shape of trap (`create_package_flow.ts`'s own
                // `offered[0]`).
                const first = ids[0];
                this.flow.values.groups = first ? [first.res_id] : [];
            }
        });
    }

    get groupIds(): number[] {
        return this.flow.values.groups || [];
    }

    onGroups(ids: number[]): void {
        this.flow.values.groups = ids;
    }
}

class MenuStep extends Component<FlowStepProps> {
    static override template = "app_builder_model.BuildAppMenu";
    static components = { RecordSelector };
    static override props = { shell: Object, flow: Object };

    flow!: { values: BuildAppValues };

    override setup(): void {
        this.flow = useState(this.props.flow);
        if (!this.flow.values.menu_kind) {
            this.flow.values.menu_kind = "new_root";
        }
    }

    get parentId(): number | false {
        return this.flow.values.parent_menu_id || false;
    }

    onParent(id: number | false): void {
        this.flow.values.parent_menu_id = id || false;
    }
}

class ReviewStep extends Component<FlowStepProps<FlowStepShell>> {
    static override template = "app_builder_model.BuildAppReview";
    static override props = { shell: Object, flow: Object };

    flow!: { values: BuildAppValues };
    shell!: FlowStepShell;

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.shell = useState(this.props.shell);
    }

    get modelName(): string | undefined {
        return this.flow.values.model_name;
    }

    get fileName(): string {
        return (this.modelName || "").replace(/\./g, "_");
    }

    /** What lands on disk, in the order the package loads it. */
    get files(): string[] {
        const name = this.fileName;
        const features = this.flow.values.features || [];
        const files = [`models/${name}.py`];
        if (features.includes("tags")) {
            files.push(`models/${name}_tag.py`);
        }
        if (features.includes("lines")) {
            files.push(`models/${name}_line.py`);
        }
        files.push(`views/${name}_views.xml`, "views/menus.xml", "security/ir.model.access.csv");
        if (features.includes("reference")) {
            files.push(`data/${name}_sequence.xml`);
        }
        return files;
    }

    get manual(): boolean {
        return Boolean(this.shell.package && this.shell.package.reload_mode === "manual");
    }
}

/** One entry of `create_app_rpc`'s own `companions`
 * (`studio_app_builder.py:create_app_rpc`, one per Tags/Lines companion
 * model built alongside the app's own). */
interface CreateAppCompanion {
    model: string;
    access_ids: number[];
}

/** One row of `create_app_rpc`'s own `visibility`
 * (`studio_app_builder.py:check_visibility`) -- `ok` is `null` when no user
 * of the group could be found to check with at all, distinct from a real
 * pass/fail. */
interface CreateAppVisibilityEntry {
    group: string;
    ok: boolean | null;
    detail: string;
}

/**
 * `create_app_rpc`'s whole return (`studio_app_builder.py:create_app_rpc`).
 * `views` is genuinely dynamic -- keyed by whichever view types
 * `_build_views` actually built for this spec (`list`/`form`/`search`
 * always, plus whatever a ticked feature's own `views` asked for) -- so it
 * stays a plain index signature rather than a fixed set of optional keys;
 * every real read of it (`onDone`'s own `built.views["form"]`) goes
 * through bracket notation, which `noPropertyAccessFromIndexSignature`
 * requires for an index-signature-only type anyway.
 */
interface CreateAppResult {
    model: string;
    model_id: number;
    action_id: number;
    menu_id: number;
    root_menu_id: number | false;
    views: Record<string, number>;
    access_ids: number[];
    sequence_id: number | false;
    companions: CreateAppCompanion[];
    visibility: CreateAppVisibilityEntry[];
}

/**
 * The `shell` members `onDone` actually reads or writes -- narrowed the
 * same way `create_package_flow.ts`'s own `FlowShell` is: the real
 * `StudioShell` (`shell/shell_model.ts`) satisfies this structurally with
 * no change on its own side, and nothing here needs the other ~20 members
 * of the full class just to finish this one flow. `env` is typed no more
 * precisely than `compat.clearViewCaches`'s own (unexported) `EnvWithBus`
 * parameter needs.
 */
interface FlowShell {
    orm: OrmService;
    packageId: number | false;
    env: { bus: { trigger: (name: string) => void } };
    inventory: unknown;
    /** `StudioShell.callout` itself (`shell_model.ts`) is typed
     * `{key, title, lines} | null`, without `model` -- this flow (and
     * `adopt_model_flow.js`'s own still-untyped `onDone`) both build a
     * callout literal with an extra `model` key nothing ever reads back
     * (grepped every `.callout` read in the tree: `shell.xml` only shows
     * `key`/`title`/`lines`). `model` is optional here rather than
     * widening the real class's own field for a key nothing reads --
     * the real `StudioShell.callout` (no `model` at all) still satisfies
     * this structurally, since a missing optional property is fine, so
     * no change to `shell_model.ts` is needed for this file to compile.
     * Worth adding `model?: string` to `StudioShell.callout` itself the
     * day a second field or a real reader makes it worth widening
     * centrally (see this file's own `newSharedTypes` note). */
    callout: { key: string; title: string; lines: string[]; model?: string } | null;
    refreshPackages(): Promise<void>;
    openView(target: OpenViewTarget): Promise<void>;
}

paneRegistry.add("build_app", {
    // `PaneRegistration.label` is a plain `string`, never the
    // `string | Markup | LazyTranslatedString` union `_t()` itself
    // returns -- the same `String(_t(...))` pattern
    // `create_package_flow.ts` already uses throughout, applied here too.
    label: String(_t("Build an app")),
    icon: "fa fa-cubes",
    scope: "package",
    tab: false,
    flow: {
        key: "build_app",
        title: String(_t("Build an app")),
        doneLabel: String(_t("Build it")),
        steps: [
            {
                key: "name",
                label: String(_t("Name")),
                Component: NameStep,
                validate: (values: BuildAppValues): string => {
                    if (!(values.label || "").trim()) {
                        return String(_t("The app needs a name."));
                    }
                    // Captured once: reading `values.model_name` a third
                    // time inside this block, after the `.test()` call
                    // already ran, is exactly the "an intervening call can
                    // lose narrowing of a property read" shape TYPING.md's
                    // "Known traps" warns about -- a local `const` sidesteps
                    // the question rather than relying on it.
                    const modelName = values.model_name;
                    if (modelName && !/^[a-z][a-z0-9_.]*$/.test(modelName)) {
                        return String(
                            _t(
                                "'%s' is not a valid model name: lowercase letters, digits, dots and underscores.",
                                modelName,
                            ),
                        );
                    }
                    return "";
                },
            },
            { key: "features", label: String(_t("Features")), Component: FeaturesStep },
            {
                key: "who",
                label: String(_t("Who can use it")),
                Component: WhoStep,
                validate: (values: BuildAppValues): string =>
                    (values.groups || []).length
                        ? ""
                        : String(_t("Pick at least one group, or nobody can open it.")),
            },
            {
                key: "menu",
                label: String(_t("Menu")),
                Component: MenuStep,
                validate: (values: BuildAppValues): string =>
                    values.menu_kind === "under" && !values.parent_menu_id
                        ? String(_t("Say which app the menu goes under."))
                        : "",
            },
            { key: "review", label: String(_t("Review")), Component: ReviewStep },
        ],
        onDone: async (
            shell: FlowShell,
            flow: { values: BuildAppValues },
        ): Promise<CreateAppResult> => {
            const values = flow.values;
            const built = await shell.orm.call<CreateAppResult>(
                "studio.app.builder",
                "create_app_rpc",
                [
                    shell.packageId,
                    {
                        label: (values.label || "").trim(),
                        model_name: values.model_name || "",
                        features: values.features || [],
                        groups: values.groups || [],
                        menu:
                            values.menu_kind === "under"
                                ? { parent_id: values.parent_menu_id }
                                : { new_root: true },
                    },
                ],
            );
            // The registry changed under the web client: its view and menu
            // caches are stale.
            compat.clearViewCaches(shell.env);
            await shell.refreshPackages();
            shell.inventory = null;
            await shell.openView({
                model: built.model,
                view_type: "form",
                view_id: built.views["form"] || false,
            });
            shell.callout = {
                key: "built_app",
                title: String(_t("%s is live", (values.label || "").trim())),
                lines: [
                    String(
                        _t(
                            "Its form is on the canvas: drop fields on it, or open the other views from the switcher.",
                        ),
                    ),
                    String(_t("Automations, access and rules are one tab away.")),
                ],
                model: built.model,
            };
            return built;
        },
    },
});

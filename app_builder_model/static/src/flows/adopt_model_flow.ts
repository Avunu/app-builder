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
import { _t } from "@app_builder_view/console/l10n";
import { useService } from "@app_builder_view/console/odoo";
import * as compat from "@app_builder_view/console/compat";
import { paneRegistry } from "@app_builder_view/console/shell/pane_registry";
import type { OrmService } from "@app_builder_view/console/types";

/**
 * One entry of `adoptable_models()` (`studio_app_builder.py:adoptable_models`)
 * -- a manual `ir.model` no package defines in Python yet, with a preview of
 * the class the studio would write for it. `owner_package` is `None` when
 * the model was made entirely by hand in Settings › Technical, an object
 * when a package's own scaffolding created it (still adoptable if that
 * package never captured it in Python).
 */
interface AdoptableModelEntry {
    id: number;
    model: string;
    name: string;
    origin: "studio" | "manual";
    owner_package: { id: number; name: string } | null;
    field_count: number;
    record_count: number;
    preview: string;
}

/**
 * `adopt()`'s own answer (`studio_app_builder.py:adopt`) -- what names were
 * captured into the package, whether the reload actually applied, and
 * whether that reload needs a restart to take effect (`package.reload_mode
 * == "manual"`, mirrored on the answer as `restart_required` rather than
 * re-read off the package here).
 */
interface AdoptResult {
    adopted: string[];
    captured: string[];
    applied: boolean;
    restart_required: boolean;
}

/**
 * This flow's own `flow.values` bag (`flows/flow.ts:FlowModel.values`,
 * starting at `{}` since this registration passes no `spec.initial`):
 * which models are checked on the Choose step, and each one's preview
 * source, fetched once and kept for the Preview step to read back by name.
 */
interface AdoptModelValues {
    models?: string[];
    previews?: Record<string, string>;
}

/**
 * `shell_model.ts:openTarget`'s default branch -- this pane's own `scope`
 * is `"package"`, never `"views"`, so `open()` is always handed
 * `{model, packageId, ...paneState}`; only `model` is ever read here (when
 * the flow was opened from a model already on the crumb, e.g. from Home).
 */
interface AdoptModelTarget {
    model?: string;
}

/**
 * What every step of this flow receives (`flows/flow.ts`'s own contract: a
 * step component takes `{shell, flow}`). `shell` is typed `unknown` rather
 * than the real `StudioShell` (`shell/shell_model.ts`), matching
 * `create_package_flow.ts`'s own precedent: neither `ChooseStep` nor
 * `PreviewStep` below ever reads a member off it -- only `ReviewStep` does
 * (see its own, narrower `ReviewStepProps`), and this file's own `onDone`,
 * a separate function passed to the flow spec rather than a step, does the
 * rest (see `FlowShell`).
 */
interface FlowStepProps {
    shell: unknown;
    flow: { values: AdoptModelValues; target?: AdoptModelTarget };
}

class ChooseStep extends Component<FlowStepProps> {
    static override template = "app_builder_model.AdoptChoose";
    static override props = { shell: Object, flow: Object };

    flow!: { values: AdoptModelValues; target?: AdoptModelTarget };
    orm!: OrmService;
    state!: { models: AdoptableModelEntry[]; loading: boolean };

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState<{ models: AdoptableModelEntry[]; loading: boolean }>({
            models: [],
            loading: true,
        });
        onWillStart(async () => {
            this.state.models = await this.orm.call<AdoptableModelEntry[]>(
                "studio.app.builder",
                "adoptable_models",
                [],
            );
            this.state.loading = false;
            // Opened on a model from Home: it is the one chosen.
            const preset = this.flow.target && this.flow.target.model;
            if (preset && !this.flow.values.models) {
                this.flow.values.models = this.state.models.some((m) => m.model === preset)
                    ? [preset]
                    : [];
            }
            this.flow.values.models = this.flow.values.models || [];
            // Explicitly typed as a tuple array, not left to plain
            // array-literal inference: `.map((m) => [m.model, m.preview])`
            // would otherwise widen to a non-tuple `string[][]`, which
            // `Object.fromEntries` only accepts through its loose, untyped
            // fallback overload (`outline.ts:saveFolds` hit the identical
            // gap first; TYPING.md's "Implemented so far" has the account).
            const previewEntries: [string, string][] = this.state.models.map((m) => [
                m.model,
                m.preview,
            ]);
            this.flow.values.previews = Object.fromEntries(previewEntries);
        });
    }

    isOn(name: string): boolean {
        return (this.flow.values.models || []).includes(name);
    }

    toggle(name: string): void {
        const current = new Set(this.flow.values.models || []);
        if (current.has(name)) {
            current.delete(name);
        } else {
            current.add(name);
        }
        this.flow.values.models = [...current];
    }

    /** Where the model came from, in a phrase. */
    origin(entry: AdoptableModelEntry): unknown {
        if (entry.owner_package) {
            return _t("Made by the studio in %s, as records", entry.owner_package.name);
        }
        return _t("Made by hand in Settings › Technical");
    }
}

class PreviewStep extends Component<FlowStepProps> {
    static override template = "app_builder_model.AdoptPreview";
    static override props = { shell: Object, flow: Object };

    flow!: { values: AdoptModelValues; target?: AdoptModelTarget };

    override setup(): void {
        this.flow = useState(this.props.flow);
    }

    get previews(): { name: string; code: string }[] {
        const previews = this.flow.values.previews || {};
        return (this.flow.values.models || []).map((name) => ({
            name,
            code: previews[name] || "",
        }));
    }
}

/** What `ReviewStep` reads off `shell` -- just enough to answer whether the
 * package's own reload mode needs a restart (`StudioShell.package`,
 * `shell/shell_model.ts`, satisfies this structurally). */
interface ReviewShell {
    package: { reload_mode: string } | null;
}

interface ReviewStepProps {
    shell: ReviewShell;
    flow: { values: AdoptModelValues };
}

class ReviewStep extends Component<ReviewStepProps> {
    static override template = "app_builder_model.AdoptReview";
    static override props = { shell: Object, flow: Object };

    flow!: { values: AdoptModelValues };
    shell!: ReviewShell;

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.shell = useState(this.props.shell);
    }

    get files(): string[] {
        return (this.flow.values.models || []).map(
            (name) => `models/${name.replace(/\./g, "_")}.py`,
        );
    }

    get manual(): boolean {
        return Boolean(this.shell.package && this.shell.package.reload_mode === "manual");
    }
}

/**
 * The `shell` members `onDone` actually calls -- the same narrow-owner-
 * interface idea as `create_package_flow.ts`'s own `FlowShell` (the real
 * `StudioShell`, `shell/shell_model.ts`, satisfies this structurally with
 * no change on its own side): `orm`/`packageId` for the `adopt` RPC, `env`
 * for `compat.clearViewCaches`, `refreshPackages`/`openView` to land the
 * shell on the model now that it is Python, and `inventory`/`callout` to
 * leave the shell in the state a completed flow expects.
 */
interface FlowShell {
    orm: OrmService;
    packageId: number | false;
    env: { bus: { trigger: (name: string) => void } };
    inventory: unknown;
    refreshPackages(): Promise<void>;
    openView(target: { model?: string; view_type?: string }): Promise<void>;
    /** `StudioShell.callout`'s own type carries no `model` key -- only
     * `key`/`title`/`lines` (`shell_model.ts`, `shell.xml`'s own reads).
     * This flow (and its sibling `build_app_flow.js`, still untyped) sets
     * one anyway; typed `model?: string` here, optional, precisely so this
     * structurally still satisfies the real, narrower field -- see this
     * conversion's own findings for the dead-field question that raises. */
    callout: { key: string; title: string; lines: string[]; model?: string } | null;
}

paneRegistry.add("adopt_model", {
    // Lazy `_t` values, not `String(...)`: this runs at module load, before
    // translations exist (`PaneRegistration.label`).
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
                validate: (values: AdoptModelValues): string =>
                    (values.models || []).length ? "" : String(_t("Choose at least one model.")),
            },
            { key: "preview", label: _t("Preview"), Component: PreviewStep },
            { key: "review", label: _t("Review"), Component: ReviewStep },
        ],
        onDone: async (
            shell: FlowShell,
            flow: { values: AdoptModelValues },
        ): Promise<AdoptResult> => {
            const names = flow.values.models || [];
            const answer = await shell.orm.call<AdoptResult>("studio.app.builder", "adopt", [
                shell.packageId,
                names,
            ]);
            compat.clearViewCaches(shell.env);
            await shell.refreshPackages();
            shell.inventory = null;
            // The "choose" step's own `validate` above refuses to let the
            // flow advance with zero models picked, so `names` is never
            // empty by the time `onDone` runs -- an invariant
            // `noUncheckedIndexedAccess` cannot see across the two
            // separate functions (the same shape of fix `flow.ts:step`
            // already uses for its own always-in-range index read).
            const firstName = names[0]!;
            await shell.openView({ model: firstName, view_type: "form" });
            shell.callout = {
                key: "adopted",
                title: answer.restart_required
                    ? String(_t("%s is written; restart to make it Python", names.join(", ")))
                    : String(_t("%s is Python now", names.join(", "))),
                lines: [
                    String(
                        _t(
                            "Its fields live in models/ as a class; the studio keeps the marked block in sync and leaves the rest to you.",
                        ),
                    ),
                    String(_t("New fields on it are staged and applied with one reload.")),
                ],
                model: firstName,
            };
            return answer;
        },
    },
});

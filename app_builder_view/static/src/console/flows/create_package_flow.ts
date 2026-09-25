/** @odoo-module **/
/**
 * Create a package: a name, a place on the addons path, git.
 *
 * The first thing anybody does in the studio, and the one flow that must
 * not fail twenty minutes later: every reason a package could fail to
 * load is checked by the server before anything is written
 * (`studio.workspace.create_package`), and the review step says what
 * lands on disk.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { useService } from "../odoo";
import { paneRegistry } from "../shell/pane_registry";
import type { OrmService } from "../types";
import type { PackageEntryJSON } from "../wire";

/**
 * This flow's own `flow.values` bag -- built up one field at a time as
 * each step's own `setup()` runs (`FlowModel.values` starts at `{}`,
 * `flows/flow.js`; this registration passes no `spec.initial`). Every
 * field is optional on its own terms, not just defensively, since a step
 * earlier in the rail may not have run yet the moment a later one reads
 * its own field -- true in principle even though a flow always restarts
 * at its first step today, so nothing here actually depends on the
 * stronger guarantee holding.
 */
interface CreatePackageValues {
    title?: string;
    name?: string;
    nameTouched?: boolean;
    summary?: string;
    root_dir?: string;
    git_init?: boolean;
    auto_commit?: "off" | "stage" | "commit";
}

/**
 * What every step of this flow receives (`flows/flow.js`'s own contract:
 * a step component takes `{shell, flow}`). `shell` is typed `unknown`
 * rather than the real `StudioShell` (`shell/shell_model.ts`): none of
 * the four steps below ever reads a member off it directly -- only this
 * file's own `onDone`, a separate function passed to the flow spec
 * rather than a step, does that (see `FlowShell`). Typing it ahead of a
 * reader that does not exist here would be exactly what this migration's
 * own rule against that warns against (`DraftPayload.spec`,
 * `CanvasPayload.models`, ...). `flow` is the reactive `FlowModel`
 * instance (`flows/flow.js`, not yet converted) narrowed to the one
 * member every step reads and writes -- its own per-flow `values` bag.
 */
interface FlowStepProps {
    shell: unknown;
    flow: { values: CreatePackageValues };
}

class NameStep extends Component<FlowStepProps> {
    static override template = "app_builder_view.CreatePackageName";
    static override props = { shell: Object, flow: Object };

    flow!: { values: CreatePackageValues };

    override setup(): void {
        this.flow = useState(this.props.flow);
    }

    onTitle(ev: InputEvent): void {
        const title = (ev.target as HTMLInputElement).value;
        this.flow.values.title = title;
        if (!this.flow.values.nameTouched) {
            this.flow.values.name = slug(title);
        }
    }

    onName(ev: InputEvent): void {
        this.flow.values.name = (ev.target as HTMLInputElement).value.trim();
        this.flow.values.nameTouched = true;
    }
}

function slug(text: string): string {
    const base = (text || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
    return base && /^[a-z]/.test(base) ? base : base ? "x_" + base : "";
}

/** One entry of `addons_dirs()` -- a directory on the addons path, and
 * whether a new package could be written there
 * (`app_builder_base/models/studio_workspace.py:addons_dirs`). Core's own
 * directories are still listed (`kind: "core"`) so the picker can say why
 * they are not offered, never as something to write into.
 *
 * Not yet promoted to `wire.ts` alongside this same file's other
 * `studio_workspace.py` shapes (`PackageEntryJSON`, `UserPrefsJSON`,
 * `ApplyEntryJSON`) -- this is, so far, the only real caller of
 * `addons_dirs()`; belongs there the day a second one appears, per
 * `wire.ts`'s own "group by Python source" convention rather than "how
 * many callers".
 */
interface AddonsDirEntry {
    path: string;
    writable: boolean;
    kind: "core" | "custom" | "config";
}

class WhereStep extends Component<FlowStepProps> {
    static override template = "app_builder_view.CreatePackageWhere";
    static override props = { shell: Object, flow: Object };

    flow!: { values: CreatePackageValues };
    orm!: OrmService;
    state!: { dirs: AddonsDirEntry[] };

    override setup(): void {
        this.flow = useState(this.props.flow);
        this.orm = useService("orm");
        this.state = useState<{ dirs: AddonsDirEntry[] }>({ dirs: [] });
        onWillStart(async () => {
            this.state.dirs = await this.orm.call<AddonsDirEntry[]>(
                "studio.workspace",
                "addons_dirs",
                [],
            );
            const offered = this.state.dirs.filter((d) => d.writable);
            // `offered.length` was checked in the original just above this
            // read, but that does not narrow `offered[0]` itself under
            // `noUncheckedIndexedAccess` -- capturing the element into a
            // local first is the fix used throughout this migration for
            // the identical shape of trap.
            const first = offered[0];
            if (!this.flow.values.root_dir && first) {
                this.flow.values.root_dir = first.path;
            }
        });
    }

    get offered(): AddonsDirEntry[] {
        return this.state.dirs.filter((d) => d.kind !== "core");
    }

    get none(): boolean {
        return this.state.dirs.length > 0 && !this.offered.some((d) => d.writable);
    }
}

class GitStep extends Component<FlowStepProps> {
    static override template = "app_builder_view.CreatePackageGit";
    static override props = { shell: Object, flow: Object };

    flow!: { values: CreatePackageValues };

    override setup(): void {
        this.flow = useState(this.props.flow);
        if (this.flow.values.git_init === undefined) {
            this.flow.values.git_init = true;
        }
        if (!this.flow.values.auto_commit) {
            this.flow.values.auto_commit = "stage";
        }
    }

    get autoCommitHint(): string {
        // `this.flow.values.auto_commit` is always set by the moment this
        // getter can run -- `setup()`, just above, defaults it the first
        // time this step opens, and nothing else clears it -- but that
        // invariant lives across two separate calls (a `useState` proxy
        // read after a method boundary, not narrowing TS can see), so the
        // index below still needs a fallback to stay in the object
        // literal's own key type. `?? "stage"` matches `setup()`'s own
        // default and can never actually apply at render time.
        const key = this.flow.values.auto_commit ?? "stage";
        return String(
            {
                off: _t("Off: nothing is staged or committed; git is yours to run."),
                stage: _t(
                    "Stage only: every write is staged; you commit from Changes with a message of your own.",
                ),
                commit: _t(
                    "Commit each change: every write is a commit, with a message the studio makes up.",
                ),
            }[key],
        );
    }
}

class ReviewStep extends Component<FlowStepProps> {
    static override template = "app_builder_view.CreatePackageReview";
    static override props = { shell: Object, flow: Object };

    flow!: { values: CreatePackageValues };

    override setup(): void {
        this.flow = useState(this.props.flow);
    }

    get path() {
        const values = this.flow.values;
        return values.root_dir ? `${values.root_dir}/${values.name}` : values.name;
    }
}

/**
 * The four `shell` members `onDone` actually calls -- narrowed the same
 * way `ConsoleModelOwner` (`console_model.ts`) and `CanvasDragModel`
 * (`drag.ts`) were: the real `StudioShell` (`shell/shell_model.ts`)
 * satisfies this structurally with no change on its own side (`orm`,
 * `refreshPackages`, `setPackage` and `openPane` all match its real
 * declarations exactly), and nothing here needs the other ~25 members of
 * the full class just to finish this one flow.
 */
interface FlowShell {
    orm: OrmService;
    refreshPackages(): Promise<void>;
    setPackage(packageId: number | false): Promise<void>;
    openPane(key: string, patch?: Record<string, unknown>): Promise<void>;
}

paneRegistry.add("create_package", {
    // Lazy `_t` values, not `String(...)`: this runs at module load, before
    // translations exist (`PaneRegistration.label`).
    label: _t("Create a package"),
    icon: "fa fa-cube",
    scope: "package",
    tab: false,
    flow: {
        key: "create_package",
        title: _t("Create a package"),
        doneLabel: _t("Create package"),
        steps: [
            {
                key: "name",
                label: _t("Name"),
                Component: NameStep,
                validate: (values: CreatePackageValues): string => {
                    if (!values.name) {
                        return String(_t("The package needs a technical name."));
                    }
                    if (!/^[a-z][a-z0-9_]*$/.test(values.name)) {
                        return String(
                            _t(
                                "'%s' is not a valid module name: lowercase letters, digits and underscores, starting with a letter.",
                                values.name,
                            ),
                        );
                    }
                    return "";
                },
            },
            {
                key: "where",
                label: _t("Where"),
                Component: WhereStep,
                validate: (values: CreatePackageValues): string =>
                    values.root_dir
                        ? ""
                        : String(_t("No entry on the addons path can be written to.")),
            },
            { key: "git", label: _t("Git"), Component: GitStep },
            { key: "review", label: _t("Review"), Component: ReviewStep },
        ],
        onDone: async (
            shell: FlowShell,
            flow: { values: CreatePackageValues },
        ): Promise<PackageEntryJSON> => {
            const values = flow.values;
            const created = await shell.orm.call<PackageEntryJSON>(
                "studio.workspace",
                "create_package",
                [
                    {
                        name: values.name,
                        title: values.title || values.name,
                        summary: values.summary || "",
                        root_dir: values.root_dir,
                        git_init: Boolean(values.git_init),
                        auto_commit: values.auto_commit || "stage",
                    },
                ],
            );
            await shell.refreshPackages();
            await shell.setPackage(created.id);
            await shell.openPane("home", { created: created.id });
            return created;
        },
    },
});

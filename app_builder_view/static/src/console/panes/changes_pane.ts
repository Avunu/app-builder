/** @odoo-module **/
/**
 * Changes: what is pending, written, committed and applied, for the
 * package in the top bar.
 *
 * Four sections, in the order a change goes through them. Pending on
 * models: the drafts, with Apply and Discard. Written files: every file
 * the package generated, drifted ones first, with the diff between what
 * the database would write and what is on disk. Git: the branch, what is
 * uncommitted, a diff per file; the commit box is the sidebar. Apply
 * history: every apply, with its error verbatim and a rollback where
 * there is a backup to put back.
 */

import { Component, useState } from "@odoo/owl";
import { _t } from "../l10n";
import { ApplyDialog } from "../apply_dialog";
import { ConfirmationDialog, useService } from "../odoo";
import type { DialogService } from "../odoo";
import { messageOf } from "../shell/draft_model";
import type { PlaceResult } from "../shell/draft_model";
import { paneRegistry } from "../shell/pane_registry";
import type { StudioShell } from "../shell/shell_model";
import type { OdooRpcError, OrmService, PaneActivity, PaneModel } from "../types";
import type { ApplyEntryJSON, PackageEntryJSON } from "../wire";

// -- the "changes" RPC surface -----------------------------------------
//
// `studio.workspace.changes`/`git_diff`/`drift_diff`/`apply_diff`/`commit`
// (`app_builder_base/models/studio_workspace.py`), traced directly from
// their real Python construction rather than guessed. Kept local to this
// file rather than promoted to `wire.ts`, matching the precedent
// `canvas.ts`'s own `CanvasModelEntry` already set for a shape with
// exactly one real reader so far -- promote verbatim if a second file
// (a future `top_bar.ts`, say) ever needs the same shapes.

/** One entry of `changes()`'s `git.log` (`gitrepo.py:log`). Read only by
 * this file's own template (`changes_pane.xml`'s `git.log.slice(0, 5)`),
 * never by a `.ts` code path here -- typed fully anyway, since the real
 * shape was traced directly from the Python source and this is the one
 * file that renders it, unlike the "typing ahead of a reader" cases
 * elsewhere in this migration that involve a file not yet converted. */
interface ChangesGitLogEntry {
    sha: string;
    short: string;
    author: string;
    date: string;
    subject: string;
}

/** One entry of `changes()`'s `git.status` (`_git_status`). */
interface ChangesGitStatusEntry {
    path: string;
    /** A `git status --porcelain` code (`M`, `A`, `??`, a rename's `R100`,
     * ...), defaulting to `"M"` when the porcelain line names none. */
    state: string;
}

/** `changes()`'s own `git` block. */
interface ChangesGit {
    is_git: boolean;
    branch: string;
    status: ChangesGitStatusEntry[];
    log: ChangesGitLogEntry[];
    auto_commit: string;
}

/** One entry of `changes()`'s `drift` list -- a file whose disk copy
 * disagrees with what the database would write. */
interface ChangesDriftEntry {
    path: string;
    status: "missing" | "edited";
}

/** One entry of `changes()`'s `files` list -- every generated file, in
 * sync or not. */
interface ChangesFileEntry {
    path: string;
    status: "in_sync" | "missing" | "edited";
}

/** One entry of `changes()`'s `drafts` list (`_drafts`) -- a dirty
 * `studio.model.draft` on some model in the package, whether or not it is
 * this user's own. */
interface ChangesDraftSummary {
    id: number;
    model: string;
    change_count: number;
    user: { id: number; name: string };
    mine: boolean;
    write_date: string | false;
}

/** `changes()`'s whole return -- everything the pane and its sidebar
 * need in one call. */
interface ChangesPayload {
    package: PackageEntryJSON;
    drift: ChangesDriftEntry[];
    files: ChangesFileEntry[];
    pending_write: boolean;
    git: ChangesGit;
    applies: ApplyEntryJSON[];
    drafts: ChangesDraftSummary[];
}

/** `git_diff`/`drift_diff`/`apply_diff`'s common shape -- `git_diff` alone
 * also carries `truncated`, read by nothing here, so it stays optional on
 * this one shared shape rather than three near-identical interfaces. */
interface DiffResult {
    diff: string;
    truncated?: boolean;
}

/** `commit()`'s own answer (`studio_workspace.py:commit`) -- read by
 * `ChangesSidebar.onCommit`. */
type CommitResult = { committed: true; sha: string } | { committed: false; reason: string };

export class ChangesModel implements PaneModel {
    shell: StudioShell;
    orm: OrmService;
    changes: ChangesPayload | null;
    busy: boolean;
    error: string;
    opened: boolean;
    // Which file's diff is open, and the diff text per file.
    openDiff: string | null;
    diffs: Record<string, string | null>;
    /** Never read anywhere -- not by this file, not by its own template
     * (`changes_pane.xml`). Typed `unknown` rather than a guessed shape,
     * matching this migration's own rule against inventing a field's
     * shape with nothing to trace it against; flagged in this
     * conversion's own findings rather than silently dropped. */
    selected: unknown;

    constructor(shell: StudioShell) {
        this.shell = shell;
        this.orm = shell.orm;
        this.changes = null;
        this.busy = false;
        this.error = "";
        this.opened = false;
        this.openDiff = null;
        this.diffs = {};
        this.selected = null;
    }

    get activity(): PaneActivity {
        return { busy: this.busy, status: "saved", error: "", drag: null, applying: false };
    }

    get history(): null {
        return null;
    }

    async open(target: unknown): Promise<void> {
        void target;
        await this.reactivate();
    }

    async reactivate(): Promise<void> {
        if (!this.shell.packageId) {
            this.changes = null;
            return;
        }
        this.busy = true;
        this.error = "";
        try {
            this.changes = await this.orm.call<ChangesPayload>("studio.workspace", "changes", [
                this.shell.packageId,
            ]);
            this.diffs = {};
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.error = messageOf(err);
        } finally {
            this.busy = false;
        }
    }

    async afterApply(): Promise<void> {
        await this.reactivate();
    }

    /** One call on the workspace, then everything read again. */
    async act<T = unknown>(
        method: string,
        args: unknown[] = [],
        { packageFirst = true }: { packageFirst?: boolean } = {},
    ): Promise<T | undefined> {
        this.busy = true;
        this.error = "";
        try {
            const params = packageFirst ? [this.shell.packageId, ...args] : args;
            const result = await this.orm.call<T>("studio.workspace", method, params);
            await this.reactivate();
            await this.shell.refreshPackages();
            return result;
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.error = messageOf(err);
            return undefined;
        } finally {
            this.busy = false;
        }
    }

    /** A diff, read once per kind and path and kept until the next reload. */
    async toggleDiff(
        kind: "git" | "drift" | "apply",
        path: string,
        applyId: number | null = null,
    ): Promise<void> {
        const key = `${kind}:${applyId || ""}:${path}`;
        if (this.openDiff === key) {
            this.openDiff = null;
            return;
        }
        this.openDiff = key;
        if (this.diffs[key] !== undefined) {
            return;
        }
        this.diffs[key] = null;
        let result: DiffResult | undefined;
        try {
            if (kind === "git") {
                result = await this.orm.call<DiffResult>("studio.workspace", "git_diff", [
                    this.shell.packageId,
                    path,
                ]);
            } else if (kind === "drift") {
                result = await this.orm.call<DiffResult>("studio.workspace", "drift_diff", [
                    this.shell.packageId,
                    path,
                ]);
            } else {
                result = await this.orm.call<DiffResult>("studio.workspace", "apply_diff", [
                    applyId,
                    path,
                ]);
            }
            this.diffs[key] = result.diff || String(_t("(no difference)"));
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.diffs[key] = messageOf(err);
        }
    }
}

interface Props {
    shell: StudioShell;
    model: ChangesModel;
}

export class ChangesPane extends Component<Props> {
    static override template = "app_builder_view.ChangesPane";
    static override props = { shell: Object, model: { type: Object, optional: true } };

    shell!: StudioShell;
    model!: ChangesModel;
    dialog!: DialogService;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
    }

    get changes(): ChangesPayload | null {
        return this.model.changes;
    }

    get drafts(): ChangesDraftSummary[] {
        return (this.changes && this.changes.drafts) || [];
    }

    /** Every generated file, the drifted ones first. */
    get files(): ChangesFileEntry[] {
        const files = (this.changes && this.changes.files) || [];
        return files
            .slice()
            .sort(
                (a, b) =>
                    Number(a.status === "in_sync") - Number(b.status === "in_sync") ||
                    a.path.localeCompare(b.path),
            );
    }

    statusLabel(status: string): string {
        const labels: Record<string, ReturnType<typeof _t>> = {
            in_sync: _t("in sync"),
            edited: _t("edited on disk"),
            missing: _t("missing"),
        };
        return String(labels[status] || status);
    }

    get git(): ChangesGit | null {
        return (this.changes && this.changes.git) || null;
    }

    get applies(): ApplyEntryJSON[] {
        return (this.changes && this.changes.applies) || [];
    }

    applyState(apply: ApplyEntryJSON): string {
        const labels: Record<string, ReturnType<typeof _t>> = {
            pending: _t("In progress"),
            applied: _t("Applied"),
            awaiting_restart: _t("Awaiting restart"),
            failed: _t("Failed"),
            rolled_back: _t("Rolled back"),
        };
        return String(labels[apply.state] || apply.state);
    }

    diffKey(kind: "git" | "drift" | "apply", path: string, applyId: number | null = null): string {
        return `${kind}:${applyId || ""}:${path}`;
    }

    diffLines(key: string): { text: string; cls: string }[] {
        const text = this.model.diffs[key];
        if (!text) {
            return [];
        }
        return text.split("\n").map((line) => ({
            text: line,
            cls: line.startsWith("+")
                ? "add"
                : line.startsWith("-")
                  ? "del"
                  : line.startsWith("@@")
                    ? "hunk"
                    : "",
        }));
    }

    // -- actions ---------------------------------------------------------------

    openApply(): void {
        // `ApplyDialog`'s own `Props` (`apply_dialog.ts`, not exported)
        // declares `close: () => void` required, for its own internal
        // `this.props.close()` reads -- but no real caller of
        // `dialog.add(ApplyDialog, ...)` (this one, or `top_bar.js`'s
        // still-untyped sibling call) ever supplies one: the dialog
        // service injects `close` itself before constructing, the exact
        // reason `odoo.ts`'s own `ConfirmationDialogProps` deliberately
        // leaves `close` out of its own interface instead. `apply_dialog.ts`'s
        // `Props` was not given the same treatment (see this conversion's
        // own findings for the recommended fix there, which this file
        // cannot make itself). Asserted past the missing key here, the
        // same double-cast idiom `odoo.ts` itself already uses for
        // `ConfirmationDialogImpl`, rather than fabricating a no-op
        // `close` that would silently break the dialog's own real close
        // behavior.
        this.dialog.add(ApplyDialog, { shell: this.props.shell } as unknown as {
            shell: StudioShell;
            close: () => void;
        });
    }

    onDiscardDraft(draft: ChangesDraftSummary): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s) on %s? Nothing has been applied, so nothing else is lost.",
                draft.change_count,
                draft.model,
            ),
            confirmLabel: _t("Discard"),
            confirm: () => {
                // The original discards, then re-reads -- in that order,
                // not two independent fire-and-forget calls -- so the
                // sequence is kept exactly as an async IIFE, wrapped in
                // `void` the same way `apply_dialog.ts`'s own
                // `onDiscard`/`remove_flow.ts`'s `confirm` already handle
                // a promise-returning body against `ConfirmationDialogProps.confirm`'s
                // `() => void` type.
                void (async () => {
                    await this.shell.discard();
                    await this.model.reactivate();
                })();
            },
            cancel: () => {},
        });
    }

    async onPlacePending(): Promise<void> {
        const result: PlaceResult = await this.shell.draft.placePending();
        if (!result.placed && result.reason) {
            this.model.error = result.reason;
        }
        await this.model.reactivate();
    }

    onReloadFile(): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Reload from disk"),
            body: _t(
                "Re-reads the package from disk into the database; the hand edits become the records. The package is reloaded.",
            ),
            confirmLabel: _t("Reload"),
            confirm: () => {
                void this.model.act("reload");
            },
            cancel: () => {},
        });
    }

    onWriteFiles(): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Write to disk"),
            body: _t("Overwrites the files with what the database says; hand edits are lost."),
            confirmLabel: _t("Write"),
            confirm: () => {
                void this.model.act("write_files");
            },
            cancel: () => {},
        });
    }

    onCheckDrift(): Promise<unknown> {
        return this.model.act("check_drift");
    }

    onRollback(apply: ApplyEntryJSON): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Roll back"),
            body: _t(
                'Puts back the %s file(s) as they were before "%s" and reloads the package. The apply is recorded as rolled back; its backup is kept until you discard it.',
                apply.files.length,
                apply.reason,
            ),
            confirmLabel: _t("Roll back"),
            confirm: () => {
                void this.model.act("rollback", [apply.id], { packageFirst: false });
            },
            cancel: () => {},
        });
    }

    onDiscardBackup(apply: ApplyEntryJSON): void {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard backup"),
            body: _t("Deletes the backup copy; this apply can no longer be rolled back."),
            confirmLabel: _t("Discard backup"),
            confirm: () => {
                void this.model.act("discard_backup", [apply.id], { packageFirst: false });
            },
            cancel: () => {},
        });
    }
}

interface SidebarState {
    message: string;
    result: string;
}

export class ChangesSidebar extends Component<Props> {
    static override template = "app_builder_view.ChangesSidebar";
    static override props = { shell: Object, model: { type: Object, optional: true } };

    shell!: StudioShell;
    model!: ChangesModel;
    state!: SidebarState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.state = useState<SidebarState>({ message: "", result: "" });
    }

    get git(): ChangesGit | null {
        return (this.model.changes && this.model.changes.git) || null;
    }

    get dirtyCount(): number {
        return this.git ? this.git.status.length : 0;
    }

    get summary(): string {
        const status = this.git ? this.git.status : [];
        const modified = status.filter((s) => s.state !== "??" && s.state !== "A").length;
        const added = status.length - modified;
        return String(_t("%s files · %s modified · %s new", status.length, modified, added));
    }

    get autoCommitHint(): string {
        const mode = this.git && this.git.auto_commit;
        const hints: Record<string, ReturnType<typeof _t>> = {
            off: _t("Off: nothing is staged or committed; git is yours to run."),
            stage: _t(
                "Stage only: every write is staged; you commit from here with a message of your own.",
            ),
            commit: _t(
                "Commit each change: every write is a commit, with a message the studio makes up.",
            ),
        };
        return String((mode ? hints[mode] : undefined) || "");
    }

    async onAutoCommit(ev: Event): Promise<void> {
        await this.model.act("set_auto_commit", [(ev.target as HTMLSelectElement).value]);
    }

    async onCommit(): Promise<void> {
        const result = await this.model.act<CommitResult>("commit", [this.state.message]);
        if (result && result.committed) {
            this.state.result = String(
                _t("Committed %s · nothing to commit.", result.sha.slice(0, 7)),
            );
            this.state.message = "";
        } else if (result) {
            this.state.result = result.reason || "";
        }
    }

    async onGitInit(): Promise<void> {
        await this.model.act("git_init");
    }
}

paneRegistry.add(
    "changes",
    {
        label: _t("Changes"),
        icon: "fa fa-code-fork",
        scope: "package",
        Component: ChangesPane,
        sidebar: ChangesSidebar,
        // `PaneRegistration.makeModel` is a *property* typed as an arrow
        // function (`((shell: unknown) => PaneModel) | null`), not a
        // method-shorthand signature -- unlike `FlowSpec.onDone`
        // (`types.ts`), which is a method shorthand and so gets TS's
        // bivariant method-parameter check for free (see
        // `create_package_flow.ts`'s own `FlowShell`, the same
        // narrow-owner-interface idea, which relies on exactly that
        // exemption). A property-typed function is checked contravariantly
        // under `strictFunctionTypes`, so `ChangesModel`'s constructor
        // keeps taking the real `StudioShell` (matching
        // `record_pane_model.ts`'s own precedent) and the cast happens
        // here instead, inside a wrapper whose own parameter is left
        // unannotated so TS infers it as the target property's `unknown`
        // from context -- the same shape of fix `resolvePane`
        // (`pane_registry.ts`) already uses for `Registry.get`.
        makeModel: (shell) => new ChangesModel(shell as StudioShell),
    },
    { sequence: 900 },
);

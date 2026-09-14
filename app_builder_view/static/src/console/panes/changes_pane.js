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
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { ApplyDialog } from "../apply_dialog";
import { messageOf } from "../shell/draft_model";
import { paneRegistry } from "../shell/pane_registry";

export class ChangesModel {
    constructor(shell) {
        this.shell = shell;
        this.orm = shell.orm;
        this.changes = null;
        this.busy = false;
        this.error = "";
        this.opened = false;
        // Which file's diff is open, and the diff text per file.
        this.openDiff = null;
        this.diffs = {};
        this.selected = null;
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
        if (!this.shell.packageId) {
            this.changes = null;
            return;
        }
        this.busy = true;
        this.error = "";
        try {
            this.changes = await this.orm.call("studio.workspace", "changes", [this.shell.packageId]);
            this.diffs = {};
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.error = messageOf(err);
        } finally {
            this.busy = false;
        }
    }

    async afterApply() {
        await this.reactivate();
    }

    /** One call on the workspace, then everything read again. */
    async act(method, args = [], { packageFirst = true } = {}) {
        this.busy = true;
        this.error = "";
        try {
            const params = packageFirst ? [this.shell.packageId, ...args] : args;
            const result = await this.orm.call("studio.workspace", method, params);
            await this.reactivate();
            await this.shell.refreshPackages();
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

    /** A diff, read once per kind and path and kept until the next reload. */
    async toggleDiff(kind, path, applyId = null) {
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
        let result;
        try {
            if (kind === "git") {
                result = await this.orm.call("studio.workspace", "git_diff", [this.shell.packageId, path]);
            } else if (kind === "drift") {
                result = await this.orm.call("studio.workspace", "drift_diff", [this.shell.packageId, path]);
            } else {
                result = await this.orm.call("studio.workspace", "apply_diff", [applyId, path]);
            }
            this.diffs[key] = result.diff || _t("(no difference)");
        } catch (err) {
            if (!(err && err.data)) {
                throw err;
            }
            this.diffs[key] = messageOf(err);
        }
    }
}

export class ChangesPane extends Component {
    static template = "app_builder_view.ChangesPane";
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
    }

    get changes() {
        return this.model.changes;
    }

    get drafts() {
        return (this.changes && this.changes.drafts) || [];
    }

    /** Every generated file, the drifted ones first. */
    get files() {
        const files = (this.changes && this.changes.files) || [];
        return files
            .slice()
            .sort(
                (a, b) =>
                    (a.status === "in_sync") - (b.status === "in_sync") ||
                    a.path.localeCompare(b.path)
            );
    }

    statusLabel(status) {
        return { in_sync: _t("in sync"), edited: _t("edited on disk"), missing: _t("missing") }[status] || status;
    }

    get git() {
        return (this.changes && this.changes.git) || null;
    }

    get applies() {
        return (this.changes && this.changes.applies) || [];
    }

    applyState(apply) {
        return {
            pending: _t("In progress"),
            applied: _t("Applied"),
            awaiting_restart: _t("Awaiting restart"),
            failed: _t("Failed"),
            rolled_back: _t("Rolled back"),
        }[apply.state] || apply.state;
    }

    diffKey(kind, path, applyId = null) {
        return `${kind}:${applyId || ""}:${path}`;
    }

    diffLines(key) {
        const text = this.model.diffs[key];
        if (!text) {
            return [];
        }
        return text.split("\n").map((line) => ({
            text: line,
            cls: line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : "",
        }));
    }

    // -- actions ---------------------------------------------------------------

    openApply() {
        this.dialog.add(ApplyDialog, { shell: this.props.shell });
    }

    onDiscardDraft(draft) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s) on %s? Nothing has been applied, so nothing else is lost.",
                draft.change_count,
                draft.model
            ),
            confirmLabel: _t("Discard"),
            confirm: async () => {
                await this.shell.discard();
                await this.model.reactivate();
            },
            cancel: () => {},
        });
    }

    async onPlacePending() {
        const result = await this.shell.draft.placePending();
        if (!result.placed && result.reason) {
            this.model.error = result.reason;
        }
        await this.model.reactivate();
    }

    onReloadFile() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Reload from disk"),
            body: _t(
                "Re-reads the package from disk into the database; the hand edits become the records. The package is reloaded."
            ),
            confirmLabel: _t("Reload"),
            confirm: () => this.model.act("reload"),
            cancel: () => {},
        });
    }

    onWriteFiles() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Write to disk"),
            body: _t("Overwrites the files with what the database says; hand edits are lost."),
            confirmLabel: _t("Write"),
            confirm: () => this.model.act("write_files"),
            cancel: () => {},
        });
    }

    onCheckDrift() {
        return this.model.act("check_drift");
    }

    onRollback(apply) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Roll back"),
            body: _t(
                'Puts back the %s file(s) as they were before "%s" and reloads the package. The apply is recorded as rolled back; its backup is kept until you discard it.',
                apply.files.length,
                apply.reason
            ),
            confirmLabel: _t("Roll back"),
            confirm: () => this.model.act("rollback", [apply.id], { packageFirst: false }),
            cancel: () => {},
        });
    }

    onDiscardBackup(apply) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard backup"),
            body: _t("Deletes the backup copy; this apply can no longer be rolled back."),
            confirmLabel: _t("Discard backup"),
            confirm: () => this.model.act("discard_backup", [apply.id], { packageFirst: false }),
            cancel: () => {},
        });
    }
}

export class ChangesSidebar extends Component {
    static template = "app_builder_view.ChangesSidebar";
    static props = { shell: Object, model: { type: Object, optional: true } };

    setup() {
        this.shell = useState(this.props.shell);
        this.model = useState(this.props.model);
        this.state = useState({ message: "", result: "" });
    }

    get git() {
        return (this.model.changes && this.model.changes.git) || null;
    }

    get dirtyCount() {
        return this.git ? this.git.status.length : 0;
    }

    get summary() {
        const status = this.git ? this.git.status : [];
        const modified = status.filter((s) => s.state !== "??" && s.state !== "A").length;
        const added = status.length - modified;
        return _t("%s files · %s modified · %s new", status.length, modified, added);
    }

    get autoCommitHint() {
        const mode = this.git && this.git.auto_commit;
        return {
            off: _t("Off: nothing is staged or committed; git is yours to run."),
            stage: _t("Stage only: every write is staged; you commit from here with a message of your own."),
            commit: _t("Commit each change: every write is a commit, with a message the studio makes up."),
        }[mode] || "";
    }

    async onAutoCommit(ev) {
        await this.model.act("set_auto_commit", [ev.target.value]);
    }

    async onCommit() {
        const result = await this.model.act("commit", [this.state.message]);
        if (result && result.committed) {
            this.state.result = _t("Committed %s · nothing to commit.", result.sha.slice(0, 7));
            this.state.message = "";
        } else if (result) {
            this.state.result = result.reason || "";
        }
    }

    async onGitInit() {
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
        makeModel: (shell) => new ChangesModel(shell),
    },
    { sequence: 900 }
);

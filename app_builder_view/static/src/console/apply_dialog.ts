/** @odoo-module **/
/**
 * Apply: the one moment a staged changeset becomes real.
 *
 * Everything staged on a Python-owned model is a class attribute waiting
 * for the package to be written and re-imported, and that is not a click
 * to make lightly: it reloads the package -- in place, or by restarting
 * the server, depending on how it runs -- and a removal may drop a column
 * with data in it. So the dialog says, before the button is pressed,
 * exactly what will happen: every pending change, the ones that would
 * lose data marked as such and held behind an explicit "Apply anyway",
 * the diff of the source that will be written for anyone who wants to
 * read it, and what the reload will cost on this server. Under `manual`
 * reload the server cannot pick the change up by itself, so staging is
 * allowed and Apply is not, with the reason where the button is.
 *
 * While it runs the dialog stays up over the canvas, spinner and all --
 * the canvas is about to be rebuilt, and nothing on it should be touched
 * meanwhile. Success closes it with a toast; a refusal keeps it open with
 * the server's sentence, so the answer can be read against the list that
 * caused it. A field the canvas has no ghost for -- dropped on another
 * view of the model, or never dropped anywhere -- is listed with a word
 * on where it will land, since nothing else on this screen says so.
 *
 * "Discard all" is the top bar's Discard by another door, and asks the
 * same question first: it throws away every staged definition, and a
 * mis-click beside Apply must not be the end of them.
 */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "./l10n";
import { ConfirmationDialog, useService } from "./odoo";
import type { DialogService } from "./odoo";
import type { PendingChangeJSON } from "./wire";
import type { ConsoleModel } from "./console_model";
import type { DraftModel } from "./shell/draft_model";
import type { StudioShell } from "./shell/shell_model";

/** `{shell, close}`, as `static props` below validates it: the shell in
 * hand (read live through `useState`, same object the rest of the
 * console shares) and the dialog service's own `close`. */
interface Props {
    shell: StudioShell;
    close: () => void;
}

/**
 * The dialog's own local state -- everything here is UI bookkeeping, not
 * part of the shell or the draft. `diff` starts `null` (not yet asked
 * for) rather than `""` (asked for and empty), so `toggleDiff` can tell
 * "never fetched" from "fetched, empty" and not re-fetch on every
 * re-open of the same session.
 */
interface ApplyDialogState {
    allowDestructive: boolean;
    showDiff: boolean;
    diff: string | null;
    loadingDiff: boolean;
    error: string;
    refusedAsDestructive: boolean;
}

export class ApplyDialog extends Component<Props> {
    // `template`/`props` are both declared on Owl's own `Component` base
    // class (`template: string`, `props?: Schema`), so `noImplicitOverride`
    // requires `override` here; `components` is not a static member of
    // `Component` itself (only of the unrelated `StaticComponentProperties`
    // helper type `ComponentConstructor` uses), so `override` on it is a
    // real `tsc` error ("not declared in the base class") -- confirmed
    // against `node_modules/@odoo/owl/dist/types/runtime/component.d.ts`
    // directly, not guessed.
    static override template = "app_builder_view.ApplyDialog";
    static components = { Dialog };
    static override props = {
        shell: Object,
        close: Function,
    };

    // Assigned in `setup()`, not a field initializer or the constructor
    // (Owl components are set up through the `setup()` lifecycle hook, not
    // a constructor this class writes its own) -- `declare` here adds a
    // compile-time type and nothing else: no field-initializer emission,
    // so the emitted `.js` is unchanged, and `strictPropertyInitialization`
    // does not ask for an assignment it cannot see.
    declare shell: StudioShell;
    declare dialog: DialogService;
    declare state: ApplyDialogState;

    override setup(): void {
        this.shell = useState(this.props.shell);
        this.dialog = useService("dialog");
        this.state = useState<ApplyDialogState>({
            allowDestructive: false,
            showDiff: false,
            diff: null,
            loadingDiff: false,
            error: "",
            refusedAsDestructive: false,
        });
    }

    get title(): string {
        return String(_t("Apply %s pending change(s)", this.draft.pendingCount));
    }

    /** The shell's draft on the model in hand. */
    get draft(): DraftModel {
        return this.shell.draft;
    }

    /**
     * The Views pane's own model, when the console is on a canvas.
     * `shell.activeModel` is typed to the generic `PaneModel` contract
     * every pane satisfies (`shell_model.ts`); the real object it holds
     * whenever `pane === "views"` is always a `ConsoleModel`
     * (`views_pane.js`'s own registration is the one thing that ever puts
     * something there under that key), so the downcast asserts an
     * invariant the caller below already relies on (`.pending`/`.viewId`,
     * neither part of the generic `PaneModel` contract) rather than
     * guessing a shape -- `ConsoleModel implements PaneModel`, so the two
     * are related types and the assertion is a real narrowing.
     */
    get views(): ConsoleModel | null {
        return this.shell.pane === "views" ? (this.shell.activeModel as ConsoleModel | null) : null;
    }

    get changes(): PendingChangeJSON[] {
        return this.draft.pendingChanges;
    }

    /**
     * For an added field the canvas does not draw, where it will land:
     * anchored on another view of the model, or placed by the balanced
     * fallback. `""` for a field with a ghost, or a change that is not
     * an addition.
     *
     * An anchor on *this* view whose ghost could not be spliced -- the
     * neighbour is gone and the view has no fallback spot to draw at, as
     * a kanban has not -- is the fallback case too: the field was dropped
     * here, and it is the balanced placement that will put it here.
     */
    whereabouts(change: PendingChangeJSON): string {
        // `this.views` is a getter (it re-derives from `this.shell.pane`/
        // `this.shell.activeModel` on every call, not a plain field), so a
        // second read does not stay narrowed past the guard below the way
        // a plain property would -- captured once into a local instead,
        // the same fix this migration has used everywhere else a nullable
        // `this.<field>` is read more than once (TYPING.md's own "Known
        // traps").
        const views = this.views;
        if (change.kind !== "added" || !views) {
            return "";
        }
        const entry = views.pending.find((p) => p.name === change.name);
        if (!entry || entry.placed) {
            return "";
        }
        if (entry.view_id && entry.view_id !== views.viewId) {
            return String(_t("Not on this canvas: it was dropped on another view of this model."));
        }
        return String(_t("Not on this canvas: it will be placed automatically after Apply."));
    }

    get errors(): string[] {
        return this.draft.errors;
    }

    /** Whether anything here would lose data, so "Apply anyway" is offered. */
    get hasDestructive(): boolean {
        return this.state.refusedAsDestructive || this.changes.some((change) => change.destructive);
    }

    get reloadMode(): string | false {
        return this.draft.reloadMode;
    }

    get reloadNotice(): string {
        if (this.reloadMode === "manual") {
            return String(
                _t(
                    "This server runs several workers, so it cannot reload in place. " +
                        "The files are written and the package is marked for upgrade; " +
                        "restart the server and Odoo loads it on the way up. Until then " +
                        "the fields are in the file, not in the database.",
                ),
            );
        }
        return String(_t("Applying reloads this package in place. It takes a moment."));
    }

    /** What the primary button says: a write under workers, an apply otherwise. */
    get applyLabel(): string {
        return this.reloadMode === "manual" ? String(_t("Write files")) : String(_t("Apply"));
    }

    /** Why Apply cannot be pressed, or `""`. */
    get blocker(): string {
        const blocker = this.draft.applyBlocker;
        if (blocker) {
            return blocker;
        }
        if (this.hasDestructive && !this.state.allowDestructive) {
            return String(_t('Tick "Apply anyway" to accept the data that would be kept aside.'));
        }
        return "";
    }

    get canApply(): boolean {
        return !this.draft.applying && !this.blocker;
    }

    get applying(): boolean {
        return this.draft.applying;
    }

    async toggleDiff(): Promise<void> {
        this.state.showDiff = !this.state.showDiff;
        if (this.state.showDiff && this.state.diff === null) {
            this.state.loadingDiff = true;
            try {
                this.state.diff = await this.draft.previewDiff();
            } finally {
                this.state.loadingDiff = false;
            }
        }
    }

    async onApply(): Promise<void> {
        if (!this.canApply) {
            return;
        }
        this.state.error = "";
        const result = await this.shell.apply(this.state.allowDestructive);
        if (result.ok) {
            this.props.close();
            return;
        }
        this.state.error = result.message;
        if (result.destructive) {
            // Refused once, on purpose, so the loss is read before it is
            // accepted; the checkbox appears with the sentence.
            this.state.refusedAsDestructive = true;
        }
    }

    onDiscard(): void {
        if (this.applying || this.shell.activity.busy) {
            return;
        }
        // `ConfirmationDialog`'s props are typed against `odoo.ts`'s own
        // `ConfirmationDialogProps` (see that file for why it is
        // re-exported from there rather than imported straight from the
        // vendor module). `title`/`body`/`confirmLabel` are left as the
        // lazy `_t(...)` values themselves (not `String(...)`-eagerly-
        // stringified, unlike this file's own plain-string getters above)
        // since they are handed straight to another component's props,
        // the one case `odoo.ts`'s own docstring calls out for keeping
        // the lazy value.
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
                this.draft.pendingCount,
            ),
            confirmLabel: _t("Discard"),
            confirm: () => {
                this.props.close();
                void this.shell.discard();
            },
            cancel: () => {},
        });
    }
}

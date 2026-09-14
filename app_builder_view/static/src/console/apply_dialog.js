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
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

export class ApplyDialog extends Component {
    static template = "app_builder_view.ApplyDialog";
    static components = { Dialog };
    static props = {
        model: Object,
        close: Function,
    };

    setup() {
        this.model = useState(this.props.model);
        this.dialog = useService("dialog");
        this.state = useState({
            allowDestructive: false,
            showDiff: false,
            diff: null,
            loadingDiff: false,
            error: "",
            refusedAsDestructive: false,
        });
    }

    get title() {
        return _t("Apply %s pending change(s)", this.model.pendingCount);
    }

    get changes() {
        return this.model.pendingChanges;
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
    whereabouts(change) {
        if (change.kind !== "added") {
            return "";
        }
        const entry = this.model.pending.find((p) => p.name === change.name);
        if (!entry || entry.placed) {
            return "";
        }
        if (entry.view_id && entry.view_id !== this.model.viewId) {
            return _t("Not on this canvas: it was dropped on another view of this model.");
        }
        return _t("Not on this canvas: it will be placed automatically after Apply.");
    }

    get errors() {
        return this.model.draftErrors;
    }

    /** Whether anything here would lose data, so "Apply anyway" is offered. */
    get hasDestructive() {
        return this.state.refusedAsDestructive || this.changes.some((change) => change.destructive);
    }

    get reloadMode() {
        return this.model.reloadMode;
    }

    get reloadNotice() {
        const mode = this.reloadMode;
        if (mode === "manual") {
            return _t(
                "This server runs several workers, so it cannot reload in place. " +
                    "Staging works; to apply, restart the server after writing the package."
            );
        }
        if (mode === "restart") {
            return _t(
                "Applying restarts the server, which takes a few seconds; the console reconnects by itself."
            );
        }
        return _t("Applying reloads this package in place. It takes a moment.");
    }

    /** Why Apply cannot be pressed, or `""`. */
    get blocker() {
        const blocker = this.model.applyBlocker;
        if (blocker) {
            return blocker;
        }
        if (this.hasDestructive && !this.state.allowDestructive) {
            return _t("Tick \"Apply anyway\" to accept the data that would be kept aside.");
        }
        return "";
    }

    get canApply() {
        return !this.model.applying && !this.blocker;
    }

    get applying() {
        return this.model.applying;
    }

    async toggleDiff() {
        this.state.showDiff = !this.state.showDiff;
        if (this.state.showDiff && this.state.diff === null) {
            this.state.loadingDiff = true;
            try {
                this.state.diff = await this.model.previewDiff();
            } finally {
                this.state.loadingDiff = false;
            }
        }
    }

    async onApply() {
        if (!this.canApply) {
            return;
        }
        this.state.error = "";
        const result = await this.model.applyDraft(this.state.allowDestructive);
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

    onDiscard() {
        if (this.applying || this.model.busy) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard pending changes"),
            body: _t(
                "Throw away the %s staged change(s)? Nothing has been applied, so nothing else is lost.",
                this.model.pendingCount
            ),
            confirmLabel: _t("Discard"),
            confirm: () => {
                this.props.close();
                this.model.discardDraft();
            },
            cancel: () => {},
        });
    }
}

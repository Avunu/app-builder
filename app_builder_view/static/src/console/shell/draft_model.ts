/** @odoo-module **/
/**
 * A Python-owned model's staged changes, held by the shell for every pane.
 *
 * A field dropped on a Python-owned model is a class attribute waiting for
 * an Apply, staged on this user's `studio.model.draft`; the draft is per
 * model, not per view, and the pill that counts what is pending and the
 * button that applies it belong to the top bar on every pane. So the
 * draft lives here, on the shell, and the Views pane's model reads it
 * through thin delegations rather than owning it.
 *
 * What this knows: the draft's payload as `studio.model.draft.load()`
 * returns it, whether an Apply is running, and the hints the view's
 * editing context carries about a draft that exists but has not been
 * read (`draft_id`, `reload_mode`). What it does: every call on the
 * draft, Apply, Discard, and the diff for the dialog. What it never does:
 * refresh a canvas -- the pane that asked refreshes itself.
 *
 * No Owl in here. Reactivity is the caller's business (`useState` on the
 * shell); this class is plain so it can be tested and ported as it is.
 */

import { markRaw } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import type { NotificationService, OdooRpcError, OrmService } from "../types";
import type { DraftFieldJSON, DraftPackageJSON, DraftPayload, PendingChangeJSON } from "../wire";

/** The sentence an RPC error carries for the user. */
export function messageOf(err: unknown): string {
    const rpcErr = err as OdooRpcError | undefined;
    if (rpcErr?.data?.message) {
        return rpcErr.data.message;
    }
    return rpcErr?.message || String(_t("Something went wrong."));
}

/** What the shell (`ShellModel`) answers that `DraftModel` needs of its owner. */
export interface DraftModelOwner {
    modelName: string | null;
    packageId: number | false | null;
    pythonOwned: boolean;
}

/** A hint the view's editing context carries about a draft that exists
 * but has not been read yet (`setHints`). */
export interface DraftHints {
    draft_id?: number | false;
    reload_mode?: string | false;
}

/** One entry of `modelFields`: a draft field with the kind of pending
 * change it carries, or `null` when it has none. A field the draft has
 * removed but that `fields` no longer lists gets a synthetic minimal
 * entry (`{name, string, pendingKind: "removed"}`) rather than the full
 * `DraftFieldJSON` shape, so this only requires what both share. */
export interface DraftFieldWithPending extends Partial<DraftFieldJSON> {
    name: string;
    pendingKind: PendingChangeJSON["kind"] | null;
}

/** What `apply()` reports back: whether it went through, and how. */
export type ApplyResult =
    { ok: true; restartRequired: boolean } | { ok: false; message: string; destructive: boolean };

/** What `placePending()` reports back. */
export interface PlaceResult {
    placed: boolean;
    reason: string;
}

export class DraftModel {
    env: { services: { orm: OrmService; notification: NotificationService } };
    orm: OrmService;
    notification: NotificationService;
    owner: DraftModelOwner;
    draft: DraftPayload | null;
    applying: boolean;
    busy: boolean;
    /** What the editing context said about a draft not yet read. */
    hints: { draft_id: number | false; reload_mode: string | false };

    constructor(
        env: { services: { orm: OrmService; notification: NotificationService } },
        owner: DraftModelOwner,
    ) {
        this.env = env;
        this.orm = env.services.orm;
        this.notification = env.services.notification;
        this.owner = owner;
        this.draft = null;
        this.applying = false;
        this.busy = false;
        this.hints = { draft_id: false, reload_mode: false };
    }

    // -- reading ------------------------------------------------------------

    get modelName(): string | null {
        return this.owner.modelName;
    }

    get pythonOwned(): boolean {
        return Boolean(this.owner.pythonOwned);
    }

    /** The draft addressed, from whichever answer named it last. */
    get draftId(): number | false {
        return this.draft?.id || this.hints.draft_id || false;
    }

    get pendingCount(): number {
        return this.draft?.change_count || 0;
    }

    /** The staged changes, as the draft lists them for its tray. */
    get pendingChanges(): PendingChangeJSON[] {
        return this.draft?.pending || [];
    }

    get errors(): string[] {
        return this.draft?.errors || [];
    }

    get package(): DraftPackageJSON | null {
        return this.draft?.package || null;
    }

    /** `inproc` or `manual`: what an Apply costs on this server. */
    get reloadMode(): string | false {
        return this.package?.reload_mode || this.hints.reload_mode || false;
    }

    /** Why Apply is not on offer right now, or `""` when it is. */
    get applyBlocker(): string {
        if (!this.pendingCount) {
            return String(_t("Nothing is pending."));
        }
        if (this.package && !this.package.writable) {
            return String(_t("This package is read-only, so nothing can be applied."));
        }
        if (this.errors.length) {
            return this.errors.join("\n");
        }
        return "";
    }

    get canApply(): boolean {
        return !this.applying && !this.busy && !this.applyBlocker;
    }

    /** The staged definition of a pending field, from the draft. */
    stagedField(name: string): DraftFieldJSON | null {
        const fields = this.draft?.fields || [];
        return fields.find((field) => field.name === name) || null;
    }

    /**
     * The model's fields in class order, each with the kind of change the
     * draft holds for it (`added`, `changed`, `removed`) or `null`. Fields
     * the draft has removed are listed still, marked, so the removal can
     * be seen and undone before Apply makes it a dropped column.
     */
    get modelFields(): DraftFieldWithPending[] {
        const draft = this.draft;
        if (!draft) {
            return [];
        }
        const kinds = new Map<string, PendingChangeJSON["kind"]>();
        for (const change of draft.pending || []) {
            if (change.name && change.kind !== "model" && !change.model) {
                kinds.set(change.name, change.kind);
            }
        }
        const listed: DraftFieldWithPending[] = (draft.fields || []).map((field) => ({
            ...field,
            pendingKind: kinds.get(field.name) || null,
        }));
        for (const change of draft.pending || []) {
            if (
                change.kind === "removed" &&
                !change.model &&
                !listed.some((f) => f.name === change.name)
            ) {
                listed.push({ name: change.name, string: change.name, pendingKind: "removed" });
            }
        }
        return listed;
    }

    // -- loading ------------------------------------------------------------

    /** What the view's editing context said; read before `load`. */
    setHints({
        draft_id: draftId = false,
        reload_mode: reloadMode = false,
    }: DraftHints = {}): void {
        this.hints = {
            draft_id: draftId || false,
            reload_mode: reloadMode || false,
        };
    }

    /** Forget the draft: the shell moved to another model. */
    reset(): void {
        this.draft = null;
        this.hints = { draft_id: false, reload_mode: false };
    }

    /**
     * This user's draft on the model, when there is one.
     *
     * Never created here: opening the console is not an edit, and the
     * first staged drop makes the draft. A draft that has gone -- vacuumed
     * after its idle window -- is not an error either: the id is dropped
     * so the next drop opens a fresh one.
     */
    async load(): Promise<DraftPayload | null> {
        const id = this.draftId;
        if (!id) {
            this.draft = null;
            return null;
        }
        try {
            this.draft = markRaw(
                await this.orm.call<DraftPayload>("studio.model.draft", "load", [[id]]),
            );
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.draft = null;
            this.hints.draft_id = false;
        }
        return this.draft;
    }

    /**
     * The draft the editor's questions go to, opened when the model has
     * none yet: `inverse_options` and `resolve_related` are methods of a
     * draft, and a Python-owned model with nothing staged has no draft
     * until its first drop. Opening one for a question is not an edit --
     * a clean draft is nothing to apply -- and the drop that follows
     * stages on it.
     */
    async ensure(): Promise<DraftPayload | null> {
        if (this.draft) {
            return this.draft;
        }
        if (this.draftId) {
            await this.load();
            if (this.draft) {
                return this.draft;
            }
        }
        if (!this.modelName || !this.pythonOwned) {
            return null;
        }
        const payload = await this._guard(() =>
            this.orm.call<DraftPayload>("studio.model.draft", "open_for_model", [this.modelName]),
        );
        if (payload) {
            this.draft = markRaw(payload);
        }
        return this.draft;
    }

    // -- calls ----------------------------------------------------------------

    /**
     * One call on the draft, then the draft read again. The draft is
     * opened on demand: editing the definition of a field the class
     * already has is the first thing a Python-owned model may be asked,
     * and it has no draft until something is staged on it.
     */
    async call<T = unknown>(
        method: string,
        args: unknown[],
        { silent = false }: { silent?: boolean } = {},
    ): Promise<T | undefined> {
        if (!this.draftId && this.pythonOwned) {
            await this.ensure();
        }
        const id = this.draftId;
        if (!id) {
            return undefined;
        }
        this.busy = true;
        try {
            const result = await this._guardDraft(
                () => this.orm.call<T>("studio.model.draft", method, [[id], ...args]),
                silent,
            );
            if (result === undefined) {
                return undefined;
            }
            await this.load();
            return result;
        } finally {
            this.busy = false;
        }
    }

    async _guardDraft<T>(run: () => Promise<T>, silent: boolean): Promise<T | undefined> {
        try {
            return await run();
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            if (!silent) {
                this.notification.add(messageOf(err), { type: "warning" });
            }
            return undefined;
        }
    }

    /** Run a read that may fail, showing the reason rather than dying. */
    async _guard<T>(run: () => Promise<T>): Promise<T | undefined> {
        try {
            return await run();
        } catch (err) {
            if (!(err as OdooRpcError)?.data) {
                throw err;
            }
            this.notification.add(messageOf(err), { type: "warning" });
            return undefined;
        }
    }

    /** Un-stage a field: its ghost goes with it. */
    async removePending(name: string): Promise<unknown> {
        return this.call("remove_field", [name]);
    }

    /** Change a staged field's definition; the ghost follows the label. */
    async updateStaged(
        name: string,
        values: Record<string, unknown> | null | undefined,
    ): Promise<unknown> {
        // `defined`/`error`/`inverse`/`relatedInfo`/`showCompute` are the
        // field editor's own UI-only bookkeeping, not part of the staged
        // definition: this destructure exists purely to strip them before
        // forwarding `rest`.
        const { defined, error, inverse, relatedInfo, showCompute, ...rest } = values || {};
        if (rest["field_description"] && !rest["string"]) {
            rest["string"] = rest["field_description"];
        }
        delete rest["field_description"];
        return this.call("update_field", [name, rest]);
    }

    /**
     * Reorder the class: `name` goes before `before`, or last. Class
     * order is the order the fields are written to Python and the order a
     * scaffolded view shows them in, so this is a layout gesture too.
     */
    async moveField(name: string, before: string | null = null): Promise<unknown> {
        return this.call("move_field", [name, before]);
    }

    /** Stage a field with no place on any canvas; Apply places it. */
    async addModelField(spec: Record<string, unknown>): Promise<unknown> {
        return this.call("add_field", [spec]);
    }

    /** Everything the draft has staged, thrown away; the ghosts go too. */
    async discard(): Promise<unknown> {
        return this.call("action_discard", []);
    }

    /** The unified diff of what Apply would write, for the dialog. */
    async previewDiff(): Promise<string> {
        const id = this.draftId;
        if (!id) {
            return "";
        }
        const diff = await this._guard(() =>
            this.orm.call<string>("studio.model.draft", "preview_diff", [[id]]),
        );
        return diff || "";
    }

    /**
     * Apply the draft: write the package, reload it, place what was
     * staged where it was dropped.
     *
     * Returns `{ok: true}` once it went through, `{ok: true,
     * restartRequired: true}` when the server wrote the files but cannot
     * reload in place -- the fields stay pending until it is restarted,
     * and `placePending` finishes the apply afterwards -- or `{ok: false,
     * message, destructive}` with the server's sentence when it refused;
     * `destructive` when it refused because data would go, so the dialog
     * can offer "Apply anyway".
     */
    async apply(allowDestructive = false): Promise<ApplyResult> {
        const id = this.draftId;
        if (!id) {
            return {
                ok: false,
                message: String(_t("There is nothing to apply.")),
                destructive: false,
            };
        }
        this.applying = true;
        try {
            let result: { restart_required?: boolean } | undefined;
            try {
                result = await this.orm.call("studio.model.draft", "action_apply", [
                    [id],
                    allowDestructive,
                ]);
            } catch (err) {
                if (!(err as OdooRpcError)?.data) {
                    throw err;
                }
                const message = messageOf(err);
                return {
                    ok: false,
                    message,
                    destructive:
                        !allowDestructive && /remove|drop|destructive|kept aside/i.test(message),
                };
            }
            await this.load();
            if (result?.restart_required) {
                this.notification.add(
                    String(
                        _t(
                            "Written to disk. Restart the server to load it; the changes stay pending until then.",
                        ),
                    ),
                    { type: "info", sticky: true },
                );
                return { ok: true, restartRequired: true };
            }
            this.notification.add(String(_t("Applied.")), { type: "success" });
            return { ok: true, restartRequired: false };
        } finally {
            this.applying = false;
        }
    }

    /**
     * The rest of an apply that was written without being loaded: the
     * placement and the baseline, from the anchors the draft still holds,
     * once the server has been restarted. `{placed, reason}` as the
     * server says it; a refusal is not thrown, since the caller has a
     * sentence of its own to put it in.
     */
    async placePending(): Promise<PlaceResult> {
        const id = this.draftId;
        if (!id) {
            return { placed: false, reason: "" };
        }
        try {
            const result = await this.orm.call<PlaceResult>("studio.model.draft", "place_pending", [
                [id],
            ]);
            await this.load();
            return result || { placed: false, reason: "" };
        } catch (err) {
            if ((err as OdooRpcError)?.data) {
                return { placed: false, reason: messageOf(err) };
            }
            throw err;
        }
    }
}

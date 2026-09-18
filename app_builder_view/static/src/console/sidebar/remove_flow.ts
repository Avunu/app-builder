/** @odoo-module **/
/**
 * Taking a node out of the view, with the one question that may come
 * back. Asked the same way from the frame's cross, the properties'
 * Remove button and the outline: the model refuses a container with
 * something in it -- or a staged field -- the first time and hands back
 * the sentence to ask with, and the answer sends the same request with
 * `force`.
 */

import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "../odoo";
import type { DialogService } from "../odoo";
import type { Token } from "../types";
import type { OperationResult } from "../wire";

/**
 * What `ConsoleModel.remove` answers back (`console_model.ts`'s own real
 * return type, transcribed rather than guessed): the applied edit's
 * `OperationResult`, a question to ask before applying it (sent back as
 * `{confirm: sentence}`, its `context` unread by anything so far -- left
 * `unknown` rather than typed ahead of a reader that does not exist
 * yet), or `undefined` when the view changed under the request and
 * nothing was applied.
 */
type RemoveResult = OperationResult | { confirm: string; context: unknown } | undefined;

/**
 * `removeWithConfirm` only ever calls `model.remove(token, force)` --
 * the same narrow-owner-interface pattern this migration already uses
 * for `ConsoleModel` itself (`ConsoleModelOwner`, `console_model.ts`)
 * and for `CanvasDrag` (`CanvasDragModel`, `drag.ts`): name only what
 * this function reads off a much larger real collaborator, rather than
 * importing the whole `ConsoleModel` class just to construct one for a
 * caller or a test. The real `ConsoleModel` satisfies this structurally
 * with no change on its own side.
 */
interface RemoveFlowModel {
    remove(token: Token, force: boolean): Promise<RemoveResult>;
}

interface RemoveWithConfirmParams {
    /** The model to ask, narrowed to `RemoveFlowModel` -- see its own
     * doc comment for why not the full `ConsoleModel`. */
    model: RemoveFlowModel;
    /** The dialog service. */
    dialog: DialogService;
    /** The node to remove. */
    token: Token;
}

/**
 * Removes `token`, asking first when the model refuses to do it
 * silently. Returns the model's answer to the first request; a
 * confirmation, when asked for, is sent on its own and its own answer is
 * not awaited here -- the dialog closes itself once `confirm` resolves.
 */
export async function removeWithConfirm({
    model,
    dialog,
    token,
}: RemoveWithConfirmParams): Promise<RemoveResult> {
    const result = await model.remove(token, false);
    if (result && "confirm" in result && result.confirm) {
        // `ConfirmationDialog`'s props are typed against `odoo.ts`'s own
        // `ConfirmationDialogProps` (see that file for why it is
        // re-exported from there rather than imported straight from the
        // vendor module). `close` is not supplied here: `dialog_service.js`'s
        // own `add()` injects it itself at mount time (`subProps: markRaw({
        // ...props, close })`). `title`/`confirmLabel` are handed `_t(...)`'s
        // result unwrapped (no `String(...)`), matching the vendor
        // component's own `title` validator, which explicitly accepts a
        // lazy, not-yet-stringified value.
        dialog.add(ConfirmationDialog, {
            title: _t("Remove from view"),
            body: result.confirm,
            confirmLabel: _t("Remove"),
            confirm: () => {
                void model.remove(token, true);
            },
            cancel: () => {},
        });
    }
    return result;
}

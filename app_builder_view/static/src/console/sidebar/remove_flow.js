/** @odoo-module **/
/**
 * Taking a node out of the view, with the one question that may come
 * back. Asked the same way from the frame's cross, the properties'
 * Remove button and the outline: the model refuses a container with
 * something in it -- or a staged field -- the first time and hands back
 * the sentence to ask with, and the answer sends the same request with
 * `force`.
 */

import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * @param {Object} params
 * @param {ConsoleModel} params.model
 * @param {Object} params.dialog the dialog service
 * @param {string} params.token the node to remove
 * @returns {Promise<Object|undefined>} the model's answer to the first
 *   request; a confirmation, when asked for, is sent on its own
 */
export async function removeWithConfirm({ model, dialog, token }) {
    const result = await model.remove(token, false);
    if (result && result.confirm) {
        dialog.add(ConfirmationDialog, {
            title: _t("Remove from view"),
            body: result.confirm,
            confirmLabel: _t("Remove"),
            confirm: () => model.remove(token, true),
            cancel: () => {},
        });
    }
    return result;
}

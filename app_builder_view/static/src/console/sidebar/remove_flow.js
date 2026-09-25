import { _t } from "../l10n";
import { ConfirmationDialog } from "../odoo";
async function removeWithConfirm({
  model,
  dialog,
  token
}) {
  const result = await model.remove(token, false);
  if (result && "confirm" in result && result.confirm) {
    dialog.add(ConfirmationDialog, {
      title: _t("Remove from view"),
      body: result.confirm,
      confirmLabel: _t("Remove"),
      confirm: () => {
        void model.remove(token, true);
      },
      cancel: () => {
      }
    });
  }
  return result;
}
export {
  removeWithConfirm
};

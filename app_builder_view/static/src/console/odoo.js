import { useService as useServiceUntyped } from "@web/core/utils/hooks";
import { ConfirmationDialog as ConfirmationDialogImpl } from "@web/core/confirmation_dialog/confirmation_dialog";
const ConfirmationDialog = ConfirmationDialogImpl;
function useService(name) {
  return useServiceUntyped(name);
}
export {
  ConfirmationDialog,
  useService
};

import { user as userUntyped } from "@web/core/user";
import { useService as useServiceUntyped } from "@web/core/utils/hooks";
import { ConfirmationDialog as ConfirmationDialogImpl } from "@web/core/confirmation_dialog/confirmation_dialog";
const ConfirmationDialog = ConfirmationDialogImpl;
function useService(name) {
  const service = useServiceUntyped(name);
  return service;
}
const user = userUntyped;
export {
  ConfirmationDialog,
  useService,
  user
};

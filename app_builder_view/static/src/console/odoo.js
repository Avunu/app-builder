import { useService as useServiceUntyped } from "@web/core/utils/hooks";
function useService(name) {
  return useServiceUntyped(name);
}
export {
  useService
};

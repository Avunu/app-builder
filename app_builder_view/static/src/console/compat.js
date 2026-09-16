import { rpcBus } from "@web/core/network/rpc";
import { session } from "@web/session";
function serverVersion() {
  const info = session.server_version_info || [];
  const major = digitsOf(info[0]);
  const minor = digitsOf(info[1]);
  return Number.isFinite(major) ? [major, Number.isFinite(minor) ? minor : 0] : [18, 0];
}
function digitsOf(value) {
  if (value === void 0 || value === null) {
    return NaN;
  }
  return parseInt(String(value).replace(/\D/g, ""), 10);
}
function versionAtLeast(major, minor = 0) {
  const [ownMajor, ownMinor] = serverVersion();
  return ownMajor > major || ownMajor === major && ownMinor >= minor;
}
function is19Line() {
  return versionAtLeast(19);
}
function isMasterLine() {
  return versionAtLeast(19, 5);
}
function dragRef(ref) {
  return isMasterLine() ? () => ref.el : ref;
}
function dragExtraParams() {
  return { allowDisconnected: true };
}
function readonlyViewProps() {
  return is19Line() ? { readonly: true } : { mode: "readonly" };
}
function rowRect(el) {
  const cell = el.closest(".o_cell");
  if (!cell) {
    return el.getBoundingClientRect();
  }
  const label = cell.previousElementSibling;
  if (label && label.matches(".o_cell.o_wrap_label")) {
    return union(label.getBoundingClientRect(), cell.getBoundingClientRect());
  }
  return cell.getBoundingClientRect();
}
function labelWidget(label) {
  const doc = label.ownerDocument;
  if (label.htmlFor) {
    const input = doc.getElementById(label.htmlFor);
    const widget = input && input.closest(".o_field_widget");
    if (widget) {
      return widget;
    }
  }
  const cell = label.closest(".o_cell.o_wrap_label, .o_wrap_label");
  const next = cell && cell.nextElementSibling;
  if (next) {
    return next.matches(".o_field_widget") ? next : next.querySelector(".o_field_widget");
  }
  return null;
}
function union(a, b) {
  const top = Math.min(a.top, b.top);
  const left = Math.min(a.left, b.left);
  const bottom = Math.max(a.bottom, b.bottom);
  const right = Math.max(a.right, b.right);
  return { top, left, bottom, right, width: right - left, height: bottom - top };
}
const TAB_SELECTOR = ".o_notebook .nav-link";
function isStaleError(err) {
  const name = err?.data?.name || "";
  return name.endsWith(".StudioStaleView");
}
function isConfirmError(err) {
  const context = err?.data?.context || {};
  return Boolean(context.confirm_required);
}
function clearViewCaches(env) {
  rpcBus.trigger("CLEAR-CACHES", "get_views");
  env.bus.trigger("CLEAR-CACHES");
}
function fieldSelectorFollow(follow = true) {
  if (versionAtLeast(19, 5)) {
    return { followRelation: follow };
  }
  return { followRelations: follow };
}
export {
  TAB_SELECTOR,
  clearViewCaches,
  dragExtraParams,
  dragRef,
  fieldSelectorFollow,
  isConfirmError,
  isStaleError,
  labelWidget,
  readonlyViewProps,
  rowRect,
  serverVersion,
  versionAtLeast
};

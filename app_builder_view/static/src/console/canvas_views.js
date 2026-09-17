import { registry } from "@web/core/registry";
const viewRegistry = registry.category("views");
const CANVAS_PREFIX = "app_builder_canvas__";
function canvasJsClass(type, origJsClass = null) {
  const base = origJsClass && viewRegistry.contains(origJsClass) ? origJsClass : type;
  if (!viewRegistry.contains(base)) {
    return null;
  }
  const name = CANVAS_PREFIX + base;
  if (!viewRegistry.contains(name)) {
    const found = viewRegistry.get.call(
      viewRegistry,
      base
    );
    viewRegistry.add(name, deriveCanvasView(found));
  }
  return name;
}
function deriveCanvasView(descriptor) {
  const derived = { ...descriptor };
  if (descriptor.Controller) {
    derived.Controller = noSave(descriptor.Controller);
  }
  if (descriptor.Renderer) {
    derived.Renderer = noResequence(descriptor.Renderer);
  }
  return derived;
}
const NO_SAVE_OVERRIDES = {
  beforeVisibilityChange() {
  },
  async beforeLeave() {
  },
  async beforeUnload() {
  },
  // `async` on purpose despite no `await`: the real hook this
  // overrides is awaited by its caller (`useViewButtons`), which
  // expects a Promise back, and `false` synchronously wrapped in one
  // by `async` is exactly what "the action is not to run" means here
  // -- see this file's own module docstring.
  // eslint-disable-next-line @typescript-eslint/require-await
  async beforeExecuteActionButton() {
    return false;
  }
};
function noSave(Controller) {
  class NoSaveController extends Controller {
  }
  const prototype = Controller.prototype;
  for (const [name, fn] of Object.entries(NO_SAVE_OVERRIDES)) {
    if (typeof prototype[name] === "function") {
      Object.defineProperty(NoSaveController.prototype, name, {
        value: fn,
        writable: true,
        configurable: true
      });
    }
  }
  return NoSaveController;
}
const RESEQUENCE_GETTERS = ["canResequenceRows", "canResequenceRecords", "canResequenceGroups"];
function noResequence(Renderer) {
  class NoResequenceRenderer extends Renderer {
  }
  for (const name of RESEQUENCE_GETTERS) {
    if (name in Renderer.prototype) {
      Object.defineProperty(NoResequenceRenderer.prototype, name, {
        get: () => false,
        configurable: true
      });
    }
  }
  return NoResequenceRenderer;
}
export {
  CANVAS_PREFIX,
  canvasJsClass,
  deriveCanvasView,
  noResequence,
  noSave
};

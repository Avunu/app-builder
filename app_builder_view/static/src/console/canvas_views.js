/** @odoo-module **/
/**
 * The real view, with its side effects taken out.
 *
 * The canvas renders through the stock `View` -- that is the point of a
 * WYSIWYG canvas -- but the stock controllers do things a canvas must never
 * do. A form saves its record when the tab is hidden or the page unloads
 * (`form_controller.js beforeVisibilityChange/beforeUnload`, with no dirty
 * check in 18 and 19), a button click saves and runs the action, a list lets
 * its rows be resequenced and a kanban its cards, each of which writes.
 *
 * So the canvas never renders under the stock class. For each view type it
 * registers, lazily, a derived entry in the `views` registry whose controller
 * has those hooks turned into no-ops and whose renderer cannot resequence.
 * The server strips `js_class` from the canvas arch and returns it, so the
 * derived class wraps the view's *own* class when it has one -- a project
 * task form keeps its behaviour and loses only the saving.
 *
 * A registry entry rather than a patch: patching `FormController` would
 * change every form in the web client; an entry changes only what the
 * canvas asks for, by name.
 */

import { registry } from "@web/core/registry";

const viewRegistry = registry.category("views");

export const CANVAS_PREFIX = "app_builder_canvas__";

/**
 * The name of the derived entry for a view type and its optional
 * `js_class`, registering it on first use. Returns `null` when nothing is
 * registered under either name, so the caller can fall back to the type.
 */
export function canvasJsClass(type, origJsClass = null) {
    const base = origJsClass && viewRegistry.contains(origJsClass) ? origJsClass : type;
    if (!viewRegistry.contains(base)) {
        return null;
    }
    const name = CANVAS_PREFIX + base;
    if (!viewRegistry.contains(name)) {
        viewRegistry.add(name, deriveCanvasView(viewRegistry.get(base)));
    }
    return name;
}

/**
 * A view descriptor with its controller and renderer neutered.
 *
 * Exported on its own so a test can mount the derived descriptor without
 * touching the registry.
 */
export function deriveCanvasView(descriptor) {
    const derived = { ...descriptor };
    if (descriptor.Controller) {
        derived.Controller = noSave(descriptor.Controller);
    }
    if (descriptor.Renderer) {
        derived.Renderer = noResequence(descriptor.Renderer);
    }
    return derived;
}

/**
 * A controller that never saves.
 *
 * The three lifecycle hooks are overridden to do nothing, returning what
 * their callers expect: `beforeLeave` is awaited for a promise, and
 * `beforeUnload` is given the event to cancel -- left untouched, the
 * browser leaves. `beforeExecuteActionButton` returning `false` tells
 * `useViewButtons` the action is not to run. Only hooks the base class
 * actually defines are overridden, so a controller without them (a pivot,
 * a graph) is left as it is.
 */
export function noSave(Controller) {
    const overrides = {
        beforeVisibilityChange() {},
        async beforeLeave() {},
        async beforeUnload() {},
        async beforeExecuteActionButton() {
            return false;
        },
    };
    class NoSaveController extends Controller {}
    for (const [name, fn] of Object.entries(overrides)) {
        if (typeof Controller.prototype[name] === "function") {
            Object.defineProperty(NoSaveController.prototype, name, {
                value: fn,
                writable: true,
                configurable: true,
            });
        }
    }
    return NoSaveController;
}

/**
 * A renderer whose rows, records and groups cannot be dragged about.
 *
 * The three getters exist on different renderers -- `canResequenceRows` on
 * a list, `canResequenceRecords`/`canResequenceGroups` on a kanban -- and
 * are read by the sortable hooks' `enable` callbacks, so a getter that
 * answers `false` leaves those hooks inert without touching them.
 */
export function noResequence(Renderer) {
    class NoResequenceRenderer extends Renderer {}
    for (const name of ["canResequenceRows", "canResequenceRecords", "canResequenceGroups"]) {
        if (name in Renderer.prototype) {
            Object.defineProperty(NoResequenceRenderer.prototype, name, {
                get: () => false,
                configurable: true,
            });
        }
    }
    return NoResequenceRenderer;
}

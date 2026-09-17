/** @odoo-module **/
/**
 * The one place the console knows which Odoo it is running on.
 *
 * Everything else in `console/` is written against a contract that holds in
 * 18, 19 and master; what does *not* hold -- a prop that was renamed, a hook
 * whose `ref` changed shape, a DOM the form compiler lays out differently --
 * is answered here, once, from `session.server_version_info`. A module that
 * needs to know the version asks this one; nothing else reads it. That is what
 * makes the port to the next branch a diff of this file rather than a hunt
 * through the rest.
 *
 * Each export says which versions it exists for and why it differs, with the
 * core lines that were read to say so -- `18:`, `19:` and `master:` name the
 * 18.0, 19.0 and master checkouts the console was audited against. Keep the
 * shims thin: one that grows logic of its own is a second module in disguise.
 * `FORWARD_COMPAT.md` at the repository root is the longer account, including
 * what the next port will have to do outside this file.
 *
 * Two lines are drawn, not one. The 19 line is `19.0` and after. The master
 * line -- Owl 3, callable refs -- is the branch that becomes 20, but it does
 * not carry that number yet: `odoo/release.py:15` on master reads
 * `(19, 5, 0, ALPHA, 1)`, and the Owl 3 build and the callable-ref change
 * both landed under it. So the master line starts at `19.5`, and a check
 * that waited for `20` would hand master the 18 shapes and crash at the
 * first drag.
 */

import { rpcBus } from "@web/core/network/rpc";
import { session } from "@web/session";
import type { BoxRect } from "./types";

/**
 * `session.server_version_info`, narrowly: element 0 (the major, sometimes
 * a `saas~xx` string per `odoo/release.py`) and element 1 (the minor),
 * both read by digits alone. The rest of `session` is untyped Odoo global
 * state this file has no business widening.
 */
/** A digit-bearing primitive, the only shape a version part is ever
 * spelled as (a number, or a `saas~xx` string). Narrower than `unknown`
 * so `String(...)` on one is never the "[object Object]" `no-base-to-string`
 * warns about -- and genuinely narrower, not a lint workaround: nothing
 * in `odoo/release.py`'s own version tuple is ever an object. */
type VersionPart = string | number;

interface VersionInfo {
    server_version_info?: readonly [VersionPart, VersionPart, ...VersionPart[]];
}

/** `[major, minor]`, both numbers. */
type ServerVersion = readonly [number, number];

/**
 * `[major, minor]` of the server, as numbers; `[18, 0]` when it cannot be read.
 *
 * The major is not always a number: `odoo/release.py` 19:14 says it "can
 * become an arbitrary string ('saas~xx')" during a release, and every saas
 * build ships it that way -- the form core itself reads by replacing the
 * `~` (`views/widgets/documentation_link/documentation_link.js` 18:23-27).
 * So the digits are what is parsed, and the fallback is for a value with
 * none at all, both numbers together: a minor without its major would name
 * no line.
 */
export function serverVersion(): ServerVersion {
    const info = (session as VersionInfo).server_version_info || [];
    const major = digitsOf(info[0]);
    const minor = digitsOf(info[1]);
    return Number.isFinite(major) ? [major, Number.isFinite(minor) ? minor : 0] : [18, 0];
}

/** The integer spelled by the digits of `value`, or `NaN` when there are none. */
function digitsOf(value: VersionPart | undefined): number {
    if (value === undefined || value === null) {
        return NaN;
    }
    return parseInt(String(value).replace(/\D/g, ""), 10);
}

/** Whether the server is `major.minor` or later. */
export function versionAtLeast(major: number, minor = 0): boolean {
    const [ownMajor, ownMinor] = serverVersion();
    return ownMajor > major || (ownMajor === major && ownMinor >= minor);
}

/** The 19 line: 19.0 and everything after it, master included. */
function is19Line(): boolean {
    return versionAtLeast(19);
}

/**
 * The master line: the branch that becomes 20, versioned `19.5` for now.
 * The number is where master stood when it was audited, not a promise
 * about saas releases in between; see the module docstring.
 */
function isMasterLine(): boolean {
    return versionAtLeast(19, 5);
}

/**
 * The `ref` a drag hook takes.
 *
 * `makeDraggableHook` validates the param's type and reads it once:
 * `ref: [Object]` read as `ctx.ref.el` in 18 (`draggable_hook_builder.js`
 * 18:91, :897) and 19 (19:92, :920); `ref: [Function]` called as
 * `ctx.ref()` on master (master:142, :1004). `useNativeDraggable` reads it
 * the same way before the builder does (`html_editor/utils/drag_and_drop.js`
 * 18:70 and 19:70 `initialParams.ref.el`; master:70 `initialParams.ref()`).
 * A function cannot double as the object -- the check is `typeof`
 * (18:935-948) -- so the shape has to be chosen.
 */
export interface DragRef {
    el: HTMLElement | null;
}

export function dragRef(ref: DragRef): DragRef | (() => HTMLElement | null) {
    return isMasterLine() ? () => ref.el : ref;
}

/**
 * Extra params the drag hook acts on in newer branches only.
 *
 * `allowDisconnected` lets a drag outlive the element it started from: the
 * canvas re-renders under a drag when a tab switches, and without it 19
 * and master end the drag the moment the source is gone
 * (`draggable_hook_builder.js` 19:89, :104, :584, :810; master:139, :155,
 * :643, :884). 18 has no such param and does not mind being given one: its
 * validator walks the params it *accepts* and never the ones it was handed
 * (18:935-948), so the key is passed everywhere and there is no branch.
 */
export function dragExtraParams(): { allowDisconnected: boolean } {
    return { allowDisconnected: true };
}

/**
 * How a form View is told to render read-only.
 *
 * 18's `FormController` takes `mode: "readonly"` (`form_controller.js`
 * 18:143-145); 19 removed that prop and takes `readonly: true` (19:140,
 * read by `form_renderer.js` 19:52), as does master (`form_controller.js`
 * master:133, `form_renderer.js` master:40). In dev mode -- which every
 * tour runs in -- the wrong key is an "unknown prop" error, so the two
 * cannot simply both be passed.
 */
export function readonlyViewProps(): { readonly: boolean } | { mode: string } {
    return is19Line() ? { readonly: true } : { mode: "readonly" };
}

/**
 * The rectangle a form field occupies, label included.
 *
 * A field's own element is the input half of its row; the outline the user
 * expects covers the label too. In 18, 19 and master alike the compiler
 * emits a generated label as `.o_cell.o_wrap_label` immediately followed by
 * the widget's `.o_cell.o_wrap_input` (`form_group/form_group.xml` 18:43-50,
 * 19:46-54, master:44-52; booleans 18:54-60, 19:58-64, master:56-62), so the
 * previous sibling of the widget's cell is its label when it has one, and
 * the walk is version-free. What *does* differ is the wrapper around them:
 * 18 wraps a whole grid *row* in `.o_wrap_field` (18:19 iterates
 * `getRows()`, so a `<group col="4">` puts two fields in one wrapper); 19 and
 * master drop it (19:19-40, master:19-37) and keep only a `display:
 * contents` wrapper around a boolean's pair (19:57 `.o_wrap_field_boolean`,
 * master:55 `.o_wrap_field_inline`). None of those is a field, so none is
 * read: the sibling walk is what gives each field its own rect on every
 * line. Returns a DOMRect-like `{top, left, width, height, bottom, right}`
 * in viewport coordinates.
 */
export function rowRect(el: Element): BoxRect {
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

/**
 * The field widget a generated form label belongs to, or `null`.
 *
 * A `<field>` in a group gets its label from the compiler, and that label
 * carries the group's classes, never the field's: the token is on the
 * widget alone. The label's `for` names the widget's input, which only
 * exists in edit mode -- the canvas is read-only -- so the layout is the
 * reliable route: in 18, 19 and master the label's `.o_cell.o_wrap_label`
 * is followed by the cell holding the widget (`form_group.xml` 18:43-49,
 * 19:46-52, master:44-50). An explicit `<label for>` in the arch is
 * stamped in its own right and never reaches this.
 */
export function labelWidget(label: HTMLLabelElement): Element | null {
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

function union(a: BoxRect, b: BoxRect): BoxRect {
    const top = Math.min(a.top, b.top);
    const left = Math.min(a.left, b.left);
    const bottom = Math.max(a.bottom, b.bottom);
    const right = Math.max(a.right, b.right);
    return { top, left, bottom, right, width: right - left, height: bottom - top };
}

/**
 * A notebook tab. An `<a>` in 18 and 19 (`core/notebook/notebook.xml` 18:9,
 * 19:9), a `<button>` on master (master:10): selected by class alone so
 * all three match, and `name` is on it in each.
 */
export const TAB_SELECTOR = ".o_notebook .nav-link";

/**
 * Whether an RPC error says the view changed under the client.
 *
 * The server raises `StudioStaleView` for that, and the RPC layer serialises
 * the exception's class name -- the one thing about it that is not
 * translated -- so that is what is matched. `data.name` is
 * `f"{module}.{name}"` in all three (`odoo/http.py` 18:432-441, 19:469-478;
 * `odoo/http/dispatcher.py` master:78-91).
 */
/** The shape of an RPC error's `data` this file reads, whatever else it
 * carries (the message, the traceback -- none of that is our business). */
interface OdooRpcError {
    data?: {
        name?: string;
        context?: { confirm_required?: boolean };
    };
}

export function isStaleError(err: unknown): boolean {
    const name = (err as OdooRpcError | undefined)?.data?.name || "";
    return name.endsWith(".StudioStaleView");
}

/**
 * Whether an RPC error is the server asking for a confirmation first.
 *
 * `StudioConfirmRequired` travels with a `context` the RPC layer keeps
 * (`getattr(exception, 'context', {})`, the same lines as above), so a
 * client can word its own question rather than parse the sentence.
 */
export function isConfirmError(err: unknown): boolean {
    const context = (err as OdooRpcError | undefined)?.data?.context || {};
    return Boolean(context.confirm_required);
}

/**
 * Drop the web client's cached view definitions.
 *
 * The canvas never needs this -- it renders from the arch the server hands
 * it -- but the *real* views do, on Close and after a search-view edit whose
 * host list loads its search view the ordinary way. 18 listens on the env
 * bus (`views/view_service.js` 18:56); 19 and master listen on the RPC bus,
 * keyed by what to clear (19:51 and master:55 trigger it themselves;
 * `core/network/rpc.js` 19:85, master:85 invalidate the cache). Neither
 * bus has a listener for the other's event, and `rpcBus` is exported by
 * all three, so both are told and there is no branch.
 */
/** The one piece of `OdooEnv` this file touches. */
interface EnvWithBus {
    bus: { trigger: (name: string) => void };
}

export function clearViewCaches(env: EnvWithBus): void {
    rpcBus.trigger("CLEAR-CACHES", "get_views");
    env.bus.trigger("CLEAR-CACHES");
}

/**
 * The prop that lets a `ModelFieldSelector` follow relations, by the name
 * this branch gives it: `followRelations` on 18
 * (`core/model_field_selector/model_field_selector.js` 18:20), renamed
 * `followRelation` on master (:23). 19.0 has not been checked against a
 * checkout; it is assumed to be on the 18 side until it is.
 */
export function fieldSelectorFollow(
    follow = true,
): { followRelation: boolean } | { followRelations: boolean } {
    if (versionAtLeast(19, 5)) {
        return { followRelation: follow };
    }
    return { followRelations: follow };
}

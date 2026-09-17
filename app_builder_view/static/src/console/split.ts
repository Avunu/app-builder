/** @odoo-module **/
/**
 * A divider that is dragged up and down to give one panel more of a
 * column and the other less: the outline above the sidebar's tabs.
 *
 * Core's `ResizablePanel` is a width, and only a width, so the height
 * is done here in the same few moves it makes: the pointer is captured
 * on the handle, the body takes no pointer events and no selection
 * while the drag is on -- the view under the canvas would otherwise
 * take the moves -- and the height is written as the pointer goes, then
 * handed back once when it is let go, for the caller to keep.
 *
 * No Owl: attached to an element the component holds, and destroyed
 * with it.
 */

/**
 * The knobs `attachVerticalResize` needs: how to read and write the
 * height it is resizing, the bounds that height must stay inside, and
 * what to do once a drag ends.
 */
export interface VerticalResizeParams {
    /** `() => px`, the height as it is. */
    getHeight: () => number;
    /** `(px) => void`, applied as the pointer moves. */
    setHeight: (px: number) => void;
    /** `() => px`, the most it may be. */
    getMax?: () => number;
    /** the least it may be. */
    min?: number;
    /** `(px) => void`, once the drag ends. */
    onDone?: (px: number) => void;
}

/** What `attachVerticalResize` hands back: a single cleanup call. */
export interface VerticalResizeHandle {
    destroy: () => void;
}

export function attachVerticalResize(
    handleEl: HTMLElement,
    {
        getHeight,
        setHeight,
        getMax = () => Infinity,
        min = 80,
        onDone = () => {},
    }: VerticalResizeParams,
): VerticalResizeHandle {
    let start: { y: number; height: number } | null = null;
    const clamp = (height: number) => Math.max(min, Math.min(getMax(), height));
    const onPointerDown = (ev: PointerEvent) => {
        if (ev.button !== 0) {
            return;
        }
        ev.preventDefault();
        start = { y: ev.clientY, height: getHeight() };
        handleEl.setPointerCapture(ev.pointerId);
        document.body.classList.add("pe-none", "user-select-none");
    };
    const onPointerMove = (ev: PointerEvent) => {
        if (start) {
            setHeight(clamp(start.height + ev.clientY - start.y));
        }
    };
    const end = (ev: PointerEvent) => {
        if (!start) {
            return;
        }
        const height = clamp(start.height + ev.clientY - start.y);
        start = null;
        document.body.classList.remove("pe-none", "user-select-none");
        if (handleEl.hasPointerCapture && handleEl.hasPointerCapture(ev.pointerId)) {
            handleEl.releasePointerCapture(ev.pointerId);
        }
        setHeight(height);
        onDone(height);
    };
    handleEl.addEventListener("pointerdown", onPointerDown);
    handleEl.addEventListener("pointermove", onPointerMove);
    handleEl.addEventListener("pointerup", end);
    handleEl.addEventListener("pointercancel", end);
    return {
        destroy() {
            handleEl.removeEventListener("pointerdown", onPointerDown);
            handleEl.removeEventListener("pointermove", onPointerMove);
            handleEl.removeEventListener("pointerup", end);
            handleEl.removeEventListener("pointercancel", end);
            if (start) {
                start = null;
                document.body.classList.remove("pe-none", "user-select-none");
            }
        },
    };
}

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
 * @param {HTMLElement} handleEl the divider
 * @param {Object} params
 * @param {Function} params.getHeight `() => px`, the height as it is
 * @param {Function} params.setHeight `(px) => void`, applied as the
 *   pointer moves
 * @param {Function} [params.getMax] `() => px`, the most it may be
 * @param {number} [params.min] the least it may be
 * @param {Function} [params.onDone] `(px) => void`, once the drag ends
 * @returns {{destroy: Function}}
 */
export function attachVerticalResize(
    handleEl,
    { getHeight, setHeight, getMax = () => Infinity, min = 80, onDone = () => {} }
) {
    let start = null;
    const clamp = (height) => Math.max(min, Math.min(getMax(), height));
    const onPointerDown = (ev) => {
        if (ev.button !== 0) {
            return;
        }
        ev.preventDefault();
        start = { y: ev.clientY, height: getHeight() };
        handleEl.setPointerCapture(ev.pointerId);
        document.body.classList.add("pe-none", "user-select-none");
    };
    const onPointerMove = (ev) => {
        if (start) {
            setHeight(clamp(start.height + ev.clientY - start.y));
        }
    };
    const end = (ev) => {
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

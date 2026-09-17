function attachVerticalResize(handleEl, {
  getHeight,
  setHeight,
  getMax = () => Infinity,
  min = 80,
  onDone = () => {
  }
}) {
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
    }
  };
}
export {
  attachVerticalResize
};

/* core/projection: adaptive 3/2/1 layout projection state machine.
   Pure function of CSS available width; layout never resets domain state. */
export const PROJECTIONS = ["wide", "medium", "compact", "phone"];

export function projectionForWidth(width) {
  if (width >= 1360) return "wide";
  if (width >= 960) return "medium";
  if (width >= 600) return "compact";
  return "phone";
}

export function projectionClass(projection) {
  return "ct-proj-" + projection;
}

export function subscribeProjection(el, onChange) {
  let current = projectionForWidth(window.innerWidth);
  const apply = () => {
    const next = projectionForWidth(window.innerWidth);
    if (next !== current) {
      current = next;
      onChange(next);
    }
  };
  window.addEventListener("resize", apply);
  return { apply, dispose: () => window.removeEventListener("resize", apply) };
}

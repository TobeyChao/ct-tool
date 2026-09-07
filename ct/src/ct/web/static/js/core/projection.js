/* core/projection: two-breakpoint adaptive layout state machine (900/740).
   docked       >=900   workbench panes dock as collapsible columns
   pane-drawer  740-899 panes become drawers, sidebar stays resident
   shell-drawer <740    panes stay drawers, sidebar becomes a hamburger drawer
   Pure function of CSS available width; layout never resets domain state. */
export const PROJECTIONS = ["docked", "pane-drawer", "shell-drawer"];

export function projectionForWidth(width) {
  if (width >= 900) return "docked";
  if (width >= 740) return "pane-drawer";
  return "shell-drawer";
}

export function projectionClass(projection) {
  return "ct-proj-" + projection;
}

export function subscribeProjection(el, onChange) {
  let current = projectionForWidth(window.innerWidth);
  const apply = () => {
    const next = projectionForWidth(window.innerWidth);
    if (next !== current) {
      const previous = current;
      current = next;
      onChange(next, previous);
    }
  };
  window.addEventListener("resize", apply);
  return { apply, dispose: () => window.removeEventListener("resize", apply) };
}

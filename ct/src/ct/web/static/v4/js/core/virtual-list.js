/* Fixed-row window calculation shared by large resource surfaces. */
export function fixedRowWindow(items, options = {}) {
  const rowHeight = Math.max(1, options.rowHeight || 34);
  const overscan = Math.max(0, options.overscan || 0);
  const scrollTop = Math.max(0, options.scrollTop || 0);
  const viewportHeight = Math.max(rowHeight, options.viewportHeight || rowHeight);
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(items.length, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan);
  return {
    start,
    end,
    rows: items.slice(start, end),
    before: start * rowHeight,
    after: Math.max(0, items.length - end) * rowHeight,
    total: items.length,
  };
}

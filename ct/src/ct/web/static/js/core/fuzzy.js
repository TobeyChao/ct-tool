/* core/fuzzy: DOM-independent fuzzy scorer with highlight ranges.
   Subsequence match; lower score = better; ties break by name. */
export function fuzzyScore(text, query) {
  if (!query) return 0;
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  let cursor = 0;
  let gaps = 0;
  let matched = false;
  for (const ch of q) {
    const at = lower.indexOf(ch, cursor);
    if (at < 0) return Infinity;
    gaps += at - cursor;
    cursor = at + 1;
    matched = true;
  }
  return matched ? gaps + cursor - lower.length + text.length : Infinity;
}

/* Returns [0-based start, end) ranges of matched characters for highlighting. */
export function highlightRanges(text, query) {
  if (!query) return [];
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const ranges = [];
  let cursor = 0;
  for (const ch of q) {
    const at = lower.indexOf(ch, cursor);
    if (at < 0) return [];
    if (ranges.length && at === ranges[ranges.length - 1][1]) {
      ranges[ranges.length - 1][1] = at + 1;
    } else {
      ranges.push([at, at + 1]);
    }
    cursor = at + 1;
  }
  return ranges;
}

/* Rank + deterministic tie-break by name. */
export function rank(items, query, getName) {
  return items
    .map((item) => {
      const name = getName(item);
      return { item, name, score: fuzzyScore(name, query) };
    })
    .filter((entry) => entry.score !== Infinity)
    .sort((a, b) => a.score - b.score || a.name.localeCompare(b.name));
}

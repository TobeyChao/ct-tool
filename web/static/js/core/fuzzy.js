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

/* Returns [0-based start, end) code-unit ranges in `text` for highlighting.
   匹配在码位（code point）级别进行：返回的下标永远落在原文码位边界上，
   不会劈开代理对，也不受 toLowerCase 变长（如 İ → i̇）造成的下标漂移影响。 */
export function highlightRanges(text, query) {
  if (!query) return [];
  const points = Array.from(text);
  const lower = points.map((p) => p.toLowerCase());
  const ranges = [];
  let cursor = 0;
  for (const ch of Array.from(query.toLowerCase())) {
    let at = -1;
    for (let i = cursor; i < lower.length; i++) {
      if (lower[i].startsWith(ch)) { at = i; break; }
    }
    if (at < 0) return [];
    if (ranges.length && at === ranges[ranges.length - 1][1]) {
      ranges[ranges.length - 1][1] = at + 1;
    } else {
      ranges.push([at, at + 1]);
    }
    cursor = at + 1;
  }
  // 码位下标 → 原文 UTF-16 下标
  const offsets = [];
  let unit = 0;
  for (const p of points) { offsets.push(unit); unit += p.length; }
  offsets.push(unit);
  return ranges.map(([s, e]) => [offsets[s], offsets[e]]);
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

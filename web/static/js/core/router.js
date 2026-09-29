/* core/router: hash-based routing; application back follows page stack. */
const listeners = new Set();

function parseHash() {
  const hash = location.hash.replace(/^#/, "");
  const [path, query] = hash.split("?");
  const params = new URLSearchParams(query || "");
  return { path: path || "/", params };
}

export function getRoute() {
  return parseHash();
}

export function navigate(path, params = {}) {
  const query = Object.keys(params).length
    ? "?" + new URLSearchParams(params).toString()
    : "";
  const next = path + query;
  if (("#" + next) !== location.hash) {
    try { history.pushState(null, "", "#" + next); } catch (e) { /* ignore */ }
  }
  emit();
}

export function replace(path) {
  try { history.replaceState(null, "", "#" + path); } catch (e) { /* ignore */ }
  emit();
}

export function onRouteChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  const route = getRoute();
  for (const fn of listeners) fn(route);
}

window.addEventListener("hashchange", emit);

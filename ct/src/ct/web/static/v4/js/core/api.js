/* core/api: fetch wrapper with ok/error contract and actionable errors. */
export async function api(path, opts = {}) {
  const resp = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  let payload = null;
  try { payload = await resp.json(); } catch (e) { payload = null; }
  if (!resp.ok || !payload || payload.ok === false) {
    const error = new Error((payload && payload.error) || ("HTTP " + resp.status));
    error.status = resp.status;
    throw error;
  }
  return payload.data;
}

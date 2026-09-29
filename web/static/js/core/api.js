/* core/api: fetch wrapper with ok/error contract and actionable errors. */
export async function api(path, opts = {}) {
  const { timeoutMs, ...requestOptions } = opts;
  const write = requestOptions.method && requestOptions.method.toUpperCase() !== "GET";
  const controller = timeoutMs ? new AbortController() : null;
  const timeout = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let resp;
  try {
    resp = await fetch(path, Object.assign(
      { headers: { "Content-Type": "application/json" } },
      requestOptions,
      controller ? { signal: controller.signal } : {},
    ));
  }
  catch (cause) {
    if (timeout !== null) clearTimeout(timeout);
    const error = new Error(write
      ? (controller?.signal.aborted
        ? "请求超时，操作结果未知；请核对当前状态后再操作。"
        : "连接中断，操作结果未知；请核对当前状态后再操作。")
      : "无法连接面板服务，请检查服务状态。");
    error.cause = cause;
    error.outcomeUnknown = Boolean(write);
    throw error;
  }
  let payload = null;
  try { payload = await resp.json(); } catch (e) { payload = null; }
  finally { if (timeout !== null) clearTimeout(timeout); }
  if (!resp.ok || !payload || payload.ok === false) {
    const error = new Error((payload && payload.error) || (controller?.signal.aborted
      ? "请求超时，操作结果未知；请核对当前状态后再操作。"
      : write && !payload
        ? "响应中断，操作结果未知；请核对当前状态后再操作。"
        : "HTTP " + resp.status));
    error.status = resp.status;
    error.payload = payload || null;
    error.outcomeUnknown = Boolean(write && !payload);
    throw error;
  }
  return payload.data;
}

/* core/task: persistent task state for long-running work (survives module switch). */
import { api } from "./api.js";

const listeners = new Set();
let tasks = [];
let timer = null;
let instance = null;
let recovering = false;
let recoveryResult = "";

function renderRecovery(note) {
  let banner = document.getElementById("ct-recovery-notice");
  if (!note && !recoveryResult) { banner?.remove(); return; }
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "ct-recovery-notice";
    banner.className = "ct-error-inline";
    banner.setAttribute("role", "alert");
    const message = document.createElement("p");
    message.dataset.recoveryMessage = "";
    const result = document.createElement("p");
    result.dataset.recoveryResult = "";
    const button = document.createElement("button");
    button.className = "ct-btn ct-btn-secondary";
    button.textContent = "恢复未完成发布";
    button.addEventListener("click", async () => {
      if (recovering) return;
      recovering = true;
      button.disabled = true;
      try {
        await api("/api/workspace/recover", { method: "POST", body: "{}" });
        recoveryResult = "恢复完成。请刷新页面重新读取工作区；刷新前请先备份提示未持久化的草稿。";
      } catch (error) {
        recoveryResult = error.message;
      } finally {
        recovering = false;
        result.textContent = recoveryResult;
        await refresh();
      }
    });
    banner.append(message, result, button);
    document.querySelector("main")?.prepend(banner);
  }
  banner.querySelector("[data-recovery-message]").textContent = note || "";
  banner.querySelector("[data-recovery-result]").textContent = recoveryResult;
  banner.querySelector("button").hidden = !note;
  banner.querySelector("button").disabled = recovering;
}

export function onTasks(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) fn(tasks);
}

export async function refresh() {
  try {
    const service = await api("/api/service");
    renderRecovery(service.recovery);
    let previous = instance;
    try { previous ||= sessionStorage.getItem("ct-service-instance"); } catch (_) {}
    if (previous && previous !== service.instanceId) {
      let notice = document.getElementById("ct-service-notice");
      if (!notice) {
        notice = document.createElement("div");
        notice.id = "ct-service-notice";
        notice.className = "ct-error-inline";
        notice.setAttribute("role", "alert");
        notice.textContent = "面板服务已重启；重启前未收到结果的操作状态未知，请核对文件或历史后再操作。草稿仍保留。";
        document.querySelector("main")?.prepend(notice);
      }
    }
    instance = service.instanceId;
    try { sessionStorage.setItem("ct-service-instance", instance); } catch (_) {}
    tasks = await api("/api/tasks");
    notify();
  } catch (e) { /* keep last known tasks */ }
}

export function startPolling(intervalMs = 1500) {
  if (timer) return;
  refresh();
  timer = window.setInterval(refresh, intervalMs);
}

export function stopPolling() {
  if (timer) { window.clearInterval(timer); timer = null; }
}

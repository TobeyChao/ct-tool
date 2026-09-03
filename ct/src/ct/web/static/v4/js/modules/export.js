/* export module: workspace summary, start export, poll progress. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

export async function mount(container) {
  const state = getState();
  if (state.mounted) return state;
  state.mounted = true;
  render();

  async function render() {
    let ws = null;
    try { ws = await api("/api/workspace"); } catch (e) { ws = null; }
    const changed = (ws && ws.status && ws.status.changed) || [];
    container.innerHTML = `
      <div class="ct-page-wrap">
        <div class="ct-panel">
          <div class="ct-panel-head"><span class="ct-panel-title">导出</span>
            <span class="ct-topbar-spacer" style="flex:1"></span>
            <button class="ct-btn ct-btn-ghost" id="v4-cancel" disabled>取消</button>
            <button class="ct-btn ct-btn-primary" id="v4-export">导出</button>
          </div>
          <div class="ct-panel-body">
            <div class="ct-badge ${changed.length ? "ct-badge-warn" : "ct-badge-ok"}">${changed.length ? changed.length + " 张表待导出" : "数据与模板均已同步"}</div>
            <div id="v4-progress"></div>
          </div>
        </div>
      </div>`;
    container.querySelector("#v4-export").addEventListener("click", async () => {
      try {
        const progress = await api("/api/export", { method: "POST", body: JSON.stringify({ forced: true }) });
        state.progress = progress;
        renderProgress();
        container.querySelector("#v4-cancel").disabled = false;
        poll();
      } catch (e) { showError(e.message); }
    });
    container.querySelector("#v4-cancel").addEventListener("click", async () => {
      try {
        state.progress = await api("/api/export/cancel", { method: "POST" });
        renderProgress();
      } catch (e) { showError(e.message); }
    });
  }

  function showError(message) {
    const host = container.querySelector("#v4-progress");
    if (host) host.innerHTML = '<div class="ct-error-inline">' + escapeHtml(message) + "</div>";
  }

  function renderProgress() {
    const host = container.querySelector("#v4-progress");
    if (!host || !state.progress) return;
    const p = state.progress;
    host.innerHTML = `<div class="ct-draft-status">步骤 ${p.current || ""} / ${p.total || ""} · ${escapeHtml(p.message || "")}</div>`;
  }

  let timer = null;
  function poll() {
    if (timer) return;
    timer = window.setInterval(async () => {
      try {
        state.progress = await api("/api/export/progress");
        renderProgress();
        if (!state.progress.running) {
          window.clearInterval(timer);
          timer = null;
        }
      } catch (e) { /* keep polling */ }
    }, 1000);
  }

  return state;
}

const _state = {};
function getState() { return _state; }

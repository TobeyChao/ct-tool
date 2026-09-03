/* export module: workspace summary, forced toggle, phase progress cells,
   last-export summary restored from /api/history. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

export async function mount(container) {
  const state = getState();
  if (state.mounted) return state;
  state.mounted = true;
  state.forced = true; // 管线当前恒为全量重建
  let ws = null;
  let lastExport = null;
  try { ws = await api("/api/workspace"); } catch (e) { ws = null; }
  try {
    const entries = await api("/api/history");
    lastExport = (entries && entries.length) ? entries[entries.length - 1] : null;
  } catch (e) { /* 忽略瞬时失败 */ }
  const changed = (ws && ws.status && ws.status.changed) || [];
  render(changed, lastExport);
  if (state.progress && state.progress.status === "running") poll();

  function render(changed, lastExport) {
    const p = state.progress;
    const running = !!(p && p.status === "running");
    container.innerHTML = `
      <div class="ct-page-wrap">
        <div class="ct-panel">
          <div class="ct-panel-head">
            <span class="ct-panel-title">导出</span>
            <span class="ct-topbar-spacer" style="flex:1"></span>
            <button class="ct-btn ct-btn-ghost" id="cancel" ${running ? "" : "disabled"}>取消</button>
            <button class="ct-btn ct-btn-primary" id="export" ${running ? "disabled" : ""}>${state.hasRun ? "重新导出" : "导出"}</button>
          </div>
          <div class="ct-panel-body">
            <div class="ct-export-toolbar">
              <label class="ct-check"><input type="checkbox" id="forced" ${state.forced ? "checked" : ""} ${running ? "disabled" : ""}>强制重建</label>
              <span class="ct-hint">当前恒为全量重建</span>
              <span style="flex:1"></span>
              <span class="ct-badge ${badgeClass(p, changed, lastExport)}" id="badge">${badgeText(p, changed, lastExport)}</span>
            </div>
            <div id="progress"></div>
            ${ws ? `<div class="ct-progress-line ct-mono">产物目录 ${escapeHtml(String(ws.root))}/output</div>` : ""}
          </div>
        </div>
      </div>`;

    container.querySelector("#forced").addEventListener("change", (e) => {
      state.forced = e.target.checked;
    });
    container.querySelector("#export").addEventListener("click", async () => {
      try {
        state.progress = await api("/api/export", {
          method: "POST",
          body: JSON.stringify({ forced: state.forced }),
        });
        state.hasRun = true;
        state.sessionRun = true;
        updateChrome();
        poll();
      } catch (e) { showError(e.message); }
    });
    container.querySelector("#cancel").addEventListener("click", async () => {
      try {
        state.progress = await api("/api/export/cancel", { method: "POST" });
        updateChrome();
      } catch (e) { showError(e.message); }
    });
    renderProgress();
  }

  function showError(message) {
    const host = container.querySelector("#progress");
    if (host) host.innerHTML = '<div class="ct-error-inline">' + escapeHtml(message) + "</div>";
  }

  function updateChrome() {
    const p = state.progress;
    const running = !!(p && p.status === "running");
    const cancel = container.querySelector("#cancel");
    const exportBtn = container.querySelector("#export");
    if (cancel) cancel.disabled = !running;
    if (exportBtn) exportBtn.disabled = running;
    const forced = container.querySelector("#forced");
    if (forced) forced.disabled = running;
    renderProgress();
  }

  function badgeClass(p, changed, lastExport) {
    if (!p || p.status === "idle") {
      if (lastExport) return "ct-badge-mute";
      return changed.length ? "ct-badge-warn" : "ct-badge-ok";
    }
    if (p.status === "running") return "ct-badge-mute";
    if (p.status === "done") return "ct-badge-ok";
    if (p.status === "cancelled") return "ct-badge-warn";
    return "ct-badge-err";
  }

  function badgeText(p, changed, lastExport) {
    if (!p || p.status === "idle") {
      if (lastExport) return lastExport.result;
      return changed.length ? changed.length + " 张表待导出" : "数据与模板均已同步";
    }
    if (p.status === "running") return "进行中";
    if (p.status === "done") return "成功 · " + p.tables_exported + " 张表" + (p.forced ? " · 强制重建" : "");
    if (p.status === "cancelled") return "已取消";
    return "已中止";
  }

  function cellClass(p, i) {
    if (p.status === "cancelled") return i < p.step_index ? "done" : (i === p.step_index ? "active" : "");
    if (p.status === "error") return i < p.step_index ? "done" : (i === p.step_index ? "error" : "");
    if (i < p.step_index) return "done";
    if (i === p.step_index) return p.status === "running" ? "active" : "done";
    return "";
  }

  function renderProgress() {
    const p = state.progress;
    const host = container.querySelector("#progress");
    const badgeEl = container.querySelector("#badge");
    if (badgeEl) {
      badgeEl.className = "ct-badge " + badgeClass(p, changed, lastExport);
      badgeEl.textContent = badgeText(p, changed, lastExport);
    }
    if (!host) return;
    // 本会话内任务或运行中：进度格子视图；否则回退到上次导出摘要/空态
    if (p && (state.sessionRun || p.status === "running")) {
      let html = "";
      if (p.steps && p.steps.length) {
        html += '<div class="ct-prog-cells">' + p.steps.map((s, i) => {
          const cls = cellClass(p, i);
          return `<span class="ct-prog-cell${cls ? " " + cls : ""}"><span class="ct-prog-num">${i + 1}</span>${escapeHtml(s)}</span>`;
        }).join("") + "</div>";
      }
      if (p.message) html += `<div class="ct-progress-line">${escapeHtml(p.message)}</div>`;
      if (p.errors && p.errors.length) {
        html += p.errors.map((e) => `<div class="ct-error-inline">${escapeHtml(e)}</div>`).join("");
      }
      if (p.status === "running" || p.status === "done" || p.status === "cancelled" || p.status === "error") {
        html += `<div class="ct-summary-line">`
          + `<span>已导出 <b>${p.tables_exported || 0}</b> 张表</span>`
          + `<span>状态 <b>${escapeHtml(p.status)}</b></span>`
          + `<span>耗时 <b>${p.elapsed || 0}s</b></span>`
          + `</div>`;
      }
      host.innerHTML = html;
    } else if (lastExport) {
      host.innerHTML = `<div class="ct-progress-line">上次导出 ${escapeHtml(String(lastExport.time))}`
        + ` · ${escapeHtml(String(lastExport.scope))} · ${lastExport.tables} 张表 · ${lastExport.elapsed}s</div>`;
    } else {
      host.innerHTML = '<div class="ct-empty"><div class="ct-empty-title">还没有导出记录</div>'
        + '<div class="ct-empty-sub">点击「导出」进行第一次导出</div></div>';
    }
  }

  let timer = null;
  function poll() {
    if (timer) return;
    timer = window.setInterval(async () => {
      try {
        state.progress = await api("/api/export/progress");
        updateChrome();
        if (state.progress.status !== "running") {
          window.clearInterval(timer);
          timer = null;
        }
      } catch (e) { /* keep polling */ }
    }, 700);
  }

  return state;
}

const _state = {};
function getState() { return _state; }

/* Export module: full-rebuild context, phase progress, and persistent task state. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

const STATUS = {
  idle: { label: "准备就绪", badge: "ct-badge-mute" },
  running: { label: "导出中", badge: "ct-badge-mute" },
  done: { label: "导出成功", badge: "ct-badge-ok" },
  cancelled: { label: "已取消", badge: "ct-badge-warn" },
  error: { label: "导出中止", badge: "ct-badge-err" },
};

const _state = {};

function statusView(progress, changed, lastExport) {
  if (!progress || progress.status === "idle") {
    if (changed.length) return { label: `${changed.length} 张表待导出`, badge: "ct-badge-warn" };
    if (lastExport) return { label: "上次导出成功", badge: "ct-badge-ok" };
    return STATUS.idle;
  }
  const base = STATUS[progress.status] || STATUS.error;
  const label = progress.status === "done"
    ? `成功 · ${progress.tables_exported || 0} 张表`
    : base.label;
  return { ...base, label };
}

function phaseClass(progress, index) {
  if (!progress) return "";
  if (index < progress.step_index) return "done";
  if (index > progress.step_index) return "";
  if (progress.status === "error") return "error";
  if (progress.status === "running") return "active";
  return progress.status === "done" ? "done" : "";
}

export async function mount(container) {
  const state = _state;
  let timer = null;
  if (state.mounted) return state;
  state.mounted = true;

  try { state.workspace = await api("/api/workspace"); } catch (error) { state.workspaceError = error.message; }
  try { state.progress = await api("/api/export/progress"); } catch (error) { state.progress = null; }
  try {
    const entries = await api("/api/history");
    state.lastExport = entries?.length ? entries[entries.length - 1] : null;
  } catch (error) { state.lastExport = null; }

  state.changed = state.workspace?.status?.changed || [];
  state.hasRun = state.progress?.status !== "idle" || Boolean(state.lastExport);
  renderShell();
  update();
  if (state.progress?.status === "running") poll();

  function renderShell() {
    container.innerHTML = `
      <div class="ct-page-wrap">
        <div class="ct-panel">
          <div class="ct-panel-head ct-module-head">
            <div><h1 class="ct-panel-title">导出</h1><p>全量重建：校验通过后生成 JSON、FBS、Binary 与 C#/Lua Accessor。</p></div>
            <div class="ct-module-actions">
              <span class="ct-badge" id="export-badge"></span>
              <div class="ct-command-actions" id="export-actions"></div>
            </div>
          </div>
          <div class="ct-panel-body">
            ${state.workspaceError ? `<div class="ct-error-inline">${escapeHtml(state.workspaceError)}</div>` : ""}
            <div class="ct-export-layout">
              <section class="ct-workbench-section" aria-labelledby="export-progress-title">
                <div class="ct-section-bar">
                  <div><h2 id="export-progress-title">执行进度</h2><p id="export-message">尚未开始导出</p></div>
                  <span class="ct-live-note"><span aria-hidden="true"></span>任务状态自动更新</span>
                </div>
                <div id="progress" aria-live="polite"></div>
              </section>
              <aside class="ct-export-context" aria-label="导出上下文">
                <h2>本次导出</h2>
                <dl class="ct-context-list">
                  <div><dt>构建模式</dt><dd>全量重建</dd></div>
                  <div><dt>待处理</dt><dd id="export-context-pending"></dd></div>
                  <div><dt>执行结果</dt><dd id="export-context-result"></dd></div>
                  <div class="ct-context-path"><dt>产物目录</dt><dd>${outputPath()}</dd></div>
                </dl>
              </aside>
            </div>
          </div>
        </div>
      </div>`;
  }

  function renderActions() {
    const host = container.querySelector("#export-actions");
    if (!host) return;
    const running = state.progress?.status === "running";
    host.innerHTML = `
      <button class="ct-btn ct-btn-ghost" id="export-cancel" ${running ? "" : "hidden"}>取消</button>
      <button class="ct-btn ct-btn-primary" id="export-start" ${running ? "disabled" : ""}>${state.hasRun ? "重新导出" : "开始导出"}</button>`;
    host.querySelector("#export-start").addEventListener("click", startExport);
    host.querySelector("#export-cancel")?.addEventListener("click", cancelExport);
  }

  async function startExport() {
    try {
      state.progress = await api("/api/export", { method: "POST", body: JSON.stringify({}) });
      state.hasRun = true;
      state.sessionRun = true;
      update();
      poll();
    } catch (error) { showError(error.message); }
  }

  async function cancelExport() {
    try {
      state.progress = await api("/api/export/cancel", { method: "POST" });
      update();
    } catch (error) { showError(error.message); }
  }

  function update() {
    const view = statusView(state.progress, state.changed, state.lastExport);
    const badge = container.querySelector("#export-badge");
    if (badge) {
      badge.className = `ct-badge ${view.badge}`;
      badge.textContent = view.label;
    }
    renderContext();
    renderProgress();
    renderActions();
  }

  function renderContext() {
    const progress = state.progress;
    const pending = container.querySelector("#export-context-pending");
    const result = container.querySelector("#export-context-result");
    if (pending) {
      pending.textContent = progress?.status === "done" ? "0 张表" : `${state.changed.length} 张表`;
    }
    if (!result) return;
    if (!progress || progress.status === "idle") {
      result.textContent = lastExportText();
    } else if (progress.status === "running") {
      result.textContent = progress.step_name ? `进行中 · ${progress.step_name}` : "准备中";
    } else if (progress.status === "done") {
      result.textContent = `成功 · ${progress.tables_exported || 0} 张表 · ${progress.elapsed || 0}s`;
    } else if (progress.status === "cancelled") {
      result.textContent = "已取消";
    } else {
      result.textContent = progress.message || "导出中止";
    }
  }

  function renderProgress() {
    const progress = state.progress;
    const host = container.querySelector("#progress");
    const message = container.querySelector("#export-message");
    if (!host || !message) return;

    if (progress && (state.sessionRun || progress.status !== "idle")) {
      message.textContent = progress.message || STATUS[progress.status]?.label || "正在处理";
      const phases = progress.steps?.length
        ? `<ol class="ct-prog-cells">${progress.steps.map((step, index) => {
          const cls = phaseClass(progress, index);
          return `<li class="ct-prog-cell${cls ? ` ${cls}` : ""}"><span class="ct-prog-num">${index + 1}</span><span>${escapeHtml(step)}</span></li>`;
        }).join("")}</ol>`
        : "";
      const errors = progress.errors?.length
        ? `<div class="ct-export-errors">${progress.errors.map((error) => `<div class="ct-error-inline">${escapeHtml(error)}</div>`).join("")}</div>`
        : "";
      host.innerHTML = `${phases}${errors}<div class="ct-summary-line">
        <span>已导出 <b>${progress.tables_exported || 0}</b> 张表</span>
        <span>当前阶段 <b>${escapeHtml(progress.step_name || "—")}</b></span>
        <span>耗时 <b>${progress.elapsed || 0}s</b></span>
      </div>`;
      return;
    }

    message.textContent = state.lastExport ? "可以重新生成当前工作区产物" : "完成首次导出后，这里会保留阶段结果";
    host.innerHTML = `<div class="ct-empty ct-export-empty">
      <div class="ct-empty-title">${state.lastExport ? "工作区可以导出" : "还没有导出记录"}</div>
      <div class="ct-empty-sub">${state.changed.length ? `${state.changed.length} 张表存在待导出变更` : "当前源数据与模板状态正常"}</div>
    </div>`;
  }

  function showError(message) {
    const host = container.querySelector("#progress");
    if (host) host.innerHTML = `<div class="ct-error-inline">${escapeHtml(message)}</div>`;
  }

  function lastExportText() {
    const entry = state.lastExport;
    if (!entry) return "暂无记录";
    return `${String(entry.time)} · ${String(entry.result)}`;
  }

  function outputPath() {
    if (!state.workspace?.root) return "—";
    const path = `${String(state.workspace.root)}/output`;
    return `<code title="${escapeHtml(path)}">${escapeHtml(path)}</code>`;
  }

  function poll() {
    if (timer) return;
    timer = window.setInterval(async () => {
      try {
        state.progress = await api("/api/export/progress");
        update();
        if (state.progress.status !== "running") {
          window.clearInterval(timer);
          timer = null;
        }
      } catch (error) { /* retain the last known task state */ }
    }, 500);
  }

  return state;
}

/* Export module: incremental/forced builds, phase progress, and persistent task state. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { confirmDialog, openDialog } from "../core/dialog.js";
import { resultLabel } from "../core/labels.js";

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
  state.drifted = state.workspace?.status?.drifted || [];
  state.missing = state.workspace?.status?.missing || [];
  state.hasRun = state.progress?.status !== "idle" || Boolean(state.lastExport);
  renderShell();
  update();
  if (state.progress?.status === "running") poll();

  // The export page stays mounted while switching modules. Refresh the
  // workspace status whenever the user returns, otherwise changed/drifted can
  // remain a stale snapshot from the previous visit.
  window.addEventListener("ct:module", (event) => {
    if (event.detail === "export") refreshWorkspaceStatus();
  });

  async function refreshWorkspaceStatus() {
    try {
      state.workspace = await api("/api/workspace");
      state.changed = state.workspace?.status?.changed || [];
      state.drifted = state.workspace?.status?.drifted || [];
      state.missing = state.workspace?.status?.missing || [];
      update();
    } catch (error) {
      state.workspaceError = error.message;
      update();
    }
  }

  function renderShell() {
    container.innerHTML = `
      <div class="ct-page-wrap">
        <div class="ct-panel">
          <div class="ct-panel-head ct-module-head">
            <div><h1 class="ct-panel-title">导出</h1><p>增量导出：校验通过后复用未变化产物，生成 JSON、FBS、Binary 与 C#/Lua Accessor。</p></div>
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
                  <div><dt>构建模式</dt><dd id="export-context-mode">增量导出</dd></div>
                  <div><dt>待导出</dt><dd id="export-context-pending"></dd></div>
                  <div><dt>模板待更新</dt><dd id="export-context-drifted"></dd></div>
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
    const busy = running || state.submitting;
    const pendingTemplates = state.drifted.length + state.missing.length;
    host.innerHTML = `
      ${pendingTemplates && !running ? '<button class="ct-btn ct-btn-ghost" id="export-regenerate-template">重新生成模板</button>' : ""}
      <button class="ct-btn ct-btn-ghost" id="export-cancel" ${running ? "" : "hidden"}>取消</button>
      <button class="ct-btn ct-btn-ghost" id="export-force" title="跳过增量缓存，重新生成所有产物" ${busy ? "disabled" : ""}>强制全量重建</button>
      <button class="ct-btn ct-btn-primary" id="export-start" ${busy ? "disabled" : ""}>${state.hasRun ? "重新导出" : "开始导出"}</button>`;
    host.querySelector("#export-start").addEventListener("click", () => startExport(false));
    host.querySelector("#export-force").addEventListener("click", () => startExport(true));
    host.querySelector("#export-cancel")?.addEventListener("click", cancelExport);
    host.querySelector("#export-regenerate-template")?.addEventListener("click", regenerateTemplates);
  }

  function regenerateTemplates() {
    const drifted = [...state.drifted];
    const missing = [...state.missing];
    if (!drifted.length && !missing.length) return;
    // 漂移 = 覆盖已有 Excel（迁移保留数据行）；缺失 = 全新文件，无覆盖风险
    const driftedBlock = drifted.length
      ? `<p>以下表的 Schema 与 Excel 模板布局不一致：</p><p class="ct-mono">${drifted.map(escapeHtml).join("、")}</p>`
      : "";
    const missingBlock = missing.length
      ? `<p>以下表还没有 Excel 模板，将按当前 Schema 新建：</p><p class="ct-mono">${missing.map(escapeHtml).join("、")}</p>`
      : "";
    const warning = drifted.length
      ? '<p class="ct-dialog-warning">重新生成会覆盖漂移表的 Excel 文件，请确认已备份或不再需要当前填写内容。</p>'
      : "<p>新建模板不会覆盖任何已有文件。</p>";
    confirmDialog({
      title: "重新生成模板？",
      body: driftedBlock + missingBlock + warning,
      confirmLabel: drifted.length ? "覆盖并生成" : "生成模板",
      onConfirm: (handle) => {
        const button = handle.el.querySelector("[data-confirm]");
        if (button) { button.disabled = true; button.textContent = "生成中…"; }
        const tables = [...new Set([...drifted, ...missing])];
        Promise.all(tables.map((table) => api("/api/schema-workspace/gen-template", {
          method: "POST",
          body: JSON.stringify({ table }),
        }))).then(async () => {
          handle.close();
          state.workspace = await api("/api/workspace");
          state.changed = state.workspace?.status?.changed || [];
          state.drifted = state.workspace?.status?.drifted || [];
          state.missing = state.workspace?.status?.missing || [];
          update();
          window.dispatchEvent(new CustomEvent("ct:draft", { detail: { successText: `已重新生成模板：${tables.join("、")}` } }));
        }).catch((error) => {
          if (button) { button.disabled = false; button.textContent = "覆盖并生成"; }
          openDialog({ title: "模板生成失败", body: `<p>${escapeHtml(error.message)}</p>`, footer: '<button class="ct-btn ct-btn-primary" data-close>知道了</button>' });
        });
        return false;
      },
    });
  }

  async function startExport(forced = false) {
    if (state.submitting || state.progress?.status === "running") return;
    state.submitting = true;
    renderActions();
    try {
      state.progress = await api("/api/export", { method: "POST", body: JSON.stringify({ forced }) });
      state.hasRun = true;
      state.sessionRun = true;
      update();
      poll();
    } catch (error) { showError(error.message); }
    finally {
      state.submitting = false;
      renderActions();
    }
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
    const mode = container.querySelector("#export-context-mode");
    if (mode) mode.textContent = progress?.forced ? "强制全量重建" : "增量导出";
    const pending = container.querySelector("#export-context-pending");
    const drifted = container.querySelector("#export-context-drifted");
    const result = container.querySelector("#export-context-result");
    if (pending) {
      pending.textContent = progress?.status === "done" ? "0 张表" : `${state.changed.length} 张表`;
    }
    if (drifted) {
      const pendingTemplates = state.drifted.length + state.missing.length;
      drifted.textContent = pendingTemplates ? `${pendingTemplates} 张表` : "无";
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
      <div class="ct-empty-sub">${(state.drifted.length || state.missing.length)
        ? `${state.drifted.length + state.missing.length} 张表模板待更新`
        : state.changed.length ? `${state.changed.length} 张表存在待导出变更` : "当前源数据与模板状态正常"}</div>
    </div>`;
  }

  function showError(message) {
    const host = container.querySelector("#progress");
    if (host) host.innerHTML = `<div class="ct-error-inline">${escapeHtml(message)}</div>`;
  }

  function lastExportText() {
    const entry = state.lastExport;
    if (!entry) return "暂无记录";
    return `${String(entry.time)} · ${resultLabel(entry.result)}`;
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

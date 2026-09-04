/* Logs module: filterable live log stream that stays fresh across module switches. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

const MODULES = ["all", "导出", "校验", "i18n", "模板", "系统"];
const LEVELS = ["all", "INFO", "WARN", "ERROR"];
const _state = {};

function badgeClass(level) {
  if (level === "ERROR") return "ct-badge-err";
  if (level === "WARN") return "ct-badge-warn";
  return "ct-badge-mute";
}

export async function mount(container) {
  const state = _state;
  let timer = null;
  if (state.mounted) return state;
  state.mounted = true;
  state.module = "all";
  state.level = "all";
  state.search = "";
  state.logs = [];

  renderShell();
  bindControls();
  await refreshLogs();
  startPolling();

  function renderShell() {
    container.innerHTML = `
      <div class="ct-page-wrap">
        <div class="ct-panel">
          <div class="ct-panel-head ct-module-head">
            <div><h1 class="ct-panel-title">日志</h1><p>跟踪导出、校验与工作区操作。</p></div>
            <div class="ct-module-actions"><span class="ct-live-note"><span aria-hidden="true"></span>自动更新</span></div>
          </div>
          <div class="ct-panel-body ct-log-body">
            <div class="ct-log-controls" aria-label="日志筛选">
              <div class="ct-filter-group" id="log-modules" aria-label="模块"></div>
              <div class="ct-filter-divider" aria-hidden="true"></div>
              <div class="ct-filter-group" id="log-levels" aria-label="级别"></div>
              <label class="ct-log-search-wrap">
                <span class="ct-sr-only">搜索日志</span>
                <input class="ct-input ct-log-search" id="log-search" type="search" placeholder="搜索日志…" autocomplete="off">
              </label>
              <button class="ct-btn ct-btn-ghost ct-btn-sm" id="logs-refresh">刷新</button>
            </div>
            <div class="ct-log-summary" id="log-summary" aria-live="polite"></div>
            <div id="log-content"></div>
          </div>
        </div>
      </div>`;
    renderFilters();
  }

  function renderFilters() {
    const modules = container.querySelector("#log-modules");
    const levels = container.querySelector("#log-levels");
    modules.innerHTML = MODULES.map((module) => `<button class="ct-pill ${state.module === module ? "active" : ""}" data-module="${module}" aria-pressed="${state.module === module}">${module === "all" ? "全部模块" : module}</button>`).join("");
    levels.innerHTML = LEVELS.map((level) => `<button class="ct-pill ${state.level === level ? "active" : ""}" data-level="${level}" aria-pressed="${state.level === level}">${level === "all" ? "全部级别" : level}</button>`).join("");
  }

  function bindControls() {
    container.addEventListener("click", (event) => {
      const moduleButton = event.target.closest("#log-modules [data-module]");
      const levelButton = event.target.closest("#log-levels [data-level]");
      if (moduleButton) {
        state.module = moduleButton.dataset.module;
        renderFilters();
        refreshLogs();
      } else if (levelButton) {
        state.level = levelButton.dataset.level;
        renderFilters();
        renderLogs();
      } else if (event.target.closest("#logs-clear-filters")) {
        state.module = "all";
        state.level = "all";
        state.search = "";
        container.querySelector("#log-search").value = "";
        renderFilters();
        refreshLogs();
      } else if (event.target.closest("#logs-go-export")) {
        location.hash = "#/export";
      } else if (event.target.closest("#logs-retry")) {
        refreshLogs();
      } else if (event.target.closest("#logs-refresh")) {
        refreshLogs();
      }
    });
    container.querySelector("#log-search").addEventListener("input", (event) => {
      state.search = event.target.value;
      renderLogs();
    });
  }

  function visibleLogs() {
    const query = state.search.trim().toLocaleLowerCase();
    return state.logs.filter((row) => {
      const levelMatches = state.level === "all" || (row.level || "INFO").toUpperCase() === state.level;
      const queryMatches = !query || `${row.time} ${row.module} ${row.level} ${row.message}`.toLocaleLowerCase().includes(query);
      return levelMatches && queryMatches;
    });
  }

  async function refreshLogs() {
    try {
      state.logs = await api(`/api/logs?module=${encodeURIComponent(state.module)}`);
      state.error = "";
    } catch (error) {
      state.error = error.message;
    }
    renderLogs();
  }

  function renderLogs() {
    const host = container.querySelector("#log-content");
    const summary = container.querySelector("#log-summary");
    if (!host || !summary) return;

    if (state.error) {
      summary.textContent = "日志暂不可用";
      host.innerHTML = `<div class="ct-error-inline ct-log-error"><span>${escapeHtml(state.error)}</span><button class="ct-inline-btn" id="logs-retry">重试</button></div>`;
      return;
    }

    const rows = visibleLogs();
    summary.textContent = `${rows.length} 条记录${rows.length !== state.logs.length ? ` · 共 ${state.logs.length} 条` : ""}`;
    if (!rows.length) {
      const filtered = state.module !== "all" || state.level !== "all" || state.search.trim();
      host.innerHTML = `<div class="ct-empty ct-log-empty">
        <div class="ct-empty-title">${filtered ? "没有匹配的日志" : "还没有运行日志"}</div>
        <div class="ct-empty-sub">${filtered ? "调整筛选条件，或清除筛选查看全部记录。" : "运行一次导出后，执行过程会实时显示在这里。"}</div>
        <button class="ct-btn ct-btn-ghost ct-empty-cta" id="${filtered ? "logs-clear-filters" : "logs-go-export"}">${filtered ? "清除筛选" : "前往导出"}</button>
      </div>`;
      return;
    }

    host.innerHTML = `<div class="ct-table-wrap ct-log-table-wrap"><table class="ct-data ct-log-table">
      <thead><tr><th>时间</th><th>模块</th><th>级别</th><th>信息</th></tr></thead>
      <tbody>${rows.map((row) => `<tr>
        <td data-label="时间"><span class="ct-mono">${escapeHtml(row.time)}</span></td>
        <td data-label="模块">${escapeHtml(row.module)}</td>
        <td data-label="级别"><span class="ct-badge ${badgeClass((row.level || "INFO").toUpperCase())}">${escapeHtml(row.level)}</span></td>
        <td data-label="信息" class="ct-log-message">${escapeHtml(row.message)}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function startPolling() {
    if (timer) return;
    timer = window.setInterval(refreshLogs, 1200);
  }

  return state;
}

/* logs module: module-filtered log list with live refresh. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

const MODULES = ["all", "导出", "校验", "i18n", "模板", "系统"];
const LEVELS = ["all", "INFO", "WARN", "ERROR"];

export async function mount(container) {
  const state = getState();
  if (state.mounted) return state;
  state.mounted = true;
  state.module = state.module || "all";
  state.level = state.level || "all";
  state.search = state.search || "";
  render();

  function visibleLogs(logs) {
    let visible = logs;
    if (state.level !== "all") {
      visible = visible.filter((row) => (row.level || "INFO").toUpperCase() === state.level);
    }
    if (state.search) {
      const query = state.search.toLowerCase();
      visible = visible.filter((row) => (row.message || "").toLowerCase().includes(query));
    }
    return visible;
  }

  function logRows(logs) {
    return visibleLogs(logs).map((row) => `<tr><td class="ct-mono">${escapeHtml(row.time)}</td><td>${escapeHtml(row.module)}</td>
      <td><span class="ct-badge ct-badge-mute">${escapeHtml(row.level)}</span></td><td>${escapeHtml(row.message)}</td></tr>`).join("");
  }

  async function render() {
    let logs = [];
    try { logs = await api("/api/logs?module=" + encodeURIComponent(state.module)); } catch (e) { logs = []; }
    container.innerHTML = `
      <div class="ct-page-wrap">
        <div class="ct-panel">
          <div class="ct-panel-head"><span class="ct-panel-title">运行日志</span></div>
          <div class="ct-panel-body">
            <div class="ct-log-toolbar">${MODULES.map((m) =>
              `<button class="ct-pill ${state.module === m ? "active" : ""}" data-module="${m}">${m === "all" ? "全部" : m}</button>`
            ).join("")}</div>
            <div class="ct-log-toolbar">${LEVELS.map((l) =>
              `<button class="ct-pill ${state.level === l ? "active" : ""}" data-level="${l}">${l === "all" ? "全部级别" : l}</button>`
            ).join("")}
            <input class="ct-input ct-log-search" id="log-search" placeholder="搜索日志…" value="${escapeHtml(state.search || "")}"></div>
            <div class="ct-table-wrap"><table class="ct-data"><thead><tr><th>时间</th><th>模块</th><th>级别</th><th>信息</th></tr></thead>
            <tbody>${logRows(logs)}
            </tbody></table></div>
          </div>
        </div>
      </div>`;
    container.querySelectorAll("[data-module]").forEach((btn) => {
      btn.addEventListener("click", () => { state.module = btn.dataset.module; render(); });
    });
    container.querySelectorAll("[data-level]").forEach((btn) => {
      btn.addEventListener("click", () => { state.level = btn.dataset.level; render(); });
    });
    const search = container.querySelector("#log-search");
    if (search) search.addEventListener("input", () => {
      state.search = search.value;
      const body = container.querySelector(".ct-data tbody");
      if (body) body.innerHTML = logRows(logs);
    });
  }
  return state;
}
const _state = {};
function getState() { return _state; }

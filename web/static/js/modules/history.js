/* history module: recent export history. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { resultLabel } from "../core/labels.js";

function exactCount(value) {
  if (value && typeof value === "object" && Object.keys(value).length === 1 && typeof value.$int === "string") return value.$int;
  return value ?? "";
}

export async function mount(container) {
  const state = getState();
  if (state.mounted) return state;
  state.mounted = true;
  window.addEventListener("ct:module", (event) => { if (event.detail === "history") refresh(); });
  return refresh();

  async function refresh() {
  state.error = "";
  let history = [];
  try { history = await api("/api/history"); } catch (e) { state.error = e.message; }
  container.innerHTML = `
    <div class="ct-page-wrap">
      <div class="ct-panel">
        <div class="ct-panel-head ct-module-head">
          <div><h1 class="ct-panel-title">历史</h1><p>最近导出记录与结果。</p></div>
        </div>
        <div class="ct-panel-body">
          ${state.error ? '<div class="ct-error-inline">' + escapeHtml(state.error) + "</div>" : ""}
          ${history.length ? `<div class="ct-table-wrap" role="region" tabindex="0" aria-label="导出历史"><table class="ct-data"><thead><tr><th>时间</th><th>范围</th><th>结果</th><th>表数</th><th>耗时</th></tr></thead>
          <tbody>${history.map((h) => `<tr><td class="ct-mono">${escapeHtml(h.time)}</td><td>${escapeHtml(h.scope)}</td>
            <td><span class="ct-badge ${h.result === "success" ? "ct-badge-ok" : "ct-badge-err"}">${escapeHtml(resultLabel(h.result))}</span></td>
            <td>${escapeHtml(exactCount(h.tables))}</td><td>${escapeHtml(h.elapsed ?? "")}s</td></tr>`).join("")}</tbody></table></div>`
            : '<div class="ct-empty"><div class="ct-empty-sub">暂无导出历史</div></div>'}
        </div>
      </div>
    </div>`;
  return state;
  }
}
const _state = {};
function getState() { return _state; }

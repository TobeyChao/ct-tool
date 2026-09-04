/* history module: recent export history. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

export async function mount(container) {
  const state = getState();
  if (state.mounted) return state;
  state.mounted = true;
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
          ${history.length ? `<div class="ct-table-wrap"><table class="ct-data"><thead><tr><th>时间</th><th>范围</th><th>结果</th><th>表数</th><th>耗时</th></tr></thead>
          <tbody>${history.map((h) => `<tr><td class="ct-mono">${escapeHtml(h.time)}</td><td>${escapeHtml(h.scope)}</td>
            <td><span class="ct-badge ${h.result === "success" ? "ct-badge-ok" : "ct-badge-err"}">${escapeHtml(h.result)}</span></td>
            <td>${h.tables ?? ""}</td><td>${h.elapsed ?? ""}s</td></tr>`).join("")}</tbody></table></div>`
            : '<div class="ct-empty"><div class="ct-empty-sub">暂无导出历史</div></div>'}
        </div>
      </div>
    </div>`;
  return state;
}
const _state = {};
function getState() { return _state; }

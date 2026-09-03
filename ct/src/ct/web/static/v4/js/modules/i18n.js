/* i18n module: per-language translation progress. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

export async function mount(container, force = false) {
  const state = getState();
  if (state.mounted && !force) return state;
  state.mounted = true;
  let langEntries = [];
  try {
    const data = await api("/api/i18n/status");
    const map = data && typeof data === "object" ? data : {};
    langEntries = Object.entries(map).map(([lang, value]) => ({ lang, ...(value || {}) }));
  } catch (e) { state.error = e.message; }

  container.innerHTML = `
    <div class="ct-page-wrap">
      <div class="ct-panel">
        <div class="ct-panel-head"><span class="ct-panel-title">翻译进度</span>
          <span class="ct-topbar-spacer" style="flex:1"></span>
          <button class="ct-btn ct-btn-ghost" id="i18n-compact">清理孤儿</button>
          <button class="ct-btn ct-btn-primary" id="i18n-sync">同步</button>
        </div>
        <div class="ct-panel-body">
          ${state.error ? '<div class="ct-error-inline">' + escapeHtml(state.error) + "</div>" : ""}
          <div class="ct-table-wrap"><table class="ct-data"><thead><tr><th>语言</th><th>已译</th><th>缺失</th><th>待审</th><th>孤儿</th><th>进度</th></tr></thead>
          <tbody>${langEntries.map((lang) => `<tr>
            <td>${escapeHtml(lang.lang || lang)}</td>
            <td>${lang.translated ?? 0}</td><td>${lang.missing ?? 0}</td>
            <td>${lang.stale ?? 0}</td><td>${lang.orphan ?? 0}</td>
            <td>${lang.progress ?? ""}</td></tr>`).join("")}
          </tbody></table></div>
        </div>
      </div>
    </div>`;
  container.querySelector("#i18n-sync").addEventListener("click", async () => {
    try {
      await api("/api/i18n/sync", { method: "POST", body: JSON.stringify({}) });
      mount(container, true);
    } catch (e) { state.error = e.message; mount(container, true); }
  });
  container.querySelector("#i18n-compact").addEventListener("click", async () => {
    try {
      const data = await api("/api/i18n/compact", { method: "POST", body: JSON.stringify({}) });
      state.error = data.total_removed ? "已清理 " + data.total_removed + " 条孤儿" : "";
      mount(container, true);
    } catch (e) { state.error = e.message; mount(container, true); }
  });
  return state;
}

const _state = {};
function getState() { return _state; }

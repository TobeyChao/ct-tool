/* i18n module: translation editor (choose table → pick language → inline edit →
   save per entry), per-table progress detail, and orphan compact preview.
   Rendered in the panel's new ct-* style. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

export async function mount(container, force = false) {
  const state = getState();
  if (state.mounted && !force) return state;
  state.mounted = true;

  try {
    const ws = await api("/api/workspace");
    state.primaryLang = (ws && ws.config && ws.config.primary_lang) || "zh";
    state.langs = (ws && ws.config && ws.config.secondary_langs) || [];
  } catch (e) { state.error = e.message; }
  try {
    const tables = await api("/api/i18n/tables");
    state.tables = tables || [];
    if (!state.currentTable) {
      const first = state.tables.find((t) => t.has_i18n) || state.tables[0];
      if (first) state.currentTable = first.table;
    }
  } catch (e) { state.error = e.message; }
  if (!state.lang && state.langs.length) state.lang = state.langs[0];

  bindOnce(container);
  await Promise.all([loadEntries(), loadProgress()]);
  render(container);
  return state;
}

function bindOnce(container) {
  const state = getState();
  if (state._bound) return;
  state._bound = true;

  // typing edits a draft keyed by entry.key; no re-render, so focus is kept
  container.addEventListener("input", (e) => {
    const key = e.target && e.target.dataset && e.target.dataset.key;
    if (!key) return;
    const draft = state.drafts[key] || { confirmed: false };
    draft.text = e.target.value;
    state.drafts[key] = draft;
  });

  container.addEventListener("click", (e) => {
    const outer = e.target;
    if (outer && outer.classList && outer.classList.contains("ct-dialog-mask")) {
      closeAllDialogs();
      return;
    }
    const btn = e.target.closest("button");
    if (!btn) return;
    const id = btn.id;
    const key = btn.dataset.key;
    const lang = btn.dataset.lang;
    const filter = btn.dataset.filter;
    const pick = btn.dataset.pickTable;
    const view = btn.dataset.view;

    if (id === "i18n-sync") return syncAll(container);
    if (id === "i18n-compact") return openCompact(container);
    if (id === "i18n-progress") { state.progressModal = !state.progressModal; return render(container); }
    if (id === "i18n-pick") { state.pickTable = true; return render(container); }
    if (key) return saveEntry(container, key);
    if (lang) { state.lang = lang; return refresh(container); }
    if (filter) { state.statusFilter = filter; return render(container); }
    if (pick) { state.currentTable = pick; state.pickTable = false; return refresh(container); }
    if (view) { state.progressView = view; return render(container); }
    if (btn.dataset.confirmCompact) return confirmCompact(container);
    if (btn.dataset.close) { state.pickTable = false; state.progressModal = false; state.compactModal = false; return render(container); }
  });
}

function closeAllDialogs() {
  const state = getState();
  state.pickTable = false;
  state.progressModal = false;
  state.compactModal = false;
}

/* ---------------- data loads ---------------- */

async function loadEntries() {
  const state = getState();
  if (!state.currentTable || !state.lang) return;
  try {
    state.entries = await api("/api/i18n/entries?table=" + encodeURIComponent(state.currentTable) + "&lang=" + encodeURIComponent(state.lang));
    state.drafts = {};
    state.error = "";
  } catch (e) { state.error = e.message; }
}

async function loadProgress() {
  const state = getState();
  try { state.progress = (await api("/api/i18n/status")) || {}; } catch (e) { /* 瞬时失败忽略 */ }
}

async function refresh(container) {
  const state = getState();
  try { await loadEntries(); await loadProgress(); } finally { render(container); }
}

async function saveEntry(container, key) {
  const state = getState();
  const existing = state.entries.find((en) => en.key === key);
  const draft = state.drafts[key] || {};
  const text = draft.text !== undefined ? draft.text : (existing ? existing.text : "");
  try {
    await api("/api/i18n/entry", {
      method: "POST",
      body: JSON.stringify({ table: state.currentTable, lang: state.lang, key, text, confirmed: true }),
    });
    await loadEntries();
    await loadProgress();
    state.error = "";
  } catch (e) { state.error = e.message; }
  render(container);
}

async function syncAll(container) {
  const state = getState();
  state.busy = true;
  render(container);
  try {
    await api("/api/i18n/sync", { method: "POST", body: JSON.stringify({ table: state.currentTable }) });
    await loadEntries();
    await loadProgress();
  } catch (e) { state.error = e.message; }
  finally { state.busy = false; render(container); }
}

async function openCompact(container) {
  const state = getState();
  try {
    state.compactPreview = await api("/api/i18n/compact", { method: "POST", body: JSON.stringify({ table: state.currentTable, dry_run: true }) });
    state.compactModal = true;
    state.error = "";
  } catch (e) { state.error = e.message; }
  render(container);
}

async function confirmCompact(container) {
  const state = getState();
  try {
    await api("/api/i18n/compact", { method: "POST", body: JSON.stringify({ table: state.currentTable, dry_run: false }) });
    state.compactModal = false;
    await loadEntries();
    await loadProgress();
  } catch (e) { state.error = e.message; }
  render(container);
}

/* ---------------- render ---------------- */

function render(container) {
  const state = getState();
  const filtered = state.entries.filter((e) => state.statusFilter === "all" || e.status === state.statusFilter);
  const orphans = currentOrphans();
  container.innerHTML = `
    <div class="ct-page-wrap">
      <div class="ct-panel">
        <div class="ct-panel-head">
          <span class="ct-panel-title">翻译 i18n</span>
          <span class="ct-topbar-spacer" style="flex:1"></span>
          <button class="ct-btn ct-btn-ghost" id="i18n-progress">全部表进度</button>
          <button class="ct-btn ct-btn-danger" id="i18n-compact" ${orphans > 0 ? "" : "disabled"}>清理无主条目${orphans > 0 ? "（" + orphans + "）" : ""}</button>
          <button class="ct-btn ct-btn-primary" id="i18n-sync" ${state.busy ? "disabled" : ""}>${state.busy ? "同步中…" : "同步全部语言"}</button>
        </div>
        <div class="ct-panel-body">
          <div class="ct-export-toolbar">
            <span class="ct-hint">表</span>
            <button class="ct-btn ct-btn-ghost ct-btn-sm" id="i18n-pick">选择表</button>
            <strong>${escapeHtml(state.currentTable || "—")}</strong>
            <span style="flex:1"></span>
            <span class="ct-hint">语言</span>
            ${state.langs.map((l) => `<button class="ct-pill${l === state.lang ? " active" : ""}" data-lang="${escapeHtml(l)}">${escapeHtml(l)}</button>`).join("")}
          </div>
          <div class="ct-log-toolbar">
            <span class="ct-hint">状态</span>
            ${[["all", "全部"], ["missing", "missing"], ["stale", "stale"], ["translated", "translated"]]
              .map(([v, label]) => `<button class="ct-pill${state.statusFilter === v ? " active" : ""}" data-filter="${v}">${label}</button>`).join("")}
          </div>
          ${state.error ? '<div class="ct-error-inline">' + escapeHtml(state.error) + "</div>" : ""}
          ${renderTable(filtered)}
          <div class="ct-hint" style="margin-top:10px">译文保存在 <span class="ct-mono">i18n/${escapeHtml(state.lang)}/${escapeHtml(state.currentTable)}.json</span>；填写后点「保存」，下次导出自动合并。</div>
        </div>
      </div>
    </div>
    ${renderPickModal()}
    ${renderProgressModal()}
    ${renderCompactModal()}`;
}

function renderTable(rows) {
  const state = getState();
  if (!state.entries.length) {
    return '<div class="ct-empty"><div class="ct-empty-title">暂无翻译条目</div><div class="ct-empty-sub">请先「同步全部语言」生成骨架</div></div>';
  }
  if (!rows.length) {
    return '<div class="ct-empty"><div class="ct-empty-title">该状态下暂无译文条目</div></div>';
  }
  return `<div class="ct-table-wrap"><table class="ct-data"><thead><tr><th>主键</th><th>字段</th><th>${escapeHtml(state.primaryLang)} 原文</th><th style="min-width:200px">${escapeHtml(state.lang)} 译文</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(rowHtml).join("")}</tbody></table></div>`;
}

function rowHtml(e) {
  const state = getState();
  const draft = state.drafts[e.key] || { text: e.text, confirmed: e.confirmed };
  const badge = statusBadge(e.status);
  const isLong = e.source.length > 40 || e.text.length > 40;
  const editor = isLong
    ? `<textarea class="ct-input" data-key="${escapeHtml(e.key)}" rows="2">${escapeHtml(draft.text)}</textarea>`
    : `<input class="ct-input" data-key="${escapeHtml(e.key)}" value="${escapeHtml(draft.text)}">`;
  const saveLabel = e.status === "stale" ? "确认并保存" : "保存";
  return `<tr>
    <td class="ct-mono">${escapeHtml(e.id)}</td>
    <td class="ct-mono">${escapeHtml(e.field)}</td>
    <td>${escapeHtml(e.source)}</td>
    <td>${editor}</td>
    <td><span class="ct-badge ${badge.cls}">${badge.text}</span></td>
    <td class="ct-row-ops"><button class="ct-btn ct-btn-ghost ct-btn-sm" data-key="${escapeHtml(e.key)}">${saveLabel}</button></td>
  </tr>`;
}

function renderPickModal() {
  const state = getState();
  if (!state.pickTable) return "";
  return `<div class="ct-dialog-mask">
    <div class="ct-dialog" role="dialog">
      <div class="ct-dialog-head"><span>选择翻译表</span><span class="ct-mono" style="margin-left:10px;color:var(--ct-ink-3)">含 i18n 字段</span></div>
      <div class="ct-dialog-body">
        ${state.tables.map((t) => `<button class="ct-pill${t.table === state.currentTable ? " active" : ""}" data-pick-table="${escapeHtml(t.table)}" ${t.has_i18n ? "" : "disabled"}>${escapeHtml(t.table)} <span style="opacity:.7">· ${t.field_count} 字段 · i18n ${t.i18n_count}</span></button>`).join("")}
      </div>
      <div class="ct-dialog-foot"><button class="ct-btn ct-btn-ghost" data-close>关闭</button></div>
    </div>
  </div>`;
}

function renderProgressModal() {
  const state = getState();
  if (!state.progressModal) return "";
  const langs = state.langs.length ? state.langs : Object.keys(state.progress);
  const body = state.progressView === "lang"
    ? langs.map((lang) => {
        const lc = state.progress[lang];
        if (!lc) return "";
        return `<div class="ct-progress-line"><span class="ct-badge ct-badge-mute">${escapeHtml(lang)}</span> 进度 ${Math.round((lc.progress || 0) * 100)}%</div><div class="ct-progress-line ct-mono">${countLine(lc)}</div>`;
      }).join("")
    : langs.map((lang) => {
        const lc = state.progress[lang];
        if (!lc) return "";
        const tables = lc.tables || {};
        return `<div class="ct-progress-line" style="font-weight:700;margin-top:6px">${escapeHtml(lang)}</div>`
          + Object.keys(tables).map((table) => `<div class="ct-progress-line ct-mono">${escapeHtml(table)}: ${countLine(tables[table])}</div>`).join("");
      }).join("");
  return `<div class="ct-dialog-mask">
    <div class="ct-dialog" role="dialog">
      <div class="ct-dialog-head"><span>翻译进度</span><span style="flex:1"></span>
        <button class="ct-pill${state.progressView === "lang" ? " active" : ""}" data-view="lang">语言</button>
        <button class="ct-pill${state.progressView === "table" ? " active" : ""}" data-view="table">按表</button>
      </div>
      <div class="ct-dialog-body">${body || '<div class="ct-empty"><div class="ct-empty-sub">暂无进度</div></div>'}</div>
      <div class="ct-dialog-foot"><button class="ct-btn ct-btn-ghost" data-close>关闭</button></div>
    </div>
  </div>`;
}

function renderCompactModal() {
  const state = getState();
  if (!state.compactModal) return "";
  const p = state.compactPreview || {};
  const files = p.files || [];
  const body = files.length
    ? files.map((f) => `<div class="ct-progress-line" style="margin-bottom:6px">${escapeHtml(f.lang)} / ${escapeHtml(f.table)}</div><div class="ct-mono" style="padding:0 0 10px 8px">${f.removed_keys.map((k) => escapeHtml(k)).join("<br>")}</div>`).join("")
    : '<div class="ct-empty"><div class="ct-empty-sub">没有无主条目</div></div>';
  return `<div class="ct-dialog-mask">
    <div class="ct-dialog" role="dialog">
      <div class="ct-dialog-head">确认清理 ${p.total_removed || 0} 条无主条目</div>
      <div class="ct-dialog-body">${body}<div class="ct-hint" style="margin-top:8px">删除后不可恢复，翻译文件将从语言包中移除这些 key。</div></div>
      <div class="ct-dialog-foot"><button class="ct-btn ct-btn-ghost" data-close>取消</button><button class="ct-btn ct-btn-danger" data-confirm-compact>确认清理</button></div>
    </div>
  </div>`;
}

function countLine(c) {
  return `${c.translated || 0}/${c.total || 0} translated · ${c.missing || 0} missing · ${c.stale || 0} stale · ${c.orphan || 0} orphan`;
}

function currentOrphans() {
  const state = getState();
  let n = 0;
  for (const lang in state.progress) {
    const t = state.progress[lang].tables && state.progress[lang].tables[state.currentTable];
    if (t) n += t.orphan || 0;
  }
  return n;
}

function statusBadge(status) {
  if (status === "translated") return { cls: "ct-badge-ok", text: "translated" };
  if (status === "missing") return { cls: "ct-badge-warn", text: "missing" };
  if (status === "stale") return { cls: "ct-badge-warn", text: "stale" };
  return { cls: "ct-badge-mute", text: status || "unknown" };
}

const _state = { statusFilter: "all", entries: [], drafts: {}, error: "" };
function getState() { return _state; }

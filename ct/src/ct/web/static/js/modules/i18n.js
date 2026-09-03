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
    const el = e.target;
    if (!el) return;
    if (el.id === "pick-search") {
      state.pickQuery = el.value;
      render(container);
      const search = container.querySelector("#pick-search");
      if (search) search.focus();
      return;
    }
    const key = el.dataset && el.dataset.key;
    if (!key) return;
    const draft = state.drafts[key] || { confirmed: false };
    draft.text = el.value;
    state.drafts[key] = draft;
    if (el.classList && el.classList.contains("is-area")) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 220) + "px";
    }
  });

  container.addEventListener("click", (e) => {
    const outer = e.target;
    if (outer && outer.classList && outer.classList.contains("ct-dialog-mask")) {
      closeAllDialogs();
      render(container);
      return;
    }
    const expand = e.target.closest(".trans-preview");
    if (expand && expand.dataset.expandKey) {
      state.editingKey = expand.dataset.expandKey;
      render(container);
      focusEditing(container);
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
    if (id === "i18n-pick") {
      state.pickTable = true;
      state.pickStatus = state.pickStatus || "all";
      render(container);
      const search = container.querySelector("#pick-search");
      if (search) search.focus();
      return;
    }
    if (key) return saveEntry(container, key);
    if (lang) { state.lang = lang; return refresh(container); }
    const pickStatus = btn.dataset.pickStatus;
    if (pickStatus) { state.pickStatus = pickStatus; return render(container); }
    if (filter) { state.statusFilter = filter; return render(container); }
    if (pick) { state.currentTable = pick; state.pickTable = false; return refresh(container); }
    if (view) { state.progressView = view; return render(container); }
    if ("confirmCompact" in btn.dataset) return confirmCompact(container);
    if ("close" in btn.dataset) { state.pickTable = false; state.progressModal = false; state.compactModal = false; return render(container); }
  });

  // blur collapses the long-text editor back to preview (draft is kept)
  container.addEventListener("blur", (e) => {
    if (e.target && e.target.classList && e.target.classList.contains("is-area")) {
      state.editingKey = null;
      render(container);
    }
  }, true);

  // Esc closes any open i18n dialog
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && (state.pickTable || state.progressModal || state.compactModal)) {
      closeAllDialogs();
      render(container);
    }
  });
}

function focusEditing(container) {
  const ta = container.querySelector("textarea.is-area[data-key]");
  if (!ta) return;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 220) + "px";
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
          <div class="ct-controls" aria-label="翻译筛选">
            <div class="ct-filter-group" aria-label="表">
              <button class="ct-btn ct-btn-ghost ct-btn-sm" id="i18n-pick">选择表</button>
              <strong class="ct-current-table">${escapeHtml(state.currentTable || "—")}</strong>
            </div>
            <div class="ct-filter-divider" aria-hidden="true"></div>
            <div class="ct-filter-group" aria-label="语言">
              ${state.langs.map((l) => `<button class="ct-pill${l === state.lang ? " active" : ""}" data-lang="${escapeHtml(l)}" aria-pressed="${l === state.lang}">${escapeHtml(l)}</button>`).join("")}
            </div>
            <div class="ct-filter-divider" aria-hidden="true"></div>
            <div class="ct-filter-group" aria-label="状态">
              ${[["all", "全部"], ["missing", "missing"], ["stale", "stale"], ["translated", "translated"]]
                .map(([v, label]) => `<button class="ct-pill${state.statusFilter === v ? " active" : ""}" data-filter="${v}" aria-pressed="${state.statusFilter === v}">${label}</button>`).join("")}
            </div>
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
  return `<div class="ct-table-wrap ct-i18n-table"><table class="ct-data ct-col-rules"><thead><tr><th>主键</th><th>字段</th><th>${escapeHtml(state.primaryLang)} 原文</th><th style="min-width:200px">${escapeHtml(state.lang)} 译文</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(rowHtml).join("")}</tbody></table></div>`;
}

function rowHtml(e) {
  const state = getState();
  const draft = state.drafts[e.key] || { text: e.text, confirmed: e.confirmed };
  const badge = statusBadge(e.status);
  const isLong = e.source.length > 40 || e.text.length > 40;
  const editing = state.editingKey === e.key;
  const saveLabel = e.status === "stale" ? "确认并保存" : "保存";
  const saveClass = e.status === "stale" ? "ct-btn ct-btn-accent ct-btn-sm" : "ct-btn ct-btn-ghost ct-btn-sm";
  let editor;
  if (!isLong) {
    editor = `<input class="ct-input trans-input" data-key="${escapeHtml(e.key)}" value="${escapeHtml(draft.text)}">`;
  } else if (editing) {
    editor = `<textarea class="ct-input trans-input is-area" data-key="${escapeHtml(e.key)}" rows="2">${escapeHtml(draft.text)}</textarea>`;
  } else {
    editor = `<div class="trans-preview${draft.text ? "" : " placeholder"}" data-expand-key="${escapeHtml(e.key)}" title="点击编辑"><span class="clamp">${escapeHtml(draft.text || "点击填写译文…")}</span></div>`;
  }
  return `<tr>
    <td class="ct-mono">${escapeHtml(e.id)}</td>
    <td class="ct-mono">${escapeHtml(e.field)}</td>
    <td class="src-cell"><span class="src-text${isLong && editing ? " expanded" : ""}">${escapeHtml(e.source)}</span></td>
    <td class="trans-cell">${editor}</td>
    <td><span class="ct-badge ${badge.cls}">${badge.text}</span></td>
    <td class="ct-row-ops"><button class="${saveClass}" data-key="${escapeHtml(e.key)}">${saveLabel}</button></td>
  </tr>`;
}

function tableStatus(table) {
  const state = getState();
  let missing = 0, stale = 0, total = 0;
  for (const lang of Object.keys(state.progress || {})) {
    const t = (state.progress[lang].tables || {})[table];
    if (t) { missing += t.missing || 0; stale += t.stale || 0; total += t.total || 0; }
  }
  return { missing, stale, total, done: total > 0 && missing === 0 && stale === 0 };
}

function renderPickModal() {
  const state = getState();
  if (!state.pickTable) return "";
  const i18nTables = (state.tables || []).filter((t) => t.has_i18n);
  let filtered = i18nTables;
  if (state.pickStatus === "missing") filtered = filtered.filter((t) => tableStatus(t.table).missing > 0);
  if (state.pickStatus === "stale") filtered = filtered.filter((t) => tableStatus(t.table).stale > 0);
  if (state.pickStatus === "done") filtered = filtered.filter((t) => tableStatus(t.table).done);
  const query = (state.pickQuery || "").trim().toLowerCase();
  if (query) filtered = filtered.filter((t) => t.table.toLowerCase().includes(query));
  const rows = filtered.map((t, i) => {
    const st = tableStatus(t.table);
    const tag = st.missing > 0
      ? `<span class="ct-badge ct-badge-warn">缺 ${st.missing}</span>`
      : st.stale > 0
        ? `<span class="ct-badge ct-badge-warn">待审 ${st.stale}</span>`
        : st.done ? `<span class="ct-badge ct-badge-ok">已译完</span>` : "";
    const active = t.table === state.currentTable ? " active" : "";
    return `<button class="ct-picker-row${active}" data-pick-table="${escapeHtml(t.table)}">` +
      `<span class="ct-picker-name">${escapeHtml(t.table)}</span>` +
      `<span class="ct-mono ct-picker-meta">· ${t.field_count} 字段 · i18n ${t.i18n_count}</span>` +
      `<span class="ct-picker-spacer" style="flex:1"></span>${tag}</button>`;
  }).join("");
  const empty = filtered.length
    ? ""
    : '<div class="ct-empty"><div class="ct-empty-title">没有匹配的表</div><div class="ct-empty-sub">试试其他关键词或筛选条件</div></div>';
  return `<div class="ct-dialog-mask">
    <div class="ct-dialog ct-picker" role="dialog">
      <div class="ct-dialog-head"><span>选择翻译表</span><span style="flex:1"></span><span class="ct-mono ct-hint">含 i18n 字段</span></div>
      <div class="ct-dialog-body">
        <input class="ct-input" id="pick-search" placeholder="搜索表名…" value="${escapeHtml(state.pickQuery || "")}">
        <div class="ct-pick-filters">
          ${[["all", "全部"], ["missing", "有缺失"], ["stale", "有待审"], ["done", "已译完"]]
            .map(([v, label]) => `<button class="ct-pill${state.pickStatus === v ? " active" : ""}" data-pick-status="${v}">${label}</button>`).join("")}
        </div>
        <div class="ct-picker-count">${filtered.length} / ${i18nTables.length} 张含 i18n 的表</div>
        <div class="ct-picker-list">${rows}${empty}</div>
      </div>
      <div class="ct-dialog-foot">
        <button class="ct-btn ct-btn-ghost" data-close>关闭</button>
      </div>
    </div>
  </div>`;
}

function renderProgressModal() {
  const state = getState();
  if (!state.progressModal) return "";
  const langs = state.langs.length ? state.langs : Object.keys(state.progress);
  const statusCell = (v) => v > 0 ? `<span class="ct-badge ct-badge-warn">${v}</span>` : `<span class="ct-mono ct-ink-3">0</span>`;
  const orphanCell = (v) => v > 0 ? `<span class="ct-badge ct-badge-mute">${v}</span>` : `<span class="ct-mono ct-ink-3">0</span>`;
  const body = state.progressView === "lang"
    ? `<div class="ct-table-wrap"><table class="ct-data ct-progress-matrix">
        <thead><tr><th>语言</th><th>进度</th><th>translated / total</th><th>missing</th><th>stale</th><th>orphan</th></tr></thead>
        <tbody>${langs.map((lang) => {
          const lc = state.progress[lang];
          if (!lc) return "";
          return `<tr>
            <td><span class="ct-badge ct-badge-mute">${escapeHtml(lang)}</span></td>
            <td class="ct-matrix-cell">${Math.round((lc.progress || 0) * 100)}%</td>
            <td class="ct-matrix-cell"><span class="ct-badge ct-badge-ok">${lc.translated || 0}/${lc.total || 0}</span></td>
            <td class="ct-matrix-cell">${statusCell(lc.missing || 0)}</td><td class="ct-matrix-cell">${statusCell(lc.stale || 0)}</td><td class="ct-matrix-cell">${orphanCell(lc.orphan || 0)}</td>
          </tr>`;
        }).join("")}</tbody>
      </table></div>`
    : (() => {
        // matrix: one row per table, one column per language (scales with langs)
        const matrixCell = (tc) => {
          if (!tc) return `<td><span class="ct-mono ct-ink-3">—</span></td>`;
          const t = tc.total || 0, tr = tc.translated || 0, m = tc.missing || 0, s = tc.stale || 0, o = tc.orphan || 0;
          const cls = (m + s) > 0 ? "ct-badge-warn" : o > 0 ? "ct-badge-mute" : t > 0 ? "ct-badge-ok" : "ct-badge-mute";
          const detail = `${tr}/${t} translated · ${m} missing · ${s} stale · ${o} orphan`;
          return `<td class="ct-matrix-cell"><span class="ct-badge ${cls}" title="${escapeHtml(detail)}">${tr}/${t}</span></td>`;
        };
        const tableNames = [];
        const seen = new Set();
        for (const lang of langs) {
          for (const table of Object.keys((state.progress[lang] || {}).tables || {})) {
            if (!seen.has(table)) { seen.add(table); tableNames.push(table); }
          }
        }
        tableNames.sort();
        const rows = tableNames.map((table) => {
          let aggT = 0, aggTr = 0, aggM = 0, aggS = 0, aggO = 0;
          const cells = langs.map((lang) => {
            const tc = (state.progress[lang] || {}).tables ? (state.progress[lang].tables[table]) : undefined;
            if (tc) { aggT += tc.total || 0; aggTr += tc.translated || 0; aggM += tc.missing || 0; aggS += tc.stale || 0; aggO += tc.orphan || 0; }
            return matrixCell(tc);
          }).join("");
          const aggCls = (aggM + aggS) > 0 ? "ct-badge-warn" : aggO > 0 ? "ct-badge-mute" : aggT > 0 ? "ct-badge-ok" : "ct-badge-mute";
          const aggDetail = `${aggTr}/${aggT} translated · ${aggM} missing · ${aggS} stale · ${aggO} orphan`;
          return `<tr><td class="ct-mono ct-matrix-table">${escapeHtml(table)}</td>${cells}<td class="ct-matrix-cell"><span class="ct-badge ${aggCls}" title="${escapeHtml(aggDetail)}">${aggTr}/${aggT}</span></td></tr>`;
        }).join("");
        return `<div class="ct-table-wrap"><table class="ct-data ct-progress-matrix"><thead><tr><th>表</th>${langs.map((l) => `<th>${escapeHtml(l)}</th>`).join("")}<th>汇总</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      })();
  return `<div class="ct-dialog-mask">
    <div class="ct-dialog ct-progress-dialog" role="dialog">
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

const _state = { statusFilter: "all", progressView: "lang", entries: [], drafts: {}, error: "" };
function getState() { return _state; }

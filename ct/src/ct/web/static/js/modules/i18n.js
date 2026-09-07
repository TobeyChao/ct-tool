/* i18n module: translation editor (choose table → pick language → inline edit →
   save per entry), fullscreen long-text editor, source expand tails, column
   visibility, per-table progress detail, and orphan compact preview.
   Dialogs ride the shared core/dialog stack. */
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { openDialog, pushEscLayer } from "../core/dialog.js";

const STATUS_LABEL = { translated: "已译完", stale: "待审", missing: "缺失" };
/* hide-able columns in the entry table: 原文/译文/状态/操作 */
const COL_INDEX = { src: 3, trans: 4, status: 5, ops: 6 };

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
    const expand = e.target.closest(".trans-preview");
    if (expand && expand.dataset.expandKey) {
      state.editingKey = expand.dataset.expandKey;
      render(container);
      focusEditing(container);
      return;
    }
    const corner = e.target.closest(".ct-trans-expand");
    if (corner && corner.dataset.key) {
      openFullEditor(container, corner.dataset.key);
      return;
    }
    const more = e.target.closest(".ct-src-more");
    if (more) {
      const text = more.parentElement.querySelector(".ct-src-text");
      if (text) {
        const expanded = text.classList.toggle("expanded");
        more.querySelector(".ct-src-lab").textContent = expanded ? "收起" : "展开";
        more.setAttribute("aria-expanded", String(expanded));
      }
      return;
    }
    const btn = e.target.closest("button");
    if (!btn) return;
    const id = btn.id;
    const key = btn.dataset.key;
    const lang = btn.dataset.lang;
    const filter = btn.dataset.filter;

    if (id === "i18n-sync") return syncAll(container);
    if (id === "i18n-compact") return openCompact(container);
    if (id === "i18n-progress") return openProgress(container);
    if (id === "i18n-pick") return openPickTable(container);
    if (id === "i18n-colvis-btn") return toggleColVis(container);
    if (key) return saveEntry(container, key);
    if (lang) { state.lang = lang; return refresh(container); }
    if (filter) { state.statusFilter = filter; return render(container); }
    if ("confirmCompact" in btn.dataset) return confirmCompact(container);
  });

  // blur collapses the long-text editor back to preview (draft is kept)
  container.addEventListener("blur", (e) => {
    if (e.target && e.target.classList && e.target.classList.contains("is-area")) {
      state.editingKey = null;
      render(container);
    }
  }, true);

  // column visibility menu: outside click closes (Esc handled via layer)
  document.addEventListener("click", (e) => {
    const menu = container.querySelector(".ct-col-menu");
    if (menu && !e.target.closest(".ct-colvis")) menu.hidden = true;
  });

  // re-evaluate source truncation tails on resize (双向：可增可删)
  let resizeRaf = 0;
  window.addEventListener("resize", () => {
    if (resizeRaf) return;
    resizeRaf = requestAnimationFrame(() => {
      resizeRaf = 0;
      initSrcMore(container);
    });
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

/* ---------------- dialogs (shared stack) ---------------- */

function openPickTable(container) {
  const state = getState();
  state.pickStatus = state.pickStatus || "all";
  const i18nTables = (state.tables || []).filter((t) => t.has_i18n);
  const handle = openDialog({
    title: "选择翻译表",
    titleExtra: '<span class="ct-hint ct-mono">含 i18n 字段</span>',
    initialFocusSelector: "[data-pick-search]",
    body: `<input class="ct-dlg-input" data-pick-search placeholder="搜索表名…" autocomplete="off">
      <div class="ct-pick-filters">
        ${[["all", "全部"], ["missing", "有缺失"], ["stale", "有待审"], ["done", "已译完"]]
          .map(([v, label]) => `<button class="ct-pill${state.pickStatus === v ? " active" : ""}" data-pick-status="${v}">${label}</button>`).join("")}
      </div>
      <div class="ct-picker-count" data-pick-count></div>
      <div class="ct-picker-list" data-pick-list></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-pick-close>关闭</button>`,
  });
  handle.el.querySelector("[data-pick-close]").addEventListener("click", () => handle.close());
  const search = handle.el.querySelector("[data-pick-search]");
  const filters = handle.el.querySelector(".ct-pick-filters");
  const count = handle.el.querySelector("[data-pick-count]");
  const list = handle.el.querySelector("[data-pick-list]");
  function renderList() {
    let filtered = i18nTables;
    if (state.pickStatus === "missing") filtered = filtered.filter((t) => tableStatus(t.table).missing > 0);
    if (state.pickStatus === "stale") filtered = filtered.filter((t) => tableStatus(t.table).stale > 0);
    if (state.pickStatus === "done") filtered = filtered.filter((t) => tableStatus(t.table).done);
    const query = (search.value || "").trim().toLowerCase();
    if (query) filtered = filtered.filter((t) => t.table.toLowerCase().includes(query));
    count.textContent = `${filtered.length} / ${i18nTables.length} 张含 i18n 的表`;
    const rows = filtered.map((t) => {
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
        `<span class="ct-spacer"></span>${tag}</button>`;
    }).join("");
    list.innerHTML = rows || '<div class="ct-empty"><div class="ct-empty-title">没有匹配的表</div><div class="ct-empty-sub">试试其他关键词或筛选条件</div></div>';
    list.querySelectorAll("[data-pick-table]").forEach((row) => {
      row.addEventListener("click", () => {
        state.currentTable = row.dataset.pickTable;
        handle.close();
        refresh(container);
      });
    });
  }
  search.addEventListener("input", renderList);
  filters.addEventListener("click", (e) => {
    const pill = e.target.closest("[data-pick-status]");
    if (!pill) return;
    state.pickStatus = pill.dataset.pickStatus;
    filters.querySelectorAll(".ct-pill").forEach((p) => p.classList.toggle("active", p === pill));
    renderList();
  });
  renderList();
}

function openProgress(container) {
  const state = getState();
  const handle = openDialog({
    title: "翻译进度",
    titleExtra: `<button class="ct-pill${state.progressView === "table" ? " active" : ""}" data-pv="table">按表</button>
      <button class="ct-pill${state.progressView === "lang" ? " active" : ""}" data-pv="lang">语言</button>`,
    initialFocusSelector: "[data-pv]",
    body: `<div data-progress-body></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-progress-close>关闭</button>`,
  });
  handle.el.querySelector("[data-progress-close]").addEventListener("click", () => handle.close());
  const body = handle.el.querySelector("[data-progress-body]");
  function renderBody() {
    const langs = state.langs.length ? state.langs : Object.keys(state.progress);
    if (state.progressView === "lang") {
      const statusCell = (v) => v > 0 ? `<span class="ct-badge ct-badge-warn">${v}</span>` : `<span class="ct-mono ct-ink-3">0</span>`;
      const orphanCell = (v) => v > 0 ? `<span class="ct-badge ct-badge-mute">${v}</span>` : `<span class="ct-mono ct-ink-3">0</span>`;
      body.innerHTML = `<div class="ct-table-wrap" role="region" tabindex="0" aria-label="翻译进度（按语言）"><table class="ct-data ct-progress-matrix">
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
        </table></div>`;
      return;
    }
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
    body.innerHTML = `<div class="ct-table-wrap" role="region" tabindex="0" aria-label="翻译进度（按表）"><table class="ct-data ct-progress-matrix"><thead><tr><th>表</th>${langs.map((l) => `<th>${escapeHtml(l)}</th>`).join("")}<th>汇总</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  handle.el.querySelector(".ct-dialog-head").addEventListener("click", (e) => {
    const pill = e.target.closest("[data-pv]");
    if (!pill) return;
    state.progressView = pill.dataset.pv;
    handle.el.querySelectorAll("[data-pv]").forEach((p) => p.classList.toggle("active", p === pill));
    renderBody();
  });
  renderBody();
}

async function openCompact(container) {
  const state = getState();
  try {
    state.compactPreview = await api("/api/i18n/compact", { method: "POST", body: JSON.stringify({ table: state.currentTable, dry_run: true }) });
  } catch (e) { state.error = e.message; render(container); return; }
  const p = state.compactPreview || {};
  const files = p.files || [];
  const body = files.length
    ? files.map((f) => `<div class="ct-compact-file">${escapeHtml(f.lang)} / ${escapeHtml(f.table)}</div><div class="ct-mono ct-compact-keys">${f.removed_keys.map((k) => escapeHtml(k)).join("<br>")}</div>`).join("")
    : '<div class="ct-empty"><div class="ct-empty-sub">没有无主条目</div></div>';
  const handle = openDialog({
    title: `确认清理 ${p.total_removed || 0} 条无主条目`,
    initialFocusSelector: "[data-cancel-compact]",
    body: `${body}<div class="ct-hint" style="margin-top:8px">删除后不可恢复，翻译文件将从语言包中移除这些 key。</div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel-compact>取消</button>
      <button class="ct-btn ct-btn-danger-solid" data-confirm-compact>确认清理</button>`,
  });
  handle.el.querySelector("[data-cancel-compact]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-confirm-compact]").addEventListener("click", async () => {
    try {
      await api("/api/i18n/compact", { method: "POST", body: JSON.stringify({ table: state.currentTable, dry_run: false }) });
      await loadEntries();
      await loadProgress();
    } catch (e) { state.error = e.message; }
    handle.close();
    render(container);
  });
}

/* fullscreen long-text editor: 原文只读对照 + 大 textarea（进入前先提交行内编辑） */
function openFullEditor(container, key) {
  const state = getState();
  const entry = state.entries.find((en) => en.key === key);
  if (!entry) return;
  // 进入全屏前先提交行内编辑（原型行为），关闭后直接回预览态
  if (state.editingKey) {
    state.editingKey = null;
    render(container);
  }
  const draft = state.drafts[key] || { text: entry.text };
  const handle = openDialog({
    title: `${entry.id} · ${entry.field} · ${state.lang}`,
    variant: "wide",
    initialFocusSelector: "[data-full-trans]",
    body: `<div class="ct-dlg-field"><label class="ct-dlg-label">原文（${escapeHtml(state.lang)}）</label>
        <div class="ct-dlg-src">${escapeHtml(entry.source)}</div></div>
      <div class="ct-dlg-field"><label class="ct-dlg-label">译文</label>
        <textarea class="ct-dlg-trans" data-full-trans rows="8">${escapeHtml(draft.text || "")}</textarea></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-full-cancel>取消</button>
      <button class="ct-btn ct-btn-primary" data-full-save>保存</button>`,
  });
  handle.el.querySelector("[data-full-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-full-save]").addEventListener("click", () => {
    const text = handle.el.querySelector("[data-full-trans]").value;
    state.drafts[key] = { confirmed: true, text };
    handle.close();
    saveEntry(container, key);
  });
}

/* ---------------- column visibility ---------------- */

function hiddenCols() {
  const state = getState();
  if (!state.hiddenCols) {
    let stored = null;
    try { stored = JSON.parse(localStorage.getItem("ct-i18n-cols") || "null"); } catch (e) { /* ignore */ }
    state.hiddenCols = new Set(Array.isArray(stored) ? stored : []);
  }
  return state.hiddenCols;
}

function applyColVisibility(container) {
  const hidden = hiddenCols();
  const table = container.querySelector("table.ct-col-rules");
  if (!table) return;
  Object.entries(COL_INDEX).forEach(([key, index]) => {
    const display = hidden.has(key) ? "none" : "";
    const th = table.querySelector(`thead th:nth-child(${index})`);
    if (th) th.style.display = display;
    table.querySelectorAll(`tbody td:nth-child(${index})`).forEach((td) => { td.style.display = display; });
  });
}

function toggleColVis(container) {
  const state = getState();
  const menu = container.querySelector(".ct-col-menu");
  if (!menu) return;
  const show = menu.hidden;
  menu.hidden = !show;
  if (!show) return;
  if (state._colEscLayer) state._colEscLayer();
  state._colEscLayer = pushEscLayer(() => {
    const m = container.querySelector(".ct-col-menu");
    if (m && !m.hidden) { m.hidden = true; return true; }
    return false;
  }, 10);
  menu.querySelectorAll("input[data-col]").forEach((box) => {
    box.addEventListener("change", () => {
      const hidden = hiddenCols();
      if (box.checked) hidden.delete(box.dataset.col);
      else hidden.add(box.dataset.col);
      try { localStorage.setItem("ct-i18n-cols", JSON.stringify([...hidden])); } catch (e) { /* ignore */ }
      applyColVisibility(container);
    }, { once: true });
  });
}

/* ---------------- source truncation tails ---------------- */

function initSrcMore(container) {
  container.querySelectorAll(".ct-src-text").forEach((el) => {
    const wrap = el.parentElement;
    if (!wrap) return;
    const existing = wrap.querySelector(".ct-src-more");
    const expanded = el.classList.contains("expanded");
    const truncated = el.scrollHeight > el.clientHeight + 1;
    if (truncated || expanded) {
      wrap.classList.add("ct-expandable");
      if (existing) {
        existing.querySelector(".ct-src-lab").textContent = expanded ? "收起" : "展开";
        existing.setAttribute("aria-expanded", String(expanded));
      } else {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ct-src-more";
        btn.innerHTML = `<span class="ct-src-lab">${expanded ? "收起" : "展开"}</span><span aria-hidden="true">▾</span>`;
        btn.setAttribute("aria-expanded", String(expanded));
        btn.setAttribute("aria-label", expanded ? "收起原文" : "展开原文");
        wrap.appendChild(btn);
      }
    } else {
      wrap.classList.remove("ct-expandable");
      if (existing) existing.remove();
    }
  });
}

/* ---------------- render ---------------- */

function render(container) {
  const state = getState();
  const filtered = state.entries.filter((e) => state.statusFilter === "all" || e.status === state.statusFilter);
  const orphans = currentOrphans();
  container.innerHTML = `
    <div class="ct-page-wrap ct-i18n-page">
      <div class="ct-panel">
        <div class="ct-panel-head ct-module-head">
          <div><h1 class="ct-panel-title">翻译 i18n</h1><p>选择表与语言，逐条维护译文；同步后自动合并到导出产物。</p></div>
          <div class="ct-module-actions">
            <button class="ct-btn ct-btn-ghost" id="i18n-progress">全部表进度</button>
            <button class="ct-btn ct-btn-danger" id="i18n-compact" ${orphans > 0 ? "" : "disabled"}>清理无主条目${orphans > 0 ? "（" + orphans + "）" : ""}</button>
            <button class="ct-btn ct-btn-primary" id="i18n-sync" ${state.busy ? "disabled" : ""}>${state.busy ? "同步中…" : "同步全部语言"}</button>
          </div>
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
              ${[["all", "全部"], ["missing", "缺失"], ["stale", "待审"], ["translated", "已译完"]]
                .map(([v, label]) => `<button class="ct-pill${state.statusFilter === v ? " active" : ""}" data-filter="${v}" aria-pressed="${state.statusFilter === v}">${label}</button>`).join("")}
            </div>
            <div class="ct-colvis" style="margin-left:auto">
              <button class="ct-btn ct-btn-ghost ct-btn-sm" id="i18n-colvis-btn">列 ▾</button>
              <div class="ct-col-menu" hidden>
                <label><input type="checkbox" data-col="src" ${hiddenCols().has("src") ? "" : "checked"}>原文</label>
                <label><input type="checkbox" data-col="trans" ${hiddenCols().has("trans") ? "" : "checked"}>译文</label>
                <label><input type="checkbox" data-col="status" ${hiddenCols().has("status") ? "" : "checked"}>状态</label>
                <label><input type="checkbox" data-col="ops" ${hiddenCols().has("ops") ? "" : "checked"}>操作</label>
              </div>
            </div>
          </div>
          ${state.error ? '<div class="ct-error-inline">' + escapeHtml(state.error) + "</div>" : ""}
          ${renderTable(filtered)}
          <div class="ct-hint" style="margin-top:10px">译文保存在 <span class="ct-mono">i18n/${escapeHtml(state.lang)}/${escapeHtml(state.currentTable)}.json</span>；填写后点「保存」，下次导出自动合并。</div>
        </div>
      </div>
    </div>`;
  applyColVisibility(container);
  initSrcMore(container);
}

function renderTable(rows) {
  const state = getState();
  if (!state.entries.length) {
    return '<div class="ct-empty"><div class="ct-empty-title">暂无翻译条目</div><div class="ct-empty-sub">请先「同步全部语言」生成骨架</div></div>';
  }
  if (!rows.length) {
    return '<div class="ct-empty"><div class="ct-empty-title">该状态下暂无译文条目</div></div>';
  }
  return `<div class="ct-table-wrap ct-i18n-table" role="region" tabindex="0" aria-label="翻译条目表"><table class="ct-data ct-col-rules"><thead><tr><th>主键</th><th>字段</th><th>${escapeHtml(state.primaryLang)} 原文</th><th>${escapeHtml(state.lang)} 译文</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(rowHtml).join("")}</tbody></table></div>`;
}

function rowHtml(e) {
  const state = getState();
  const draft = state.drafts[e.key] || { text: e.text, confirmed: e.confirmed };
  const badge = statusBadge(e.status);
  const editing = state.editingKey === e.key;
  const saveLabel = e.status === "stale" ? "确认并保存" : "保存";
  const saveClass = e.status === "stale" ? "ct-btn ct-btn-accent ct-btn-sm" : "ct-btn ct-btn-ghost ct-btn-sm";
  const preview = `<div class="trans-preview${draft.text ? "" : " placeholder"}" data-expand-key="${escapeHtml(e.key)}" title="点击编辑"><span class="clamp">${escapeHtml(draft.text || "点击填写译文…")}</span></div>`;
  let editor;
  if (editing) {
    editor = `<textarea class="ct-input trans-input is-area" data-key="${escapeHtml(e.key)}" rows="2">${escapeHtml(draft.text)}</textarea>`;
  } else {
    editor = `<div class="ct-trans-box">${preview}<button class="ct-trans-expand" type="button" data-key="${escapeHtml(e.key)}" title="全屏编辑译文" aria-label="全屏编辑译文">⤢</button></div>`;
  }
  return `<tr>
    <td class="ct-mono">${escapeHtml(e.id)}</td>
    <td class="ct-mono">${escapeHtml(e.field)}</td>
    <td class="src-cell"><span class="ct-src-wrap"><span class="ct-src-text">${escapeHtml(e.source)}</span></span></td>
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
  if (status === "translated") return { cls: "ct-badge-ok", text: STATUS_LABEL.translated };
  if (status === "missing") return { cls: "ct-badge-warn", text: STATUS_LABEL.missing };
  if (status === "stale") return { cls: "ct-badge-warn", text: STATUS_LABEL.stale };
  return { cls: "ct-badge-mute", text: status || "unknown" };
}

const _state = { statusFilter: "all", progressView: "lang", entries: [], drafts: {}, error: "" };
function getState() { return _state; }

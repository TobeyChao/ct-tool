/* schema editor module: grouped resource list + fuzzy filter, field list,
   draft commands -> change plan dialog -> prepare-apply -> apply.
   Owns #page-schema; panes are collapsible docked columns (>=900, default
   collapsed) or slide-out drawers (<900, one-cut). Draft state lives in the
   shared pageState and is surfaced by the shell draft bar via ct:draft. */
import { api } from "../core/api.js";
import { fuzzyScore } from "../core/fuzzy.js";
import { loadDraft, saveDraft, clearDraft } from "../core/draft-store.js";
import { getPageState } from "../app-shell.js";
import { escapeHtml } from "../core/dom.js";
import { fixedRowWindow } from "../core/virtual-list.js";
import { openDialog, pushEscLayer } from "../core/dialog.js";
import {
  confirmDeleteField,
  confirmDeleteResource,
  promptRenameField,
  promptEnumValue,
  openTypePicker,
  openAddField,
  openChangePlan,
  openDiscardDraft,
  KIND_LABEL,
  resourceKind,
} from "./schema-dialogs.js";

function readJsonPreference(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch (error) {
    return fallback;
  }
}

function writeJsonPreference(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* preference only */ }
}

function typeText(resource) {
  if (resource.kind === "enum") return "enum";
  if (resource.fields && resource.fields.length) return resource.fields.length + " 字段";
  return "";
}

function highlight(text, query) {
  if (!query) return escapeHtml(text);
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const index = lower.indexOf(q);
  if (index < 0) return escapeHtml(text);
  return escapeHtml(text.slice(0, index))
    + "<mark>" + escapeHtml(text.slice(index, index + q.length)) + "</mark>"
    + escapeHtml(text.slice(index + q.length));
}

export async function mount(container) {
  const state = getPageState("schema");
  if (state.mounted) return state;
  state.mounted = true;
  state.selection = state.selection || null;
  state.activeTool = state.activeTool ?? null; // inspector tool: null = collapsed
  state.query = state.query || localStorage.getItem("ct-filter") || "";
  state.resourceOpen = state.resourceOpen ?? false; // panes default collapsed
  state.collapsedGroups = state.collapsedGroups || readJsonPreference("ct-resource-groups", {});
  state.recentResources = state.recentResources || readJsonPreference("ct-recent-resources", []);
  state.indexesByTable = state.indexesByTable || {};
  state.commands = state.commands || [];
  state.cursor = state.commands.length;
  state.applyResult = state.applyResult || null;

  if (!state.resources) {
    try {
      const snapshot = await api("/api/schema-workspace");
      state.baseRevision = snapshot.revision;
      state.resources = snapshot.resources || [];
      state.reverseRefs = snapshot.reverseRefs || {};
    } catch (e) {
      state.error = e.message;
      state.resources = [];
    }
  }
  if (!state.root) {
    try {
      const ws = await api("/api/workspace");
      state.root = ws.root;
    } catch (e) { state.root = "/"; }
  }
  await restoreDraft(state);

  async function restoreDraft(s) {
    if (!s.baseRevision) return;
    try {
      const stored = await loadDraft(s.root);
      if (stored && stored.revision === s.baseRevision) {
        s.commands = stored.commands;
        s.cursor = stored.commands.length;
      } else if (stored) {
        await clearDraft(s.root); // source changed: discard stale draft
      }
    } catch (e) {
      s.persistWarning = e.message;
    }
  }

  async function persist(s) {
    if (!s.baseRevision) return;
    try {
      await saveDraft(s.root, s.baseRevision, s.commands);
      s.persistWarning = null;
    } catch (e) {
      s.persistWarning = e.message;
    }
    publishDraft();
  }

  container.innerHTML = `
    <div class="ct-page-wrap ct-workbench-page">
      <div class="ct-panel-head ct-module-head">
        <div><h1 class="ct-panel-title">Schema</h1><p>编辑资源结构，变更以草稿方式校验后原子应用。</p></div>
        <div class="ct-module-actions">
          <button class="ct-btn ct-btn-sm ct-btn-ghost ct-m-only" id="inspector-open-m">属性 ›</button>
          <button class="ct-btn ct-btn-sm ct-btn-danger ct-d-only" id="head-delete-resource" title="删除资源">删除资源</button>
        </div>
      </div>
      <div class="ct-workspace-layout" data-resource-open="${state.resourceOpen}" data-inspector-open="${state.activeTool === "inspector"}">
      <aside class="ct-resource-pane" aria-label="Schema 资源">
        <div class="ct-resource-pane-inner">
          <header class="ct-pane-head">
            <div><strong>Schema 资源</strong><span>Tables · Records · Enums</span></div>
            <button class="ct-icon-btn" id="resource-close" title="收起资源" aria-label="收起资源">‹</button>
          </header>
          <div class="ct-resource-content">
            <input class="ct-input" id="resource-filter" placeholder="搜索资源" value="${escapeHtml(state.query)}">
            <div id="resource-list" class="ct-resource-groups" role="tree" aria-label="Schema 资源列表"></div>
          </div>
          <footer class="ct-pane-footer ct-resource-count" id="resource-summary"></footer>
        </div>
      </aside>
      <section class="ct-editor" id="editor">
        <div class="ct-editor-chrome">
          <header class="ct-resource-header">
            <div class="ct-rhead-left">
              <button class="ct-icon-btn" id="quick-open-head" title="快速打开 · Cmd/Ctrl+P" aria-label="快速打开">⌕</button>
              <button class="ct-icon-btn" id="resource-toggle" title="资源面板" aria-label="资源面板" aria-expanded="${state.resourceOpen}" aria-controls="editor">☰</button>
              <div class="ct-resource-title">
                <span class="ct-eyebrow" id="editor-kind">Schema</span>
                <h1 id="editor-title" tabindex="-1">选择一个资源</h1>
                <span class="ct-resource-subtitle" id="editor-meta">从资源列表开始</span>
              </div>
            </div>
          </header>
          <nav class="ct-resource-tabs" aria-label="资源编辑区域">
            <button class="ct-resource-tab active" data-editor-tab="fields">字段 <span id="field-count">0</span></button>
            <button class="ct-resource-tab" data-editor-tab="indexes">查询索引</button>
            <button class="ct-resource-tab" data-editor-tab="dependencies">依赖</button>
          </nav>
        </div>
        <div class="ct-editor-body" id="editor-body">
          <div class="ct-empty"><div class="ct-empty-sub">在左侧选择 Table / Record / Enum 开始编辑</div></div>
        </div>
      </section>
      <aside class="ct-side" aria-label="字段属性">
        <div class="ct-side-inner">
          <header class="ct-pane-head">
            <button class="ct-icon-btn" id="inspector-back" aria-label="收起属性">‹</button>
            <div><strong>字段属性</strong><span id="inspector-path">选择字段</span></div>
          </header>
          <div class="ct-side-body" id="side-inspector"></div>
          <footer class="ct-pane-footer">修改只进入 Workspace Draft</footer>
        </div>
      </aside>
      <nav class="ct-right-activity" aria-label="右侧工具">
        <button class="ct-side-tab" id="side-tab" aria-label="字段属性" aria-pressed="${state.activeTool === "inspector"}">属性</button>
        <span class="ct-activity-spacer"></span>
      </nav>
      <div class="ct-pane-backdrop" id="pane-backdrop"></div>
      </div>
    </div>`;

  const resourcePane = container.querySelector(".ct-resource-pane");
  const sidePane = container.querySelector(".ct-side");
  const workspaceLayout = container.querySelector(".ct-workspace-layout");
  const paneBackdrop = container.querySelector("#pane-backdrop");
  const editorMain = container.querySelector(".ct-editor");
  const savedResourceW = localStorage.getItem("ct-resource-w-wide");
  const savedSideW = localStorage.getItem("ct-side-w-wide");
  if (savedResourceW) workspaceLayout.style.setProperty("--ct-resource-w", savedResourceW + "px");
  if (savedSideW) workspaceLayout.style.setProperty("--ct-inspector-w", savedSideW + "px");

  const list = container.querySelector("#resource-list");
  const editorBody = container.querySelector("#editor-body");
  const editorTitle = container.querySelector("#editor-title");
  const filterInput = container.querySelector("#resource-filter");
  const inspector = container.querySelector("#side-inspector");
  const inspectorPath = container.querySelector("#inspector-path");
  const editorKind = container.querySelector("#editor-kind");
  const editorMeta = container.querySelector("#editor-meta");
  const fieldCount = container.querySelector("#field-count");
  const sideTab = container.querySelector("#side-tab");

  const GROUPS = ["table", "record", "enum"];
  const GROUP_TITLES = { table: "Tables", record: "Records", enum: "Enums" };
  const ROW_HEIGHT = 34;
  const OVERSCAN = 8;

  /* ---- dialog flow context handed to schema-dialogs ---- */
  const ctx = {
    state,
    pushCommand,
    effectiveCommands,
    pendingCount: () => state.cursor,
    clearDraftState,
    applyCommands,
    refreshAll: () => { renderList(); renderEditor(); renderInspector(); },
  };

  function resourceRows() {
    const q = state.query.trim();
    const grouped = { table: [], record: [], enum: [] };
    state.resources.forEach((resource) => {
      const name = resource.name || resource.table || resource.resourceId || "";
      const kind = resourceKind(resource);
      const score = fuzzyScore(name, q);
      if (score === Infinity || !grouped[kind]) return;
      grouped[kind].push({ type: "resource", resource, name, kind, score });
    });
    const rows = [];
    GROUPS.forEach((kind) => {
      const matches = grouped[kind].sort((a, b) => a.score - b.score || a.name.localeCompare(b.name));
      if (q && !matches.length) return;
      rows.push({ type: "group", kind, count: matches.length });
      if (q || !state.collapsedGroups[kind]) rows.push(...matches);
    });
    return rows;
  }

  function renderList() {
    const visible = resourceRows();
    const query = state.query.trim();
    const matchCount = state.resources.filter((resource) => {
      const name = resource.name || resource.table || resource.resourceId || "";
      return fuzzyScore(name, query) !== Infinity;
    }).length;
    const allCount = state.resources.length;
    const summary = container.querySelector("#resource-summary");
    if (summary) summary.textContent = `${matchCount} 匹配 · ${allCount} 总计 · 状态已保存`;
    if (!matchCount) {
      list.innerHTML = '<div class="ct-empty"><div class="ct-empty-title">没有匹配的资源</div><div class="ct-empty-sub">换一个名称或清空搜索。</div></div>';
      return;
    }
    const scrollTop = state.listScrollTop || 0;
    const viewportHeight = list.clientHeight || 600;
    const windowed = fixedRowWindow(visible, { rowHeight: ROW_HEIGHT, overscan: OVERSCAN, scrollTop, viewportHeight });
    const { start, end } = windowed;
    const resourceTotal = visible.reduce((count, entry) => count + (entry.type === "resource" ? 1 : 0), 0);
    let resourcePosition = visible.slice(0, start).reduce((count, entry) => count + (entry.type === "resource" ? 1 : 0), 0);
    const windowRows = windowed.rows.map((entry) => {
      if (entry.type === "group") {
        const expanded = !!state.query.trim() || !state.collapsedGroups[entry.kind];
        return `<button class="ct-group-toggle" data-group="${entry.kind}" aria-expanded="${expanded}"><span><span class="ct-chevron">${expanded ? "⌄" : "›"}</span>${GROUP_TITLES[entry.kind]}</span><span class="ct-group-count">${entry.count}</span></button>`;
      }
      const { resource, name, kind } = entry;
      const selected = state.selection === name;
      resourcePosition += 1;
      return `<button class="ct-resource-row${selected ? " active" : ""}" role="treeitem" aria-selected="${selected}" aria-posinset="${resourcePosition}" aria-setsize="${resourceTotal}" data-name="${escapeHtml(name)}" data-index="${escapeHtml(name)}">` +
        `<span class="ct-resource-kind">${KIND_LABEL[kind]}</span>` +
        highlight(name, state.query.trim()) +
        `<span class="ct-resource-meta">${typeText(resource)}</span></button>`;
    }).join("");
    // spacer preserves total scroll height; window rows share one rendering path
    list.innerHTML = `<div class="ct-vlist-spacer" style="height:${windowed.before}px"></div>` +
      `<div class="ct-vlist-window">${windowRows}</div>` +
      `<div class="ct-vlist-spacer" style="height:${windowed.after}px"></div>`;
    list.querySelectorAll(".ct-resource-row").forEach((row) => {
      row.addEventListener("click", () => {
        openResource(row.dataset.name);
      });
    });
    list.querySelectorAll(".ct-group-toggle").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const kind = toggle.dataset.group;
        state.collapsedGroups[kind] = !state.collapsedGroups[kind];
        writeJsonPreference("ct-resource-groups", state.collapsedGroups);
        renderList();
      });
    });
  }

  function wireListScroll() {
    list.addEventListener("scroll", () => {
      state.listScrollTop = list.scrollTop;
      renderList();
    }, { passive: true });
  }

  function selectedResource() {
    const pool = state.candidate || state.resources;
    return pool.find((r) => (r.name || r.table || r.resourceId) === state.selection) || null;
  }

  function namedTypeTarget(typeExpression) {
    const match = String(typeExpression || "").trim().match(/^vector\s*<\s*([^<>]+)\s*>$|^([^<>]+)$/);
    const name = match && (match[1] || match[2] || "").trim();
    if (!name) return null;
    const pool = state.candidate || state.resources;
    return pool.find((resource) => {
      const kind = resource.kind;
      const resourceName = resource.name || resource.table || resource.resourceId;
      return (kind === "record" || kind === "enum") && resourceName === name;
    }) || null;
  }

  function renderTypeExpression(typeExpression) {
    const target = namedTypeTarget(typeExpression);
    const editBtn = `<button class="ct-type-edit" data-act="type" title="修改类型" aria-label="修改 ${escapeHtml(typeExpression)} 类型">✎</button>`;
    if (!target) {
      return `<span class="ct-type-expression">${escapeHtml(typeExpression)}${editBtn}</span>`;
    }
    const targetName = target.name || target.table || target.resourceId;
    const vector = String(typeExpression).trim().startsWith("vector");
    return `<span class="ct-type-expression">${vector ? "vector&lt;" : ""}` +
      `<button class="ct-type-link" data-navigate-type="${escapeHtml(targetName)}" title="打开 ${escapeHtml(targetName)}">${escapeHtml(targetName)}</button>` +
      `${vector ? "&gt;" : ""}${editBtn}</span>`;
  }

  function openResource(name) {
    state.selection = name;
    state.recentResources = [name, ...state.recentResources.filter((item) => item !== name)].slice(0, 12);
    writeJsonPreference("ct-recent-resources", state.recentResources);
    renderList();
    renderEditor();
    renderInspector();
    if (window.innerWidth < 900) setResourceOpen(false); // 抽屉内点选即收起
    updateHeadButtons();
    requestAnimationFrame(() => editorTitle.focus({ preventScroll: true }));
  }

  function syncPaneBackdrop() {
    const anyOpen = state.resourceOpen || state.activeTool === "inspector";
    paneBackdrop.classList.toggle("show", anyOpen && window.innerWidth < 900);
    // Drawer overlay must inert the main editor (<900 while a pane drawer is open);
    // docked mode never inert the editor.
    editorMain.toggleAttribute("inert", Boolean(anyOpen && window.innerWidth < 900));
  }

  let paneEscLayer = null;
  function syncPaneEscLayer() {
    const drawerActive = window.innerWidth < 900 && (state.resourceOpen || state.activeTool === "inspector");
    if (drawerActive && !paneEscLayer) {
      paneEscLayer = pushEscLayer(() => {
        if (!(window.innerWidth < 900 && (state.resourceOpen || state.activeTool === "inspector"))) return false;
        setResourceOpen(false);
        setInspectorOpen(false);
        return true;
      }, 20);
    } else if (!drawerActive && paneEscLayer) {
      paneEscLayer();
      paneEscLayer = null;
    }
  }

  function setResourceOpen(open, { restoreFocusTo = null } = {}) {
    const previous = state.resourceOpen;
    state.resourceOpen = open;
    workspaceLayout.dataset.resourceOpen = String(open);
    resourcePane.toggleAttribute("inert", !open);
    resourcePane.setAttribute("aria-hidden", String(!open));
    const toggleBtn = container.querySelector("#resource-toggle");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", String(open));
    if (open && !previous && window.innerWidth < 900) {
      state.resOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const first = resourcePane.querySelector("input, button");
      if (first) first.focus();
    } else if (!open && previous && window.innerWidth < 900) {
      const opener = restoreFocusTo || state.resOpener;
      if (opener && opener.isConnected) opener.focus();
    }
    syncPaneBackdrop();
    syncPaneEscLayer();
  }

  function setInspectorOpen(open) {
    const previous = state.activeTool === "inspector";
    state.activeTool = open ? "inspector" : null;
    workspaceLayout.dataset.inspectorOpen = String(open);
    sidePane.toggleAttribute("inert", !open);
    sidePane.setAttribute("aria-hidden", String(!open));
    sideTab.setAttribute("aria-pressed", String(open));
    if (open && !previous && window.innerWidth < 900) {
      state.inspOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const first = sidePane.querySelector("input, button, select");
      if (first) first.focus();
    } else if (!open && previous && window.innerWidth < 900) {
      const opener = state.inspOpener;
      if (opener && opener.isConnected) opener.focus();
    }
    renderInspector();
    syncPaneBackdrop();
    syncPaneEscLayer();
  }

  function updateHeadButtons() {
    const headDelete = container.querySelector("#head-delete-resource");
    if (headDelete) headDelete.disabled = !state.selection;
  }

  function effectiveCommands() {
    return state.commands.slice(0, state.cursor);
  }

  function pushCommand(command) {
    state.commands = state.commands.slice(0, state.cursor);
    state.commands.push(command);
    state.cursor = state.commands.length;
    refreshDraft();
  }

  function undo() {
    if (state.cursor > 0) { state.cursor -= 1; refreshDraft(); }
  }

  function redo() {
    if (state.cursor < state.commands.length) { state.cursor += 1; refreshDraft(); }
  }

  function publishDraft() {
    window.dispatchEvent(new CustomEvent("ct:draft", { detail: {
      pending: state.cursor,
      canRedo: state.commands.length > state.cursor,
      warn: Boolean(state.persistWarning),
    } }));
  }

  function refreshDraft() {
    state.draftVersion = (state.draftVersion || 0) + 1;
    renderEditor();
    renderInspector();
    persist(state);
    refreshCandidate();
    publishDraft();
  }

  async function refreshCandidate() {
    const version = state.draftVersion || 0;
    try {
      const data = await api("/api/schema-workspace/candidate", {
        method: "POST", body: JSON.stringify({ commands: effectiveCommands() }),
      });
      if (version !== (state.draftVersion || 0)) return; // stale candidate
      state.candidate = data.resources || state.resources;
      renderList();
      renderEditor();
      renderInspector();
    } catch (e) { /* keep base view */ }
  }

  async function clearDraftState() {
    state.commands = [];
    state.cursor = 0;
    state.candidate = null;
    state.selectedField = null;
    if (state.root) await clearDraft(state.root).catch(() => {});
    renderList();
    renderEditor();
    renderInspector();
    publishDraft();
  }

  async function applyCommands(commands) {
    const prepared = await api("/api/schema-workspace/prepare-apply", {
      method: "POST", body: JSON.stringify({ commands }),
    });
    const result = await api("/api/schema-workspace/apply", {
      method: "POST",
      body: JSON.stringify({ planId: prepared.planId, baseRevision: prepared.baseRevision, candidateHash: prepared.candidateHash }),
    });
    state.applyResult = result;
    state.commands = [];
    state.cursor = 0;
    state.candidate = null;
    if (state.root) await clearDraft(state.root).catch(() => {});
    try {
      const snapshot = await api("/api/schema-workspace");
      state.baseRevision = snapshot.revision;
      state.resources = snapshot.resources || [];
      state.reverseRefs = snapshot.reverseRefs || {};
    } catch (e) { /* keep stale resources */ }
    renderList();
    renderEditor();
    renderInspector();
    publishDraft();
    const names = [...new Set(commands.map((c) => {
      const raw = c.payload?.owner || c.payload?.name || "";
      return raw.split(":").pop();
    }).filter(Boolean))];
    return { names: names.join("、") };
  }

  function renderEditor() {
    const resource = selectedResource();
    const headDelete = container.querySelector("#head-delete-resource");
    if (headDelete) headDelete.disabled = !resource;
    if (!resource) {
      editorTitle.textContent = "选择一个资源";
      editorKind.textContent = "Schema";
      editorMeta.textContent = "从资源列表开始";
      fieldCount.textContent = "0";
      editorBody.innerHTML = '<div class="ct-empty"><div class="ct-empty-sub">在左侧选择资源开始编辑</div></div>';
      return;
    }
    const kind = resourceKind(resource);
    const resourceName = resource.name || resource.table;
    editorKind.textContent = KIND_LABEL[kind];
    editorTitle.textContent = resourceName;
    editorMeta.textContent = kind === "table"
      ? `${resource.excel_file || resourceName + ".xlsx"} · ${(resource.fields || []).length} 个字段 · 主键 ${resource.primary || "—"}`
      : kind === "record"
        ? `${(resource.fields || []).length} 个字段 · 可复用命名类型`
        : `${(resource.values || []).length} 个值 · wire type byte`;
    fieldCount.textContent = String((resource.fields || resource.values || []).length);
    if (kind !== "table" && state.tab === "indexes") state.tab = "fields";
    container.querySelectorAll("[data-editor-tab]").forEach((tab) => {
      const active = tab.dataset.editorTab === state.tab;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      if (tab.dataset.editorTab === "indexes") tab.hidden = kind !== "table";
    });
    const warning = state.persistWarning
      ? '<div class="ct-error-inline">草稿未持久化（IndexedDB）：' + escapeHtml(state.persistWarning) + "</div>" : "";
    if (state.tab === "dependencies") {
      const refs = state.reverseRefs[resource.resourceId] || [];
      editorBody.innerHTML = `${warning}<section class="ct-editor-section"><div class="ct-section-heading"><div><h2>资源依赖</h2><p>删除或改名之前必须先解决所有反向引用。</p></div></div><div class="ct-card-list">${refs.map((ref) => `<article class="ct-dependency-card"><span class="ct-index-glyph">IN</span><div><strong>${escapeHtml(ref.field)}</strong><span>${escapeHtml(ref.kind || "资源引用")}</span></div></article>`).join("") || '<div class="ct-empty"><div class="ct-empty-sub">当前资源没有反向引用</div></div>'}</div></section>`;
      return;
    }
    if (state.tab === "indexes" && kind === "table") {
      editorBody.innerHTML = `${warning}<section class="ct-editor-section"><div class="ct-section-heading"><div><h2>查询索引</h2><p>查询契约生成稳定的 C# / Lua 访问 API。</p></div></div>${renderIndexCards(resource)}
        <div class="ct-editor-actions"><button class="ct-btn ct-btn-primary" id="review-plan">审查并应用</button></div></section>`;
      wireIndexCards(resource);
      editorBody.querySelector("#review-plan").addEventListener("click", () => openChangePlan(ctx));
      return;
    }
    if (resource.kind === "enum" || !resource.fields) {
      const values = resource.values || [];
      const refs = state.reverseRefs[resource.resourceId] || [];
      const enumId = resource.resourceId;
      editorBody.innerHTML = `${warning}
        <div class="ct-field"><label class="ct-field-label">Wire 类型</label><div><span class="ct-badge ct-badge-mute">byte（只读，FlatBuffers 固定）</span></div></div>
        <div class="ct-field"><label class="ct-field-label">值</label>
          <div class="ct-enum-values">${values.map((v) =>
            `<div class="ct-enum-value"><span class="ct-mono">${escapeHtml(v)}</span><button class="ct-inline-btn ct-danger" data-enum-remove="${escapeHtml(v)}">✕</button></div>`
          ).join("") || '<div class="ct-empty-sub">（空）</div>'}</div>
          <button class="ct-btn ct-btn-ghost" id="enum-add-value">新增值</button></div>
        <div class="ct-field"><label class="ct-field-label">反向引用（${refs.length}）</label>
          <div class="ct-ref-list">${refs.map((r) => `<div class="ct-mono">${escapeHtml(r.field)}（${escapeHtml(r.kind)}）</div>`).join("") || '<div class="ct-empty-sub">未被引用</div>'}</div></div>
        <div class="ct-editor-actions"><button class="ct-btn ct-btn-primary" id="review-plan" ${state.cursor ? "" : "disabled"}>审查并应用</button></div>`;
      editorBody.querySelector("#enum-add-value").addEventListener("click", () => promptEnumValue(ctx, resource, values));
      editorBody.querySelectorAll("[data-enum-remove]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const value = btn.dataset.enumRemove;
          pushCommand({ type: "set_enum_values", payload: { name: enumId, values: values.filter((v) => v !== value) } });
        });
      });
      const reviewBtn = editorBody.querySelector("#review-plan");
      if (reviewBtn) reviewBtn.addEventListener("click", () => openChangePlan(ctx));
      return;
    }
    const refs = state.reverseRefs[resource.resourceId] || [];
    editorBody.innerHTML = `${warning}<section class="ct-editor-section">
      <div class="ct-section-heading"><div><h2>字段结构</h2><p>选择字段后在右侧设置类型、Excel 表达和引用约束。</p></div></div>
      <div class="ct-field-table"><table class="ct-data ct-field-grid"><thead><tr><th>字段</th><th>类型表达式</th><th>Excel</th><th>角色与约束</th><th aria-label="操作"></th></tr></thead>
      <tbody>${resource.fields.map((f, index) => {
        const rawType = f.type || f.type_expr || "?";
        const typeExpr = typeof rawType === "string" ? rawType : JSON.stringify(rawType);
        const selected = state.selectedField === f.name;
        return `<tr class="${selected ? "ct-row-selected" : ""}" data-field="${escapeHtml(f.name)}">
          <td><button class="ct-inline-btn" data-act="rename" title="改名">${escapeHtml(f.name)}</button>
              <span class="ct-field-role">${f.i18n ? "🌐" : ""}${f.server_only ? "🖥" : ""}${f.ref ? "🔗" : ""}</span></td>
          <td>${renderTypeExpression(typeExpr)}</td>
          <td class="ct-mono">${f.excel_columns ? `expanded × ${f.excel_columns}` : f.separator ? "single cell" : "1 column"}</td>
          <td><span class="ct-role-list">${f.name === resource.primary ? '<span class="ct-badge ct-badge-warn">PRIMARY</span>' : ""}${f.i18n ? '<span class="ct-badge ct-badge-mute">I18N</span>' : ""}${f.server_only ? '<span class="ct-badge ct-badge-mute">SERVER</span>' : ""}${f.ref ? `<button class="ct-type-link" data-navigate-type="${escapeHtml(f.ref.split(".")[0])}" title="打开 ${escapeHtml(f.ref.split(".")[0])}">REF ${escapeHtml(f.ref)}</button>` : ""}</span></td>
          <td class="ct-row-ops">
            <button class="ct-inline-btn" data-act="up" ${index === 0 ? "disabled" : ""} title="上移">↑</button>
            <button class="ct-inline-btn" data-act="down" ${index === resource.fields.length - 1 ? "disabled" : ""} title="下移">↓</button>
            <button class="ct-inline-btn ct-danger" data-act="delete" title="删除字段">✕</button>
          </td></tr>`;
      }).join("")}</tbody></table><button class="ct-add-row" id="add-field">＋ 添加字段</button></div>
      <div class="ct-editor-actions">
        <button class="ct-btn ct-btn-primary" id="review-plan" ${state.cursor ? "" : "disabled"}>审查并应用</button>
        <button class="ct-btn ct-btn-danger" id="discard-draft" ${state.commands.length ? "" : "disabled"}>放弃草稿</button>
      </div></section>`;
    editorBody.querySelectorAll("[data-navigate-type]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        state.selectedField = null;
        openResource(button.dataset.navigateType);
      });
    });
    editorBody.querySelectorAll("[data-act]").forEach((button) => {
      const fieldName = button.closest("tr").dataset.field;
      const act = button.dataset.act;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (act === "rename") {
          promptRenameField(ctx, resource, fieldName);
        } else if (act === "type") {
          openTypePicker(ctx, {
            role: "",
            onPick: (typeTextValue) => {
              pushCommand({ type: "set_type", payload: { owner: resource.resourceId, name: fieldName, type_text: typeTextValue } });
            },
          });
        } else if (act === "delete") {
          const field = resource.fields.find((f) => f.name === fieldName);
          const rawType = field ? (field.type || field.type_expr || "") : "";
          confirmDeleteField(ctx, resource, fieldName, typeof rawType === "string" ? rawType : "");
          if (state.selectedField === fieldName) state.selectedField = null;
        } else if (act === "up") {
          pushCommand({ type: "move_field", payload: { owner: resource.resourceId, name: fieldName, to: Math.max(0, indexOf(fieldName) - 1) } });
        } else if (act === "down") {
          pushCommand({ type: "move_field", payload: { owner: resource.resourceId, name: fieldName, to: indexOf(fieldName) + 1 } });
        }
      });
    });
    editorBody.querySelectorAll("tr[data-field]").forEach((row) => {
      row.addEventListener("click", () => {
        state.selectedField = row.dataset.field;
        renderEditor();
        renderInspector();
      });
    });
    container.querySelector("#add-field").addEventListener("click", () => openAddField(ctx, resource));
    editorBody.querySelector("#review-plan").addEventListener("click", () => openChangePlan(ctx));
    editorBody.querySelector("#discard-draft").addEventListener("click", () => openDiscardDraft(ctx));
  }

  function indexOf(fieldName) {
    const resource = selectedResource();
    return resource ? resource.fields.findIndex((f) => f.name === fieldName) : -1;
  }

  function renderIndexCards(resource) {
    if (!resource.primary) return "";
    const current = state.indexesByTable[resource.resourceId] || [];
    const card = (kind, label, preview) => {
      const selected = (current.find((i) => i.kind === kind) || {}).field || "";
      return `<div class="ct-index-card">
        <div class="ct-index-card-head">${label}<span class="ct-mono ct-index-preview">${preview}</span></div>
        <select class="ct-input" data-index-kind="${kind}">
          <option value="">（无）</option>
          ${resource.fields.map((f) => `<option value="${escapeHtml(f.name)}" ${f.name === selected ? "selected" : ""}>${escapeHtml(f.name)}</option>`).join("")}
        </select></div>`;
    };
    return `<div class="ct-index-cards">
      <div class="ct-index-cards-title">查询索引</div>
      ${card("code", "Code（唯一）", "ByCode(code)")}
      ${card("group", "Group（一对多）", "ByGroupKey(value)")}
    </div>`;
  }

  function wireIndexCards(resource) {
    editorBody.querySelectorAll("[data-index-kind]").forEach((select) => {
      select.addEventListener("change", () => {
        const kind = select.dataset.indexKind;
        const current = (state.indexesByTable[resource.resourceId] || []).filter((i) => i.kind !== kind);
        if (select.value) current.push({ kind, field: select.value });
        state.indexesByTable[resource.resourceId] = current;
        pushCommand({ type: "set_indexes", payload: { table: resource.resourceId, indexes: current } });
      });
    });
  }

  function renderInspector() {
    sideTab.setAttribute("aria-pressed", String(state.activeTool === "inspector"));
    if (state.activeTool !== "inspector") {
      inspector.setAttribute("inert", "");
      inspector.innerHTML = "";
      return;
    }
    inspector.removeAttribute("inert");
    const resource = selectedResource();
    const field = resource && state.selectedField
      ? resource.fields.find((f) => f.name === state.selectedField)
      : null;
    inspectorPath.textContent = field ? `${resource.name || resource.table}.${field.name}` : (state.selection || "选择字段");
    if (!field) {
      inspector.innerHTML = '<div class="ct-field"><label class="ct-field-label">选择</label><div>' +
        escapeHtml(state.selection || "—") + "</div></div>" +
        (state.applyResult ? '<div class="ct-field"><label class="ct-field-label">上次结果</label><div>' + escapeHtml(state.applyResult.message || "成功") + "</div></div>" : "");
      return;
    }
    const rawType = field.type || field.type_expr || "";
    const typeExpr = typeof rawType === "string" ? rawType : JSON.stringify(rawType);
    const input = (label, prop, current, kind = "text") =>
      `<div class="ct-field"><label class="ct-field-label">${escapeHtml(label)}</label>
       <input class="ct-input" type="${kind}" data-prop="${escapeHtml(prop)}" value="${escapeHtml(current == null ? "" : current)}"></div>`;
    const check = (label, prop, current) =>
      `<label class="ct-check"><input type="checkbox" data-prop="${escapeHtml(prop)}" ${current ? "checked" : ""}> ${escapeHtml(label)}</label>`;
    inspector.innerHTML =
      `<section class="ct-inspector-section"><h2>定义</h2>
         <div class="ct-field"><label class="ct-field-label">字段名</label><div class="ct-inspector-value ct-mono">${escapeHtml(field.name)}</div></div>
         <div class="ct-field"><label class="ct-field-label">类型表达式</label><div class="ct-inspector-value ct-mono">${escapeHtml(typeExpr)}</div></div>
       </section>
       <section class="ct-inspector-section"><h2>Excel 表达</h2>${input("展开列组数", "excel_columns", field.excel_columns ?? "", "number")}</section>
       <section class="ct-inspector-section"><h2>角色与约束</h2>
         <div class="ct-check-group">${check("国际化 i18n", "i18n", !!field.i18n)}${check("仅服务端", "server_only", !!field.server_only)}</div>
         ${input("跨表引用", "ref", field.ref || "")}
       </section>
       <section class="ct-inspector-section"><h2>说明</h2>${input("字段注释", "comment", field.comment || "")}</section>
       <button class="ct-btn ct-btn-ghost" id="field-save">应用属性</button>`;
    inspector.querySelector("#field-save").addEventListener("click", () => {
      const comment = inspector.querySelector('[data-prop="comment"]').value;
      const i18n = inspector.querySelector('[data-prop="i18n"]').checked;
      const serverOnly = inspector.querySelector('[data-prop="server_only"]').checked;
      const ref = inspector.querySelector('[data-prop="ref"]').value;
      const excelColumns = inspector.querySelector('[data-prop="excel_columns"]').value;
      pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: field.name, property: "comment", value: comment } });
      pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: field.name, property: "i18n", value: i18n } });
      pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: field.name, property: "server_only", value: serverOnly } });
      pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: field.name, property: "ref", value: ref || null } });
      pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: field.name, property: "excel_columns", value: excelColumns === "" ? null : parseInt(excelColumns, 10) } });
    });
  }

  /* ---- Quick Open（palette 变体，Esc 先清查询再关闭） ---- */
  let quickOpenHandle = null;

  function openQuickOpen() {
    if (quickOpenHandle) return;
    state.quickOpenActive = 0;
    state.quickOpenScrollTop = 0;
    state.quickOpenQuery = "";
    quickOpenHandle = openDialog({
      title: "快速打开",
      variant: "palette",
      initialFocusSelector: "[data-qo-input]",
      onEsc: () => {
        const input = quickOpenHandle?.el.querySelector("[data-qo-input]");
        if (input && input.value) {
          input.value = "";
          state.quickOpenActive = 0;
          renderQuickOpen("");
          return true; // consumed: first Esc clears the query
        }
        return false; // close the palette
      },
      onClose: () => { quickOpenHandle = null; },
      body: `<input class="ct-dlg-input" data-qo-input placeholder="搜索所有 Table / Record / Enum" autocomplete="off">
        <div class="ct-quick-open-list" data-qo-list style="margin-top:10px;max-height:50vh;overflow:auto"></div>
        <div class="ct-qo-hint"><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>Enter</kbd> 打开</span><span><kbd>Esc</kbd> 关闭</span></div>`,
      footer: "",
    });
    const input = quickOpenHandle.el.querySelector("[data-qo-input]");
    const resultList = quickOpenHandle.el.querySelector("[data-qo-list]");
    input.addEventListener("input", () => {
      state.quickOpenActive = 0;
      state.quickOpenScrollTop = 0;
      resultList.scrollTop = 0;
      renderQuickOpen(input.value);
    });
    resultList.addEventListener("scroll", () => {
      state.quickOpenScrollTop = resultList.scrollTop;
      renderQuickOpen(state.quickOpenQuery || "");
    }, { passive: true });
    input.addEventListener("keydown", (e) => {
      const candidates = state.quickOpenCandidates || [];
      if (!candidates.length) return;
      let index = state.quickOpenActive || 0;
      if (e.key === "ArrowDown") { e.preventDefault(); index = Math.min(index + 1, candidates.length - 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); index = Math.max(index - 1, 0); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const target = candidates[index];
        quickOpenHandle.close();
        openResource(target.name);
        return;
      }
      else return;
      state.quickOpenActive = index;
      const top = index * ROW_HEIGHT;
      const bottom = top + ROW_HEIGHT;
      if (top < resultList.scrollTop) resultList.scrollTop = top;
      else if (bottom > resultList.scrollTop + resultList.clientHeight) {
        resultList.scrollTop = bottom - resultList.clientHeight;
      }
      renderQuickOpen(state.quickOpenQuery || "");
    });
    renderQuickOpen("");
  }

  function renderQuickOpen(query) {
    if (!quickOpenHandle) return;
    const resultList = quickOpenHandle.el.querySelector("[data-qo-list]");
    if (!resultList) return;
    const recentOrder = new Map(state.recentResources.map((name, index) => [name, index]));
    let candidates = state.resources
      .map((r) => {
        const name = r.name || r.table || r.resourceId || "";
        const score = fuzzyScore(name, query);
        return { resource: r, name, score };
      })
      .filter((c) => c.score !== Infinity)
      .sort((a, b) => a.score - b.score || a.name.localeCompare(b.name));
    if (!query && recentOrder.size) {
      candidates = candidates.filter((candidate) => recentOrder.has(candidate.name))
        .sort((a, b) => recentOrder.get(a.name) - recentOrder.get(b.name));
    }
    state.quickOpenCandidates = candidates;
    state.quickOpenQuery = query;
    state.quickOpenActive = Math.min(state.quickOpenActive || 0, Math.max(0, candidates.length - 1));
    const windowed = fixedRowWindow(candidates, {
      rowHeight: ROW_HEIGHT,
      overscan: OVERSCAN,
      scrollTop: state.quickOpenScrollTop || 0,
      viewportHeight: resultList.clientHeight || 360,
    });
    resultList.innerHTML = `<div class="ct-vlist-spacer" style="height:${windowed.before}px"></div><div class="ct-vlist-window">` +
      windowed.rows.map(({ resource, name }, localIndex) => {
        const index = windowed.start + localIndex;
        return `<button class="ct-resource-row${index === state.quickOpenActive ? " active" : ""}" role="option" aria-selected="${index === state.quickOpenActive}" aria-posinset="${index + 1}" aria-setsize="${candidates.length}" data-qo-index="${index}" data-qo="${escapeHtml(name)}" tabindex="-1">` +
      `<span class="ct-resource-kind">${KIND_LABEL[resourceKind(resource)]}</span>` +
      `${highlight(name, query)}</button>`;
      }).join("") + `</div><div class="ct-vlist-spacer" style="height:${windowed.after}px"></div>`;
    if (!candidates.length) resultList.innerHTML = '<div class="ct-empty"><div class="ct-empty-sub">无匹配</div></div>';
    resultList.querySelectorAll(".ct-resource-row").forEach((row) => {
      row.addEventListener("click", () => {
        quickOpenHandle?.close();
        openResource(row.dataset.qo);
      });
    });
  }

  filterInput.addEventListener("input", () => {
    state.query = filterInput.value;
    try { localStorage.setItem("ct-filter", state.query); } catch (e) { /* ignore */ }
    renderList();
  });
  filterInput.addEventListener("keydown", (e) => {
    const rows = list.querySelectorAll(".ct-resource-row");
    if (!rows.length) return;
    const active = list.querySelector(".ct-resource-row.active");
    let index = active ? Array.prototype.indexOf.call(rows, active) : -1;
    if (e.key === "ArrowDown") { e.preventDefault(); index = Math.min(index + 1, rows.length - 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); index = Math.max(index - 1, 0); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (active) openResource(active.dataset.name);
      return;
    }
    else if (e.key === "Escape") {
      if (state.query) {
        e.preventDefault();
        state.query = "";
        filterInput.value = "";
        renderList();
      }
      return;
    }
    else return;
    rows.forEach((r, i) => r.classList.toggle("active", i === index));
  });

  container.querySelectorAll("[data-editor-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.tab = tab.dataset.editorTab;
      renderEditor();
    });
  });

  /* pane open/close entries */
  container.querySelector("#resource-toggle").addEventListener("click", () => setResourceOpen(!state.resourceOpen));
  container.querySelector("#resource-close").addEventListener("click", () => setResourceOpen(false));
  container.querySelector("#quick-open-head").addEventListener("click", openQuickOpen);
  sideTab.addEventListener("click", () => setInspectorOpen(state.activeTool !== "inspector"));
  container.querySelector("#inspector-back").addEventListener("click", () => setInspectorOpen(false));
  container.querySelector("#inspector-open-m").addEventListener("click", () => setInspectorOpen(true));
  container.querySelector("#head-delete-resource").addEventListener("click", () => {
    const resource = selectedResource();
    if (resource) confirmDeleteResource(ctx, resource);
  });
  paneBackdrop.addEventListener("click", () => { setResourceOpen(false); setInspectorOpen(false); });

  /* module-level events from shell/registry */
  window.addEventListener("ct:schema-quick-open-open", () => openQuickOpen());
  window.addEventListener("ct:schema-resource-toggle", () => setResourceOpen(!state.resourceOpen));
  window.addEventListener("ct:draft-review", () => openChangePlan(ctx));
  window.addEventListener("ct:draft-action", (e) => {
    const type = e.detail && e.detail.type;
    if (type === "undo") undo();
    else if (type === "redo") redo();
  });

  /* resize: crossing breakpoints collapses, never re-opens (只收不展) */
  let lastW = window.innerWidth;
  let resizeRaf = 0;
  window.addEventListener("resize", () => {
    if (resizeRaf) return;
    resizeRaf = requestAnimationFrame(() => {
      resizeRaf = 0;
      const w = window.innerWidth;
      if (w < 900 && lastW >= 900) { setResourceOpen(false); setInspectorOpen(false); }
      else if (w >= 900 && lastW < 900) { setResourceOpen(false); setInspectorOpen(false); }
      else if (w < 1200 && lastW >= 1200) { setInspectorOpen(false); }
      lastW = w;
      renderList();
    });
  });

  /* docked panes stay collapsed until opened; drawer widths keep them closed */
  setResourceOpen(state.resourceOpen);
  setInspectorOpen(state.activeTool === "inspector");
  updateHeadButtons();
  publishDraft();

  renderList();
  wireListScroll();
  renderEditor();
  renderInspector();

  function wireResize() {
    const editor = container.querySelector(".ct-editor");
    const startDrag = (readWidth, onMove) => (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = readWidth();
      const move = (ev) => onMove(startWidth, ev.clientX - startX);
      const up = () => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    };
    if (resourcePane && editor) {
      const handle = document.createElement("div");
      handle.className = "ct-resize-handle left";
      resourcePane.appendChild(handle);
      handle.addEventListener("mousedown", startDrag(
        () => parseFloat(getComputedStyle(workspaceLayout).getPropertyValue("--ct-resource-w")) || 248,
        (startWidth, dx) => {
        const w = Math.min(420, Math.max(200, startWidth + dx));
        workspaceLayout.style.setProperty("--ct-resource-w", w + "px");
        try { localStorage.setItem("ct-resource-w-wide", String(w)); } catch (err) { /* ignore */ }
      }));
    }
    if (sidePane && editor) {
      const handle = document.createElement("div");
      handle.className = "ct-resize-handle right";
      sidePane.appendChild(handle);
      handle.addEventListener("mousedown", startDrag(
        () => parseFloat(getComputedStyle(workspaceLayout).getPropertyValue("--ct-inspector-w")) || 300,
        (startWidth, dx) => {
        const w = Math.min(420, Math.max(240, startWidth - dx));
        workspaceLayout.style.setProperty("--ct-inspector-w", w + "px");
        try { localStorage.setItem("ct-side-w-wide", String(w)); } catch (err) { /* ignore */ }
      }));
    }
  }
  wireResize();

  return state;
}

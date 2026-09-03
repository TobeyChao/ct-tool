/* schema editor module: grouped resource list + fuzzy filter, field list,
   draft commands -> validate -> change-plan -> prepare-apply -> apply,
   and Cmd/Ctrl+P Quick Open. Owns #page-schema; selection/commands live in
   the shared pageState so they survive projection and module switches. */
import { api } from "../core/api.js";
import { fuzzyScore, highlightRanges } from "../core/fuzzy.js";
import { loadDraft, saveDraft, clearDraft } from "../core/draft-store.js";
import { getPageState } from "../app-shell.js";
import { escapeHtml } from "../core/dom.js";
import { fixedRowWindow } from "../core/virtual-list.js";

const KIND_LABEL = { table: "Table", record: "Record", enum: "Enum" };

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
  state.activeTool = state.activeTool || "inspector";
  state.query = state.query || localStorage.getItem("ct-filter") || "";
  state.view = state.view || "resources"; // resources | editor | properties (phone/compact stack)
  state.tab = state.tab || "fields";
  state.resourceOpen = state.resourceOpen ?? (window.innerWidth >= 1360);
  state.collapsedGroups = state.collapsedGroups || readJsonPreference("ct-resource-groups", {});
  state.recentResources = state.recentResources || readJsonPreference("ct-recent-resources", []);
  state.indexesByTable = state.indexesByTable || {};
  state.typePicker = null; // { owner, field, kind }
  state.commands = state.commands || [];
  state.cursor = state.commands.length;
  state.plan = state.plan || null;
  state.prepared = state.prepared || null;
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
  }

  container.innerHTML = `
    <div class="ct-workspace-layout" data-view="${state.view}" data-resource-open="${state.resourceOpen}" data-inspector-open="${state.activeTool === "inspector"}">
      <aside class="ct-resource-pane" aria-label="Schema 资源">
        <div class="ct-resource-pane-inner">
          <header class="ct-pane-head">
            <div><strong>Schema 资源</strong><span>Tables · Records · Enums</span></div>
            <button class="ct-icon-btn" id="quick-open-btn" title="快速查找 · Cmd/Ctrl+P" aria-label="快速查找">⌕</button>
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
            <div class="ct-resource-title">
              <span class="ct-eyebrow" id="editor-kind">Schema</span>
              <h1 id="editor-title" tabindex="-1">选择一个资源</h1>
              <span class="ct-resource-subtitle" id="editor-meta">从资源列表开始</span>
            </div>
            <div class="ct-resource-actions">
              <button class="ct-btn ct-btn-sm ct-btn-ghost" id="resource-toggle">资源</button>
              <button class="ct-btn ct-btn-sm ct-btn-ghost" id="view-back">← 返回</button>
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
          <header class="ct-pane-head"><div><strong>字段属性</strong><span id="inspector-path">选择字段</span></div></header>
          <div class="ct-side-body" id="side-inspector"></div>
          <footer class="ct-pane-footer">修改只进入 Workspace Draft</footer>
        </div>
      </aside>
      <nav class="ct-right-activity" aria-label="右侧工具">
        <button class="ct-side-tab" id="side-tab" aria-label="字段属性" aria-pressed="${state.activeTool === "inspector"}">属性</button>
        <span class="ct-activity-spacer"></span>
      </nav>
    </div>
    <div class="ct-dialog-mask" id="quick-open-mask" hidden>
      <div class="ct-dialog ct-quick-open" role="dialog" aria-modal="true" aria-label="快速打开资源">
        <input class="ct-input" id="quick-open-input" placeholder="搜索所有 Table / Record / Enum">
        <div id="quick-open-list" class="ct-quick-open-list"></div>
      </div>
    </div>`;

  const resourcePane = container.querySelector(".ct-resource-pane");
  const sidePane = container.querySelector(".ct-side");
  const workspaceLayout = container.querySelector(".ct-workspace-layout");
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
  const quickOpenMask = container.querySelector("#quick-open-mask");
  const quickOpenInput = container.querySelector("#quick-open-input");
  const quickOpenList = container.querySelector("#quick-open-list");

  const GROUPS = ["table", "record", "enum"];
  const GROUP_TITLES = { table: "Tables", record: "Records", enum: "Enums" };
  const ROW_HEIGHT = 34;
  const OVERSCAN = 8;

  function resourceRows() {
    const q = state.query.trim();
    const grouped = { table: [], record: [], enum: [] };
    state.resources.forEach((resource) => {
      const name = resource.name || resource.table || resource.resourceId || "";
      const kind = resource.kind || (resource.fields ? "table" : "enum");
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
    if (!target) {
      return `<button class="ct-type-chip" data-act="type">${escapeHtml(typeExpression)}</button>`;
    }
    const targetName = target.name || target.table || target.resourceId;
    const vector = String(typeExpression).trim().startsWith("vector");
    return `<span class="ct-type-expression">${vector ? "vector&lt;" : ""}` +
      `<button class="ct-type-link" data-navigate-type="${escapeHtml(targetName)}" title="打开 ${escapeHtml(targetName)}">${escapeHtml(targetName)}</button>` +
      `${vector ? "&gt;" : ""}<button class="ct-type-edit" data-act="type" title="修改类型" aria-label="修改 ${escapeHtml(typeExpression)} 类型">✎</button></span>`;
  }

  function openResource(name) {
    state.selection = name;
    state.recentResources = [name, ...state.recentResources.filter((item) => item !== name)].slice(0, 12);
    writeJsonPreference("ct-recent-resources", state.recentResources);
    renderList();
    renderEditor();
    renderInspector();
    applyView("editor", { pushHistory: true });
    if (window.innerWidth < 1360) setResourceOpen(false);
    requestAnimationFrame(() => editorTitle.focus({ preventScroll: true }));
  }

  function setResourceOpen(open) {
    state.resourceOpen = open;
    workspaceLayout.dataset.resourceOpen = String(open);
    workspaceLayout.classList.toggle("ct-resource-open", open);
    resourcePane.toggleAttribute("inert", !open && window.innerWidth >= 960);
    resourcePane.setAttribute("aria-hidden", String(!open && window.innerWidth >= 960));
    const schemaTab = document.querySelector('[data-module="schema"]');
    if (schemaTab) schemaTab.setAttribute("aria-expanded", String(open));
  }

  function setInspectorOpen(open) {
    state.activeTool = open ? "inspector" : null;
    workspaceLayout.dataset.inspectorOpen = String(open);
    sidePane.toggleAttribute("inert", !open && window.innerWidth >= 960);
    sidePane.setAttribute("aria-hidden", String(!open && window.innerWidth >= 960));
    renderInspector();
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

  function refreshDraft() {
    state.draftVersion = (state.draftVersion || 0) + 1;
    renderEditor();
    renderInspector();
    validate();
    persist(state);
    refreshCandidate();
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
      validate();
    } catch (e) { /* keep base view */ }
  }

  function applyView(view, { pushHistory = false } = {}) {
    const changed = state.view !== view;
    state.view = view;
    workspaceLayout.dataset.view = view;
    if (changed && pushHistory && window.innerWidth < 960) {
      try {
        history.pushState({ ...(history.state || {}), ctSchemaView: view }, "", location.href);
      } catch (error) { /* same-document navigation is an enhancement */ }
    }
  }

  function renderEditor() {
    const resource = selectedResource();
    if (!resource) {
      editorTitle.textContent = "选择一个资源";
      editorKind.textContent = "Schema";
      editorMeta.textContent = "从资源列表开始";
      fieldCount.textContent = "0";
      editorBody.innerHTML = '<div class="ct-empty"><div class="ct-empty-sub">在左侧选择资源开始编辑</div></div>';
      return;
    }
    const kind = resource.kind || (resource.fields ? "table" : "enum");
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
        <div class="ct-draft-status" data-cursor="${state.cursor}">${state.commands.length ? state.commands.length + " 条未应用命令" : "无未应用修改"}</div>
        <div class="ct-editor-actions"><button class="ct-btn ct-btn-ghost" id="review-plan">审查并应用</button></div><div id="plan-output"></div></section>`;
      wireIndexCards(resource);
      editorBody.querySelector("#review-plan").addEventListener("click", reviewPlan);
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
        <div class="ct-draft-status" data-cursor="${state.cursor}">${state.commands.length ? state.commands.length + " 条未应用命令" : "无未应用修改"}
          <button class="ct-inline-btn" id="undo-draft" ${state.cursor > 0 ? "" : "disabled"}>撤销</button>
          <button class="ct-inline-btn" id="redo-draft" ${state.cursor < state.commands.length ? "" : "disabled"}>重做</button></div>
        <div id="plan-output"></div>`;
      const undoButton = editorBody.querySelector("#undo-draft");
      const redoButton = editorBody.querySelector("#redo-draft");
      if (undoButton) undoButton.addEventListener("click", undo);
      if (redoButton) redoButton.addEventListener("click", redo);
      editorBody.querySelector("#enum-add-value").addEventListener("click", () => {
        const value = prompt("新枚举值");
        if (!value) return;
        pushCommand({ type: "set_enum_values", payload: { name: enumId, values: [...values, value] } });
      });
      editorBody.querySelectorAll("[data-enum-remove]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const value = btn.dataset.enumRemove;
          pushCommand({ type: "set_enum_values", payload: { name: enumId, values: values.filter((v) => v !== value) } });
        });
      });
      return;
    }
    const refs = state.reverseRefs[resource.resourceId] || [];
    editorBody.innerHTML = `${warning}<section class="ct-editor-section">
      <div class="ct-section-heading"><div><h2>字段结构</h2><p>选择字段后在右侧设置类型、Excel 表达和引用约束。</p></div>
        <button class="ct-btn ct-btn-danger" id="delete-resource" title="删除资源">删除资源</button></div>
      <div class="ct-field-table"><table class="ct-data ct-field-grid"><thead><tr><th>字段</th><th>类型表达式</th><th>Excel</th><th>角色与约束</th><th aria-label="操作"></th></tr></thead>
      <tbody>${resource.fields.map((f, index) => {
        const field = f.type || f.type_expr || "?";
        const text = typeof field === "string" ? field : JSON.stringify(field);
        const selected = state.selectedField === f.name;
        return `<tr class="${selected ? "ct-row-selected" : ""}" data-field="${escapeHtml(f.name)}">
          <td><button class="ct-inline-btn" data-act="rename" title="改名">${escapeHtml(f.name)}</button>
              <span class="ct-field-role">${f.i18n ? "🌐" : ""}${f.server_only ? "🖥" : ""}${f.ref ? "🔗" : ""}</span></td>
          <td>${renderTypeExpression(text)}</td>
          <td class="ct-mono">${f.excel_columns ? `expanded × ${f.excel_columns}` : f.separator ? "single cell" : "1 column"}</td>
          <td><span class="ct-role-list">${f.name === resource.primary ? '<span class="ct-badge ct-badge-warn">PRIMARY</span>' : ""}${f.i18n ? '<span class="ct-badge ct-badge-mute">I18N</span>' : ""}${f.server_only ? '<span class="ct-badge ct-badge-mute">SERVER</span>' : ""}${f.ref ? `<span class="ct-badge ct-badge-ok">REF ${escapeHtml(f.ref)}</span>` : ""}</span></td>
          <td class="ct-row-ops">
            <button class="ct-inline-btn" data-act="up" ${index === 0 ? "disabled" : ""} title="上移">↑</button>
            <button class="ct-inline-btn" data-act="down" ${index === resource.fields.length - 1 ? "disabled" : ""} title="下移">↓</button>
            <button class="ct-inline-btn ct-danger" data-act="delete" title="删除">✕</button>
          </td></tr>`;
      }).join("")}</tbody></table><button class="ct-add-row" id="add-field">＋ 添加字段</button></div>
      <div class="ct-editor-actions">
        <button class="ct-btn ct-btn-ghost" id="review-plan">审查并应用</button>
        <button class="ct-btn ct-btn-danger" id="discard-draft" ${state.commands.length ? "" : "disabled"}>放弃草稿</button>
      </div>
      <div class="ct-draft-status" data-cursor="${state.cursor}">${state.commands.length ? state.commands.length + " 条未应用命令" : "无未应用修改"}
        <button class="ct-inline-btn" id="undo-draft" ${state.cursor > 0 ? "" : "disabled"}>撤销</button>
        <button class="ct-inline-btn" id="redo-draft" ${state.cursor < state.commands.length ? "" : "disabled"}>重做</button></div>
      <div id="plan-output"></div></section>`;
    const undoButton = editorBody.querySelector("#undo-draft");
    const redoButton = editorBody.querySelector("#redo-draft");
    if (undoButton) undoButton.addEventListener("click", undo);
    if (redoButton) redoButton.addEventListener("click", redo);
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
          const value = prompt("新字段名", fieldName);
          if (!value || value === fieldName) return;
          pushCommand({ type: "rename_field", payload: { owner: resource.resourceId, old: fieldName, new: value } });
          state.selectedField = value;
        } else if (act === "type") {
          state.typePickerReturnFocus = button;
          state.typePicker = { owner: resource.resourceId, name: fieldName, kind: resource.kind || "table" };
          renderTypePicker(resource);
        } else if (act === "delete") {
          pushCommand({ type: "delete_field", payload: { owner: resource.resourceId, name: fieldName } });
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
        applyView("properties", { pushHistory: true });
      });
    });
    container.querySelector("#add-field").addEventListener("click", () => {
      const name = prompt("新字段名");
      if (!name) return;
      pushCommand({ type: "add_field", payload: { owner: resource.resourceId, field: { name, type: "int32" } } });
    });
    const deleteResource = editorBody.querySelector("#delete-resource");
    if (deleteResource) {
      deleteResource.addEventListener("click", () => {
        const refs = state.reverseRefs[resource.resourceId] || [];
        if (refs.length) {
          const output = planOutput();
          if (output) output.innerHTML = '<div class="ct-error-inline">无法删除：仍被引用 ' +
            refs.map((r) => escapeHtml(r.field)).join("、") + "（不提供级联删除）</div>";
          return;
        }
        pushCommand({ type: "delete_resource", payload: { name: resource.resourceId } });
        state.selection = null;
      });
    }
    container.querySelector("#review-plan").addEventListener("click", reviewPlan);
    container.querySelector("#discard-draft").addEventListener("click", () => {
      state.commands = [];
      state.cursor = 0;
      state.candidate = null;
      state.plan = null;
      state.prepared = null;
      state.applyResult = null;
      state.selectedField = null;
      renderEditor();
      renderInspector();
      clearDraft(state.root).catch(() => {});
    });
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

  const BASE_TYPES = ["int32", "int64", "float", "double", "bool", "string"];

  function renderTypePicker(resource) {
    let mask = container.querySelector("#type-picker-mask");
    if (!mask) {
      mask = document.createElement("div");
      mask.className = "ct-dialog-mask";
      mask.id = "type-picker-mask";
      container.appendChild(mask);
    }
    const named = state.resources.filter((r) => r.kind === "enum" || r.kind === "record");
    mask.innerHTML = `<div class="ct-dialog ct-type-picker" role="dialog" aria-modal="true" aria-label="选择字段类型">
      <div class="ct-dialog-head">选择类型 · ${escapeHtml(state.typePicker.name)}</div>
      <div class="ct-dialog-body">
        <input class="ct-input" id="type-picker-search" placeholder="搜索类型…">
        <label class="ct-check"><input type="checkbox" id="type-picker-vector"> vector（数组）</label>
        <div class="ct-type-groups">
          <div class="ct-resource-group-title">基础类型</div>
          ${BASE_TYPES.map((bt) => `<button class="ct-type-option" data-type="${bt}">${bt}</button>`).join("")}
          <div class="ct-resource-group-title">Enum / Record</div>
          <div id="type-picker-named">${named.map((r) =>
            `<button class="ct-type-option" data-type="${escapeHtml(r.name)}" data-named="1">${KIND_LABEL[r.kind]} ${escapeHtml(r.name)}</button>`
          ).join("") || '<div class="ct-empty-sub">无具名类型</div>'}</div>
        </div>
      </div>
      <div class="ct-dialog-foot"><button class="ct-btn ct-btn-ghost" id="type-picker-cancel">取消</button></div>
    </div>`;
    mask.hidden = false;
    const search = mask.querySelector("#type-picker-search");
    const vectorCheck = mask.querySelector("#type-picker-vector");
    search.focus();
    search.addEventListener("input", () => {
      const q = search.value.toLowerCase();
      mask.querySelectorAll(".ct-type-option").forEach((btn) => {
        const match = !q || btn.dataset.type.toLowerCase().includes(q);
        btn.style.display = match ? "" : "none";
      });
    });
    mask.querySelectorAll(".ct-type-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        let typeText = btn.dataset.type;
        if (vectorCheck.checked) typeText = "vector<" + typeText + ">";
        pushCommand({ type: "set_type", payload: { owner: state.typePicker.owner, name: state.typePicker.name, type_text: typeText } });
        state.typePicker = null;
        mask.hidden = true;
      });
    });
    mask.querySelector("#type-picker-cancel").addEventListener("click", () => {
      state.typePicker = null;
      mask.hidden = true;
      if (state.typePickerReturnFocus && state.typePickerReturnFocus.isConnected) state.typePickerReturnFocus.focus();
    });
  }

  function indexOf(fieldName) {
    const resource = selectedResource();
    return resource ? resource.fields.findIndex((f) => f.name === fieldName) : -1;
  }

  function planOutput() {
    return container.querySelector("#plan-output");
  }

  async function validate() {
    const version = state.draftVersion || 0;
    try {
      const data = await api("/api/schema-workspace/validate", {
        method: "POST", body: JSON.stringify({ commands: effectiveCommands() }),
      });
      if (version !== (state.draftVersion || 0)) return; // stale result
      const output = planOutput();
      if (!output) return;
      output.innerHTML = data.valid
        ? '<div class="ct-badge ct-badge-ok">草稿校验通过</div>'
        : `<div class="ct-error-inline">${data.issues.map((i) => escapeHtml(i.message + (i.location ? "（" + i.location + "）" : ""))).join("<br>")}</div>`;
    } catch (e) {
      const output = planOutput();
      if (output) output.innerHTML = '<div class="ct-error-inline">' + escapeHtml(e.message) + "</div>";
    }
  }

  async function reviewPlan() {
    const output = container.querySelector("#plan-output");
    if (!output) return;
    try {
      const data = await api("/api/schema-workspace/change-plan", {
        method: "POST", body: JSON.stringify({ commands: effectiveCommands() }),
      });
      state.plan = data;
      const blocked = data.blocked;
      const grouped = { safe: [], "data-dependent": [], destructive: [], incompatible: [], "dependency-breaking": [] };
      (data.impacts || []).forEach((i) => { grouped[data.risk] = grouped[data.risk] || []; grouped[data.risk].push(i); });
      const impacts = Object.entries(grouped).filter(([, v]) => v && v.length).map(([risk, list]) =>
        `<div class="ct-plan-group"><span class="ct-badge ${risk === "safe" ? "ct-badge-ok" : "ct-badge-warn"}">${escapeHtml(risk)}</span>` +
        list.map((i) => `<div class="ct-mono ct-plan-impact">${escapeHtml(i.artifact)} · ${escapeHtml(i.table)} · ${escapeHtml(i.action)}</div>`).join("") + "</div>"
      ).join("");
      const blockers = (data.issues || []).filter((i) => i.kind === "blocker" || i.kind === "untracked").map((i) =>
        `<div class="ct-error-inline" data-issue-loc="${escapeHtml(i.location || "")}">${escapeHtml(i.message)}${i.location ? "（" + escapeHtml(i.location) + "）" : ""}${i.samples ? " · 样例 " + escapeHtml(String(i.samples)) : ""}</div>`
      ).join("");
      output.innerHTML = `<div class="ct-plan"><div class="ct-badge ${blocked ? "ct-badge-err" : "ct-badge-ok"}">风险：${escapeHtml(data.risk)}</div>${impacts}${blockers}</div>` +
        (blocked
          ? '<button class="ct-btn ct-btn-primary" disabled>应用（存在阻塞项）</button>'
          : '<button class="ct-btn ct-btn-primary" id="apply-plan">应用变更</button>');
      const applyButton = container.querySelector("#apply-plan");
      if (applyButton) applyButton.addEventListener("click", applyPlan);
    } catch (e) { output.innerHTML = '<div class="ct-error-inline">' + escapeHtml(e.message) + "</div>"; }
  }

  async function applyPlan() {
    const output = container.querySelector("#plan-output");
    try {
      const prepared = await api("/api/schema-workspace/prepare-apply", {
        method: "POST", body: JSON.stringify({ commands: effectiveCommands() }),
      });
      state.prepared = prepared;
      const result = await api("/api/schema-workspace/apply", {
        method: "POST",
        body: JSON.stringify({ planId: prepared.planId, baseRevision: prepared.baseRevision, candidateHash: prepared.candidateHash }),
      });
      state.applyResult = result;
      state.commands = [];
      state.cursor = 0;
      state.candidate = null;
      state.plan = null;
      clearDraft(state.root).catch(() => {});
      try {
        state.resources = (await api("/api/schema-workspace")).resources || [];
      } catch (e) { /* ignore */ }
      renderList(); renderEditor(); renderInspector();
      const freshOutput = container.querySelector("#plan-output");
      if (freshOutput) {
        freshOutput.innerHTML = '<div class="ct-badge ct-badge-ok">已应用：' + escapeHtml((result.published || []).join(", ")) + "</div>";
      }
    } catch (e) {
      output.innerHTML = '<div class="ct-error-inline">' + escapeHtml(e.message) + "</div>";
    }
  }

  function renderInspector() {
    const resource = selectedResource();
    sideTab.setAttribute("aria-pressed", String(state.activeTool === "inspector"));
    if (state.activeTool !== "inspector") {
      inspector.setAttribute("inert", "");
      inspector.innerHTML = "";
      return;
    }
    inspector.removeAttribute("inert");
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
    const typeText = typeof rawType === "string" ? rawType : JSON.stringify(rawType);
    const input = (label, prop, current, kind = "text") =>
      `<div class="ct-field"><label class="ct-field-label">${escapeHtml(label)}</label>
       <input class="ct-input" type="${kind}" data-prop="${escapeHtml(prop)}" value="${escapeHtml(current == null ? "" : current)}"></div>`;
    const check = (label, prop, current) =>
      `<label class="ct-check"><input type="checkbox" data-prop="${escapeHtml(prop)}" ${current ? "checked" : ""}> ${escapeHtml(label)}</label>`;
    inspector.innerHTML =
      `<div class="ct-side-head"><button class="ct-btn ct-btn-sm ct-btn-ghost" id="side-back">← 返回</button></div>
       <section class="ct-inspector-section"><h2>定义</h2>
         <div class="ct-field"><label class="ct-field-label">字段名</label><div class="ct-inspector-value ct-mono">${escapeHtml(field.name)}</div></div>
         <div class="ct-field"><label class="ct-field-label">类型表达式</label><div class="ct-inspector-value ct-mono">${escapeHtml(typeText)}</div></div>
       </section>
       <section class="ct-inspector-section"><h2>Excel 表达</h2>${input("展开列组数", "excel_columns", field.excel_columns ?? "", "number")}</section>
       <section class="ct-inspector-section"><h2>角色与约束</h2>
         <div class="ct-check-group">${check("国际化 i18n", "i18n", !!field.i18n)}${check("仅服务端", "server_only", !!field.server_only)}</div>
         ${input("跨表引用", "ref", field.ref || "")}
       </section>
       <section class="ct-inspector-section"><h2>说明</h2>${input("字段注释", "comment", field.comment || "")}</section>
       <button class="ct-btn ct-btn-ghost" id="field-save">应用属性</button>`;
    const sideBack = inspector.querySelector("#side-back");
    if (sideBack) sideBack.addEventListener("click", () => {
      if (window.innerWidth < 960) history.back();
      else applyView("editor");
    });
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

  function openQuickOpen() {
    state.quickOpenReturnFocus = document.activeElement;
    quickOpenMask.hidden = false;
    quickOpenInput.value = "";
    state.quickOpenActive = 0;
    state.quickOpenScrollTop = 0;
    quickOpenList.scrollTop = 0;
    renderQuickOpen("");
    quickOpenInput.focus();
  }

  function renderQuickOpen(query) {
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
      viewportHeight: quickOpenList.clientHeight || 360,
    });
    quickOpenList.innerHTML = `<div class="ct-vlist-spacer" style="height:${windowed.before}px"></div><div class="ct-vlist-window">` +
      windowed.rows.map(({ resource, name }, localIndex) => {
        const index = windowed.start + localIndex;
        return `<button class="ct-resource-row${index === state.quickOpenActive ? " active" : ""}" role="option" aria-selected="${index === state.quickOpenActive}" aria-posinset="${index + 1}" aria-setsize="${candidates.length}" data-qo-index="${index}" data-qo="${escapeHtml(name)}" tabindex="-1">` +
      `<span class="ct-resource-kind">${KIND_LABEL[resource.kind || (resource.fields ? "table" : "enum")]}</span>` +
      `${highlight(name, query)}</button>`;
      }).join("") + `</div><div class="ct-vlist-spacer" style="height:${windowed.after}px"></div>`;
    if (!candidates.length) quickOpenList.innerHTML = '<div class="ct-empty"><div class="ct-empty-sub">无匹配</div></div>';
    quickOpenList.querySelectorAll(".ct-resource-row").forEach((row) => {
      row.addEventListener("click", () => {
        closeQuickOpen();
        openResource(row.dataset.qo);
      });
    });
  }

  function closeQuickOpen() {
    if (quickOpenMask.hidden) return;
    quickOpenMask.hidden = true;
    if (state.quickOpenReturnFocus && state.quickOpenReturnFocus.isConnected) {
      state.quickOpenReturnFocus.focus();
    }
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
  container.querySelector("#quick-open-btn").addEventListener("click", openQuickOpen);
  quickOpenInput.addEventListener("input", () => {
    state.quickOpenActive = 0;
    state.quickOpenScrollTop = 0;
    quickOpenList.scrollTop = 0;
    renderQuickOpen(quickOpenInput.value);
  });
  quickOpenList.addEventListener("scroll", () => {
    state.quickOpenScrollTop = quickOpenList.scrollTop;
    renderQuickOpen(state.quickOpenQuery || "");
  }, { passive: true });
  quickOpenInput.addEventListener("keydown", (e) => {
    const candidates = state.quickOpenCandidates || [];
    if (!candidates.length) return;
    let index = state.quickOpenActive || 0;
    if (e.key === "ArrowDown") { e.preventDefault(); index = Math.min(index + 1, candidates.length - 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); index = Math.max(index - 1, 0); }
    else if (e.key === "Enter") {
      e.preventDefault();
      closeQuickOpen();
      openResource(candidates[index].name);
      return;
    }
    else return;
    state.quickOpenActive = index;
    const top = index * ROW_HEIGHT;
    const bottom = top + ROW_HEIGHT;
    if (top < quickOpenList.scrollTop) quickOpenList.scrollTop = top;
    else if (bottom > quickOpenList.scrollTop + quickOpenList.clientHeight) {
      quickOpenList.scrollTop = bottom - quickOpenList.clientHeight;
    }
    renderQuickOpen(state.quickOpenQuery || "");
  });
  quickOpenMask.addEventListener("click", (e) => { if (e.target === quickOpenMask) closeQuickOpen(); });
  sideTab.addEventListener("click", () => {
    setInspectorOpen(state.activeTool !== "inspector");
  });
  container.querySelectorAll("[data-editor-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.tab = tab.dataset.editorTab;
      renderEditor();
    });
  });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "p") {
      e.preventDefault();
      if (quickOpenMask.hidden) openQuickOpen();
    }
    if (e.key === "Escape") closeQuickOpen();
  });

  renderList();
  wireListScroll();
  renderEditor();
  renderInspector();
  wireResize();

  const resourceToggle = container.querySelector("#resource-toggle");
  const viewBack = container.querySelector("#view-back");
  const resourceClose = container.querySelector("#resource-close");
  if (resourceToggle) {
    resourceToggle.addEventListener("click", () => {
      if (window.innerWidth < 960) applyView("resources");
      else setResourceOpen(true);
      const filter = container.querySelector("#resource-filter");
      if (filter) filter.focus();
    });
  }
  if (resourceClose) {
    resourceClose.addEventListener("click", () => {
      if (window.innerWidth < 960) applyView(state.selection ? "editor" : "resources");
      else setResourceOpen(false);
    });
  }
  if (viewBack) {
    viewBack.addEventListener("click", () => {
      if (window.innerWidth < 960) history.back();
      else if (state.view === "properties") applyView("editor");
      else if (state.view === "editor") applyView("resources");
    });
  }
  window.addEventListener("popstate", (event) => {
    if (window.innerWidth >= 960) return;
    applyView((event.state && event.state.ctSchemaView) || "resources");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.view === "properties") applyView("editor");
    else if (e.key === "Escape" && window.innerWidth >= 960 && window.innerWidth < 1360 && state.resourceOpen) setResourceOpen(false);
  });
  window.addEventListener("ct:schema-resource-toggle", () => {
    if (window.innerWidth < 960) applyView("resources");
    else setResourceOpen(!state.resourceOpen);
  });
  setResourceOpen(state.resourceOpen);
  setInspectorOpen(state.activeTool === "inspector");
  return state;

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
}

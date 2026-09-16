/* schema editor module: grouped resource list + fuzzy filter, field list.
   Edits collect as a draft command log; the server-authoritative net
   difference decides what the shell draft bar shows, and one save request
   publishes only the YAML that actually changed (POST
   /api/schema-workspace/save). Owns #page-schema; panes are collapsible docked
   columns (>=900, default collapsed) or slide-out drawers (<900, one-cut).
   Draft state lives in the shared pageState and is surfaced by the shell draft
   bar via ct:draft. */
import { api } from "../core/api.js";
import { fuzzyScore, highlightRanges } from "../core/fuzzy.js";
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
  promptRenameEnumValue,
  openEnumCommentEditor,
  openTypePicker,
  openFieldTypeEditor,
  openFieldCommentEditor,
  openAddField,
  openCreateResource,
  openDiscardDraft,
  openDraftSummary,
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
  const ranges = highlightRanges(text, query);
  if (!ranges.length) return escapeHtml(text);
  let cursor = 0;
  let result = "";
  for (const [start, end] of ranges) {
    result += escapeHtml(text.slice(cursor, start));
    result += "<mark>" + escapeHtml(text.slice(start, end)) + "</mark>";
    cursor = end;
  }
  return result + escapeHtml(text.slice(cursor));
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
  state.commands = state.commands || [];
  state.cursor = state.commands.length;
  state.schemaRevision = state.schemaRevision || "";
  state.netDiff = state.netDiff || null;
  state.candidateHash = state.candidateHash || "";
  state.issues = state.issues || [];
  state.saving = false;
  state.saveError = null;
  state.busy = false;
  state.notice = state.notice || "";
  state.templateStatus = state.templateStatus || null;
  state.statusError = state.statusError || "";
  state.templateError = state.templateError || null;
  state.templateTables = state.templateTables || [];
  state.lastSavedTables = state.lastSavedTables || [];

  if (!state.resources) {
    try {
      const snapshot = await api("/api/schema-workspace");
      state.baseRevision = snapshot.revision;
      state.schemaRevision = snapshot.schemaRevision || "";
      state.resources = snapshot.resources || [];
      state.reverseRefs = snapshot.reverseRefs || {};
      state.netDiff = null;
      state.error = null;
    } catch (e) {
      state.error = e.message;
      state.resources = [];
    }
  }
  if (!state.root) {
    // 首次挂载（刷新/新会话）顺带取回模板状态：横幅入口不能只活在
    // 「这次会话保存过」的记忆里，否则刷新后缺失模板的表就没有入口了。
    try {
      const ws = await api("/api/workspace");
      state.root = ws.root;
      state.templateStatus = ws.status || {};
      state.statusError = "";
    } catch (e) {
      state.root = "/";
      state.templateStatus = null;
      state.statusError = "模板状态暂不可用";
    }
  }
  state.templateTables = pendingTemplateTables();
  await restoreDraft(state);
  // 恢复出来的草稿也要让服务器算一次净差异（状态条只显示净变化资源数）
  if (state.commands.length) refreshCandidate();

  // Schema stays mounted while switching modules. Refresh the persisted
  // snapshot when returning so external YAML edits are visible immediately.
  window.addEventListener("ct:module", (event) => {
    if (event.detail === "schema") {
      refreshSchemaSnapshot();
      // 回到 Schema 页也刷新模板状态：外部（CLI/其他标签页）生成模板后横幅即时收敛
      refreshTemplateStatus().then(renderBanner);
    }
  });

  async function refreshSchemaSnapshot() {
    try {
      const snapshot = await api("/api/schema-workspace");
      const changed = state.schemaRevision && snapshot.schemaRevision
        && snapshot.schemaRevision !== state.schemaRevision;
      if (changed && (state.commands.length || state.netDiff)) {
        // 源 Schema 变了：不静默重放到新基线，也不自动清空草稿。
        state.notice = "Schema 基线已变化，草稿需核对后重新加载";
        state.netDiff = null;
        state.candidateHash = "";
        publishDraft();
        renderList();
        renderEditor();
        renderInspector();
        return;
      }
      state.baseRevision = snapshot.revision;
      state.schemaRevision = snapshot.schemaRevision || state.schemaRevision;
      state.resources = snapshot.resources || [];
      state.reverseRefs = snapshot.reverseRefs || {};
      state.error = null;
      if (!state.commands.length) {
        state.candidate = null;
        state.netDiff = null;
      }
      renderList();
      renderEditor();
      renderInspector();
    } catch (error) {
      state.error = error.message;
    }
  }

  async function restoreDraft(s) {
    if (!s.schemaRevision) return;
    let stored = null;
    try {
      stored = await loadDraft(s.root);
    } catch (e) {
      s.persistWarning = e.message;
      return;
    }
    if (!stored || !stored.commands.length) return;
    if (stored.schemaRevision && stored.schemaRevision !== s.schemaRevision) {
      s.commands = stored.commands;
      s.cursor = stored.cursor || 0;
      s.schemaRevision = stored.schemaRevision;
      s.notice = "草稿基于旧 Schema 基线，需核对后重新加载";
      publishDraft();
      return;
    }
    s.commands = stored.commands;
    s.cursor = Math.min(stored.cursor ?? stored.commands.length, stored.commands.length);
  }

  async function persist(s) {
    if (!s.schemaRevision) return;
    try {
      await saveDraft(s.root, {
        schemaRevision: s.schemaRevision,
        commands: s.commands,
        cursor: s.cursor,
      });
      s.persistWarning = null;
    } catch (e) {
      s.persistWarning = e.message;
    }
    publishDraft();
  }

  container.innerHTML = `
    <div class="ct-page-wrap ct-workbench-page">
      <div class="ct-panel-head ct-module-head">
        <div><h1 class="ct-panel-title">Schema</h1><p id="schema-subtitle">编辑资源结构，保存时只写实际变化的 YAML。</p></div>
        <div class="ct-module-actions">
          <button class="ct-btn ct-btn-sm ct-btn-ghost ct-m-only" id="inspector-open-m">属性 ›</button>
          <button class="ct-btn ct-btn-sm ct-btn-primary" id="head-create-resource" title="新增 Table / Record / Enum">新增 Schema</button>
          <button class="ct-btn ct-btn-sm ct-btn-danger ct-d-only" id="head-delete-resource" title="删除资源">删除资源</button>
        </div>
      </div>
      <div class="ct-draft-banner" id="draft-banner" hidden></div>
      <div class="ct-workspace-layout" data-resource-open="${state.resourceOpen}" data-inspector-open="${state.activeTool === "inspector"}">
      <aside class="ct-resource-pane" aria-label="Schema 资源">
        <div class="ct-resource-pane-inner">
          <header class="ct-pane-head">
            <div><strong>Schema 资源</strong><span>Tables · Records · Enums</span></div>
            <button class="ct-icon-btn" id="resource-close" title="收起资源" aria-label="收起资源"><svg class="ct-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7"></path></svg></button>
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
              <button class="ct-icon-btn ct-editor-icon-btn" id="quick-open-head" title="快速打开 · Cmd/Ctrl+P" aria-label="快速打开"><svg class="ct-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"></circle><path d="m16 16 4 4"></path></svg></button>
              <button class="ct-icon-btn ct-editor-icon-btn" id="resource-toggle" title="资源面板" aria-label="资源面板" aria-expanded="${state.resourceOpen}" aria-controls="editor"><svg class="ct-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"></path></svg></button>
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
            <button class="ct-icon-btn" id="inspector-back" aria-label="收起属性"><svg class="ct-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7"></path></svg></button>
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
    changedResources: () => (state.netDiff ? state.netDiff.changedResources : 0),
    candidatePool,
    precheck,
    startCreate,
    clearDraftState,
    saveChanges,
    refreshAll: () => { renderList(); renderEditor(); renderInspector(); },
  };

  function candidatePool() {
    return state.candidate || state.resources;
  }

  function candidateReverseRefs(pool) {
    /** 反向引用从**当前候选**派生：新建资源的引用立刻可见，撤销后立刻消失。 */
    const source = pool || candidatePool();
    const byName = new Map(
      source.map((resource) => [resource.name || resource.table || resource.resourceId, resource])
    );
    const refs = {};
    const add = (targetId, owner, field, kind) => {
      refs[targetId] = (refs[targetId] || []).concat([{ owner, field, kind }]);
    };
    source.forEach((resource) => {
      const ownerName = resource.name || resource.table || resource.resourceId;
      const ownerId = resource.resourceId || ownerName;
      (resource.fields || []).forEach((field) => {
        if (field.ref) {
          const target = String(field.ref).split(".")[0];
          add(`table:${target}`, ownerId, `${ownerName}/${field.name}`, "ref");
          return;
        }
        const raw = String(field.type || "").trim();
        const match = raw.match(/^vector\s*<\s*([^<>]+?)\s*>$/) || raw.match(/^([^<>]+)$/);
        const named = match ? match[1].trim() : "";
        const target = byName.get(named);
        if (!target || (target.kind !== "record" && target.kind !== "enum")) return;
        add(`${target.kind}:${named}`, ownerId, `${ownerName}/${field.name}`, "named");
      });
    });
    return refs;
  }

  function ensureSelection() {
    /** 撤销/删除后选择失效：退回最近仍存在的资源，否则返回空状态。 */
    if (selectedResource()) return;
    const pool = candidatePool();
    const fallback = (state.recentResources || []).find((name) =>
      pool.some((resource) => (resource.name || resource.table || resource.resourceId) === name));
    state.selection = fallback || null;
  }

  function selectCreated(name, kind) {
    /** 新建后选中它：过滤隐藏则清空过滤、展开分组，但不强行打开折叠的 pane。 */
    const filter = container.querySelector("#resource-filter");
    if (state.query && fuzzyScore(name, state.query) === Infinity) {
      state.query = "";
      if (filter) filter.value = "";
    }
    state.collapsedGroups[kind] = false;
    writeJsonPreference("ct-resource-groups", state.collapsedGroups);
    state.selection = name;
    state.recentResources = [name, ...state.recentResources.filter((item) => item !== name)].slice(0, 12);
    writeJsonPreference("ct-recent-resources", state.recentResources);
    renderList();
    renderEditor();
    renderInspector();
    updateHeadButtons();
    requestAnimationFrame(() => editorTitle.focus({ preventScroll: true }));
  }

  async function precheck(command) {
    /** 服务端预检：只返回结论，绝不回写草稿状态（旧响应不回写）。 */
    const version = state.draftVersion || 0;
    const commands = effectiveCommands().concat([command]);
    const data = await api("/api/schema-workspace/candidate", {
      method: "POST", body: JSON.stringify({ commands }),
    });
    if (version !== (state.draftVersion || 0)) return { stale: true, issues: [] };
    return {
      stale: false,
      issues: (data.issues || []).filter((issue) => issue.kind !== "warning"),
      resources: data.resources || [],
    };
  }

  function startCreate(kind) {
    if (state.saving) return;
    openCreateResource(ctx, {
      kind: kind || "",
      onCreated: (name, createdKind) => selectCreated(name, createdKind),
    });
  }

  function resourceRows() {
    const q = state.query.trim();
    const grouped = { table: [], record: [], enum: [] };
    candidatePool().forEach((resource) => {
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
    const query = state.query.trim();
    const groups = GROUPS.map((kind) => {
      const matches = candidatePool()
        .filter((resource) => resourceKind(resource) === kind)
        .map((resource) => ({
          resource,
          name: resource.name || resource.table || resource.resourceId || "",
        }))
        .filter(({ name }) => fuzzyScore(name, query) !== Infinity)
        .sort((a, b) => a.name.localeCompare(b.name));
      return { kind, matches };
    }).filter(({ matches }) => !query || matches.length);
    const matchCount = groups.reduce((count, group) => count + group.matches.length, 0);
    const allCount = candidatePool().length;
    const summary = container.querySelector("#resource-summary");
    if (summary) summary.textContent = `${matchCount} 匹配 · ${allCount} 总计 · 状态已保存`;
    if (!allCount && state.error) {
      // 加载失败 ≠ 空工作区：给出原因，而不是让人在坏工作区里新建资源
      list.innerHTML = '<div class="ct-empty"><div class="ct-empty-title">Schema 未加载</div>'
        + `<div class="ct-empty-sub" id="resource-load-error">${escapeHtml(state.error)}</div>`
        + '<div class="ct-empty-sub">修好 YAML 后切回本模块或刷新页面重试。</div></div>';
      return;
    }
    if (!allCount) {
      list.innerHTML = '<div class="ct-empty"><div class="ct-empty-title">还没有任何 Schema</div>'
        + '<div class="ct-empty-sub">从这里新增 Table / Record / Enum，无需先手写 YAML。</div>'
        + '<button class="ct-btn ct-btn-primary ct-btn-sm" id="empty-create-resource">新增 Schema</button></div>';
      const button = list.querySelector("#empty-create-resource");
      if (button) button.addEventListener("click", () => startCreate(""));
      return;
    }
    if (!matchCount) {
      list.innerHTML = '<div class="ct-empty"><div class="ct-empty-title">没有匹配的资源</div><div class="ct-empty-sub">换一个名称或清空搜索。</div></div>';
      return;
    }
    const resourceTotal = groups.reduce((count, group) => count + group.matches.length, 0);
    const scrollTop = state.listScrollTop || 0;
    const viewportHeight = list.clientHeight || 600;
    let resourcePosition = 0;
    list.innerHTML = groups.map(({ kind, matches }) => {
      const expanded = Boolean(query) || !state.collapsedGroups[kind];
      const windowed = fixedRowWindow(matches, {
        rowHeight: ROW_HEIGHT,
        overscan: OVERSCAN,
        scrollTop,
        viewportHeight,
      });
      resourcePosition += windowed.start;
      const windowRows = windowed.rows.map(({ resource, name }) => {
        const selected = state.selection === name;
        resourcePosition += 1;
        return `<button class="ct-resource-row${selected ? " active" : ""}" role="treeitem" aria-selected="${selected}" aria-posinset="${resourcePosition}" aria-setsize="${resourceTotal}" data-name="${escapeHtml(name)}" data-index="${escapeHtml(name)}">` +
          `<span class="ct-resource-kind">${KIND_LABEL[kind]}</span>` +
          highlight(name, query) +
          `<span class="ct-resource-meta">${typeText(resource)}</span></button>`;
      }).join("");
      const rows = `<div class="ct-vlist-spacer" style="height:${windowed.before}px"></div><div class="ct-vlist-window">${windowRows}</div><div class="ct-vlist-spacer" style="height:${windowed.after}px"></div>`;
      resourcePosition += matches.length - windowed.start - windowed.rows.length;
      return `<section class="ct-resource-group${expanded ? " is-open" : ""}" data-open="${expanded}">
        <div class="ct-group-head"><button class="ct-group-toggle" data-group="${kind}" data-group-toggle="${kind}" aria-expanded="${expanded}"><span><span class="ct-chevron" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="m9 6 6 6-6 6"></path></svg></span>${GROUP_TITLES[kind]}</span><span class="ct-group-count">${matches.length}</span></button><button class="ct-group-create" data-create-kind="${kind}" title="新增 ${KIND_LABEL[kind]}" aria-label="新增 ${KIND_LABEL[kind]}">＋</button></div>
        <div class="ct-resource-group-body"><div class="ct-resource-group-rows">${rows}</div></div>
      </section>`;
    }).join("");
    list.querySelectorAll(".ct-resource-row").forEach((row) => {
      row.addEventListener("click", () => {
        openResource(row.dataset.name);
      });
    });
    list.querySelectorAll("[data-create-kind]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        startCreate(button.dataset.createKind);
      });
    });
    list.querySelectorAll(".ct-group-toggle").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const kind = toggle.dataset.groupToggle;
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
    setResourceOpen(false); // 选择资源后统一收起资源面板，编辑区保留当前资源
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
    if (state.saving) return;
    state.commands = state.commands.slice(0, state.cursor);
    state.commands.push(command);
    state.cursor = state.commands.length;
    refreshDraft();
  }

  function undo() {
    if (state.saving) return;
    if (state.cursor > 0) { state.cursor -= 1; refreshDraft(); }
  }

  function redo() {
    if (state.saving) return;
    if (state.cursor < state.commands.length) { state.cursor += 1; refreshDraft(); }
  }

  function netChangedResources() {
    if (state.netDiff) return state.netDiff.changedResources || 0;
    return state.commands.length ? null : 0;
  }

  function publishDraft() {
    const changed = netChangedResources();
    window.dispatchEvent(new CustomEvent("ct:draft", { detail: {
      changedResources: changed === null ? 0 : changed,
      computing: Boolean(state.candidateComputing),
      canUndo: state.cursor > 0,
      canRedo: state.commands.length > state.cursor,
      canDiscard: Boolean(state.commands.length),
      warn: Boolean(state.persistWarning),
      busy: Boolean(state.busy),
      saving: Boolean(state.saving),
      blocked: state.issues.length > 0,
      notice: state.notice || "",
      error: state.saveError ? state.saveError.message : "",
      summary: state.netDiff ? state.netDiff.resources : [],
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
    state.candidateComputing = true;
    state.netDiff = null;
    state.candidateHash = "";
    publishDraft();
    const version = state.draftVersion || 0;
    try {
      const data = await api("/api/schema-workspace/candidate", {
        method: "POST", body: JSON.stringify({ commands: effectiveCommands(), schemaRevision: state.schemaRevision }),
      });
      if (version !== (state.draftVersion || 0) || state.saving) return; // stale response
      state.candidate = data.resources || state.resources;
      state.netDiff = data.netDiff || null;
      state.candidateHash = data.candidateHash || "";
      state.issues = (data.issues || []).filter((issue) => issue.kind !== "warning");
      state.reverseRefs = candidateReverseRefs(state.candidate);
      ensureSelection();
    } catch (e) {
      if (version !== (state.draftVersion || 0) || state.saving) return;
      state.netDiff = null;
      state.candidateHash = "";
      state.issues = [];
      state.saveError = e;
      state.notice = e.message;
    }
    state.candidateComputing = false;
    renderList();
    renderEditor();
    renderInspector();
    publishDraft();
  }

  async function clearDraftState() {
    if (state.saving) return;
    state.saveError = null;
    state.templateError = null;
    state.notice = "";
    state.commands = [];
    state.cursor = 0;
    state.candidate = null;
    state.netDiff = null;
    state.candidateHash = "";
    state.issues = [];
    state.selectedField = null;
    state.reverseRefs = candidateReverseRefs(state.resources);
    ensureSelection();
    if (state.root) await clearDraft(state.root).catch(() => {});
    renderList();
    renderEditor();
    renderInspector();
    publishDraft();
  }

  async function saveChanges() {
    if (state.saving || !state.netDiff || !state.candidateHash) return null;
    if (state.issues.length) {
      state.saveError = new Error(
        `存在结构阻塞项，共 ${state.issues.length} 项，请先修复：`
        + state.issues.map((i) => (i.location ? `${i.message}（${i.location}）` : i.message)).join("；")
      );
      publishDraft();
      return null;
    }
    const commands = effectiveCommands();
    const changed = state.netDiff ? state.netDiff.changedResources : (commands.length ? 1 : 0);
    if (!commands.length || changed === 0) {
      state.notice = "无未保存修改";
      state.saveError = null;
      publishDraft();
      return null;
    }

    state.saving = true;
    state.saveError = null;
    state.busy = false;
    publishDraft();
    try {
      const result = await api("/api/schema-workspace/save", {
        method: "POST",
        body: JSON.stringify({
          schemaRevision: state.schemaRevision,
          commands,
          candidateHash: state.candidateHash,
        }),
      });
      state.commands = [];
      state.cursor = 0;
      state.candidate = null;
      state.netDiff = null;
      state.candidateHash = "";
      state.issues = [];
      state.notice = "";
      state.schemaRevision = result.schemaRevision || state.schemaRevision;
      state.baseRevision = result.revision || state.baseRevision;
      state.resources = result.resources || state.resources;
      state.reverseRefs = result.reverseRefs || state.reverseRefs;
      if (state.root) await clearDraft(state.root).catch(() => {});
      state.lastSavedTables = (result.written || []).map(
        (path) => String(path).replace(/\.[^.]+$/, "").split("/").pop()
      );
      await refreshTemplateStatus();
      renderList();
      renderEditor();
      renderInspector();
      const note = templateNote();
      window.dispatchEvent(new CustomEvent("ct:draft", { detail: {
        successText: result.isNoOp
          ? "无未保存修改"
          : `已保存 ${(result.written || []).length} 个 YAML` + (note ? ` · ${note}` : ""),
      } }));
      return result;
    } catch (e) {
      // 保存失败：草稿、光标和净差异原样保留，错误持续可见
      const conflict = e.payload && e.payload.conflict;
      const kind = conflict && conflict.kind;
      if (kind === "schema-revision") {
        state.notice = "Schema 基线已变化，草稿保留；请重新加载后核对";
      } else if (kind === "legacy-apply") {
        state.notice = "旧 Apply 事务材料无法可靠还原，已阻止保存";
      } else if (kind === "legacy-apply-recovered") {
        state.notice = "旧 Apply 事务已恢复，请重新加载后核对";
      } else if (kind === "candidate-hash") {
        state.notice = "候选已过期，请重新编辑后再保存";
      } else if (e.payload && e.payload.busy) {
        state.busy = true;
        state.notice = "工作区正在导出或部署，稍后重试";
      }
      state.saveError = e;
      publishDraft();
      return null;
    } finally {
      state.saving = false;
      publishDraft();
    }
  }

  async function refreshTemplateStatus() {
    // 保存已经成功；状态查询失败只说明状态暂不可用，绝不反过来标记保存失败
    try {
      const ws = await api("/api/workspace");
      state.templateStatus = ws.status || {};
      state.statusError = "";
    } catch (e) {
      state.templateStatus = null;
      state.statusError = "模板状态暂不可用";
    }
    state.templateTables = pendingTemplateTables();
  }

  function pendingTemplateTables() {
    // 横幅展示工作区全部模板待办（缺模板 + 已漂移），不与「本次保存了什么」
    // 求交集：刷新或重开会话后，更新模板的入口依然成立。
    if (!state.templateStatus) return [];
    return [...new Set([].concat(
      state.templateStatus.missing || [],
      state.templateStatus.drifted || []
    ))];
  }

  function affectedTables() {
    // 保存成功提示只提本次保存的表：精确反馈这次动作的后果
    if (!state.templateStatus) return [];
    const saved = new Set(state.lastSavedTables || []);
    const tables = [].concat(
      state.templateStatus.missing || [],
      state.templateStatus.drifted || []
    );
    return [...new Set(tables)].filter((table) => saved.has(table));
  }

  async function regenerateTemplate(table) {
    // 显式入口：只在用户点击时重建模板，保存本身绝不触发
    try {
      await api("/api/schema-workspace/gen-template", {
        method: "POST", body: JSON.stringify({ table }),
      });
      state.templateError = null;
      state.notice = `模板已更新：${table}`;
    } catch (e) {
      // 模板失败独立展示：不能反过来把已成功的 YAML 保存标成失败
      state.templateError = e;
    }
    await refreshTemplateStatus();
    renderEditor();
    publishDraft();
  }

  function unsavedTableNotice() {
    /** 新 Table 必须先保存才能生成模板：没有落盘就没有可生成的 schema。 */
    const selected = selectedResource();
    if (!selected || resourceKind(selected) !== "table") return "";
    const persisted = (state.resources || []).some(
      (resource) => resource.resourceId === selected.resourceId);
    if (persisted) return "";
    return `${selected.name || selected.table} 尚未保存：保存后才能生成模板`;
  }

  function templateNote() {
    if (state.statusError) return state.statusError;
    const affected = affectedTables();
    return affected.length ? `模板待更新：${affected.join("、")}` : "";
  }

  function discardDraft() {
    if (state.saving || !state.commands.length) return;
    openDiscardDraft(ctx, {
      onDiscard: () => {
        state.saveError = null;
        state.notice = "";
      },
    });
  }

  function renderBanner() {
    const banner = container.querySelector("#draft-banner");
    if (!banner) return;
    const messages = [];
    if (state.error) messages.push(`Schema 快照加载失败：${state.error}`);
    if (state.saveError) messages.push(state.saveError.message);
    if (state.notice) messages.push(state.notice);
    state.issues.forEach((issue) =>
      messages.push(issue.location ? `${issue.message}（${issue.location}）` : issue.message));
    const template = state.templateTables || [];
    const templateBlock = template.length
      ? `<div class="ct-error-inline" id="template-note">模板待更新：${template.map((table) =>
          `${escapeHtml(table)}<button class="ct-btn ct-btn-sm ct-btn-ghost banner-gen-template" data-table="${escapeHtml(table)}">更新模板</button>`
        ).join("、")}</div>`
      : "";
    const templateFailure = state.templateError
      ? `<div class="ct-error-inline" id="template-error">模板生成失败：${escapeHtml(state.templateError.message || "")}
           <button class="ct-btn ct-btn-sm ct-btn-ghost" id="banner-retry-template">重试</button></div>`
      : "";
    const unsaved = unsavedTableNotice();
    const unsavedBlock = unsaved
      ? `<div class="ct-error-inline" id="template-unsaved">${escapeHtml(unsaved)}</div>`
      : "";
    banner.hidden = !messages.length && !template.length && !templateFailure && !unsavedBlock;
    banner.innerHTML = (messages.length
      ? `<div class="ct-error-inline">${messages.map((m) => escapeHtml(m)).join("<br>")}</div>`
      : "") + templateBlock + templateFailure + unsavedBlock;
    const retry = banner.querySelector("#banner-retry-template");
    if (retry) {
      retry.addEventListener("click", () => {
        const table = (state.templateTables || [])[0]
          || (state.lastSavedTables || [])[0];
        if (table) regenerateTemplate(table);
      });
    }
    banner.querySelectorAll(".banner-gen-template").forEach((button) => {
      button.addEventListener("click", () => regenerateTemplate(button.dataset.table));
    });
  }

  function renderEditor() {
    renderBanner();
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
      editorBody.innerHTML = `${warning}<section class="ct-editor-section"><div class="ct-section-heading"><div><h2>查询索引</h2><p>查询契约生成稳定的 C# / Lua 访问 API。</p></div></div>${renderIndexCards(resource)}</section>`;
      wireIndexCards(resource);
      return;
    }
    if (resource.kind === "enum" || !resource.fields) {
      const values = resource.values || [];
      const enumId = resource.resourceId;
      const enumRows = values.map((v, ordinal) => {
        const item = typeof v === "string" ? { name: v, comment: "" } : v;
        return `<tr data-enum-value="${escapeHtml(item.name)}">
          <td><span class="ct-mono ct-hint">${ordinal}:</span> <button class="ct-inline-btn" data-act="rename" title="重命名">${escapeHtml(item.name)}</button></td>
          <td class="ct-mono">${escapeHtml(item.comment || "")}</td>
          <td class="ct-row-ops">
            <button class="ct-inline-btn" data-act="comment" title="编辑值注释">注释</button>
            <button class="ct-inline-btn ct-danger" data-act="delete" title="删除值">✕</button>
          </td>
        </tr>`;
      }).join("");
      editorBody.innerHTML = `${warning}
        <section class="ct-editor-section">
          <div class="ct-section-heading"><div><h2>值</h2><p>列表位置即 wire 序号（byte），点击值名可重命名。</p></div></div>
          <div class="ct-field-table"><table class="ct-data ct-field-grid"><thead><tr><th>值</th><th>注释</th><th aria-label="操作"></th></tr></thead>
          <tbody>${enumRows || '<tr><td colspan="3" class="ct-empty-sub">（空）</td></tr>'}</tbody></table>
          <button class="ct-add-row" id="enum-add-value">＋ 新增值</button></div>
        </section>`;
      editorBody.querySelector("#enum-add-value").addEventListener("click", () => promptEnumValue(ctx, resource, values));
      editorBody.querySelectorAll("[data-act]").forEach((btn) => {
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          const value = btn.closest("tr").dataset.enumValue;
          const ordinal = values.findIndex((v) => (typeof v === "string" ? v : v.name) === value);
          const act = btn.dataset.act;
          if (act === "rename") {
            promptRenameEnumValue(ctx, resource, value, ordinal);
          } else if (act === "comment") {
            const item = values[ordinal];
            openEnumCommentEditor(ctx, resource, typeof item === "string" ? { name: item, comment: "" } : item, ordinal);
          } else if (act === "delete") {
            pushCommand({ type: "set_enum_values", payload: { name: enumId, values: values.filter((v) => (typeof v === "string" ? v : v.name) !== value) } });
          }
        });
      });
      return;
    }
    const refs = state.reverseRefs[resource.resourceId] || [];
    // Record 字段没有角色/约束语义（i18n / server_only / ref / Code 均为表级概念），
    // 隐藏该列与字段名旁的标记，避免空列误导；Table 保持完整列。
    const isRecord = kind === "record";
    const roleHeader = isRecord ? "" : "<th>角色与约束</th>";
    const roleMark = (f) => isRecord ? "" : `<span class="ct-field-role">${f.i18n ? "🌐" : ""}${f.server_only ? "🖥" : ""}${f.ref ? "🔗" : ""}</span>`;
    const roleTd = (f) => isRecord ? "" : `<td><span class="ct-role-list">${f.name === resource.primary ? '<span class="ct-badge ct-badge-warn">PRIMARY</span>' : ""}${f.i18n ? '<span class="ct-badge ct-badge-mute">I18N</span>' : ""}${f.server_only ? '<span class="ct-badge ct-badge-mute">SERVER</span>' : ""}${f.ref ? `<button class="ct-type-link" data-navigate-type="${escapeHtml(f.ref.split(".")[0])}" title="打开 ${escapeHtml(f.ref.split(".")[0])}">REF ${escapeHtml(f.ref)}</button>` : ""}</span></td>`;
    editorBody.innerHTML = `${warning}<section class="ct-editor-section">
      <div class="ct-section-heading"><div><h2>字段结构</h2><p>类型和字段注释可直接在字段操作中编辑。</p></div></div>
      <div class="ct-field-table"><table class="ct-data ct-field-grid"><thead><tr><th>字段</th><th>类型表达式</th><th>Excel</th>${roleHeader}<th aria-label="操作"></th></tr></thead>
      <tbody>${resource.fields.map((f, index) => {
        const rawType = f.type || f.type_expr || "?";
        const typeExpr = typeof rawType === "string" ? rawType : JSON.stringify(rawType);
        const selected = state.selectedField === f.name;
        const isPrimary = f.name === resource.primary;
        return `<tr class="${selected ? "ct-row-selected" : ""}" data-field="${escapeHtml(f.name)}">
          <td><button class="ct-inline-btn" data-act="rename" title="改名">${escapeHtml(f.name)}</button>
              ${roleMark(f)}</td>
          <td>${renderTypeExpression(typeExpr)}</td>
          <td class="ct-mono">${f.excel_columns ? `expanded × ${f.excel_columns}` : "1 column"}</td>
          ${roleTd(f)}
          <td class="ct-row-ops">
            <button class="ct-inline-btn" data-act="up" ${isPrimary || index === 0 ? "disabled" : ""} title="${isPrimary ? "主键字段不可调整顺序" : "上移"}">↑</button>
            <button class="ct-inline-btn" data-act="down" ${isPrimary || index === resource.fields.length - 1 ? "disabled" : ""} title="${isPrimary ? "主键字段不可调整顺序" : "下移"}">↓</button>
            <button class="ct-inline-btn" data-act="comment" title="编辑字段注释">注释</button>
            <button class="ct-inline-btn ct-danger" data-act="delete" ${isPrimary ? "disabled" : ""} title="${isPrimary ? "主键字段不可删除" : "删除字段"}">✕</button>
          </td></tr>`;
      }).join("")}</tbody></table><button class="ct-add-row" id="add-field">＋ 添加字段</button></div>
      </section>`;
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
          const field = resource.fields.find((item) => item.name === fieldName);
          openFieldTypeEditor(ctx, field, ({ type_text, excel_columns }) => {
            pushCommand({ type: "set_type", payload: { owner: resource.resourceId, name: fieldName, type_text } });
            pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: fieldName, property: "excel_columns", value: excel_columns } });
          });
        } else if (act === "comment") {
          const field = resource.fields.find((item) => item.name === fieldName);
          openFieldCommentEditor(ctx, resource, field);
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
  }

  function indexOf(fieldName) {
    const resource = selectedResource();
    return resource ? resource.fields.findIndex((f) => f.name === fieldName) : -1;
  }

  function renderIndexCards(resource) {
    if (!resource.primary) return "";
    const current = resource.indexes || [];
    // CodeName 索引**固定指向名为 CodeName 的 string 字段** —— 不是「随便指一个 string 字段」，
    // 所以这里是一个开关，没有字段选择器。表里没有 CodeName 字段时禁用（后端也会拒）。
    const codenameOn = current.some((i) => i.kind === "codename");
    const hasCodename = resource.fields.some((f) => f.name === "CodeName");
    const codenameCard = `<div class="ct-index-card">
      <div class="ct-index-card-head">CodeName（唯一 · 固定字段）<span class="ct-mono ct-index-preview">ByCodeName(codeName)</span></div>
      <label class="ct-index-toggle${hasCodename ? "" : " is-disabled"}">
        <input type="checkbox" data-index-codename ${codenameOn ? "checked" : ""} ${hasCodename ? "" : "disabled"}>
        <span>${hasCodename
          ? "启用（固定指向 <span class=\"ct-mono\">CodeName</span> 字段）"
          : "本表没有名为 <span class=\"ct-mono\">CodeName</span> 的 string 字段，无法启用"}</span>
      </label>
    </div>`;
    return `<div class="ct-index-cards">
      <div class="ct-index-cards-title">查询索引</div>
      ${codenameCard}
    </div>`;
  }

  function wireIndexCards(resource) {
    // CodeName 索引是个开关：勾上 = 声明 kind: codename（不写 field，后端固定指向 CodeName）
    const codenameBox = editorBody.querySelector("[data-index-codename]");
    if (codenameBox) {
      codenameBox.addEventListener("change", () => {
        const rest = (resource.indexes || []).filter(
          (i) => i.kind !== "codename"
        );
        const next = codenameBox.checked ? [...rest, { kind: "codename" }] : rest;
        pushCommand({ type: "set_indexes", payload: { table: resource.resourceId, indexes: next } });
      });
    }
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
        (state.notice ? '<div class="ct-field"><label class="ct-field-label">草稿状态</label><div>' + escapeHtml(state.notice) + "</div></div>" : "");
      return;
    }
    const rawType = field.type || field.type_expr || "";
    const typeExpr = typeof rawType === "string" ? rawType : JSON.stringify(rawType);
    const value = (label, current) =>
      `<div class="ct-field"><label class="ct-field-label">${escapeHtml(label)}</label>
       <div class="ct-inspector-value${current == null || current === "" ? " ct-inspector-muted" : ""}">${escapeHtml(current == null || current === "" ? "（无）" : current)}</div></div>`;
    const flag = (label, current) =>
      `<div class="ct-inspector-flag"><span class="ct-badge ${current ? "ct-badge-warn" : "ct-badge-mute"}">${current ? "已启用" : "未启用"}</span>${escapeHtml(label)}</div>`;
    inspector.innerHTML =
      `<section class="ct-inspector-section"><h2>定义（只读）</h2>
         <div class="ct-field"><label class="ct-field-label">字段名</label><div class="ct-inspector-value ct-mono">${escapeHtml(field.name)}</div></div>
         <div class="ct-field"><label class="ct-field-label">类型表达式</label><div class="ct-inspector-value ct-mono">${escapeHtml(typeExpr)}</div></div>
       </section>
       <section class="ct-inspector-section"><h2>Excel 表达（只读）</h2>${value("固定最大槽位", field.excel_columns ?? "")}${(field.type || "").startsWith("vector") ? value("变长文法", "[...]，英文逗号") : ""}</section>
       <section class="ct-inspector-section"><h2>角色与约束（只读）</h2>
         <div class="ct-check-group">${flag("国际化 i18n", !!field.i18n)}${flag("仅服务端", !!field.server_only)}</div>
         ${value("跨表引用", field.ref || "")}
       </section>
       <section class="ct-inspector-section"><h2>说明（只读）</h2>${value("字段注释", field.comment || "")}</section>`;
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
    let candidates = candidatePool()
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
    // Recent resources are a cross-workspace preference.  If they all belong
    // to another workspace, an empty query must still show this workspace's
    // resources instead of producing a blank palette.
    if (!query && recentOrder.size && !candidates.length) {
      candidates = candidatePool()
        .map((r) => {
          const name = r.name || r.table || r.resourceId || "";
          return { resource: r, name, score: 0 };
        })
        .sort((a, b) => a.name.localeCompare(b.name));
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
  container.querySelector("#head-create-resource").addEventListener("click", () => startCreate(""));
  container.querySelector("#head-delete-resource").addEventListener("click", () => {
    const resource = selectedResource();
    if (resource) confirmDeleteResource(ctx, resource);
  });
  paneBackdrop.addEventListener("click", () => { setResourceOpen(false); setInspectorOpen(false); });

  /* module-level events from shell/registry */
  window.addEventListener("ct:schema-quick-open-open", () => openQuickOpen());
  window.addEventListener("ct:schema-resource-toggle", () => setResourceOpen(!state.resourceOpen));
  window.addEventListener("ct:draft-action", (e) => {
    const type = e.detail && e.detail.type;
    if (type === "undo") undo();
    else if (type === "redo") redo();
    else if (type === "save") saveChanges();
    else if (type === "discard") discardDraft();
    else if (type === "summary") openDraftSummary(ctx);
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

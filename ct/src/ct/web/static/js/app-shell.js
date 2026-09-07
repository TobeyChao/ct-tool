/* AppShell: resident sidebar (module nav + doc/help/about), narrow topbar with
   hamburger drawer below 740px, page container, shell-level draft bar, taskbar.
   Core (api/router/task/projection/dialog) is imported here; business modules
   are imported by the pages they own, never by core. Global shortcuts dispatch
   domain events instead of importing business modules:
   Cmd/Ctrl+P -> ct:schema-quick-open, Cmd/Ctrl+Z / Shift -> ct:draft-action. */
import { api } from "./core/api.js";
import { navigate, onRouteChange } from "./core/router.js";
import { onTasks, startPolling } from "./core/task.js";
import { PROJECTIONS, projectionForWidth, projectionClass, subscribeProjection } from "./core/projection.js";
import { escapeHtml } from "./core/dom.js";
import { openDialog, pushEscLayer } from "./core/dialog.js";

const MODULES = [
  { id: "export", label: "导出" },
  { id: "i18n", label: "翻译 i18n" },
  { id: "schema", label: "Schema" },
  { id: "logs", label: "日志" },
  { id: "history", label: "历史" },
];

const DOCS_URL = "https://github.com/TobeyChao/ct-tool"; // 外部文档占位：发布前替换为文档站

/* per-module page state: survives projection changes and module switches */
export const pageState = new Map();
export function getPageState(moduleId) {
  if (!pageState.has(moduleId)) pageState.set(moduleId, {});
  return pageState.get(moduleId);
}

const app = document.getElementById("app");
let sidebarOpen = false;
let removeSidebarEscLayer = null;

function workspaceName(ws) {
  const root = ws && ws.root ? String(ws.root) : "";
  return root.split(/[\\/]/).filter(Boolean).at(-1) || "ct workspace";
}

function renderTopbar(wsName) {
  return `<header class="ct-topbar">
    <button class="ct-hamb" id="ct-hamb" aria-label="打开导航" aria-expanded="false" aria-controls="ct-sidebar">☰</button>
    <div class="ct-topbar-brand"><span class="ct-brand-mark">ct</span></div>
    <span class="ct-ws"><span class="ct-ws-name">${escapeHtml(wsName)}</span></span>
  </header>`;
}

function renderSidebar(active) {
  return `<nav class="ct-sidebar" id="ct-sidebar" aria-label="模块">
    <div class="ct-side-head">
      <button class="ct-icon-btn ct-side-back" id="ct-side-back" aria-label="收起导航">‹</button>
      <span class="ct-brand-mark">ct</span><span class="ct-side-title">配表工具</span>
    </div>
    <div class="ct-side-nav">
      <div class="ct-side-sec">模块</div>
      ${MODULES.map((m) =>
        `<button class="ct-sitem${m.id === active ? " active" : ""}" data-module="${m.id}"${m.id === active ? ' aria-current="page"' : ""}>${m.label}</button>`
      ).join("")}
    </div>
    <div class="ct-sfoot">
      <a class="ct-ssec" id="ct-doc-link" href="${DOCS_URL}" target="_blank" rel="noopener" title="外部文档">导出文档</a>
      <button class="ct-ssec" id="ct-help">帮助与反馈</button>
      <button class="ct-ssec" id="ct-about">关于</button>
    </div>
  </nav>`;
}

function renderPages(active) {
  return `<main class="ct-main">${MODULES.map((m) =>
    `<section class="ct-page${m.id === active ? " active" : ""}" id="page-${m.id}" data-page="${m.id}"${m.id === active ? "" : " inert aria-hidden=\"true\""}></section>`
  ).join("")}<div class="ct-draftbar" id="ct-draftbar" hidden>
    <span class="ct-draft-dot" aria-hidden="true"></span>
    <span class="ct-draft-txt" id="ct-draft-txt">0 条未应用变更</span>
    <span class="ct-draft-acts">
      <button class="ct-btn ct-btn-ghost ct-btn-sm" id="ct-draft-undo" disabled>撤销</button>
      <button class="ct-btn ct-btn-ghost ct-btn-sm" id="ct-draft-redo" disabled>重做</button>
      <button class="ct-btn ct-btn-primary ct-btn-sm" id="ct-draft-review" disabled>审查并应用</button>
    </span>
  </div><div class="ct-toast" id="ct-toast" role="status" aria-live="polite" hidden></div></main>`;
}

function renderTaskbar(tasks) {
  const items = tasks || [];
  if (!items.length) return "";
  return `<div class="ct-taskbar" role="status" aria-live="polite">${items.map((t) =>
    `<div class="ct-task ${t.status === "error" ? "error" : ""}">
      <span class="ct-task-indicator" aria-hidden="true"></span>
      <span class="ct-task-copy"><strong>${escapeHtml(t.kind)}</strong><span>${escapeHtml(t.scope)} · ${escapeHtml(t.message || t.status)}</span></span>
      ${t.target ? `<a class="ct-task-link" href="#${escapeHtml(t.target)}">查看日志</a>` : ""}
    </div>`
  ).join("")}</div>`;
}

function activateModule(moduleId) {
  app.querySelectorAll(".ct-sitem").forEach((t) => {
    const active = t.dataset.module === moduleId;
    t.classList.toggle("active", active);
    if (active) t.setAttribute("aria-current", "page");
    else t.removeAttribute("aria-current");
  });
  app.dataset.module = moduleId;
  app.querySelectorAll(".ct-page").forEach((p) => {
    const active = p.dataset.page === moduleId;
    p.classList.toggle("active", active);
    if (active) {
      p.removeAttribute("inert");
      p.removeAttribute("aria-hidden");
    } else {
      p.setAttribute("inert", "");
      p.setAttribute("aria-hidden", "true");
    }
  });
  window.dispatchEvent(new CustomEvent("ct:module", { detail: moduleId }));
  return getPageState(moduleId);
}

/* ---- hamburger drawer (<740) ---- */
function setSidebarDrawer(open) {
  const sidebar = app.querySelector("#ct-sidebar");
  const backdrop = app.querySelector("#ct-side-backdrop");
  const hamb = app.querySelector("#ct-hamb");
  if (!sidebar) return;
  const wasOpen = sidebarOpen;
  sidebarOpen = open;
  sidebar.classList.toggle("open", open);
  if (backdrop) backdrop.classList.toggle("show", open && window.innerWidth < 740);
  if (hamb) hamb.setAttribute("aria-expanded", String(open));
  // closed drawer leaves the focus order & assistive tree below 740
  sidebar.toggleAttribute("inert", window.innerWidth < 740 && !open);
  if (window.innerWidth < 740) {
    if (open && !wasOpen) {
      const first = sidebar.querySelector("button, a");
      if (first) first.focus();
      removeSidebarEscLayer = pushEscLayer(() => {
        setSidebarDrawer(false);
        if (hamb) hamb.focus();
        return true;
      }, 30);
    } else if (!open && wasOpen) {
      if (removeSidebarEscLayer) removeSidebarEscLayer();
      removeSidebarEscLayer = null;
      if (hamb) hamb.focus();
    }
  } else if (!open && removeSidebarEscLayer) {
    removeSidebarEscLayer();
    removeSidebarEscLayer = null;
  }
}

/* ---- shell draft bar: schema module publishes state via ct:draft ---- */
let draftSuccessTimer = null;
let toastTimer = null;
function showSuccessToast(text) {
  const toast = document.getElementById("ct-toast");
  if (!toast) return;
  clearTimeout(toastTimer);
  toast.textContent = text;
  toast.hidden = false;
  toast.classList.add("show");
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    toast.hidden = true;
  }, 1800);
}
function renderDraftBar(detail) {
  const bar = document.getElementById("ct-draftbar");
  if (!bar) return;
  const { pending = 0, canRedo = false, warn = false, successText = "" } = detail || {};
  if (successText) {
    clearTimeout(draftSuccessTimer);
    bar.hidden = true;
    bar.classList.remove("warn", "success");
    showSuccessToast(successText);
    return;
  }
  clearTimeout(draftSuccessTimer);
  if (!pending && !canRedo) {
    bar.hidden = true;
    bar.classList.remove("warn", "success");
    return;
  }
  bar.hidden = false;
  bar.classList.toggle("warn", Boolean(warn));
  bar.classList.remove("success");
  const note = warn ? " · 草稿未持久化（IndexedDB）" : "";
  document.getElementById("ct-draft-txt").textContent =
    (pending ? pending + " 条未应用变更" : "已全部撤销 · 可重做") + note;
  document.getElementById("ct-draft-undo").disabled = !pending;
  document.getElementById("ct-draft-redo").disabled = !canRedo;
  document.getElementById("ct-draft-review").disabled = !pending;
}

/* ---- about / help dialogs (sidebar footer) ---- */
function openAbout(wsName) {
  openDialog({
    title: "关于",
    variant: "std",
    initialFocusSelector: "[data-close]",
    body: `<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
        <span class="ct-brand-mark" style="width:38px;height:38px;border-radius:9px;font-size:14px">ct</span>
        <div><div style="font-weight:680;font-size:14px">配表工具</div>
        <div class="ct-hint ct-mono" style="margin-top:2px">版本 0.6.x · 工作区 ${escapeHtml(wsName)}</div></div>
      </div>
      <p style="margin:0 0 12px;color:var(--ct-ink-2);font-size:12.5px;line-height:1.7">将 Excel + YAML Schema 导出为 JSON · FBS · Binary · C#/Lua Accessor。</p>
      <p style="margin:0;font-size:12.5px">· <a href="${DOCS_URL}" target="_blank" rel="noopener">导出文档</a>　· <a href="${DOCS_URL}" target="_blank" rel="noopener">项目仓库</a></p>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-close>关闭</button>`,
  });
}

function openHelp() {
  openDialog({
    title: "帮助与反馈",
    variant: "std",
    initialFocusSelector: "[data-close]",
    body: `<div class="ct-dlg-label" style="font-size:11.5px;font-weight:700;color:var(--ct-ink-2);margin-bottom:5px">快捷操作</div>
      <div class="ct-keys">
        <div><kbd>⌘P</kbd>快速打开资源<span>全局</span></div>
        <div><kbd>⌘Z</kbd><kbd>⇧⌘Z</kbd>撤销 / 重做<span>草稿</span></div>
        <div><kbd>Esc</kbd>关闭浮层（逐层退）<span>全局</span></div>
      </div>
      <div class="ct-dlg-label" style="font-size:11.5px;font-weight:700;color:var(--ct-ink-2);margin-bottom:5px">遇到问题？</div>
      <p style="margin:0 0 4px;font-size:12.5px">· <a href="${DOCS_URL}" target="_blank" rel="noopener">查看导出文档</a></p>
      <p style="margin:0;font-size:12.5px">· <a href="${DOCS_URL}" target="_blank" rel="noopener">提交反馈（GitHub Issues）</a></p>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-close>关闭</button>`,
  });
}

export async function bootstrap() {
  let ws = null;
  try { ws = await api("/api/workspace"); } catch (e) { ws = null; }
  const wsName = workspaceName(ws);
  const active = MODULES.find((m) => location.hash.indexOf(m.id) !== -1)?.id || "export";
  app.classList.add("ct-app");
  app.dataset.module = active;
  app.innerHTML = `${renderTopbar(wsName)}<div class="ct-shell">${renderSidebar(active)}${renderPages(active)}</div>
    <div class="ct-side-backdrop" id="ct-side-backdrop"></div><div id="ct-taskbar"></div>`;

  const applyProjection = (projection) => {
    app.classList.remove(...PROJECTIONS.map(projectionClass));
    app.classList.add(projectionClass(projection));
    app.dataset.projection = projection;
  };
  applyProjection(projectionForWidth(window.innerWidth));
  const projectionSub = subscribeProjection(app, applyProjection);

  app.querySelectorAll(".ct-sitem").forEach((item) => {
    item.addEventListener("click", () => {
      const moduleId = item.dataset.module;
      if (moduleId === "schema" && app.dataset.module === "schema") {
        // 再点当前 Schema 条目：切换资源面板开合（与原型一致）
        window.dispatchEvent(new CustomEvent("ct:schema-resource-toggle"));
        setSidebarDrawer(false);
        return;
      }
      activateModule(moduleId);
      navigate("/" + moduleId);
      setSidebarDrawer(false);
    });
  });
  const hamb = app.querySelector("#ct-hamb");
  if (hamb) hamb.addEventListener("click", () => setSidebarDrawer(true));
  const sideBack = app.querySelector("#ct-side-back");
  if (sideBack) sideBack.addEventListener("click", () => setSidebarDrawer(false));
  const sideBackdrop = app.querySelector("#ct-side-backdrop");
  if (sideBackdrop) sideBackdrop.addEventListener("click", () => setSidebarDrawer(false));
  const aboutBtn = app.querySelector("#ct-about");
  if (aboutBtn) aboutBtn.addEventListener("click", () => openAbout(wsName));
  const helpBtn = app.querySelector("#ct-help");
  if (helpBtn) helpBtn.addEventListener("click", openHelp);

  onRouteChange((route) => {
    const moduleId = route.path.split("/").filter(Boolean)[0];
    if (MODULES.some((module) => module.id === moduleId) && app.dataset.module !== moduleId) {
      activateModule(moduleId);
    }
  });

  /* global shortcuts: dispatch domain events; the owning module reacts.
     ⌘P must work from any module: module-registry lazily mounts Schema. */
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "p") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("ct:schema-quick-open"));
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("ct:draft-action", { detail: { type: e.shiftKey ? "redo" : "undo" } }));
    }
  });

  window.addEventListener("ct:draft", (e) => renderDraftBar(e.detail || {}));

  /* draftbar buttons: shell owns the surface, schema owns the draft domain */
  const draftUndoBtn = document.getElementById("ct-draft-undo");
  const draftRedoBtn = document.getElementById("ct-draft-redo");
  const draftReviewBtn = document.getElementById("ct-draft-review");
  if (draftUndoBtn) draftUndoBtn.addEventListener("click", () =>
    window.dispatchEvent(new CustomEvent("ct:draft-action", { detail: { type: "undo" } })));
  if (draftRedoBtn) draftRedoBtn.addEventListener("click", () =>
    window.dispatchEvent(new CustomEvent("ct:draft-action", { detail: { type: "redo" } })));
  if (draftReviewBtn) draftReviewBtn.addEventListener("click", () =>
    window.dispatchEvent(new CustomEvent("ct:draft-review")));

  onTasks((tasks) => {
    const host = document.getElementById("ct-taskbar");
    if (host) host.innerHTML = renderTaskbar(tasks);
  });
  startPolling();
  return { activateModule, getPageState };
}

/* v4 AppShell: topbar, module nav, page container, adaptive projection,
   side-area activeTool, persistent per-module page state, taskbar.
   Core (api/router/task/projection) is imported here; business modules are
   imported by the pages they own, never by core. */
import { api } from "./core/api.js";
import { navigate, onRouteChange } from "./core/router.js";
import { onTasks, startPolling } from "./core/task.js";
import { PROJECTIONS, projectionForWidth, projectionClass, subscribeProjection } from "./core/projection.js";
import { escapeHtml } from "./core/dom.js";

const MODULES = [
  { id: "export", label: "导出", glyph: "EX" },
  { id: "i18n", label: "翻译 i18n", glyph: "文" },
  { id: "schema", label: "Schema", glyph: "SC" },
  { id: "logs", label: "日志", glyph: ">_" },
  { id: "history", label: "历史", glyph: "HI" },
];

/* per-module page state: survives projection changes and module switches */
export const pageState = new Map();
export function getPageState(moduleId) {
  if (!pageState.has(moduleId)) pageState.set(moduleId, {});
  return pageState.get(moduleId);
}

const app = document.getElementById("app");

function summaryText(ws) {
  if (!ws || !ws.status) return "工作区不可用";
  const st = ws.status;
  const parts = [];
  if (st.missing && st.missing.length) parts.push(st.missing.length + " 张表缺失");
  if (st.drifted && st.drifted.length) parts.push(st.drifted.length + " 张表模板漂移");
  if (st.changed && st.changed.length) parts.push(st.changed.length + " 张表待导出");
  return parts.length ? parts.join(" · ") : "数据与模板均已同步";
}

function renderTopbar(ws) {
  const root = ws && ws.root ? String(ws.root) : "工作区不可用";
  const workspaceName = root.split(/[\\/]/).filter(Boolean).at(-1) || "ct workspace";
  return `
    <header class="ct-topbar">
      <div class="ct-brand"><span class="ct-brand-mark">ct</span><span class="ct-brand-name">Workspace</span></div>
      <div class="ct-workspace-context">
        <strong>${escapeHtml(workspaceName)}</strong><span class="ct-context-separator">/</span>
        <span class="ct-workspace-path" title="${escapeHtml(root)}">${escapeHtml(root)}</span>
      </div>
      <div class="ct-topbar-actions" id="ct-module-actions"></div>
      <span class="ct-health"><span class="ct-health-dot"></span>${escapeHtml(summaryText(ws))}</span>
    </header>`;
}

function renderNav(active) {
  return `<nav class="ct-nav ct-activity-bar" aria-label="模块导航" role="tablist">${MODULES.map((m) =>
    `<button class="ct-tab ct-activity-button${m.id === active ? " active" : ""}" role="tab" aria-label="${m.label}" aria-selected="${m.id === active}" data-module="${m.id}" data-tooltip="${m.label}"><span aria-hidden="true">${m.glyph}</span><span class="ct-mobile-label">${m.label}</span></button>`
  ).join("")}<span class="ct-activity-spacer"></span><span class="ct-rail-health" aria-label="工作区健康">✓</span></nav>`;
}

function renderPages(active) {
  return `<main class="ct-main">${MODULES.map((m) =>
    `<section class="ct-page${m.id === active ? " active" : ""}" id="page-${m.id}" data-page="${m.id}"${m.id === active ? "" : " inert aria-hidden=\"true\""}></section>`
  ).join("")}</main>`;
}

function renderTaskbar(tasks) {
  const items = tasks || [];
  if (!items.length) return "";
  return `<div class="ct-taskbar">${items.map((t) =>
    `<div class="ct-task ${t.status === "error" ? "error" : ""}">${escapeHtml(t.kind)} · ${escapeHtml(t.scope)} · ${escapeHtml(t.message || t.status)}</div>`
  ).join("")}</div>`;
}

function activateModule(moduleId) {
  app.querySelectorAll(".ct-tab").forEach((t) => {
    const active = t.dataset.module === moduleId;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", String(active));
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

export async function bootstrap() {
  let ws = null;
  try { ws = await api("/api/workspace"); } catch (e) { ws = null; }
  const active = MODULES.find((m) => location.hash.indexOf(m.id) !== -1)?.id || "export";
  app.classList.add("ct-app");
  app.dataset.module = active;
  app.innerHTML = `${renderTopbar(ws)}<div class="ct-shell">${renderNav(active)}${renderPages(active)}</div><div id="ct-taskbar"></div>`;

  const applyProjection = (projection) => {
    app.classList.remove(...PROJECTIONS.map(projectionClass));
    app.classList.add(projectionClass(projection));
    app.dataset.projection = projection;
  };
  applyProjection(projectionForWidth(window.innerWidth));
  const projectionSub = subscribeProjection(app, applyProjection);

  app.querySelectorAll(".ct-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const moduleId = tab.dataset.module;
      if (moduleId === "schema" && app.dataset.module === "schema") {
        window.dispatchEvent(new CustomEvent("ct:schema-resource-toggle"));
        return;
      }
      activateModule(moduleId);
      navigate("/" + moduleId);
    });
  });
  onRouteChange((route) => {
    const moduleId = route.path.split("/").filter(Boolean)[0];
    if (MODULES.some((module) => module.id === moduleId) && app.dataset.module !== moduleId) {
      activateModule(moduleId);
    }
  });

  onTasks((tasks) => {
    const host = document.getElementById("ct-taskbar");
    if (host) host.innerHTML = renderTaskbar(tasks);
  });
  startPolling();
  return { activateModule, getPageState };
}

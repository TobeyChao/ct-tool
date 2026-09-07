/* core/dialog: shared modal stack — the single dialog contract for all modules.
   Variants: sm / std / plan / palette / wide (CSS width classes).
   Stack semantics: Escape closes the topmost layer (or lets it consume Esc,
   e.g. palette clears its query first), focus is trapped per dialog skipping
   disabled controls, closing returns focus to the opener, the app shell gets
   inert while any dialog is open, and title ids stay unique when nested. */

const FOCUSABLE = 'button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"]):not([disabled])';

const stack = []; // open dialog handles, bottom → top
const escLayers = []; // non-dialog layers (drawers, menus), bottom → top
let titleSeq = 0;
let appEl = null;

function app() {
  if (!appEl) appEl = document.getElementById("app");
  return appEl;
}

function syncAppInert() {
  const root = app();
  if (!root) return;
  if (stack.length) root.setAttribute("inert", "");
  else root.removeAttribute("inert");
}

/* ---- Esc layer registry -----------------------------------------------
   dialogs and temporary surfaces (drawers/menus) register handlers; Escape
   unwinds dialogs first, then layers by priority (higher first, later
   registration first within a priority). A handler returns true when it
   consumed the key. */
let layerSeq = 0;

export function pushEscLayer(handler, priority = 0) {
  const entry = { handler, priority, seq: ++layerSeq };
  escLayers.push(entry);
  return () => {
    const index = escLayers.indexOf(entry);
    if (index >= 0) escLayers.splice(index, 1);
  };
}

function handleEscape() {
  if (stack.length) {
    const top = stack[stack.length - 1];
    if (top.onEsc && top.onEsc(top) === true) return; // consumed (e.g. clear query)
    close(top);
    return;
  }
  const ordered = [...escLayers].sort((a, b) => b.priority - a.priority || b.seq - a.seq);
  for (const entry of ordered) {
    if (entry.handler() === true) return;
  }
}

if (typeof document !== "undefined" && !window.__ctDialogKeysBound) {
  window.__ctDialogKeysBound = true;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") handleEscape();
  });
}

function trapTab(mask, e) {
  const focusables = [...mask.querySelectorAll(FOCUSABLE)];
  if (!focusables.length) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

export function openDialog(options) {
  const {
    title = "",
    titleExtra = "",
    body = "",
    footer = "",
    variant = "std", // sm | std | plan | palette | wide
    initialFocusSelector = "", // defaults to first focusable in the dialog
    onEsc = null, // (handle) => true consumes Escape without closing
    onClose = null, // (handle) => void, also fired for programmatic close
  } = options;

  const mask = document.createElement("div");
  mask.className = "ct-dialog-mask";
  mask._opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const titleId = "ct-dlg-title-" + (++titleSeq);
  const variantClass = variant === "std" ? "" : " ct-dlg-" + variant;
  mask.innerHTML = `<div class="ct-dialog${variantClass}" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
    <div class="ct-dialog-head"><span id="${titleId}">${title}</span><span class="ct-spacer"></span>${titleExtra}<button class="ct-icon-btn" data-close aria-label="关闭">✕</button></div>
    <div class="ct-dialog-body">${body}</div>
    ${footer ? `<div class="ct-dialog-foot">${footer}</div>` : ""}
  </div>`;
  document.body.appendChild(mask);
  // 强制回流后立即加 open：过渡照常播放，且不依赖 rAF（后台标签页 rAF 冻结）
  void mask.offsetWidth;
  mask.classList.add("open");
  setTimeout(() => mask.classList.add("open"), 80);

  const dialog = mask.querySelector(".ct-dialog");
  const handle = {
    el: mask,
    dialog,
    onEsc,
    close: () => close(handle),
    setBody(html) {
      dialog.querySelector(".ct-dialog-body").innerHTML = html;
    },
  };
  stack.push(handle);

  mask.addEventListener("mousedown", (e) => {
    if (e.target === mask) close(handle);
  });
  mask.addEventListener("keydown", (e) => {
    if (e.key === "Tab") trapTab(mask, e);
  });
  mask.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => close(handle));
  });

  const focusTarget = initialFocusSelector ? mask.querySelector(initialFocusSelector) : mask.querySelector(FOCUSABLE);
  if (focusTarget) focusTarget.focus();
  else if (mask.querySelector(".ct-dialog-body")?.querySelector(FOCUSABLE)) {
    mask.querySelector(".ct-dialog-body").querySelector(FOCUSABLE).focus();
  }
  syncAppInert();
  return handle;
}

function close(handle) {
  const index = stack.indexOf(handle);
  if (index < 0) return;
  stack.splice(index, 1);
  handle.el.classList.remove("open");
  handle.el.classList.add("closing");
  if (handle.onClose) handle.onClose(handle);
  // nested dialogs keep the app inert while a lower one is still open
  const live = stack.filter((h) => !h.el.classList.contains("closing"));
  if (!live.length) syncAppInert();
  const opener = handle.el._opener;
  if (opener && opener.isConnected) {
    try { opener.focus(); } catch (e) { /* opener removed */ }
  }
  setTimeout(() => handle.el.remove(), 220);
}

/* Convenience wrappers for the shared confirmation/form surfaces. */
export function confirmDialog({ title, body, confirmLabel = "确认", danger = true, variant = "sm", onConfirm }) {
  const handle = openDialog({
    title,
    body,
    variant,
    initialFocusSelector: "[data-cancel]",
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>` +
      `<button class="${danger ? "ct-btn ct-btn-danger-solid" : "ct-btn ct-btn-primary"}" data-confirm>${confirmLabel}</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-confirm]").addEventListener("click", () => {
    if (onConfirm(handle) !== false) handle.close();
  });
  return handle;
}

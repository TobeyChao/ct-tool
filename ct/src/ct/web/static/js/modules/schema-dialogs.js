/* schema-dialogs: every Schema editing surface that is a dialog, riding the
   shared core/dialog stack (Esc 逐层退栈/焦点陷阱/还焦 are the stack's job).
   D1 删除资源(+查看影响预览) / D2 删除字段 / 改名 / 枚举新增值 /
   F1 添加字段(+F2 类型选择器) / P5 变更计划 / P6 放弃草稿.
   ctx (provided by schema.js) carries data + command flow, this file owns UI:
   - ctx.pushCommand(cmd)          append a draft command
   - ctx.effectiveCommands()       pending commands (slice to cursor)
   - ctx.pendingCount()            pending command count
   - ctx.clearDraftState()         drop the whole draft (persist + re-render)
   - ctx.applyCommands(cmds)       prepare-apply → apply; returns {names}
   - ctx.refreshAll()              re-render list/editor/inspector
   - ctx.state                     schema page state (resources, reverseRefs…) */

import { openDialog } from "../core/dialog.js";
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

const NAME_RE = /^[A-Z][A-Za-z0-9_]*$/;
export const KIND_LABEL = { table: "Table", record: "Record", enum: "Enum" };
// shared kind inference: named resources carry an explicit kind, otherwise
// tables/records have a `fields` list and enums do not.
export function resourceKind(resource) {
  return resource.kind || (resource.fields ? "table" : "enum");
}
const SCALARS = ["int32", "int64", "float", "double", "bool", "string"];
const RISK_LABEL = {
  safe: "安全",
  "data-dependent": "数据依赖",
  destructive: "破坏",
  incompatible: "不兼容",
  "dependency-breaking": "依赖破坏",
};

function validFieldName(value) {
  return NAME_RE.test(value) && !value.endsWith("_");
}

/* ---- D2 删除字段 ---- */
export function confirmDeleteField(ctx, resource, fieldName, typeLabel) {
  const handle = openDialog({
    title: "删除字段",
    variant: "sm",
    initialFocusSelector: "[data-cancel]",
    body: `<p style="margin:0 0 8px"><b class="ct-mono" style="font-weight:600">${escapeHtml(fieldName)}</b> <span class="ct-hint ct-mono">· ${escapeHtml(typeLabel || "")}</span></p>
      <p style="margin:0;color:var(--ct-ink-2);font-size:12.5px">将移出字段表与 Excel 列。作为草稿变更，可撤销。</p>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-danger-solid" data-confirm>删除</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-confirm]").addEventListener("click", () => {
    ctx.pushCommand({ type: "delete_field", payload: { owner: resource.resourceId, name: fieldName } });
    handle.close();
  });
}

/* ---- D1 删除资源（含「查看影响」预览） ---- */
export function confirmDeleteResource(ctx, resource) {
  const refs = ctx.state.reverseRefs[resource.resourceId] || [];
  const blocked = refs.length > 0;
  const kind = resourceKind(resource);
  const name = resource.name || resource.table || resource.resourceId;
  const fieldCount = (resource.fields || []).length;
  const handle = openDialog({
    title: "删除资源",
    variant: "std",
    initialFocusSelector: "[data-cancel]",
    body: `<p style="margin:0 0 10px;display:flex;align-items:center;gap:8px">
        <span class="ct-resource-kind">${escapeHtml(KIND_LABEL[kind] || kind)}</span>
        <b class="ct-mono" style="font-weight:680;font-size:14px">${escapeHtml(name)}</b></p>
      ${blocked ? `<div class="ct-blocker-list"><div class="ct-blocker">⛔ 无法删除：仍被引用 ${refs.map((r) => `<span class="ct-loc">${escapeHtml(r.field)}</span>`).join("、")}（不提供级联删除）</div></div>` : ""}
      <p style="margin:0;color:var(--ct-ink-2);font-size:12.5px;line-height:1.7">将移除：${fieldCount} 个字段${resource.excel_file ? " · " + escapeHtml(resource.excel_file) : ""}<br>变更先进入草稿，可在底部撤销，审查并应用后才真正落盘。</p>`,
    footer: `<button class="ct-btn ct-btn-ghost" id="dl-seeplan">查看影响</button>
      <button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-danger-solid" data-confirm ${blocked ? "disabled" : ""}>删除</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-confirm]").addEventListener("click", () => {
    ctx.pushCommand({ type: "delete_resource", payload: { name: resource.resourceId } });
    ctx.state.selection = null;
    handle.close();
  });
  handle.el.querySelector("#dl-seeplan").addEventListener("click", () => {
    openChangePlan(ctx, { type: "delete_resource", payload: { name: resource.resourceId } });
  });
}

/* ---- 改名字段 / 枚举新增值（表单弹窗，替换 prompt） ---- */
function formDialog({ title, label, placeholder, initial = "", submitLabel, validate, onSubmit }) {
  const handle = openDialog({
    title,
    variant: "sm",
    initialFocusSelector: "[data-form-input]",
    body: `<div class="ct-dlg-field">
        <label class="ct-dlg-label">${escapeHtml(label)}</label>
        <input class="ct-dlg-input" data-form-input placeholder="${escapeHtml(placeholder || "")}" value="${escapeHtml(initial)}" autocomplete="off">
        <div class="ct-dlg-err">${escapeHtml(validate.hint || "输入不合法")}</div>
      </div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-primary" data-submit>${escapeHtml(submitLabel)}</button>`,
  });
  const input = handle.el.querySelector("[data-form-input]");
  input.addEventListener("input", () => input.classList.remove("invalid"));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handle.el.querySelector("[data-submit]").click();
  });
  const submit = () => {
    const value = input.value.trim();
    if (!validate.check(value)) {
      input.classList.add("invalid");
      input.focus();
      return;
    }
    if (onSubmit(value, handle) !== false) handle.close();
  };
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-submit]").addEventListener("click", submit);
  return handle;
}

export function promptRenameField(ctx, resource, oldName) {
  formDialog({
    title: "重命名字段",
    label: "新字段名",
    placeholder: oldName,
    initial: oldName,
    submitLabel: "重命名",
    validate: { check: validFieldName, hint: "字段名须以大写字母开头，且不以 _ 结尾" },
    onSubmit: (value) => {
      if (value === oldName) return false;
      ctx.pushCommand({ type: "rename_field", payload: { owner: resource.resourceId, old: oldName, new: value } });
      if (ctx.state.selectedField === oldName) ctx.state.selectedField = value;
    },
  });
}

export function promptEnumValue(ctx, resource, values) {
  formDialog({
    title: "新增枚举值",
    label: "枚举值",
    placeholder: "如 Epic",
    submitLabel: "添加",
    validate: { check: (v) => v.length > 0, hint: "枚举值不能为空" },
    onSubmit: (value) => {
      ctx.pushCommand({ type: "set_enum_values", payload: { name: resource.resourceId, values: [...values, value] } });
    },
  });
}

/* ---- F2 类型选择器（可嵌套：F1 内与字段表独立入口共用） ---- */
export function openTypePicker(ctx, { role = "", onPick }) {
  const i18nOnly = role === "i18n";
  const named = i18nOnly
    ? []
    : (ctx.state.resources || []).filter((r) => r.kind === "record" || r.kind === "enum");
  const scalars = i18nOnly ? ["string"] : SCALARS;
  const handle = openDialog({
    title: "选择类型",
    variant: "sm",
    initialFocusSelector: "[data-type-search]",
    body: `${i18nOnly ? '<div class="ct-dlg-hint" style="margin-bottom:6px">I18N 角色仅支持 string 类型</div>' : ""}
      <input class="ct-dlg-input" data-type-search placeholder="搜索类型…" autocomplete="off">
      <div class="ct-dlg-list" data-type-list style="margin-top:10px"></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  const search = handle.el.querySelector("[data-type-search]");
  const list = handle.el.querySelector("[data-type-list]");
  function render(q) {
    q = (q || "").trim().toLowerCase();
    const scal = scalars.filter((t) => !q || t.includes(q));
    const nam = named.filter((r) => !q || (r.name || "").toLowerCase().includes(q));
    list.innerHTML =
      (scal.length ? `<div class="ct-dlg-sec">标量</div>` + scal.map((t) => `<button class="ct-dlg-row" data-type="${t}"><span class="ct-mono">${t}</span></button>`).join("") : "") +
      (nam.length ? `<div class="ct-dlg-sec">Enum / Record</div>` + nam.map((r) =>
        `<button class="ct-dlg-row" data-type="${escapeHtml(r.name)}"><span class="ct-mono">${escapeHtml(r.name)}</span><span class="ct-resource-kind">${KIND_LABEL[r.kind]}</span></button>`).join("") : "") +
      (!scal.length && !nam.length ? '<div class="ct-dlg-empty">无匹配</div>' : "");
  }
  render("");
  search.addEventListener("input", () => render(search.value));
  list.addEventListener("click", (e) => {
    const row = e.target.closest("[data-type]");
    if (!row) return;
    handle.close();
    onPick(row.dataset.type);
  });
}

/* ---- F1 添加字段（角色×约束互斥 + Code 固定名 + vector 修饰符） ---- */
export function openAddField(ctx, resource) {
  let typeSel = "int32";
  const hasCode = (resource.fields || []).some((f) => f.name === "Code");
  const isRefText = (t) => Boolean(t) && t.includes(".") && !t.startsWith("vector");
  const isRecordText = (t) => {
    const r = (ctx.state.resources || []).find((x) => x.name === t);
    return Boolean(r && r.kind === "record");
  };

  const handle = openDialog({
    title: "添加字段",
    variant: "std",
    initialFocusSelector: "[data-af-name]",
    body: `<div class="ct-dlg-field">
        <label class="ct-dlg-label">字段名</label>
        <input class="ct-dlg-input" data-af-name placeholder="如 DisplayName" autocomplete="off">
        <div class="ct-dlg-err">字段名须以大写字母开头，且不以 _ 结尾</div>
      </div>
      <div class="ct-dlg-field">
        <label class="ct-dlg-label">类型</label>
        <button class="ct-type-trigger" type="button" data-af-type><span class="ct-mono" data-af-type-txt>int32</span><span class="ct-caret">▾</span></button>
      </div>
      <div class="ct-opt-group">
        <div class="ct-opt-row"><span class="ct-opt-label">角色</span>
          <div class="ct-opt-chips">
            <label class="ct-chip"><input type="radio" name="af-role" value="" checked><span>无</span></label>
            <label class="ct-chip"><input type="radio" name="af-role" value="i18n"><span>I18N</span></label>
            <label class="ct-chip"><input type="radio" name="af-role" value="server"><span>Server-only</span></label>
          </div>
        </div>
        <div class="ct-opt-row"><span class="ct-opt-label">约束</span>
          <div class="ct-opt-chips">
            <label class="ct-chip"><input type="checkbox" data-af-code ${hasCode ? "disabled" : ""}><span>代号（Code）</span></label>
            <label class="ct-chip"><input type="checkbox" data-af-vec><span>vector</span></label>
          </div>
        </div>
        <div class="ct-opt-row" data-af-vec-row hidden><span class="ct-opt-label">形态</span>
          <div class="ct-seg">
            <label><input type="radio" name="af-flavor" data-af-flavor-var checked><span>变长</span></label>
            <label><input type="radio" name="af-flavor" data-af-flavor-fix><span>定长</span></label>
          </div>
        </div>
        ${hasCode ? '<div class="ct-opt-sub">该表已有代号字段 Code，一表至多一个</div>' : ""}
        <div class="ct-opt-sub" data-af-sep-note hidden>变长 · 分隔符工具内置（,）</div>
        <div class="ct-opt-sub" data-af-cols-row hidden>定长 · 固定展开列组　展开组数 <input class="ct-dlg-input" data-af-cols value="3"> 组</div>
        <div class="ct-dlg-msg" data-af-msg hidden></div>
      </div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-primary" data-af-add>添加字段</button>`,
  });

  const root = handle.el;
  const nameEl = root.querySelector("[data-af-name]");
  const codeEl = root.querySelector("[data-af-code]");
  const vecEl = root.querySelector("[data-af-vec]");
  const flavorVar = root.querySelector("[data-af-flavor-var]");
  const flavorFix = root.querySelector("[data-af-flavor-fix]");
  const vecRow = root.querySelector("[data-af-vec-row]");
  const colsRow = root.querySelector("[data-af-cols-row]");
  const colsEl = root.querySelector("[data-af-cols]");
  const sepNote = root.querySelector("[data-af-sep-note]");
  const typeEl = root.querySelector("[data-af-type]");
  const typeTxt = root.querySelector("[data-af-type-txt]");
  const roleEls = [...root.querySelectorAll('input[name="af-role"]')];
  const msgEl = root.querySelector("[data-af-msg]");
  const role = () => roleEls.find((r) => r.checked)?.value || "";

  const showMsg = (text) => { msgEl.hidden = !text; msgEl.textContent = text || ""; };
  const setFlavor = (fix) => { flavorFix.checked = fix; colsRow.hidden = !fix; sepNote.hidden = fix; };
  function syncControls() {
    const codeOn = codeEl.checked;
    nameEl.disabled = codeOn;
    typeEl.disabled = codeOn;
    roleEls.forEach((r) => { if (r.value === "i18n" || r.value === "server") r.disabled = codeOn; });
    vecEl.disabled = codeOn || role() === "i18n" || role() === "server" || isRefText(typeSel);
  }
  function syncVec() {
    const vecOn = vecEl.checked;
    vecRow.hidden = !vecOn;
    if (!vecOn) { colsRow.hidden = true; sepNote.hidden = true; return; }
    if (isRecordText(typeSel)) { flavorVar.disabled = true; flavorFix.disabled = false; setFlavor(true); }
    else { flavorVar.disabled = false; flavorFix.disabled = true; flavorVar.checked = true; setFlavor(false); }
  }
  function updateMsg() {
    if (codeEl.checked) { showMsg("Code 索引要求：非空 · 表内唯一 · 非 i18n string（程序引用键）"); return; }
    if (vecEl.checked && isRefText(typeSel)) { showMsg("ref 字段不支持 vector"); return; }
    if (vecEl.checked && isRecordText(typeSel)) { showMsg("vector<Record> 为定长（固定展开列组），需配置展开组数"); return; }
    if (isRefText(typeSel)) { showMsg("ref 外键值必须存在于引用表主键集（空值会被校验拦截）"); return; }
    showMsg("");
  }
  codeEl.addEventListener("change", () => {
    if (codeEl.checked) {
      roleEls.forEach((r) => { r.checked = r.value === ""; });
      nameEl.value = "Code";
      typeSel = "string";
      typeTxt.textContent = "string";
      vecEl.checked = false;
    } else {
      nameEl.value = "";
    }
    syncControls(); syncVec(); updateMsg();
  });
  vecEl.addEventListener("change", () => { syncControls(); syncVec(); updateMsg(); });
  flavorVar.addEventListener("change", () => { if (!flavorVar.disabled) { setFlavor(false); updateMsg(); } });
  flavorFix.addEventListener("change", () => { if (!flavorFix.disabled) { setFlavor(true); updateMsg(); } });
  roleEls.forEach((r) => r.addEventListener("change", () => { syncControls(); syncVec(); updateMsg(); }));
  nameEl.addEventListener("input", () => nameEl.classList.remove("invalid"));
  typeEl.addEventListener("click", () => {
    openTypePicker(ctx, {
      role: role(),
      onPick: (v) => {
        typeSel = v;
        typeTxt.textContent = v;
        if (isRefText(v) && vecEl.checked) vecEl.checked = false;
        syncControls(); syncVec(); updateMsg();
      },
    });
  });

  root.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  root.querySelector("[data-af-add]").addEventListener("click", async () => {
    const value = nameEl.value.trim();
    if (!validFieldName(value)) { nameEl.classList.add("invalid"); nameEl.focus(); return; }
    const currentRole = role();
    const vecOn = vecEl.checked;
    if (currentRole === "i18n" && (vecOn || typeSel !== "string")) { showMsg("I18N 角色仅支持 string 类型"); return; }
    if (value === "Code") {
      if (hasCode) { showMsg("该表已有代号字段 Code，一表至多一个"); return; }
      if (vecOn || typeSel !== "string" || currentRole !== "") { showMsg("代号字段 Code 必须为 string 且角色为「无」"); return; }
    }
    const fieldType = vecOn ? `vector<${typeSel}>` : typeSel;
    const field = { name: value, type: fieldType };
    if (currentRole === "i18n") field.i18n = true;
    if (currentRole === "server") field.server_only = true;
    if (vecOn && isRecordText(typeSel)) {
      const cols = parseInt(colsEl.value, 10);
      if (!Number.isFinite(cols) || cols < 1) { showMsg("展开组数须为正整数"); return; }
      field.excel_columns = cols;
    }
    // 提交前后端校验兜底（类型/角色边界），失败保持弹窗打开
    try {
      await api("/api/schema-workspace/validate", {
        method: "POST",
        body: JSON.stringify({ commands: [{ type: "add_field", payload: { owner: resource.resourceId, field } }] }),
      });
    } catch (e) {
      showMsg(e.message || "校验失败");
      return;
    }
    ctx.pushCommand({ type: "add_field", payload: { owner: resource.resourceId, field } });
    handle.close();
  });
}

/* ---- P5 变更计划（含删除弹窗「查看影响」预览模式） ---- */
export async function openChangePlan(ctx, extraCommand = null) {
  const preview = Boolean(extraCommand);
  const base = ctx.effectiveCommands();
  const commands = preview ? base.concat([extraCommand]) : base;
  let data;
  try {
    data = await api("/api/schema-workspace/change-plan", {
      method: "POST",
      body: JSON.stringify({ commands }),
    });
  } catch (e) {
    openDialog({
      title: "审查并应用", variant: "plan", initialFocusSelector: "[data-close]",
      body: `<div class="ct-error-inline">${escapeHtml(e.message)}</div>`,
      footer: `<button class="ct-btn ct-btn-ghost" data-close>关闭</button>`,
    });
    return null;
  }
  // blocked when plan generation failed: backend returns {plan:null, issues:[...]}
  // (key present, value null). Successful responses omit `plan`, so use strict ===,
  // never == null (which would treat an absent key as null and always block).
  const blocked = data.plan === null || Boolean(data.blocked);
  const riskLabel = RISK_LABEL[data.risk] || data.risk || (blocked ? "校验失败" : "");
  const impacts = (data.impacts || []).map((i) =>
    `<div class="ct-impact"><span class="ct-art">${escapeHtml(i.artifact)}</span><span class="ct-mono" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(i.table)}</span><span class="ct-act">${escapeHtml(i.action)}</span></div>`
  ).join("");
  const blockers = (data.issues || [])
    .filter((i) => i.kind === "blocker" || i.kind === "untracked")
    .map((i) => {
      const samples = i.samples && i.samples.length
        ? `，样例 ${escapeHtml(Array.isArray(i.samples) ? i.samples.join("、") : i.samples)}`
        : "";
      return `<div class="ct-blocker">⛔ ${escapeHtml(i.message)}${samples}${i.location ? ` <span class="ct-loc">${escapeHtml(i.location)}</span>` : ""}</div>`;
    })
    .join("");

  const handle = openDialog({
    title: "审查并应用",
    variant: "plan",
    initialFocusSelector: "[data-cancel]",
    body: `${preview ? `<div class="ct-blocker-list"><div class="ct-blocker info">预览：${escapeHtml(extraCommand.type === "delete_resource" ? "删除 " + extraCommand.payload.name : "")} 的影响（尚未加入草稿）——确认请在删除弹窗点击「删除」</div></div>` : ""}
      <div class="ct-risk-line"><span class="ct-badge ${blocked ? "ct-badge-warn" : "ct-badge-ok"}">● 风险：${escapeHtml(riskLabel)}</span></div>
      ${impacts ? `<div class="ct-impacts">${impacts}</div>` : ""}
      ${blockers ? `<div class="ct-blocker-list">${blockers}</div>` : ""}
      <div class="ct-dlg-hint">计划有效期 2 小时，过期需重新生成</div>`,
    footer: `<button class="ct-btn ct-btn-danger" data-discard ${preview || !commands.length ? "disabled" : ""}>放弃草稿</button>
      <button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-primary" data-apply ${blocked || preview ? "disabled" : ""}>应用变更</button>`,
  });

  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  if (!preview) {
    handle.el.querySelector("[data-discard]").addEventListener("click", () => {
      openDiscardDraft(ctx, { onDiscard: () => handle.close() });
    });
    handle.el.querySelector("[data-apply]").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const result = await ctx.applyCommands(commands);
        handle.close();
        window.dispatchEvent(new CustomEvent("ct:draft", { detail: { successText: "已应用：" + (result.names || "草稿变更") } }));
      } catch (err) {
        btn.disabled = false;
        const body = handle.el.querySelector(".ct-dialog-body");
        body.insertAdjacentHTML("afterbegin", `<div class="ct-error-inline">${escapeHtml(err.message)}</div>`);
      }
    });
  }
  return handle;
}

/* ---- P6 放弃草稿 ---- */
export function openDiscardDraft(ctx, opts = {}) {
  const handle = openDialog({
    title: "放弃草稿",
    variant: "sm",
    initialFocusSelector: "[data-cancel]",
    body: `<p style="margin:0;color:var(--ct-ink)">放弃 ${ctx.pendingCount()} 条未应用变更？此操作不可撤销。</p>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-danger-solid" data-confirm>放弃</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-confirm]").addEventListener("click", () => {
    ctx.clearDraftState();
    handle.close();
    if (opts.onDiscard) opts.onDiscard();
  });
}

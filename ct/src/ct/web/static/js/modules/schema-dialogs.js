/* schema-dialogs: every Schema editing surface that is a dialog, riding the
   shared core/dialog stack (Esc 逐层退栈/焦点陷阱/还焦 are the stack's job).
   D1 删除资源 / D2 删除字段 / 改名 / 枚举新增值 /
   F1 添加字段(+F2 类型选择器) / 净差异摘要 / 放弃草稿.
   ctx (provided by schema.js) carries data + command flow, this file owns UI:
   - ctx.pushCommand(cmd)          append a draft command
   - ctx.effectiveCommands()       pending commands (slice to cursor)
   - ctx.pendingCount()            pending command count
   - ctx.changedResources()        net changed resource count
   - ctx.clearDraftState()         drop the whole draft (persist + re-render)
   - ctx.saveChanges()             POST /api/schema-workspace/save
   - ctx.refreshAll()              re-render list/editor/inspector
   - ctx.state                     schema page state (resources, reverseRefs…) */

import { openDialog } from "../core/dialog.js";
import { api } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";

const NAME_RE = /^[A-Z][A-Za-z0-9_]*$/;
// 后端 EnumItem 用 str.isidentifier() 校验；这里做 ASCII 近似（允许小写开头与 _）。
const ENUM_VALUE_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const KIND_LABEL = { table: "Table", record: "Record", enum: "Enum" };
// shared kind inference: named resources carry an explicit kind, otherwise
// tables/records have a `fields` list and enums do not.
export function resourceKind(resource) {
  return resource.kind || (resource.fields ? "table" : "enum");
}
const SCALARS = ["int32", "int64", "float", "double", "bool", "string"];
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

/* ---- D1 删除资源 ---- */
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
      <p style="margin:0;color:var(--ct-ink-2);font-size:12.5px;line-height:1.7">将移除：${fieldCount} 个字段${resource.excel_file ? " · " + escapeHtml(resource.excel_file) : ""}<br>变更先进入草稿，可在底部撤销；保存时只删除该资源的 YAML，Excel 与既有产物保留。</p>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-danger-solid" data-confirm ${blocked ? "disabled" : ""}>删除</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-confirm]").addEventListener("click", () => {
    ctx.pushCommand({ type: "delete_resource", payload: { name: resource.resourceId } });
    ctx.state.selection = null;
    handle.close();
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

export function openFieldCommentEditor(ctx, resource, field) {
  const handle = openDialog({
    title: `编辑字段注释 · ${field.name}`,
    variant: "sm",
    initialFocusSelector: "[data-comment-input]",
    body: `<div class="ct-dlg-field">
        <label class="ct-dlg-label" for="field-comment-input">Excel 表头注释</label>
        <textarea class="ct-dlg-input ct-comment-input" id="field-comment-input" data-comment-input rows="4" placeholder="填写策划录入提示">${escapeHtml(field.comment || "")}</textarea>
      </div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button><button class="ct-btn ct-btn-primary" data-submit>保存注释</button>`,
  });
  const input = handle.el.querySelector("[data-comment-input]");
  const submit = () => {
    ctx.pushCommand({ type: "set_property", payload: { owner: resource.resourceId, name: field.name, property: "comment", value: input.value.trim() } });
    handle.close();
  };
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-submit]").addEventListener("click", submit);
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit();
  });
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
  const items = values.map((v) => typeof v === "string" ? { name: v, comment: "" } : v);
  const handle = openDialog({
    title: "新增值",
    variant: "sm",
    initialFocusSelector: "[data-aev-name]",
    body: `<div class="ct-dlg-field">
        <label class="ct-dlg-label">值名称</label>
        <input class="ct-dlg-input" data-aev-name placeholder="如 Epic" autocomplete="off">
        <div class="ct-dlg-err">标识符：字母/下划线开头，可含数字</div>
      </div>
      <div class="ct-dlg-field">
        <label class="ct-dlg-label">注释</label>
        <textarea class="ct-dlg-input ct-comment-input" data-aev-comment rows="3" placeholder="可选"></textarea>
      </div>
      <div class="ct-dlg-msg" data-aev-msg hidden></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-primary" data-submit>添加</button>`,
  });
  const nameEl = handle.el.querySelector("[data-aev-name]");
  const commentEl = handle.el.querySelector("[data-aev-comment]");
  const msgEl = handle.el.querySelector("[data-aev-msg]");
  const showMsg = (text) => { msgEl.hidden = !text; msgEl.textContent = text || ""; };
  let refTarget = "";
  let refType = "int32";
  const isRefMode = () => Boolean(refEl && refEl.checked);
  nameEl.addEventListener("input", () => { nameEl.classList.remove("invalid"); showMsg(""); });
  nameEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handle.el.querySelector("[data-submit]").click();
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-submit]").addEventListener("click", async () => {
    const name = nameEl.value.trim();
    if (!ENUM_VALUE_RE.test(name)) {
      nameEl.classList.add("invalid");
      nameEl.focus();
      showMsg("值名称须为标识符（字母/下划线开头，可含数字）");
      return;
    }
    if (items.some((item) => item.name === name)) {
      nameEl.classList.add("invalid");
      showMsg(`值 '${name}' 已存在`);
      return;
    }
    const next = [...items, { name, comment: commentEl.value.trim() }];
    // 提交前服务端预检（标识符/重复/256 上限）——带上当前草稿前缀，
    // 失败保持弹窗打开
    try {
      const result = await ctx.precheck({
        type: "set_enum_values",
        payload: { name: resource.resourceId, values: next },
      });
      if (result.stale) { showMsg("草稿已变化，请重试"); return; }
      const first = (result.issues || [])[0];
      if (first) {
        showMsg(first.location ? `${first.message}（${first.location}）` : first.message);
        return;
      }
    } catch (e) {
      showMsg(e.message || "校验失败");
      return;
    }
    ctx.pushCommand({ type: "set_enum_values", payload: { name: resource.resourceId, values: next } });
    handle.close();
  });
}

/* ---- 重命名枚举值（与重命名字段同为表单弹窗） ---- */
export function promptRenameEnumValue(ctx, resource, oldName, ordinal) {
  formDialog({
    title: "重命名值",
    label: "新值名称",
    placeholder: oldName,
    initial: oldName,
    submitLabel: "重命名",
    validate: {
      check: (v) =>
        ENUM_VALUE_RE.test(v) &&
        !resource.values.some((x, i) => i !== ordinal && (typeof x === "string" ? x : x.name) === v),
      hint: "标识符（字母/下划线开头），且不与现有值重复",
    },
    onSubmit: (value) => {
      if (value === oldName) return false;
      ctx.pushCommand({ type: "rename_enum_item", payload: { name: resource.resourceId, oldName, newName: value, originalOrdinal: ordinal } });
    },
  });
}

/* ---- 编辑枚举值注释（与字段注释同为 textarea 弹窗） ---- */
export function openEnumCommentEditor(ctx, resource, item, ordinal) {
  const handle = openDialog({
    title: `编辑值注释 · ${item.name}`,
    variant: "sm",
    initialFocusSelector: "[data-enum-comment-input]",
    body: `<div class="ct-dlg-field">
        <label class="ct-dlg-label" for="enum-comment-input">注释</label>
        <textarea class="ct-dlg-input ct-comment-input" id="enum-comment-input" data-enum-comment-input rows="4" placeholder="填写该枚举值含义">${escapeHtml(item.comment || "")}</textarea>
      </div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button><button class="ct-btn ct-btn-primary" data-submit>保存注释</button>`,
  });
  const input = handle.el.querySelector("[data-enum-comment-input]");
  const submit = () => {
    const values = resource.values.map((v) => typeof v === "string" ? { name: v, comment: "" } : v);
    values[ordinal] = { ...values[ordinal], comment: input.value.trim() };
    ctx.pushCommand({ type: "set_enum_values", payload: { name: resource.resourceId, values } });
    handle.close();
  };
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  handle.el.querySelector("[data-submit]").addEventListener("click", submit);
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit();
  });
  return handle;
}

/* ---- F2 类型选择器（可嵌套：F1 内与字段表独立入口共用） ---- */
export function openTypePicker(ctx, { role = "", onPick }) {
  const i18nOnly = role === "i18n";
  const pool = ctx.candidatePool ? ctx.candidatePool() : (ctx.state.resources || []);
  const named = i18nOnly
    ? []
    : pool.filter((r) => r.kind === "record" || r.kind === "enum");
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

/* 引用目标（Table.Field）：Table 只能作为 ref 目标出现，不进类型列表。 */
export function openRefPicker(ctx, { onPick }) {
  const pool = ctx.candidatePool ? ctx.candidatePool() : (ctx.state.resources || []);
  const rows = pool
    .filter((resource) => resourceKind(resource) === "table")
    .flatMap((table) =>
      (table.fields || [])
        .filter((field) => !field.server_only)
        .map((field) => ({
          ref: `${table.name || table.table}.${field.name}`,
          table: table.name || table.table,
          field,
        }))
    );
  const handle = openDialog({
    title: "选择引用目标",
    variant: "sm",
    initialFocusSelector: "[data-ref-search]",
    body: `<input class="ct-dlg-input" data-ref-search placeholder="搜索 Table.Field…" autocomplete="off">
      <div class="ct-dlg-list" data-ref-list style="margin-top:10px"></div>
      <div class="ct-dlg-hint">引用值必须存在于目标表主键/字段集合；不支持 vector 引用。</div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>`,
  });
  handle.el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  const search = handle.el.querySelector("[data-ref-search]");
  const list = handle.el.querySelector("[data-ref-list]");
  function render(query) {
    const q = (query || "").trim().toLowerCase();
    const matches = rows.filter((row) => !q || row.ref.toLowerCase().includes(q));
    list.innerHTML = matches.length
      ? matches
          .map(
            (row) =>
              `<button class="ct-dlg-row" data-ref="${escapeHtml(row.ref)}"><span class="ct-mono">${escapeHtml(row.ref)}</span><span class="ct-resource-kind">${escapeHtml(String(row.field.type || ""))}</span></button>`
          )
          .join("")
      : '<div class="ct-dlg-empty">没有可引用的表</div>';
  }
  render("");
  search.addEventListener("input", () => render(search.value));
  list.addEventListener("click", (event) => {
    const row = event.target.closest("[data-ref]");
    if (!row) return;
    const picked = rows.find((item) => item.ref === row.dataset.ref);
    handle.close();
    onPick(row.dataset.ref, String(picked.field.type || "int32"));
  });
  return handle;
}

/* Edit an existing field's base type, vector shape and Excel input layout. */
export function openFieldTypeEditor(ctx, field, onApply) {
  const raw = field.type || field.type_expr || "int32";
  const match = String(raw).match(/^vector\s*<\s*(.+)\s*>$/);
  let typeSel = match ? match[1] : String(raw);
  let vector = Boolean(match);
  let fixed = field.excel_columns != null;
  const isRecord = (name) => {
    const resource = (ctx.state.resources || []).find((item) => item.name === name);
    return Boolean(resource && resource.kind === "record");
  };
  const handle = openDialog({
    title: "编辑字段类型",
    variant: "std",
    initialFocusSelector: "[data-fe-type]",
    body: `<div class="ct-field-type-editor"><section class="ct-field-type-panel ct-type-panel"><div class="ct-field-type-heading"><span class="ct-field-type-kicker">字段类型</span><span class="ct-field-type-help">选择基础类型，再决定是否使用 vector</span></div><div class="ct-dlg-field"><label class="ct-dlg-label">基础类型</label>
        <button class="ct-type-trigger" type="button" data-fe-type><span class="ct-mono" data-fe-type-txt>${escapeHtml(typeSel)}</span><span class="ct-caret">▾</span></button></div>
      </section><section class="ct-field-type-panel ct-input-panel"><div class="ct-field-type-heading"><span class="ct-field-type-kicker">Excel 输入形态</span><span class="ct-field-type-help">仅影响表格录入方式，不改变运行时类型</span></div><div class="ct-opt-row"><span class="ct-opt-label">vector</span><label class="ct-chip"><input type="checkbox" data-fe-vector ${vector ? "checked" : ""}><span>数组</span></label></div>
      <div class="ct-opt-row ct-shape-row" data-fe-shape hidden><span class="ct-opt-label">长度</span><div class="ct-seg">
        <label><input type="radio" name="fe-flavor" data-fe-var><span>变长</span></label>
        <label><input type="radio" name="fe-flavor" data-fe-fix><span>定长</span></label></div><span class="ct-opt-sub ct-shape-detail" data-fe-cols hidden>最大槽位数 <button class="ct-stepper-btn" type="button" data-fe-cols-dec aria-label="减少槽位">−</button><input class="ct-dlg-input ct-stepper-input" data-fe-cols-input type="text" inputmode="numeric" pattern="[0-9]*" autocomplete="off" value="${escapeHtml(field.excel_columns ?? 3)}"><button class="ct-stepper-btn" type="button" data-fe-cols-inc aria-label="增加槽位">＋</button> 个</span><span class="ct-opt-sub ct-shape-detail" data-fe-note>变长 · 使用 [1,2,3] 文法（字符串使用 JSON 双引号）</span></div>
      <div class="ct-dlg-msg" data-fe-msg hidden></div></section></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button><button class="ct-btn ct-btn-primary" data-fe-apply>应用</button>`,
  });
  const root = handle.el;
  const typeBtn = root.querySelector("[data-fe-type]");
  const typeTxt = root.querySelector("[data-fe-type-txt]");
  const vectorEl = root.querySelector("[data-fe-vector]");
  const shape = root.querySelector("[data-fe-shape]");
  const varEl = root.querySelector("[data-fe-var]");
  const fixEl = root.querySelector("[data-fe-fix]");
  const cols = root.querySelector("[data-fe-cols]");
  const colsInput = root.querySelector("[data-fe-cols-input]");
  const colsDec = root.querySelector("[data-fe-cols-dec]");
  const colsInc = root.querySelector("[data-fe-cols-inc]");
  const note = root.querySelector("[data-fe-note]");
  const msg = root.querySelector("[data-fe-msg]");
  const showMsg = (text) => { msg.hidden = !text; msg.textContent = text || ""; };
  const stepColumns = (delta) => {
    const current = Number.parseInt(colsInput.value, 10);
    colsInput.value = String(Math.max(1, (Number.isInteger(current) ? current : 1) + delta));
    showMsg("");
  };
  const sync = () => {
    vector = vectorEl.checked;
    shape.hidden = !vector;
    if (!vector) {
      cols.hidden = true;
      note.hidden = true;
      return;
    }
    if (isRecord(typeSel)) {
      fixed = true;
      varEl.disabled = true;
      fixEl.disabled = false;
    } else {
      varEl.disabled = false;
      fixEl.disabled = false;
    }
    varEl.checked = !fixed;
    fixEl.checked = fixed;
    cols.hidden = !fixed;
    note.hidden = fixed;
  };
  typeBtn.addEventListener("click", () => openTypePicker(ctx, {
    onPick: (value) => { typeSel = value; typeTxt.textContent = value; sync(); },
  }));
  vectorEl.addEventListener("change", sync);
  varEl.addEventListener("change", () => { fixed = false; sync(); });
  fixEl.addEventListener("change", () => { fixed = true; sync(); });
  colsDec.addEventListener("click", () => stepColumns(-1));
  colsInc.addEventListener("click", () => stepColumns(1));
  colsInput.addEventListener("input", () => {
    colsInput.value = colsInput.value.replace(/\D/g, "");
    if (colsInput.value === "0") colsInput.value = "1";
    showMsg("");
  });
  root.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  root.querySelector("[data-fe-apply]").addEventListener("click", () => {
    if (vector && fixed) {
      const count = Number.parseInt(colsInput.value, 10);
      if (!Number.isInteger(count) || count < 1) { showMsg("固定列数不能小于 1"); return; }
      onApply({ type_text: `vector<${typeSel}>`, excel_columns: count });
    } else {
      onApply({ type_text: vector ? `vector<${typeSel}>` : typeSel, excel_columns: null });
    }
    handle.close();
  });
  sync();
}

/* ---- F1 添加字段（角色×约束互斥 + Code 固定名 + vector 修饰符） ---- */
export function openAddField(ctx, resource) {
  let typeSel = "int32";
  let fixedVector = false;
  const hasCode = (resource.fields || []).some((f) => f.name === "Code");
  const isRecord = resource.kind === "record";
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
        <div class="ct-opt-row" data-af-role-row ${isRecord ? "hidden" : ""}><span class="ct-opt-label">角色</span>
          <div class="ct-opt-chips">
            <label class="ct-chip"><input type="radio" name="af-role" value="" checked><span>无</span></label>
            <label class="ct-chip"><input type="radio" name="af-role" value="i18n" ${isRecord ? "disabled" : ""}><span>I18N</span></label>
            <label class="ct-chip"><input type="radio" name="af-role" value="server" ${isRecord ? "disabled" : ""}><span>Server-only</span></label>
          </div>
        </div>
        <div class="ct-opt-row"><span class="ct-opt-label">约束</span>
          <div class="ct-opt-chips">
            <label class="ct-chip"><input type="checkbox" data-af-code ${hasCode || isRecord ? "disabled" : ""}><span>代号（Code）</span></label>
            <label class="ct-chip"><input type="checkbox" data-af-vec><span>vector</span></label>
            <label class="ct-chip"><input type="checkbox" data-af-ref><span>引用</span></label>
          </div>
        </div>
        <div class="ct-opt-row" data-af-vec-row hidden><span class="ct-opt-label">形态</span>
          <div class="ct-seg">
            <label><input type="radio" name="af-flavor" data-af-flavor-var checked><span>变长</span></label>
            <label><input type="radio" name="af-flavor" data-af-flavor-fix><span>定长</span></label>
          </div>
        </div>
        ${isRecord ? '<div class="ct-opt-sub">Record 不支持 I18N / Server-only / 代号（Code），仅支持普通字段与 vector</div>' : ""}
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
  const refEl = root.querySelector("[data-af-ref]");
  const roleEls = [...root.querySelectorAll('input[name="af-role"]')];
  const msgEl = root.querySelector("[data-af-msg]");
  const role = () => roleEls.find((r) => r.checked)?.value || "";

  const showMsg = (text) => { msgEl.hidden = !text; msgEl.textContent = text || ""; };
  let refTarget = "";
  let refType = "int32";
  const isRefMode = () => Boolean(refEl && refEl.checked);
  const setFlavor = (fix) => { flavorFix.checked = fix; colsRow.hidden = !fix; sepNote.hidden = fix; };
  function syncControls() {
    const codeOn = codeEl.checked;
    nameEl.disabled = codeOn;
    typeEl.disabled = codeOn || isRefMode();
    if (refEl) refEl.disabled = codeOn;
    roleEls.forEach((r) => {
      if (r.value === "i18n" || r.value === "server") r.disabled = codeOn || isRecord;
    });
    vecEl.disabled = codeOn || role() === "i18n" || role() === "server" || isRefText(typeSel);
  }
  function syncVec() {
    const vecOn = vecEl.checked;
    vecRow.hidden = !vecOn;
    if (!vecOn) { colsRow.hidden = true; sepNote.hidden = true; return; }
    if (isRecordText(typeSel)) {
      flavorVar.disabled = true;
      flavorFix.disabled = false;
      fixedVector = true;
    } else {
      flavorVar.disabled = false;
      flavorFix.disabled = false;
    }
    setFlavor(fixedVector);
  }
  function updateMsg() {
    if (isRefMode()) { showMsg(refTarget ? `引用 ${refTarget}（类型 ${refType}）` : "请选择引用目标 Table.Field"); return; }
    if (codeEl.checked) { showMsg("Code 索引要求：非空 · 表内唯一 · 非 i18n string（程序引用键）"); return; }
    if (vecEl.checked && isRefText(typeSel)) { showMsg("ref 字段不支持 vector"); return; }
    if (vecEl.checked && fixedVector) { showMsg("定长 vector 使用固定展开列数，需配置展开组数"); return; }
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
  flavorVar.addEventListener("change", () => { if (!flavorVar.disabled) { fixedVector = false; setFlavor(false); updateMsg(); } });
  flavorFix.addEventListener("change", () => { if (!flavorFix.disabled) { fixedVector = true; setFlavor(true); updateMsg(); } });
  roleEls.forEach((r) => r.addEventListener("change", () => { syncControls(); syncVec(); updateMsg(); }));
  nameEl.addEventListener("input", () => nameEl.classList.remove("invalid"));
  if (refEl) {
    refEl.addEventListener("change", () => {
      if (refEl.checked) {
        vecEl.checked = false;
        vecEl.disabled = true;
        openRefPicker(ctx, {
          onPick: (ref, typeText) => {
            refTarget = ref;
            refType = typeText || "int32";
            typeTxt.textContent = ref;
            syncControls();
            updateMsg();
          },
        });
      } else {
        refTarget = "";
        vecEl.disabled = false;
        syncControls();
        updateMsg();
      }
    });
  }
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
      if (isRecord) { showMsg("Record 不支持代号字段 Code（表级概念）"); return; }
      if (hasCode) { showMsg("该表已有代号字段 Code，一表至多一个"); return; }
      if (vecOn || typeSel !== "string" || currentRole !== "") { showMsg("代号字段 Code 必须为 string 且角色为「无」"); return; }
    }
    const fieldType = isRefMode() ? refType : (vecOn ? `vector<${typeSel}>` : typeSel);
    const field = { name: value, type: fieldType };
    if (isRefMode()) {
      if (!refTarget) { showMsg("请选择引用目标 Table.Field"); return; }
      field.ref = refTarget;
    }
    if (currentRole === "i18n") field.i18n = true;
    if (currentRole === "server") field.server_only = true;
    if (vecOn && fixedVector) {
      const cols = parseInt(colsEl.value, 10);
      if (!Number.isFinite(cols) || cols < 1) { showMsg("展开组数须为正整数"); return; }
      field.excel_columns = cols;
    }
    // 提交前服务端预检（类型/角色/引用边界）：带上当前草稿前缀，因此
    // 可以直接引用同一草稿里刚创建的类型；失败保持弹窗打开
    try {
      const result = await ctx.precheck({
        type: "add_field",
        payload: { owner: resource.resourceId, field },
      });
      if (result.stale) { showMsg("草稿已变化，请重试"); return; }
      const first = (result.issues || [])[0];
      if (first) {
        showMsg(first.location ? `${first.message}（${first.location}）` : first.message);
        return;
      }
    } catch (e) {
      showMsg(e.message || "校验失败");
      return;
    }
    ctx.pushCommand({ type: "add_field", payload: { owner: resource.resourceId, field } });
    handle.close();
  });
}

/* ---- 新增 Schema：统一三类资源的最小合法创建表单 ---- */
const CREATE_HINTS = {
  table: "Table 自动带固定 Id: int32 主键；保存后仍可在编辑器里继续加字段与查询索引。",
  record: "Record 至少一个字段；需要 vector<Record> 时先选类型，保存前预检会要求 excel_columns。",
  enum: "Enum 至少一个具名项，ordinal 按输入顺序从 0 派生。",
};

export function openCreateResource(ctx, { kind = "", onCreated = null } = {}) {
  let selectedKind = ["table", "record", "enum"].includes(kind) ? kind : "table";
  let firstType = "int32";
  let firstRef = "";
  let submitting = false;

  const handle = openDialog({
    title: "新增 Schema",
    variant: "sm",
    initialFocusSelector: "[data-cr-name]",
    body: `<div class="ct-dlg-field">
        <label class="ct-dlg-label">类别</label>
        <div class="ct-chip-row" data-cr-kinds>${["table", "record", "enum"]
          .map((k) => `<button type="button" class="ct-chip${k === selectedKind ? " active" : ""}" data-cr-kind="${k}">${KIND_LABEL[k]}</button>`)
          .join("")}</div>
      </div>
      <div class="ct-dlg-field">
        <label class="ct-dlg-label">名称</label>
        <input class="ct-dlg-input" data-cr-name placeholder="Item" autocomplete="off">
      </div>
      <div class="ct-dlg-field">
        <label class="ct-dlg-label">注释</label>
        <input class="ct-dlg-input" data-cr-comment placeholder="可选" autocomplete="off">
      </div>
      <div class="ct-dlg-field" data-cr-field>
        <label class="ct-dlg-label">首个字段</label>
        <input class="ct-dlg-input" data-cr-field-name placeholder="Min" autocomplete="off">
        <button type="button" class="ct-btn ct-btn-ghost ct-btn-sm" data-cr-field-type style="margin-top:6px">类型：<span class="ct-mono" data-cr-field-type-text>${firstType}</span></button>
        <button type="button" class="ct-btn ct-btn-ghost ct-btn-sm" data-cr-ref style="margin-top:6px">引用…</button>
      </div>
      <div class="ct-dlg-field" data-cr-item hidden>
        <label class="ct-dlg-label">首个枚举项</label>
        <input class="ct-dlg-input" data-cr-item-name placeholder="Common" autocomplete="off">
        <input class="ct-dlg-input" data-cr-item-comment placeholder="注释（可选）" autocomplete="off" style="margin-top:6px">
      </div>
      <div class="ct-dlg-hint" data-cr-hint></div>
      <div class="ct-dlg-err" data-cr-err></div>`,
    footer: `<button class="ct-btn ct-btn-ghost" data-cancel>取消</button>
      <button class="ct-btn ct-btn-primary" data-submit>创建</button>`,
  });

  const el = handle.el;
  const nameInput = el.querySelector("[data-cr-name]");
  const commentInput = el.querySelector("[data-cr-comment]");
  const fieldRow = el.querySelector("[data-cr-field]");
  const fieldNameInput = el.querySelector("[data-cr-field-name]");
  const fieldTypeText = el.querySelector("[data-cr-field-type-text]");
  const itemRow = el.querySelector("[data-cr-item]");
  const itemNameInput = el.querySelector("[data-cr-item-name]");
  const itemCommentInput = el.querySelector("[data-cr-item-comment]");
  const hint = el.querySelector("[data-cr-hint]");
  const errorBox = el.querySelector("[data-cr-err]");
  const submit = el.querySelector("[data-submit]");

  function showError(message) {
    errorBox.textContent = message || "";
    errorBox.classList.toggle("show", Boolean(message));
  }

  function syncKind() {
    el.querySelectorAll("[data-cr-kind]").forEach((chip) => {
      chip.classList.toggle("active", chip.dataset.crKind === selectedKind);
    });
    fieldRow.hidden = selectedKind === "enum";
    itemRow.hidden = selectedKind !== "enum";
    hint.textContent = CREATE_HINTS[selectedKind];
    if (selectedKind === "record") nameInput.placeholder = "DropReward";
    else if (selectedKind === "enum") nameInput.placeholder = "ItemRarity";
    else nameInput.placeholder = "Item";
    showError("");
  }

  el.querySelectorAll("[data-cr-kind]").forEach((chip) => {
    chip.addEventListener("click", () => {
      selectedKind = chip.dataset.crKind;
      syncKind();
    });
  });
  el.querySelector("[data-cr-field-type]").addEventListener("click", () => {
    openTypePicker(ctx, {
      onPick: (type) => {
        firstRef = "";
        firstType = type;
        fieldTypeText.textContent = type;
      },
    });
  });
  el.querySelector("[data-cr-ref]").addEventListener("click", () => {
    openRefPicker(ctx, {
      onPick: (ref, typeText) => {
        firstRef = ref;
        firstType = typeText || "int32";
        fieldTypeText.textContent = ref;
      },
    });
  });
  syncKind();

  function buildCommand() {
    const name = nameInput.value.trim();
    if (!validFieldName(name)) {
      return { error: "名称需以大写字母开头，只含字母/数字/下划线，且不以 _ 结尾" };
    }
    const pool = ctx.candidatePool ? ctx.candidatePool() : (ctx.state.resources || []);
    if (pool.some((r) => (r.name || r.table || r.resourceId) === name)) {
      return { error: `名称 ${name} 已被占用（不区分类别）` };
    }
    const comment = commentInput.value.trim();
    if (selectedKind === "table") {
      const resource = { table: name, primary: "Id", fields: [{ name: "Id", type: "int32" }] };
      if (comment) resource.comment = comment;
      return { command: { type: "add_resource", payload: { kind: "table", resource } } };
    }
    if (selectedKind === "record") {
      const fieldName = fieldNameInput.value.trim();
      if (!validFieldName(fieldName)) {
        return { error: "首个字段名需以大写字母开头，只含字母/数字/下划线，且不以 _ 结尾" };
      }
      const firstField = { name: fieldName, type: firstType };
      if (firstRef) firstField.ref = firstRef;
      const resource = { kind: "record", name, fields: [firstField] };
      if (comment) resource.comment = comment;
      return { command: { type: "add_resource", payload: { kind: "record", resource } } };
    }
    const item = itemNameInput.value.trim();
    if (!ENUM_VALUE_RE.test(item)) {
      return { error: "首个枚举项名需为合法标识符" };
    }
    const resource = {
      kind: "enum",
      name,
      values: [{ name: item, comment: itemCommentInput.value.trim() }],
    };
    if (comment) resource.comment = comment;
    return { command: { type: "add_resource", payload: { kind: "enum", resource } } };
  }

  el.querySelector("[data-cancel]").addEventListener("click", () => handle.close());
  submit.addEventListener("click", async () => {
    if (submitting) return;
    const built = buildCommand();
    if (built.error) {
      showError(built.error);
      return;
    }
    submitting = true;
    submit.disabled = true;
    submit.textContent = "创建中…";
    try {
      const result = await ctx.precheck(built.command);
      if (result.stale) {
        showError("草稿已变化，请重新确认后提交");
        return;
      }
      const issue = (result.issues || [])[0];
      if (issue) {
        showError(issue.location ? `${issue.message}（${issue.location}）` : issue.message);
        return;
      }
      const name = built.command.payload.resource.name
        || built.command.payload.resource.table;
      ctx.pushCommand(built.command);
      handle.close();
      if (onCreated) onCreated(name, selectedKind);
    } catch (e) {
      showError(e.message || "预检失败");
    } finally {
      submitting = false;
      if (el.isConnected) {
        submit.disabled = false;
        submit.textContent = "创建";
      }
    }
  });
  return handle;
}

/* ---- 净差异摘要（服务器权威计算，不承诺产物重建） ---- */
const CHANGE_LABEL = { added: "新增", removed: "删除", modified: "修改", renamed: "重命名" };

export function openDraftSummary(ctx) {
  const diff = ctx.state.netDiff || { resources: [], changedResources: 0, isNoOp: true };
  const rows = (diff.resources || []).map((item) => {
    const fields = (item.fields || []).map((field) => {
      const label = CHANGE_LABEL[field.change] || field.change;
      const name = field.oldName && field.oldName !== field.name
        ? `${field.oldName} → ${field.name}`
        : field.name;
      const details = field.details && field.details.length ? ` · ${field.details.join("、")}` : "";
      return `<div class="ct-impact"><span class="ct-art">${escapeHtml(KIND_LABEL[item.kind] || item.kind)}</span><span class="ct-mono" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(name)}</span><span class="ct-act">${escapeHtml(label + details)}</span></div>`;
    }).join("");
    const head = item.oldName && item.oldName !== item.name
      ? `${item.oldName} → ${item.name}`
      : item.name;
    return `<div class="ct-dlg-field"><label class="ct-dlg-label">${escapeHtml(CHANGE_LABEL[item.change] || item.change)} ${escapeHtml(head)}</label>${fields || '<div class="ct-hint">资源结构或属性变化</div>'}</div>`;
  }).join("");
  const body = `
    <p style="margin:0 0 10px;color:var(--ct-ink-2);font-size:12.5px;line-height:1.7">原始结构到最终候选的净差异：<b>${diff.changedResources || 0} 个资源</b>有未保存修改。保存只写这些 YAML，不改 Excel、模板 manifest、翻译或导出产物。</p>
    ${rows || '<div class="ct-hint">没有未保存修改。</div>'}`;
  const handle = openDialog({
    title: "未保存修改",
    variant: "std",
    initialFocusSelector: "[data-close]",
    body,
    footer: `<button class="ct-btn ct-btn-ghost" data-close>关闭</button>`,
  });
  return handle;
}

/* ---- 放弃草稿 ---- */
export function openDiscardDraft(ctx, opts = {}) {
  const handle = openDialog({
    title: "放弃草稿",
    variant: "sm",
    initialFocusSelector: "[data-cancel]",
    body: `<p style="margin:0;color:var(--ct-ink)">放弃 ${ctx.changedResources()} 个资源的未保存修改？此操作不可撤销。</p>`
      + (ctx.pendingCount() && !ctx.changedResources()
        ? `<p class="ct-hint" style="margin:8px 0 0">当前没有净变化，放弃只会清除 ${ctx.pendingCount()} 步编辑历史。</p>`
        : ""),
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

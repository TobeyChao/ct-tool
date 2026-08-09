/* ct 配表工具面板：Vue 3 无构建单页应用，对接 /api/* JSON 接口 */

function serializeFields(fields) {
  const out = [];
  for (const f of fields) {
    let s = "- name: " + f.name + "\n  type: " + f.type;
    if (f.i18n) s += "\n  i18n: true";
    if (f.server_only) s += "\n  server_only: true";
    if (f.ref) s += "\n  ref: " + f.ref;
    if (f.type === "enum" && f.values) s += "\n  values: [" + f.values.join(", ") + "]";
    if (f.type === "struct" && f.fields) {
      s += "\n  fields:";
      for (const line of serializeFields(f.fields).split("\n")) s += "\n    " + line;
    }
    if (f.type === "array") {
      s += "\n  element: " + f.element;
      if (f.separator && f.separator !== ",") s += '\n  separator: "' + f.separator + '"';
      if (f.element_values) s += "\n  element_values: [" + f.element_values.join(", ") + "]";
    }
    out.push(s);
  }
  return out.join("\n");
}

Vue.createApp({
  data() {
    return {
      tab: "export",
      ws: null,
      workspaceError: "",
      statusPill: { text: "", warn: false },
      errorBanner: null,
      forced: false,

      exportState: { status: "idle", steps: [], step_index: -1, step_name: "", message: "", errors: [], tables_exported: 0, elapsed: 0 },
      sessionRun: false,

      i18nTables: [],
      i18nCurrentTable: "",
      i18nLang: "",
      i18nStatusFilter: "all",
      i18nEntries: [],
      i18nBusy: false,
      progressReport: {},
      progressModal: false,
      progressView: "lang",
      pickTableModal: false,
      compactModal: false,
      compactPreview: null,
      editingKey: null,
      editDrafts: {},

      schemas: [],
      schemaSearch: "",
      schemaStatusFilter: "all",
      schemaDetail: null,
      detailModal: false,
      createModal: false,
      editModal: false,
      editOrigin: "",
      deleteModal: false,
      deleteTarget: "",
      form: { name: "", pk: "Id", fieldsYaml: "" },

      logs: [],
      logModule: "all",
      followLatest: true,
      history: [],
    };
  },

  computed: {
    exportRunning() {
      return this.exportState.status === "running";
    },
    exportDone() {
      return this.exportState.status === "done";
    },
    exportError() {
      return this.exportState.status === "error";
    },
    exportCancelled() {
      return this.exportState.status === "cancelled";
    },
    lastExport() {
      return this.history.length ? this.history[this.history.length - 1] : null;
    },
    stepCells() {
      return this.exportState.steps;
    },
    stepCellClass() {
      return (idx) => {
        const s = this.exportState;
        if (s.status === "cancelled") {
          return idx < s.step_index ? "done" : "";
        }
        if (s.status === "error") {
          if (s.step_index === idx) return "error";
          return idx < s.step_index ? "done" : "";
        }
        if (idx < s.step_index) return "done";
        if (idx === s.step_index) return s.status === "running" ? "active" : "done";
        return "";
      };
    },
    filteredEntries() {
      if (this.i18nStatusFilter === "all") return this.i18nEntries;
      return this.i18nEntries.filter((e) => e.status === this.i18nStatusFilter);
    },
    currentOrphans() {
      let n = 0;
      for (const lang in this.progressReport) {
        const t = this.progressReport[lang].tables && this.progressReport[lang].tables[this.i18nCurrentTable];
        if (t) n += t.orphan;
      }
      return n;
    },
    filteredSchemas() {
      const q = this.schemaSearch.trim().toLowerCase();
      return this.schemas.filter((s) => {
        const hitName = q === "" || s.table.toLowerCase().indexOf(q) !== -1;
        const st = s.template_status;
        const hitStatus =
          this.schemaStatusFilter === "all" ||
          (this.schemaStatusFilter === "ok" && st === "ok") ||
          (this.schemaStatusFilter === "drift" && st !== "ok");
        return hitName && hitStatus;
      });
    },
    schemaStatusBadge() {
      return (st) => {
        if (st === "ok") return { cls: "badge-ok", text: "模板已同步" };
        if (st === "drift") return { cls: "badge-warn", text: "模板漂移" };
        if (st === "missing") return { cls: "badge-err", text: "Excel 缺失" };
        return { cls: "badge-mute", text: "未跟踪" };
      };
    },
    statusBadge() {
      return (st) => {
        if (st === "translated") return { cls: "badge-ok", text: "translated" };
        if (st === "missing") return { cls: "badge-warn", text: "missing" };
        if (st === "stale") return { cls: "badge-warn", text: "stale" };
        return { cls: "badge-mute", text: "orphan" };
      };
    },
  },

  methods: {
    async api(path, opts) {
      const resp = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
      let payload = null;
      try { payload = await resp.json(); } catch (e) { payload = null; }
      if (!resp.ok || !payload || !payload.ok) {
        throw new Error((payload && payload.error) || ("HTTP " + resp.status));
      }
      return payload.data;
    },
    showError(message) {
      this.errorBanner = { message: message || "操作失败", count: 1 };
    },
    dismissBanner() {
      this.errorBanner = null;
    },

    // ---------- 全局 ----------
    switchTab(name) {
      this.tab = name;
      try { history.replaceState(null, "", "#" + name); } catch (e) { /* 忽略 */ }
      if (name === "i18n") this.ensureI18n();
      if (name === "tables") this.loadSchemas();
      if (name === "logs") this.loadLogs();
      if (name === "history") this.loadHistory();
    },
    async refreshWorkspace() {
      try {
        this.ws = await this.api("/api/workspace");
        this.workspaceError = "";
        const st = this.ws.status;
        const parts = [];
        if (st.missing.length) parts.push(st.missing.length + " 张表缺失");
        if (st.drifted.length) parts.push(st.drifted.length + " 张表模板漂移");
        if (st.changed.length) parts.push(st.changed.length + " 张表待导出");
        this.statusPill = {
          warn: parts.length > 0,
          text: parts.length ? parts.join(" · ") : "数据与模板均已同步",
        };
      } catch (e) {
        this.workspaceError = e.message;
        this.statusPill = { warn: true, text: "工作区不可用" };
      }
    },

    // ---------- 导出 ----------
    async startExport() {
      if (this.exportRunning) return;
      this.errorBanner = null;
      this.sessionRun = true;
      try {
        this.exportState = await this.api("/api/export", {
          method: "POST",
          body: JSON.stringify({ forced: this.forced }),
        });
      } catch (e) {
        this.showError(e.message);
      }
    },
    async cancelExport() {
      try {
        this.exportState = await this.api("/api/export/cancel", { method: "POST" });
      } catch (e) {
        this.showError(e.message);
      }
    },
    async pollExport() {
      try {
        const prev = this.exportState.status;
        const s = await this.api("/api/export/progress");
        this.exportState = s;
        if (s.status === "running") this.sessionRun = true;
        if (s.status === "error" && prev !== "error" && this.sessionRun) {
          this.errorBanner = { message: s.message, count: s.errors.length || 1 };
        }
        if (prev !== s.status && (s.status === "done" || s.status === "cancelled")) {
          this.loadHistory();
          this.refreshWorkspace();
        }
      } catch (e) { /* 瞬时失败忽略 */ }
    },

    // ---------- 翻译 ----------
    async ensureI18n() {
      if (!this.i18nTables.length) {
        try {
          this.i18nTables = await this.api("/api/i18n/tables");
          if (!this.i18nCurrentTable) {
            const first = this.i18nTables.find((t) => t.has_i18n) || this.i18nTables[0];
            if (first) this.i18nCurrentTable = first.table;
          }
        } catch (e) { this.showError(e.message); }
      }
      if (!this.i18nLang && this.ws && this.ws.config.secondary_langs.length) {
        this.i18nLang = this.ws.config.secondary_langs[0];
      }
      await Promise.all([this.loadEntries(), this.loadStatusReport()]);
    },
    async loadEntries() {
      if (!this.i18nCurrentTable || !this.i18nLang) return;
      try {
        this.i18nEntries = await this.api(
          "/api/i18n/entries?table=" + encodeURIComponent(this.i18nCurrentTable) + "&lang=" + encodeURIComponent(this.i18nLang)
        );
        this.editingKey = null;
        this.editDrafts = {};
      } catch (e) { this.showError(e.message); }
    },
    async loadStatusReport() {
      try {
        this.progressReport = await this.api("/api/i18n/status");
      } catch (e) { /* 忽略 */ }
    },
    isLongEntry(entry) {
      return entry.source.length > 40 || entry.text.length > 40;
    },
    draftValue(entry) {
      const d = this.editDrafts[entry.key];
      return d && d.text !== undefined ? d.text : entry.text;
    },
    setDraft(entry, text) {
      const d = this.editDrafts[entry.key] || { text: entry.text, confirmed: entry.confirmed };
      d.text = text;
      this.editDrafts[entry.key] = d;
    },
    expandEdit(entry) {
      this.editingKey = entry.key;
      this.editDrafts[entry.key] = { text: entry.text, confirmed: entry.confirmed };
      this.$nextTick(() => {
        const el = this.$refs["ta-" + entry.key];
        if (el) el.focus();
      });
    },
    collapseEdit(entry) {
      if (this.editingKey === entry.key) {
        this.editingKey = null;
      }
    },
    async saveEntry(entry, confirmed) {
      const d = this.editDrafts[entry.key] || { text: entry.text, confirmed: entry.confirmed };
      try {
        await this.api("/api/i18n/entry", {
          method: "POST",
          body: JSON.stringify({
            table: this.i18nCurrentTable,
            lang: this.i18nLang,
            key: entry.key,
            text: d.text === undefined ? entry.text : d.text,
            confirmed: confirmed,
          }),
        });
        await Promise.all([this.loadEntries(), this.loadStatusReport()]);
      } catch (e) { this.showError(e.message); }
    },
    async syncAll() {
      this.i18nBusy = true;
      try {
        await this.api("/api/i18n/sync", { method: "POST", body: JSON.stringify({ table: this.i18nCurrentTable }) });
        await Promise.all([this.loadEntries(), this.loadStatusReport()]);
      } catch (e) { this.showError(e.message); }
      finally { this.i18nBusy = false; }
    },
    async openCompact() {
      try {
        this.compactPreview = await this.api("/api/i18n/compact", {
          method: "POST",
          body: JSON.stringify({ table: this.i18nCurrentTable, dry_run: true }),
        });
        this.compactModal = true;
      } catch (e) { this.showError(e.message); }
    },
    async confirmCompact() {
      try {
        await this.api("/api/i18n/compact", {
          method: "POST",
          body: JSON.stringify({ table: this.i18nCurrentTable, dry_run: false }),
        });
        this.compactModal = false;
        await Promise.all([this.loadEntries(), this.loadStatusReport()]);
      } catch (e) { this.showError(e.message); }
    },

    // ---------- 表格管理 ----------
    async loadSchemas() {
      try {
        this.schemas = await this.api("/api/schemas");
      } catch (e) { this.showError(e.message); }
    },
    async openDetail(table) {
      try {
        this.schemaDetail = await this.api("/api/schemas/" + encodeURIComponent(table));
        this.detailModal = true;
      } catch (e) { this.showError(e.message); }
    },
    openCreate() {
      this.form = { name: "", pk: "Id", fieldsYaml: "" };
      this.createModal = true;
    },
    openEdit() {
      const d = this.schemaDetail;
      if (!d) return;
      this.editOrigin = d.table;
      this.form = {
        name: d.table,
        pk: d.primary,
        fieldsYaml: serializeFields(d.fields),
      };
      this.detailModal = false;
      this.editModal = true;
    },
    async saveSchema() {
      const payload = {
        table: this.form.name.trim(),
        primary: this.form.pk.trim(),
        fields_yaml: this.form.fieldsYaml,
      };
      try {
        if (this.createModal) {
          await this.api("/api/schemas", { method: "POST", body: JSON.stringify(payload) });
          this.createModal = false;
        } else {
          await this.api("/api/schemas/" + encodeURIComponent(this.editOrigin), {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          this.editModal = false;
        }
        await Promise.all([this.loadSchemas(), this.refreshWorkspace()]);
      } catch (e) { this.showError(e.message); }
    },
    async rebuildTemplate() {
      const d = this.schemaDetail;
      if (!d) return;
      try {
        await this.api("/api/schemas/" + encodeURIComponent(d.table), {
          method: "PUT",
          body: JSON.stringify({
            table: d.table,
            primary: d.primary,
            fields_yaml: serializeFields(d.fields),
          }),
        });
        await this.openDetail(d.table);
        await Promise.all([this.loadSchemas(), this.refreshWorkspace()]);
      } catch (e) { this.showError(e.message); }
    },
    openDelete() {
      if (!this.schemaDetail) return;
      this.deleteTarget = this.schemaDetail.table;
      this.detailModal = false;
      this.deleteModal = true;
    },
    async confirmDelete() {
      try {
        await this.api("/api/schemas/" + encodeURIComponent(this.deleteTarget), { method: "DELETE" });
        this.deleteModal = false;
        this.schemaDetail = null;
        await Promise.all([this.loadSchemas(), this.refreshWorkspace()]);
      } catch (e) { this.showError(e.message); }
    },

    // ---------- 日志与历史 ----------
    async loadLogs() {
      try {
        this.logs = await this.api("/api/logs?module=" + encodeURIComponent(this.logModule));
        this.$nextTick(() => {
          const el = this.$refs.logList;
          if (el && this.followLatest) el.scrollTop = el.scrollHeight;
        });
      } catch (e) { /* 忽略 */ }
    },
    onLogScroll() {
      const el = this.$refs.logList;
      if (!el) return;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      this.followLatest = atBottom;
    },
    jumpToBottom() {
      const el = this.$refs.logList;
      if (el) el.scrollTop = el.scrollHeight;
      this.followLatest = true;
    },
    async loadHistory() {
      try {
        this.history = await this.api("/api/history");
      } catch (e) { /* 忽略 */ }
    },
    i18nCount(fields) {
      return fields.filter((f) => f.i18n).length;
    },
    fieldMeta(f) {
      const parts = [];
      if (f.ref) parts.push("ref " + f.ref);
      if (f.type === "enum" && f.values) parts.push(f.values.join(" / "));
      if (f.type === "struct") parts.push((f.fields || []).map((s) => s.name).join(" · "));
      if (f.type === "array") parts.push(f.element);
      if (f.i18n) parts.push("i18n");
      if (f.server_only) parts.push("server_only");
      return parts.join(" · ");
    },
  },

  mounted() {
    this.refreshWorkspace();
    this.loadHistory();
    const h = location.hash.replace("#", "");
    if (["export", "i18n", "tables", "logs", "history"].indexOf(h) !== -1) {
      this.switchTab(h);
    }
    setInterval(() => {
      this.pollExport();
      if (this.tab === "logs") this.loadLogs();
    }, 1500);
    window.addEventListener("beforeunload", (e) => {
      if (this.exportState.status === "running") {
        e.preventDefault();
        e.returnValue = "导出仍在进行，确认离开将停止任务";
      }
    });
  },

  template: `
<div>
  <!-- 顶栏 -->
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark">ct</span>
      <span><div class="brand-name">配表工具</div><div class="brand-sub">Config Table Panel</div></span>
    </div>
    <div class="topbar-spacer"></div>
    <span class="workspace-path" v-if="ws">{{ ws.root }}</span>
    <span class="status-pill" v-if="statusPill.text">
      <span class="status-dot" :style="statusPill.warn ? 'background:var(--warn)' : ''"></span>{{ statusPill.text }}
    </span>
  </header>

  <!-- 页签 -->
  <nav class="tabs">
    <button class="tab" :class="{active: tab==='export'}" @click="switchTab('export')">导出</button>
    <button class="tab" :class="{active: tab==='i18n'}" @click="switchTab('i18n')">翻译 i18n <span class="tab-count" v-if="currentOrphans">{{ currentOrphans }}</span></button>
    <button class="tab" :class="{active: tab==='tables'}" @click="switchTab('tables')">表格管理</button>
    <button class="tab" :class="{active: tab==='logs'}" @click="switchTab('logs')">日志</button>
    <button class="tab" :class="{active: tab==='history'}" @click="switchTab('history')">历史</button>
  </nav>

  <main class="layout">
    <div class="banner-error" v-if="errorBanner">
      <span>有 <b>{{ errorBanner.count }}</b> 条错误待处理</span>
      <span class="banner-fix">{{ errorBanner.message }}</span>
      <a class="btn btn-sm btn-danger" @click.prevent="switchTab('logs')" href="#">查看日志</a>
      <button class="btn btn-sm btn-ghost" @click="dismissBanner">忽略</button>
    </div>
    <div class="banner-error" v-if="workspaceError">
      <span><b>工作区不可用</b></span>
      <span class="banner-fix">{{ workspaceError }}</span>
    </div>

    <!-- ============ 导出 ============ -->
    <section class="tab-page" :class="{active: tab==='export'}">
      <div class="cmd-bar">
        <span class="cmd-spacer"></span>
        <label class="cmd-check"><input type="checkbox" v-model="forced" :disabled="exportRunning">强制重建</label>
        <button class="btn btn-primary" @click="startExport" :disabled="exportRunning">{{ exportRunning ? '导出中…' : '开始导出' }}</button>
      </div>
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">{{ sessionRun ? '导出进度' : '上次导出' }}</span>
          <span style="flex:1"></span>
          <template v-if="sessionRun">
            <span class="badge badge-ok" v-if="exportDone">成功 · {{ exportState.tables_exported }} 张表</span>
            <span class="badge badge-warn" v-if="exportCancelled">已取消</span>
            <span class="badge badge-err" v-if="exportError">已中止</span>
            <span class="badge badge-mute" v-if="exportRunning">进行中</span>
          </template>
          <span class="badge badge-mute" v-else-if="lastExport">{{ lastExport.result }}</span>
        </div>
        <div class="panel-body">
          <template v-if="sessionRun">
            <div class="cell-progress">
              <div v-for="(step, idx) in stepCells" :key="step" class="prog-cell" :class="stepCellClass(idx)">
                <span class="p-num">{{ idx + 1 }}</span><span class="p-name">{{ step }}</span>
              </div>
            </div>
            <div class="progress-line" v-if="exportState.message">{{ exportState.message }}</div>
            <div class="progress-line" v-for="line in exportState.errors" :key="line" style="color:var(--danger)">{{ line }}</div>
            <div class="summary-line" v-if="exportRunning || exportDone || exportCancelled || exportError">
              <span>已导出 <b>{{ exportState.tables_exported }}</b> 张表</span>
              <span>状态 <b>{{ exportState.status }}</b></span>
              <span>耗时 <b>{{ exportState.elapsed }}s</b></span>
              <button class="btn btn-sm btn-danger" v-if="exportRunning" @click="cancelExport">取消导出</button>
            </div>
          </template>
          <div v-else>
            <div class="empty-state" v-if="!lastExport">
              <div class="empty-title">还没有导出记录</div>
              <div class="empty-sub">点击“开始导出”进行第一次导出</div>
            </div>
            <template v-else>
              <div class="progress-line">上次导出 {{ lastExport.time }} · {{ lastExport.scope }} · {{ lastExport.tables }} 张表 · {{ lastExport.elapsed }}s</div>
            </template>
          </div>
          <div class="cmd-footnote">
            <span class="mono" v-if="ws">产物目录 {{ ws.root }}/output</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 翻译 ============ -->
    <section class="tab-page" :class="{active: tab==='i18n'}">
      <div class="cmd-bar">
        <div class="cmd-group">
          <span class="cmd-label">表</span>
          <button class="btn btn-sm btn-ghost" @click="pickTableModal = true">选择表</button>
          <span class="cmd-value">{{ i18nCurrentTable || '—' }}</span>
        </div>
        <span class="cmd-spacer"></span>
        <button class="btn btn-sm btn-ghost" @click="progressModal = true">全部表进度</button>
        <span class="cmd-vsep"></span>
        <button class="btn btn-sm btn-danger" v-if="currentOrphans > 0" @click="openCompact">清理无主条目（{{ currentOrphans }}）</button>
        <button class="btn btn-primary" @click="syncAll" :disabled="i18nBusy">{{ i18nBusy ? '同步中…' : '同步全部语言' }}</button>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">翻译表 · {{ i18nCurrentTable }}</span>
          <span style="flex:1"></span>
          <span class="cmd-label">语言</span>
          <div class="seg">
            <button v-for="l in (ws && ws.config.secondary_langs)" :key="l" class="pill" :class="{active: i18nLang===l}" @click="i18nLang = l; loadEntries()">{{ l }}</button>
          </div>
          <span class="cmd-label">状态</span>
          <div class="seg">
            <button class="pill" :class="{active: i18nStatusFilter==='all'}" @click="i18nStatusFilter='all'">全部</button>
            <button class="pill" :class="{active: i18nStatusFilter==='missing'}" @click="i18nStatusFilter='missing'">missing</button>
            <button class="pill" :class="{active: i18nStatusFilter==='stale'}" @click="i18nStatusFilter='stale'">stale</button>
            <button class="pill" :class="{active: i18nStatusFilter==='translated'}" @click="i18nStatusFilter='translated'">translated</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr><th>主键</th><th>字段</th><th>{{ ws ? ws.config.primary_lang : '' }} 原文</th><th style="min-width:200px">{{ i18nLang }} 译文</th><th>状态</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="entry in filteredEntries" :key="entry.key">
                  <td><span class="pk-cell">{{ entry.id }}</span></td>
                  <td class="mono">{{ entry.field }}</td>
                  <td class="src-cell"><span class="src-text" :class="{expanded: editingKey===entry.key}">{{ entry.source }}</span></td>
                  <td class="trans-cell">
                    <template v-if="isLongEntry(entry)">
                      <div v-if="editingKey !== entry.key" class="trans-preview" :class="{placeholder: !entry.text}" @click="expandEdit(entry)">{{ entry.text || '点击填写译文…' }}</div>
                      <textarea v-else class="trans-input is-area" :ref="'ta-' + entry.key" v-model="editDrafts[entry.key].text" @blur="collapseEdit(entry)"></textarea>
                    </template>
                    <input v-else class="trans-input" :value="draftValue(entry)" @input="setDraft(entry, $event.target.value)">
                  </td>
                  <td><span class="badge" :class="statusBadge(entry.status).cls">{{ statusBadge(entry.status).text }}</span></td>
                  <td>
                    <button class="btn btn-sm btn-ghost" @click="saveEntry(entry, true)">保存</button>
                    <button v-if="entry.status==='stale'" class="btn btn-sm btn-accent" @click="saveEntry(entry, true)">确认并保存</button>
                  </td>
                </tr>
                <tr v-if="!filteredEntries.length">
                  <td colspan="6" class="empty-cell">该状态下暂无译文条目</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="hint" style="margin-top:10px">
            译文保存在 <span class="mono">i18n/{{ i18nLang }}/{{ i18nCurrentTable }}.json</span>；填写后点“保存”，下次导出自动合并。
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 表格管理 ============ -->
    <section class="tab-page" :class="{active: tab==='tables'}">
      <div class="cmd-bar">
        <div class="cmd-group">
          <span class="cmd-label">表名</span>
          <input class="cmd-search" v-model="schemaSearch" placeholder="搜索…">
        </div>
        <div class="cmd-group">
          <span class="cmd-label">状态</span>
          <div class="seg">
            <button class="pill" :class="{active: schemaStatusFilter==='all'}" @click="schemaStatusFilter='all'">全部</button>
            <button class="pill" :class="{active: schemaStatusFilter==='ok'}" @click="schemaStatusFilter='ok'">模板已同步</button>
            <button class="pill" :class="{active: schemaStatusFilter==='drift'}" @click="schemaStatusFilter='drift'">模板漂移</button>
          </div>
        </div>
        <span class="cmd-spacer"></span>
        <button class="btn btn-primary" @click="openCreate">新增表</button>
      </div>
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">Schema 表</span>
          <span class="panel-sub">{{ schemas.length }} 张</span>
        </div>
        <div class="panel-body">
          <div class="schema-list">
            <div v-for="s in filteredSchemas" :key="s.table" class="schema-row" @click="openDetail(s.table)">
              <div class="schema-id"><div class="schema-name">{{ s.table }}</div><div class="schema-pk">{{ s.excel_file }}</div></div>
              <span class="mono row-meta">{{ s.field_count }} 字段 · i18n {{ s.i18n_count }}</span>
              <span class="badge" :class="schemaStatusBadge(s.template_status).cls">{{ schemaStatusBadge(s.template_status).text }}</span>
              <button class="btn btn-sm btn-ghost btn-row-detail" @click.stop="openDetail(s.table)">详情</button>
            </div>
          </div>
          <div class="empty-state" v-if="!filteredSchemas.length">
            <div class="empty-title">没有匹配的表</div>
            <div class="empty-sub">试试其他关键词，或调整状态筛选</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 日志 ============ -->
    <section class="tab-page" :class="{active: tab==='logs'}">
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">运行日志</span>
          <span class="panel-sub">按模块过滤 · 实时追加</span>
        </div>
        <div class="panel-body">
          <div class="log-toolbar">
            <button v-for="m in ['all','导出','校验','i18n','模板','系统']" :key="m" class="pill" :class="{active: logModule===m}" @click="logModule = m; loadLogs()">{{ m === 'all' ? '全部' : m }}</button>
          </div>
          <div class="log-wrap">
            <div class="log-list" ref="logList" @scroll="onLogScroll">
              <div v-for="(r, i) in logs" :key="i" class="log-row">
                <span class="log-time">{{ r.time }}</span>
                <span class="log-module">{{ r.module }}</span>
                <span class="log-level" :class="r.level.toLowerCase()">{{ r.level }}</span>
                <span class="log-msg">{{ r.message }}</span>
              </div>
              <div v-if="!logs.length" class="empty-state">
                <div class="empty-title">暂无日志</div>
              </div>
            </div>
            <button v-if="!followLatest" class="btn btn-sm btn-ghost btn-jump-bottom" @click="jumpToBottom">回到底部 ↓</button>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 历史 ============ -->
    <section class="tab-page" :class="{active: tab==='history'}">
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">导出历史</span>
          <span class="panel-sub">保留最近 5 次</span>
        </div>
        <div class="panel-body">
          <div v-for="(h, i) in history" :key="i" class="history-item">
            <span class="history-time">{{ h.time }}</span>
            <span class="history-scope">{{ h.scope }} <small v-if="h.forced">· 强制重建</small></span>
            <span class="badge" :class="h.result === '成功' ? 'badge-ok' : 'badge-err'">{{ h.result }} · {{ h.tables }} 张表 · {{ h.elapsed }}s</span>
          </div>
          <div v-if="!history.length" class="empty-state">
            <div class="empty-title">还没有导出记录</div>
            <div class="empty-sub">去导出页开始第一次导出</div>
          </div>
        </div>
      </div>
    </section>
  </main>

  <!-- 选择翻译表 -->
  <div class="modal-mask" v-if="pickTableModal">
    <div class="modal" role="dialog">
      <div class="modal-head"><span>选择翻译表</span><span class="mono" style="margin-left:10px;font-size:12px;color:var(--ink-3)">含 i18n 字段</span></div>
      <div class="modal-body">
        <label v-for="t in i18nTables" :key="t.table" class="pick-row">
          <input type="radio" name="pick-itable" :checked="i18nCurrentTable === t.table" :disabled="!t.has_i18n" @change="i18nCurrentTable = t.table; loadEntries()">
          {{ t.table }}
          <span class="opt-meta">{{ t.field_count }} 字段 · i18n {{ t.i18n_count }}</span>
        </label>
      </div>
      <div class="modal-foot"><button class="btn btn-ghost" @click="pickTableModal = false">关闭</button></div>
    </div>
  </div>

  <!-- 全部表进度 -->
  <div class="modal-mask" v-if="progressModal">
    <div class="modal" role="dialog">
      <div class="modal-head">
        <span>翻译进度</span>
        <span style="flex:1"></span>
        <button class="pill" :class="{active: progressView==='lang'}" @click="progressView='lang'">语言</button>
        <button class="pill" :class="{active: progressView==='table'}" @click="progressView='table'">按表</button>
      </div>
      <div class="modal-body">
        <template v-if="progressView === 'lang'">
          <div v-for="(lc, lang) in progressReport" :key="lang" class="side-row">
            <span class="badge badge-mute">{{ lang }}</span>
            <span class="side-name">进度 {{ Math.round(lc.progress * 100) }}%</span>
            <span class="side-val">{{ lc.translated }}/{{ lc.total }} translated · {{ lc.missing }} missing · {{ lc.stale }} stale · {{ lc.orphan }} orphan</span>
          </div>
        </template>
        <template v-else>
          <div v-for="(lc, lang) in progressReport" :key="lang">
            <div class="side-row" style="font-weight:700;color:var(--ink-2)">{{ lang }}</div>
            <div v-for="(tc, table) in lc.tables" :key="table" class="side-row">
              <span class="mono side-name">{{ table }}</span>
              <span class="side-badges">
                <span class="badge badge-ok">{{ lang }} {{ tc.translated }}/{{ tc.total }}</span>
                <span class="badge badge-warn" v-if="tc.missing">{{ tc.missing }} missing</span>
                <span class="badge badge-warn" v-if="tc.stale">{{ tc.stale }} stale</span>
                <span class="badge badge-mute" v-if="tc.orphan">{{ tc.orphan }} orphan</span>
              </span>
            </div>
          </div>
        </template>
      </div>
      <div class="modal-foot"><button class="btn btn-ghost" @click="progressModal = false">关闭</button></div>
    </div>
  </div>

  <!-- 清理无主条目 -->
  <div class="modal-mask" v-if="compactModal">
    <div class="modal" role="dialog">
      <div class="modal-head"><span>确认清理 {{ compactPreview.total_removed }} 条无主条目</span></div>
      <div class="modal-body">
        <div v-for="f in compactPreview.files" :key="f.lang + f.table">
          <div class="hint" style="margin-bottom:6px">{{ f.lang }} / {{ f.table }}</div>
          <div class="orphan-line" v-for="k in f.removed_keys" :key="k" style="font-family:var(--font-mono);font-size:12.5px;padding:2px 0">{{ k }}</div>
        </div>
        <div class="hint" style="margin-top:8px">删除后不可恢复，翻译文件将从语言包中移除这些 key。</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="compactModal = false">取消</button>
        <button class="btn btn-danger" @click="confirmCompact">确认清理</button>
      </div>
    </div>
  </div>

  <!-- 表详情 -->
  <div class="modal-mask" v-if="detailModal && schemaDetail">
    <div class="modal modal-lg" role="dialog">
      <div class="modal-head">
        <span>表详情 · {{ schemaDetail.table }}</span>
        <span style="flex:1"></span>
        <span class="badge" :class="schemaStatusBadge(schemaDetail.template_status).cls">{{ schemaStatusBadge(schemaDetail.template_status).text }}</span>
      </div>
      <div class="modal-body">
        <div class="kv-grid">
          <div class="kv-item"><span class="kv-label">主键</span><span class="kv-value">{{ schemaDetail.primary }} · {{ schemaDetail.pk_type }}</span></div>
          <div class="kv-item"><span class="kv-label">Excel 文件</span><span class="kv-value">{{ schemaDetail.excel_file }}</span></div>
          <div class="kv-item"><span class="kv-label">JSON 键</span><span class="kv-value">{{ schemaDetail.json_key }}</span></div>
          <div class="kv-item"><span class="kv-label">规模</span><span class="kv-value">{{ schemaDetail.fields.length }} 字段 · i18n {{ i18nCount(schemaDetail.fields) }}</span></div>
        </div>
        <div class="field">
          <span class="field-label">字段定义</span>
          <div class="field-list">
            <div v-for="f in schemaDetail.fields" :key="f.name" class="field-row">
              <span class="mono">{{ f.name }}</span><span class="tag">{{ f.type }}</span>
              <span class="f-meta">{{ fieldMeta(f) }}</span>
            </div>
          </div>
        </div>
        <div class="hint" v-if="schemaDetail.template_status === 'drift'" style="margin-top:12px">
          此漂移来自面板外的 schema 变更（如手动修改 YAML 或拉取他人提交）；点击“重建模板（保留数据）”对齐。
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="detailModal = false">关闭</button>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" :disabled="schemaDetail.template_status === 'ok'" @click="rebuildTemplate">{{ schemaDetail.template_status === 'ok' ? '模板已同步' : '重建模板（保留数据）' }}</button>
        <button class="btn btn-primary" @click="openEdit">编辑</button>
        <button class="btn btn-danger" @click="openDelete">删除</button>
      </div>
    </div>
  </div>

  <!-- 新增表 -->
  <div class="modal-mask" v-if="createModal">
    <div class="modal modal-lg" role="dialog">
      <div class="modal-head"><span>新增表</span><span class="mono" style="margin-left:10px;font-size:12px;color:var(--ink-3)">由程序建表 · schema 自动校验</span></div>
      <div class="modal-body">
        <div class="field">
          <label class="field-label">表名</label>
          <input class="form-input" v-model="form.name" placeholder="Item">
          <div class="hint">首字符大写，不含下划线</div>
        </div>
        <div class="field">
          <label class="field-label">主键字段</label>
          <input class="form-input" v-model="form.pk">
          <div class="hint">类型必须为 int32 或 int64</div>
        </div>
        <div class="field">
          <span class="field-label">字段定义（YAML）</span>
          <textarea class="form-input form-area" v-model="form.fieldsYaml" placeholder="- name: Id&#10;  type: int32&#10;- name: Name&#10;  type: string&#10;  i18n: true"></textarea>
          <div class="hint">类型映射与 fbs 结构约定自动校验，命名违规会当场报错</div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="createModal = false">取消</button>
        <button class="btn btn-primary" @click="saveSchema">创建表格与模板</button>
      </div>
    </div>
  </div>

  <!-- 编辑表 -->
  <div class="modal-mask" v-if="editModal">
    <div class="modal modal-lg" role="dialog">
      <div class="modal-head"><span>编辑表 · {{ form.name }}</span><span class="mono" style="margin-left:10px;font-size:12px;color:var(--ink-3)">保存后自动校验</span></div>
      <div class="modal-body">
        <div class="field">
          <label class="field-label">表名</label>
          <input class="form-input" v-model="form.name">
          <div class="hint">改名会影响 schema 文件与 Excel 文件名，请谨慎</div>
        </div>
        <div class="field">
          <label class="field-label">主键字段</label>
          <input class="form-input" v-model="form.pk">
        </div>
        <div class="field">
          <span class="field-label">字段定义（YAML）</span>
          <textarea class="form-input form-area" v-model="form.fieldsYaml"></textarea>
          <div class="hint">保存修改会自动按新 schema 重建表头并保留已有数据，保存后即回到“模板已同步”</div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="editModal = false">取消</button>
        <button class="btn btn-primary" @click="saveSchema">保存修改</button>
      </div>
    </div>
  </div>

  <!-- 删除确认 -->
  <div class="modal-mask" v-if="deleteModal">
    <div class="modal" role="dialog">
      <div class="modal-head"><span>删除表</span></div>
      <div class="modal-body">
        <p>将删除 <b>{{ deleteTarget }}</b> 的 schema 定义与 Excel 模板，此操作不可恢复。</p>
        <div class="hint">已导出的产物与翻译文件不受影响。</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="deleteModal = false">取消</button>
        <button class="btn btn-danger" @click="confirmDelete">删除</button>
      </div>
    </div>
  </div>
</div>
`,
})
.mount("#app");

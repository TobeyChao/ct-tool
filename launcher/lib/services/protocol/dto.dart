/// 业务方法 DTO：与 native/crates/ct-protocol/src/dto/ 同源维护。
///
/// 约定：JSON 键 camelCase；枚举线格式 snake_case；可选字段缺省即缺省键。
library;

import 'messages.dart';

// ---------------------------------------------------------------------------
// workspace
// ---------------------------------------------------------------------------

enum WorkspaceStatus {
  ready('ready'),
  recoveryNeeded('recovery_needed');

  const WorkspaceStatus(this.wire);
  final String wire;

  static WorkspaceStatus parse(String v) =>
      WorkspaceStatus.values.firstWhere((e) => e.wire == v);
}

final class RecoveryInfo {
  const RecoveryInfo({required this.needed, this.journals = const []});

  factory RecoveryInfo.fromJson(Map<String, Object?> json) => RecoveryInfo(
    needed: json['needed']! as bool,
    journals: (json['journals'] as List?)?.cast<String>() ?? const [],
  );

  final bool needed;
  final List<String> journals;

  Map<String, Object?> toJson() => {'needed': needed, 'journals': journals};
}

final class WorkspaceSnapshot {
  const WorkspaceSnapshot({
    required this.revision,
    required this.status,
    required this.recovery,
    required this.tables,
    required this.records,
    required this.enums,
  });

  factory WorkspaceSnapshot.fromJson(Map<String, Object?> json) =>
      WorkspaceSnapshot(
        revision: json['revision']! as int,
        status: WorkspaceStatus.parse(json['status']! as String),
        recovery: RecoveryInfo.fromJson(
          json['recovery']! as Map<String, Object?>,
        ),
        tables: json['tables']! as int,
        records: json['records']! as int,
        enums: json['enums']! as int,
      );

  final int revision;
  final WorkspaceStatus status;
  final RecoveryInfo recovery;
  final int tables;
  final int records;
  final int enums;

  Map<String, Object?> toJson() => {
    'revision': revision,
    'status': status.wire,
    'recovery': recovery.toJson(),
    'tables': tables,
    'records': records,
    'enums': enums,
  };
}

enum RecoverOutcome {
  recovered('recovered'),
  noop('noop'),
  blocked('blocked');

  const RecoverOutcome(this.wire);
  final String wire;

  static RecoverOutcome parse(String v) =>
      RecoverOutcome.values.firstWhere((e) => e.wire == v);
}

final class RecoverResult {
  const RecoverResult({required this.outcome, this.revision, this.detail = ''});

  factory RecoverResult.fromJson(Map<String, Object?> json) => RecoverResult(
    outcome: RecoverOutcome.parse(json['outcome']! as String),
    revision: json['revision'] as int?,
    detail: (json['detail'] as String?) ?? '',
  );

  final RecoverOutcome outcome;
  final int? revision;
  final String detail;
}

// ---------------------------------------------------------------------------
// resources
// ---------------------------------------------------------------------------

enum ResourceKind {
  table('table'),
  record('record'),
  enum_('enum');

  const ResourceKind(this.wire);
  final String wire;

  static ResourceKind parse(String v) =>
      ResourceKind.values.firstWhere((e) => e.wire == v);
}

final class ResourceEntry {
  const ResourceEntry({
    required this.name,
    required this.kind,
    required this.sourcePath,
    this.excelFile,
    this.indexes = const [],
    this.jsonKey,
    this.fields,
    this.values,
    this.primary,
  });

  factory ResourceEntry.fromJson(Map<String, Object?> json) => ResourceEntry(
    name: json['name']! as String,
    kind: ResourceKind.parse(json['kind']! as String),
    sourcePath: json['sourcePath']! as String,
    excelFile: json['excelFile'] as String?,
    indexes: (json['indexes'] as List?)?.map((e) => '$e').toList() ?? const [],
    jsonKey: json['jsonKey'] as String?,
    fields: json['fields'] as List<Object?>?,
    values: json['values'] as List<Object?>?,
    primary: json['primary'] as String?,
  );

  final String name;
  final ResourceKind kind;
  final String sourcePath;
  final String? excelFile;

  /// 仅 Table：内核已声明的查询索引 kind（当前只有 codename）。
  final List<String> indexes;
  final String? jsonKey;

  /// 内核清单自带的字段定义（table/record），形态与 YAML 文档一致。
  final List<Object?>? fields;

  /// 枚举成员（顺序即 ordinal），界面据此显示并可整表改写。
  final List<Object?>? values;

  /// 表主键名。
  final String? primary;
}

final class ResourcesListResult {
  const ResourcesListResult({
    required this.revision,
    required this.resources,
    this.schemaRevision = '',
  });

  factory ResourcesListResult.fromJson(Map<String, Object?> json) =>
      ResourcesListResult(
        revision: json['revision']! as int,
        schemaRevision: (json['schemaRevision'] as String?) ?? '',
        resources: (json['resources']! as List)
            .map((e) => ResourceEntry.fromJson(e as Map<String, Object?>))
            .toList(),
      );

  final int revision;
  final List<ResourceEntry> resources;

  /// schema 基线摘要：草稿命令与保存守卫都绑定它。
  final String schemaRevision;
}

// ---------------------------------------------------------------------------
// schema
// ---------------------------------------------------------------------------

/// 单条 Schema 编辑命令；kind 词表由内核拥有并校验，客户端原样回放。
final class SchemaCommand {
  const SchemaCommand({required this.kind, this.payload = const {}});

  factory SchemaCommand.fromJson(Map<String, Object?> json) => SchemaCommand(
    kind: json['kind']! as String,
    payload: (json['payload'] as Map<String, Object?>?) ?? const {},
  );

  final String kind;
  final Map<String, Object?> payload;

  Map<String, Object?> toJson() => {'kind': kind, 'payload': payload};
}

final class SchemaCandidateParams {
  const SchemaCandidateParams({
    required this.schemaRevision,
    this.commands = const [],
    required this.cursor,
    required this.draftGeneration,
  });

  /// schema 源文件集合的 sha256 十六进制摘要（草稿基线）。
  final String schemaRevision;
  final List<SchemaCommand> commands;
  final String cursor;
  final int draftGeneration;

  Map<String, Object?> toJson() => {
    'schemaRevision': schemaRevision,
    'commands': commands.map((c) => c.toJson()).toList(),
    'cursor': cursor,
    'draftGeneration': draftGeneration,
  };
}

/// 净差异里的一条字段或枚举成员变更：`details` 全部由内核生成。
final class NetFieldDiff {
  const NetFieldDiff({
    required this.name,
    this.change = '',
    this.oldName,
    this.details = const [],
  });

  factory NetFieldDiff.fromJson(Map<String, Object?> json) => NetFieldDiff(
    name: json['name']! as String,
    change: json['change'] as String? ?? '',
    oldName: json['oldName'] as String?,
    details: (json['details'] as List?)?.map((e) => '$e').toList() ?? const [],
  );

  final String name;

  /// 内核变更类型词表：added / removed / modified / renamed。
  final String change;

  /// 显式改名时的旧名。
  final String? oldName;

  /// 风险明细，例如 ordinal 1 变 3 的 wire 风险、API 名称变化。
  final List<String> details;
}

final class ResourceRef {
  const ResourceRef({
    required this.kind,
    required this.name,
    this.change,
    this.oldName,
    this.fields = const [],
  });

  factory ResourceRef.fromJson(Map<String, Object?> json) => ResourceRef(
    kind: json['kind']! as String,
    name: json['name']! as String,
    change: json['change'] as String?,
    oldName: json['oldName'] as String?,
    fields:
        (json['fields'] as List?)
            ?.map((e) => NetFieldDiff.fromJson(e as Map<String, Object?>))
            .toList() ??
        const [],
  );

  final String kind;
  final String name;

  /// 资源级变更类型；改名与「删除+新增」由内核区分，界面不猜。
  final String? change;

  /// 显式改名命令给出的旧名。
  final String? oldName;

  /// 字段/枚举成员明细。
  final List<NetFieldDiff> fields;

  String get label =>
      oldName == null ? '$kind:$name' : '$kind:$oldName -> $kind:$name';
}

final class NetDiff {
  const NetDiff({
    this.added = const [],
    this.removed = const [],
    this.changed = const [],
  });

  factory NetDiff.fromJson(Map<String, Object?> json) => NetDiff(
    added: _refs(json['added']),
    removed: _refs(json['removed']),
    changed: _refs(json['changed']),
  );

  static List<ResourceRef> _refs(Object? raw) =>
      (raw as List?)
          ?.map((e) => ResourceRef.fromJson(e as Map<String, Object?>))
          .toList() ??
      const [];

  final List<ResourceRef> added;
  final List<ResourceRef> removed;
  final List<ResourceRef> changed;
}

final class SchemaCandidateResult {
  const SchemaCandidateResult({
    required this.candidateHash,
    required this.draftGeneration,
    required this.netDiff,
    this.problems = const [],
  });

  factory SchemaCandidateResult.fromJson(Map<String, Object?> json) =>
      SchemaCandidateResult(
        candidateHash: json['candidateHash']! as String,
        draftGeneration: json['draftGeneration']! as int,
        netDiff: NetDiff.fromJson(json['netDiff']! as Map<String, Object?>),
        problems:
            (json['problems'] as List?)
                ?.map((e) => Issue.fromJson(e as Map<String, Object?>))
                .toList() ??
            const [],
      );

  final String candidateHash;
  final int draftGeneration;
  final NetDiff netDiff;
  final List<Issue> problems;
}

final class SchemaSaveParams {
  const SchemaSaveParams({
    required this.schemaRevision,
    required this.candidateHash,
    this.commands = const [],
    this.cursor,
  });

  /// 双守卫：基线摘要 + 候选内容哈希，缺一不可。
  final String schemaRevision;
  final String candidateHash;

  /// 草稿日志由客户端随请求重放，生效前缀由 cursor 表达（内核是权威）。
  final List<SchemaCommand> commands;
  final String? cursor;

  Map<String, Object?> toJson() => {
    'schemaRevision': schemaRevision,
    'candidateHash': candidateHash,
    'commands': commands.map((c) => c.toJson()).toList(),
    if (cursor != null) 'cursor': cursor,
  };
}

final class SchemaSaveResult {
  const SchemaSaveResult({required this.schemaRevision});

  factory SchemaSaveResult.fromJson(Map<String, Object?> json) =>
      SchemaSaveResult(schemaRevision: json['schemaRevision']! as String);

  final String schemaRevision;
}

// ---------------------------------------------------------------------------
// table.preview / template
// ---------------------------------------------------------------------------

final class PageRequest {
  const PageRequest({this.cursor, this.limit});

  final String? cursor;
  final int? limit;

  Map<String, Object?> toJson() => {
    if (cursor != null) 'cursor': cursor,
    if (limit != null) 'limit': limit,
  };
}

final class PreviewColumn {
  const PreviewColumn({
    required this.name,
    required this.typeExpr,
    this.role,
    this.i18n = false,
    this.serverOnly = false,
    this.comment = '',
    this.ref,
    this.excelColumns,
  });

  factory PreviewColumn.fromJson(Map<String, Object?> json) => PreviewColumn(
    name: json['name']! as String,
    typeExpr: json['typeExpr']! as String,
    role: json['role'] as String?,
    i18n: (json['i18n'] as bool?) ?? false,
    serverOnly: (json['serverOnly'] as bool?) ?? false,
    comment: (json['comment'] as String?) ?? '',
    ref: json['ref'] as String?,
    excelColumns: json['excelColumns'] as int?,
  );

  final String name;
  final String typeExpr;
  final String? role;

  /// 字段属性：内核未给出的键一律当作 false/未声明，界面不猜。
  final bool i18n;
  final bool serverOnly;
  final String comment;
  final String? ref;
  final int? excelColumns;
}

/// 行单元格中的超范围整数由 [decodeBigInts] 还原为 int/BigInt。
final class TablePreviewResult {
  const TablePreviewResult({
    required this.revision,
    required this.columns,
    required this.rows,
    this.nextCursor,
  });

  factory TablePreviewResult.fromJson(Map<String, Object?> json) =>
      TablePreviewResult(
        revision: json['revision']! as int,
        columns: (json['columns']! as List)
            .map((e) => PreviewColumn.fromJson(e as Map<String, Object?>))
            .toList(),
        rows: (json['rows']! as List).cast<List<Object?>>(),
        nextCursor: json['nextCursor'] as String?,
      );

  final int revision;
  final List<PreviewColumn> columns;
  final List<List<Object?>> rows;
  final String? nextCursor;
}

final class TemplatePlanResult {
  const TemplatePlanResult({
    required this.canGenerate,
    this.actions = const [],
    this.warnings = const [],
    this.problems = const [],
  });

  factory TemplatePlanResult.fromJson(Map<String, Object?> json) =>
      TemplatePlanResult(
        canGenerate: json['canGenerate']! as bool,
        actions: (json['actions'] as List?)?.cast<String>() ?? const [],
        warnings: _issues(json['warnings']),
        problems: _issues(json['problems']),
      );

  final bool canGenerate;
  final List<String> actions;
  final List<Issue> warnings;
  final List<Issue> problems;
}

/// `template.generate` 结果：迁移行数与告警（失败不覆盖原工作簿）。
final class TemplateGenerateResult {
  const TemplateGenerateResult({
    required this.migratedRows,
    this.warnings = const [],
  });

  factory TemplateGenerateResult.fromJson(Map<String, Object?> json) =>
      TemplateGenerateResult(
        migratedRows: json['migratedRows']! as int,
        warnings: _issues(json['warnings']),
      );

  final int migratedRows;
  final List<Issue> warnings;
}

// ---------------------------------------------------------------------------
// validate / export / deploy
// ---------------------------------------------------------------------------

final class ValidateResult {
  const ValidateResult({required this.ok, this.issues = const []});

  factory ValidateResult.fromJson(Map<String, Object?> json) =>
      ValidateResult(ok: json['ok']! as bool, issues: _issues(json['issues']));

  final bool ok;
  final List<Issue> issues;
}

enum TaskOutcome {
  succeeded('succeeded'),
  cancelled('cancelled');

  const TaskOutcome(this.wire);
  final String wire;

  static TaskOutcome parse(String v) =>
      TaskOutcome.values.firstWhere((e) => e.wire == v);
}

final class StageStat {
  const StageStat({required this.name, required this.elapsedMs});

  factory StageStat.fromJson(Map<String, Object?> json) => StageStat(
    name: json['name']! as String,
    elapsedMs: json['elapsedMs']! as int,
  );

  final String name;
  final int elapsedMs;
}

final class CacheStat {
  const CacheStat({required this.hits, required this.misses});

  factory CacheStat.fromJson(Map<String, Object?> json) =>
      CacheStat(hits: json['hits']! as int, misses: json['misses']! as int);

  final int hits;
  final int misses;
}

final class ExportResult {
  const ExportResult({
    required this.outcome,
    required this.tables,
    required this.durationMs,
    this.stages = const [],
    this.cache,
    this.issues = const [],
  });

  factory ExportResult.fromJson(Map<String, Object?> json) => ExportResult(
    outcome: TaskOutcome.parse(json['outcome']! as String),
    tables: json['tables']! as int,
    durationMs: json['durationMs']! as int,
    stages:
        (json['stages'] as List?)
            ?.map((e) => StageStat.fromJson(e as Map<String, Object?>))
            .toList() ??
        const [],
    cache: json['cache'] == null
        ? null
        : CacheStat.fromJson(json['cache']! as Map<String, Object?>),
    issues: _issues(json['issues']),
  );

  final TaskOutcome outcome;
  final int tables;
  final int durationMs;
  final List<StageStat> stages;
  final CacheStat? cache;
  final List<Issue> issues;
}

final class DeployResult {
  const DeployResult({required this.synced, required this.unchanged});

  factory DeployResult.fromJson(Map<String, Object?> json) => DeployResult(
    synced: json['synced']! as int,
    unchanged: json['unchanged']! as bool,
  );

  final int synced;
  final bool unchanged;
}

// ---------------------------------------------------------------------------
// i18n
// ---------------------------------------------------------------------------

enum I18nStatus {
  translated('translated'),
  missing('missing'),
  stale('stale'),
  orphan('orphan');

  const I18nStatus(this.wire);
  final String wire;

  static I18nStatus parse(String v) =>
      I18nStatus.values.firstWhere((e) => e.wire == v);
}

final class I18nEntry {
  const I18nEntry({
    required this.key,
    required this.source,
    required this.text,
    required this.confirmed,
    required this.status,
  });

  factory I18nEntry.fromJson(Map<String, Object?> json) => I18nEntry(
    key: json['key']! as String,
    source: json['source']! as String,
    text: json['text']! as String,
    confirmed: json['confirmed']! as bool,
    status: I18nStatus.parse(json['status']! as String),
  );

  final String key;
  final String source;
  final String text;
  final bool confirmed;
  final I18nStatus status;
}

/// `i18n.save` 结果：内核重新判定的状态（客户端不自行推断）。
final class I18nSaveResult {
  const I18nSaveResult({required this.status});

  factory I18nSaveResult.fromJson(Map<String, Object?> json) =>
      I18nSaveResult(status: I18nStatus.parse(json['status']! as String));

  final I18nStatus status;
}

/// `i18n.sync` 结果。
final class I18nSyncResult {
  const I18nSyncResult({required this.tables, required this.inserted});

  factory I18nSyncResult.fromJson(Map<String, Object?> json) => I18nSyncResult(
    tables: json['tables']! as int,
    inserted: json['inserted']! as int,
  );

  final int tables;
  final int inserted;
}

/// `i18n.status` 结果：各语言进度总览。
final class I18nStatusResult {
  const I18nStatusResult({this.langs = const []});

  factory I18nStatusResult.fromJson(Map<String, Object?> json) =>
      I18nStatusResult(
        langs: (json['langs'] as List? ?? const [])
            .map((e) => LangProgress.fromJson(e! as Map<String, Object?>))
            .toList(),
      );

  final List<LangProgress> langs;
}

/// `i18n.compact` 结果：dry-run 时 `entries` 是将删除的键。
final class I18nCompactResult {
  const I18nCompactResult({
    required this.dryRun,
    this.entries = const [],
    required this.removed,
  });

  factory I18nCompactResult.fromJson(Map<String, Object?> json) =>
      I18nCompactResult(
        dryRun: json['dryRun']! as bool,
        entries: (json['entries'] as List? ?? const [])
            .map((e) => '$e')
            .toList(),
        removed: json['removed']! as int,
      );

  final bool dryRun;
  final List<String> entries;
  final int removed;
}

final class I18nQueryResult {
  const I18nQueryResult({
    required this.revision,
    required this.entries,
    this.nextCursor,
  });

  factory I18nQueryResult.fromJson(Map<String, Object?> json) =>
      I18nQueryResult(
        revision: json['revision']! as int,
        entries: (json['entries']! as List)
            .map((e) => I18nEntry.fromJson(e as Map<String, Object?>))
            .toList(),
        nextCursor: json['nextCursor'] as String?,
      );

  final int revision;
  final List<I18nEntry> entries;
  final String? nextCursor;
}

final class LangProgress {
  const LangProgress({
    required this.lang,
    required this.translated,
    required this.missing,
    required this.stale,
    required this.orphan,
  });

  factory LangProgress.fromJson(Map<String, Object?> json) => LangProgress(
    lang: json['lang']! as String,
    translated: json['translated']! as int,
    missing: json['missing']! as int,
    stale: json['stale']! as int,
    orphan: json['orphan']! as int,
  );

  final String lang;
  final int translated;
  final int missing;
  final int stale;
  final int orphan;
}

// ---------------------------------------------------------------------------
// history / logs / tasks
// ---------------------------------------------------------------------------

/// 导出历史条目：内核写在配置的 cache_dir 下 `history.json`
/// （格式 `desktop-history/1`，最新在前、最多 5 条，CLI 不写）。
/// `result` 是稳定状态码（当前仅 `success`），展示文本由客户端本地化。
final class HistoryEntry {
  const HistoryEntry({
    required this.time,
    required this.scope,
    required this.result,
    required this.tables,
    required this.elapsed,
    required this.forced,
    this.error = '',
  });

  factory HistoryEntry.fromJson(Map<String, Object?> json) => HistoryEntry(
    time: json['time']! as String,
    scope: json['scope']! as String,
    result: json['result']! as String,
    tables: json['tables']! as int,
    elapsed: (json['elapsed']! as num).toDouble(),
    forced: json['forced']! as bool,
    error: (json['error'] as String?) ?? '',
  );

  final String time;
  final String scope;
  final String result;
  final int tables;
  final double elapsed;
  final bool forced;
  final String error;
}

/// worker 日志条目（区别于本地 UI 的 models/log_entry.dart LogEntry）。
final class RemoteLogEntry {
  const RemoteLogEntry({
    required this.ts,
    required this.module,
    required this.level,
    required this.message,
    this.requestId,
  });

  factory RemoteLogEntry.fromJson(Map<String, Object?> json) => RemoteLogEntry(
    ts: json['ts']! as String,
    module: json['module']! as String,
    level: json['level']! as String,
    message: json['message']! as String,
    requestId: json['requestId'] as int?,
  );

  final String ts;
  final String module;
  final String level;
  final String message;
  final int? requestId;
}

enum TaskStatus {
  running('running'),
  success('success'),
  error('error'),
  cancelled('cancelled'),

  /// worker 断连且无终态：不谎报成功/取消，不自动重放。
  unknown('unknown');

  const TaskStatus(this.wire);
  final String wire;

  static TaskStatus parse(String v) =>
      TaskStatus.values.firstWhere((e) => e.wire == v);
}

final class TaskInfo {
  const TaskInfo({
    required this.id,
    this.requestId,
    required this.method,
    required this.status,
    this.message = '',
    required this.startedAt,
    this.dismissed = false,
  });

  factory TaskInfo.fromJson(Map<String, Object?> json) => TaskInfo(
    id: json['id']! as String,
    requestId: json['requestId'] as int?,
    method: json['method']! as String,
    status: TaskStatus.parse(json['status']! as String),
    message: (json['message'] as String?) ?? '',
    startedAt: (json['startedAt']! as num).toDouble(),
    dismissed: (json['dismissed'] as bool?) ?? false,
  );

  final String id;
  final int? requestId;
  final String method;
  final TaskStatus status;
  final String message;
  final double startedAt;
  final bool dismissed;
}

List<Issue> _issues(Object? raw) =>
    (raw as List?)
        ?.map((e) => Issue.fromJson(e as Map<String, Object?>))
        .toList() ??
    const [];

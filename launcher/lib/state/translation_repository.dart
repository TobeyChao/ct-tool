import 'package:flutter/foundation.dart';

import '../services/protocol/protocol.dart';
import '../services/worker_service.dart';

/// 翻译状态筛选（`i18n.query` 的 `status`；由内核执行，客户端不再自己判）。
enum TranslationFilter {
  all(''),
  translated('translated'),
  missing('missing'),
  stale('stale'),
  orphan('orphan');

  const TranslationFilter(this.wire);

  final String wire;

  String get label => switch (this) {
    TranslationFilter.all => '全部状态',
    TranslationFilter.translated => '已翻译',
    TranslationFilter.missing => '缺失',
    TranslationFilter.stale => '过期',
    TranslationFilter.orphan => '孤立',
  };
}

/// 翻译页的数据来源（native-flutter-workbench 任务 4.1）。
///
/// 三条纪律：筛选与分页都由内核执行；改动只走 `i18n.save` 单条落盘；
/// 清理 orphan 必须先 dry-run 预检再显式执行。
class TranslationRepository extends ChangeNotifier {
  TranslationRepository({required this.worker});

  final KernelGateway worker;

  static const int pageLimit = 200;

  String _root = '';
  int _generation = 0;
  String? _workspaceId;

  /// 当前选中的表与语言（内核要求两者都选）。
  String table = '';
  String lang = '';
  TranslationFilter filter = TranslationFilter.all;

  /// 列显隐（4.1）：记「隐藏了哪些列」，切表与保存后都保留。
  final Set<String> hiddenColumns = {};

  final List<I18nEntry> entries = [];
  List<LangProgress> langs = [];
  String? _nextCursor;
  int revision = 0;

  bool loading = false;
  bool saving = false;
  bool syncing = false;
  String? error;
  String? notice;
  I18nSyncResult? lastSync;
  I18nCompactResult? lastCompact;
  String? editedKey;

  bool get busy => loading || saving || syncing;

  /// 内核按工作区归属分配的 id（用于确认数据不是上一个工作区的回声）。
  String? get workspaceId => _workspaceId;

  bool get hasWorkspace => _root.isNotEmpty;

  bool get canQuery => table.isNotEmpty && lang.isNotEmpty;

  List<String> get langNames => langs.map((l) => l.lang).toList();

  bool get canLoadMore => _nextCursor != null;

  int get shownCount => entries.length;

  bool get sampleData => false;

  /// 绑定工作区：先取各语言进度（语言下拉与进度总览的唯一来源）。
  Future<void> bind(String root) async {
    final generation = ++_generation;
    _root = root;
    _workspaceId = null;
    entries.clear();
    _nextCursor = null;
    langs = [];
    lastSync = null;
    lastCompact = null;
    error = null;
    notice = null;
    if (root.isEmpty) {
      notifyListeners();
      return;
    }
    loading = true;
    notifyListeners();
    await _loadStatus(generation);
    await _loadPage(generation, reset: true);
    if (_isCurrent(generation)) {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> refresh() => _guard((generation) async {
    await _loadStatus(generation);
    await _loadPage(generation, reset: true);
  });

  /// 切表/切语言/改筛选：只重置分页，筛选与列显隐保留（任务 4.1 的验收点）。
  Future<void> selectTable(String name) async {
    if (table == name) return;
    table = name;
    await _reloadKeepingFilters();
  }

  Future<void> selectLang(String name) async {
    if (lang == name) return;
    lang = name;
    await _reloadKeepingFilters();
  }

  Future<void> selectFilter(TranslationFilter value) async {
    if (filter == value) return;
    filter = value;
    await _reloadKeepingFilters();
  }

  void toggleColumn(String column) {
    if (!hiddenColumns.remove(column)) hiddenColumns.add(column);
    notifyListeners();
  }

  bool shown(String column) => !hiddenColumns.contains(column);

  Future<void> loadMore() =>
      _guard((generation) => _loadPage(generation, reset: false));

  Future<void> _reloadKeepingFilters() =>
      _guard((generation) => _loadPage(generation, reset: true));

  /// 单条保存：只把这一条送内核，回来后按内核给的新状态更新该行。
  Future<bool> saveRow({
    required String key,
    required String text,
    required bool confirmed,
  }) async {
    final generation = _generation;
    if (!canQuery) return false;
    final index = entries.indexWhere((e) => e.key == key);
    if (index < 0) return false;
    final before = entries[index];
    if (before.text == text && before.confirmed == confirmed) return true;
    saving = true;
    editedKey = key;
    error = null;
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.i18nSave,
        params: {
          'table': table,
          'lang': lang,
          'key': key,
          'text': text,
          'confirmed': confirmed,
        },
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return false;
      final result = I18nSaveResult.fromJson(_map(payload));
      entries[index] = I18nEntry(
        key: key,
        source: before.source,
        text: text,
        confirmed: confirmed,
        status: result.status,
      );
      notice = '$key → ${result.status.wire}';
      return true;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return false;
      error = '${e.code}：${e.message}';
      return false;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return false;
      error = '保存失败：$e';
      return false;
    } finally {
      if (_isCurrent(generation)) {
        saving = false;
        editedKey = null;
        notifyListeners();
      }
    }
  }

  /// 丢弃当前行编辑（不改状态，只清高亮）：界面用 Esc/取消按钮触发。
  void cancelEdit() {
    if (editedKey == null) return;
    editedKey = null;
    notifyListeners();
  }

  /// 显式同步：`table` 为空即全库；结果由内核给出。
  Future<I18nSyncResult?> sync({bool scopedToTable = false}) => _run(
    () async {
      final payload = await worker.query(
        Methods.i18nSync,
        params: {if (scopedToTable && table.isNotEmpty) 'table': table},
        workspaceRoot: _root,
      );
      return I18nSyncResult.fromJson(_map(payload));
    },
    label: '同步',
    onDone: (result) {
      lastSync = result;
      notice = '已同步 ${result.tables} 张表（新增 ${result.inserted} 条）';
    },
  );

  /// 清理预检：dry-run 只返回将被删除的键，绝不写盘。
  Future<I18nCompactResult?> compactPreview({bool scopedToTable = false}) =>
      _run(
        () async {
          final payload = await worker.query(
            Methods.i18nCompact,
            params: {
              'dryRun': true,
              if (scopedToTable && table.isNotEmpty) 'table': table,
            },
            workspaceRoot: _root,
          );
          return I18nCompactResult.fromJson(_map(payload));
        },
        label: '清理预检',
        onDone: (result) {
          lastCompact = result;
          notice = '预检：将清理 ${result.removed} 条孤立';
        },
      );

  /// 真正清理：必须先看过预检（界面不放行未预检的执行）。
  Future<I18nCompactResult?> compactApply({bool scopedToTable = false}) => _run(
    () async {
      final payload = await worker.query(
        Methods.i18nCompact,
        params: {
          'dryRun': false,
          if (scopedToTable && table.isNotEmpty) 'table': table,
        },
        workspaceRoot: _root,
      );
      return I18nCompactResult.fromJson(_map(payload));
    },
    label: '清理',
    onDone: (result) {
      lastCompact = result;
      notice = '已清理 ${result.removed} 条孤立';
    },
  );

  Future<T?> _run<T>(
    Future<T> Function() body, {
    required String label,
    required void Function(T result) onDone,
  }) async {
    final generation = _generation;
    if (!canQuery) {
      error = '请先选择表和语言';
      notifyListeners();
      return null;
    }
    syncing = true;
    error = null;
    notifyListeners();
    try {
      final result = await body();
      if (!_isCurrent(generation)) return null;
      onDone(result);
      return result;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return null;
      error = '$label失败：${e.code}：${e.message}';
      return null;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return null;
      error = '$label失败：$e';
      return null;
    } finally {
      if (_isCurrent(generation)) {
        syncing = false;
        notifyListeners();
      }
    }
  }

  Future<void> _guard(Future<void> Function(int generation) body) async {
    final generation = _generation;
    if (_root.isEmpty) return;
    loading = true;
    notifyListeners();
    try {
      await body(generation);
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return;
      error = '${e.code}：${e.message}';
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      error = '读取翻译失败：$e';
    } finally {
      if (_isCurrent(generation)) {
        loading = false;
        notifyListeners();
      }
    }
  }

  Future<void> _loadStatus(int generation) async {
    final payload = await worker.query(
      Methods.i18nStatus,
      workspaceRoot: _root,
    );
    if (!_isCurrent(generation)) return;
    langs = I18nStatusResult.fromJson(_map(payload)).langs;
    _workspaceId = worker.lastWorkspaceId;
    if (lang.isEmpty && langs.isNotEmpty) lang = langs.first.lang;
  }

  Future<void> _loadPage(int generation, {required bool reset}) async {
    if (!canQuery) {
      entries.clear();
      _nextCursor = null;
      return;
    }
    if (reset) {
      entries.clear();
      _nextCursor = null;
    }
    final payload = await worker.query(
      Methods.i18nQuery,
      params: {
        'table': table,
        'lang': lang,
        if (filter != TranslationFilter.all) 'status': filter.wire,
        'page': {
          'limit': pageLimit,
          if (!reset && _nextCursor != null) 'cursor': _nextCursor,
        },
      },
      workspaceRoot: _root,
    );
    if (!_isCurrent(generation)) return;
    final result = I18nQueryResult.fromJson(_map(payload));
    entries.addAll(result.entries);
    revision = result.revision;
    _nextCursor = result.nextCursor;
    error = null;
  }

  bool _isCurrent(int generation) => generation == _generation;

  static Map<String, Object?> _map(Object? payload) =>
      payload is Map<String, Object?>
      ? payload
      : throw StateError('payload 形状异常');
}

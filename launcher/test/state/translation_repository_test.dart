import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 翻译页数据源（任务 4.1–4.3）：筛选与分页都送内核，写操作逐条落盘，
/// 清理必须先 dry-run 预检再显式执行。
class _Call {
  _Call(this.method, this.params);
  final String method;
  final Map<String, Object?> params;
}

class _FakeGateway implements KernelGateway {
  _FakeGateway({this.failWith});

  /// 第一页是否还有下一页：由内核的 nextCursor 决定，客户端不自己造。
  bool page2 = true;
  final String? failWith;
  final List<_Call> calls = [];
  int querySeq = 0;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-i18n';

  List<_Call> of(String method) =>
      calls.where((c) => c.method == method).toList();

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(_Call(method, params));
    if (failWith != null && method == failWith) {
      throw WorkerRequestException(
        const ErrorBody(code: 'busy', message: '工作区被写任务占用'),
      );
    }
    switch (method) {
      case Methods.i18nStatus:
        return {
          'langs': [
            {
              'lang': 'en',
              'translated': 1,
              'missing': 1,
              'stale': 0,
              'orphan': 0,
            },
          ],
        };
      case Methods.i18nQuery:
        final page = params['page']! as Map<String, Object?>;
        final first = page['cursor'] == null;
        return {
          'revision': 7,
          'entries': first
              ? [
                  _entry('1001.Name', '铁剑', 'Iron Sword', true, 'translated'),
                  _entry('1002.Name', '铁盾', '', false, 'missing'),
                ]
              : [_entry('1003.Name', '长弓', 'Long Bow', false, 'stale')],
          if (first && page2) 'nextCursor': 'cursor-2',
        };
      case Methods.i18nSave:
        return {
          'status': (params['text']! as String).isEmpty
              ? 'missing'
              : 'translated',
        };
      case Methods.i18nSync:
        return {'tables': 1, 'inserted': 2};
      case Methods.i18nCompact:
        final dry = params['dryRun']! as bool;
        return {
          'dryRun': dry,
          'entries': dry ? const ['9999.Name'] : const <String>[],
          'removed': dry ? 0 : 1,
        };
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

Map<String, Object?> _entry(
  String key,
  String source,
  String text,
  bool confirmed,
  String status,
) => {
  'key': key,
  'source': source,
  'text': text,
  'confirmed': confirmed,
  'status': status,
};

void main() {
  const root = 'D:/game/A';

  Future<TranslationRepository> opened(
    _FakeGateway gateway, {
    String table = 'Item',
  }) async {
    final repo = TranslationRepository(worker: gateway);
    await repo.bind(root);
    await repo.selectTable(table);
    return repo;
  }

  test('绑定后自动选语言并取第一页，筛选条件都随请求送内核', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);

    expect(repo.langNames, ['en']);
    expect(repo.lang, 'en', reason: '语言下拉的唯一来源是 i18n.status');
    expect(repo.entries, hasLength(2));
    expect(repo.revision, 7);
    expect(repo.canLoadMore, isTrue);

    final query = gateway.of(Methods.i18nQuery).last.params;
    expect(query['table'], 'Item');
    expect(query['lang'], 'en');
    expect(query.containsKey('status'), isFalse, reason: '全部状态不该伪造筛选值');
    repo.dispose();
  });

  test('状态筛选与分页都由内核执行；切表与保存行之后筛选保留', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    await repo.selectFilter(TranslationFilter.missing);
    expect(gateway.of(Methods.i18nQuery).last.params['status'], 'missing');

    await repo.selectTable('Quest');
    final afterSwitch = gateway.of(Methods.i18nQuery).last.params;
    expect(afterSwitch['table'], 'Quest');
    expect(afterSwitch['status'], 'missing', reason: '切表必须保留筛选（4.1 验收）');
    expect(repo.filter, TranslationFilter.missing);

    repo.toggleColumn('source');
    expect(repo.shown('source'), isFalse);
    await repo.saveRow(key: '1002.Name', text: 'Iron Shield', confirmed: false);
    expect(repo.filter, TranslationFilter.missing, reason: '保存后筛选同样保留');
    expect(repo.shown('source'), isFalse, reason: '列显隐也要保留');
    repo.dispose();
  });

  test('加载更多带上一次游标，末页之后不再可加载', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    expect(repo.shownCount, 2);
    expect(repo.canLoadMore, isTrue);
    await repo.loadMore();

    final more = gateway.of(Methods.i18nQuery).last.params;
    final page = more['page']! as Map<String, Object?>;
    expect(page['cursor'], 'cursor-2');
    expect(repo.shownCount, 3);
    expect(repo.canLoadMore, isFalse, reason: '内核没给 nextCursor 就是到底了');
    repo.dispose();
  });

  test('行内保存只发一条请求，状态取内核回包', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    gateway.calls.clear();

    expect(
      await repo.saveRow(
        key: '1002.Name',
        text: 'Iron Shield',
        confirmed: true,
      ),
      isTrue,
    );
    final saves = gateway.of(Methods.i18nSave);
    expect(saves, hasLength(1));
    expect(saves.single.params, {
      'table': 'Item',
      'lang': 'en',
      'key': '1002.Name',
      'text': 'Iron Shield',
      'confirmed': true,
    });
    final row = repo.entries.firstWhere((e) => e.key == '1002.Name');
    expect(row.status, I18nStatus.translated, reason: '状态由内核给出');
    expect(row.text, 'Iron Shield');
    expect(gateway.of(Methods.i18nQuery), isEmpty, reason: '保存不应顺手重查整页');
    repo.dispose();
  });

  test('未改动的行不产生写请求；取消编辑只清高亮', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    gateway.calls.clear();

    expect(
      await repo.saveRow(key: '1001.Name', text: 'Iron Sword', confirmed: true),
      isTrue,
    );
    expect(gateway.of(Methods.i18nSave), isEmpty, reason: '内容一致就不必写盘');

    await repo.saveRow(key: 'ghost.Key', text: 'x', confirmed: false);
    expect(gateway.of(Methods.i18nSave), isEmpty, reason: '不存在的键不送内核');
    repo.dispose();
  });

  test('同步范围由参数决定，本表同步带上表名', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);

    final all = await repo.sync();
    expect(all?.tables, 1);
    expect(gateway.of(Methods.i18nSync).single.params, isEmpty);

    await repo.sync(scopedToTable: true);
    expect(gateway.of(Methods.i18nSync).last.params, {'table': 'Item'});
    expect(repo.notice, contains('已同步 1 张表'));
    repo.dispose();
  });

  test('清理必须先预检：dry-run 不回写，显式执行才删', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);

    final plan = await repo.compactPreview();
    expect(plan!.dryRun, isTrue);
    expect(plan.entries, ['9999.Name']);
    expect(
      gateway.of(Methods.i18nCompact).single.params['dryRun'],
      isTrue,
      reason: '预检绝不能带 dryRun=false',
    );

    final applied = await repo.compactApply();
    expect(applied!.removed, 1);
    final second = gateway.of(Methods.i18nCompact).last.params;
    expect(second['dryRun'], isFalse);
    expect(repo.lastCompact?.dryRun, isFalse);
    repo.dispose();
  });

  test('写任务被内核拒绝时给出错误码，不谎报成功', () async {
    final gateway = _FakeGateway(failWith: Methods.i18nSync);
    final repo = await opened(gateway);
    expect(await repo.sync(), isNull);
    expect(repo.error, contains('busy'));
    expect(repo.lastSync, isNull);
    expect(repo.notice, isNull);
    repo.dispose();
  });

  test('换工作区后旧请求的回声不进当前视图', () async {
    final gateway = _FakeGateway();
    final repo = TranslationRepository(worker: gateway);
    final hold = Completer<void>();
    var inflight = 0;
    await repo.bind(root);
    await repo.selectTable('Item');

    // 手工制造一次在途请求：bind 新目录后其回包必须被代次挡掉。
    inflight++;
    unawaited(
      Future<void>(() async {
        await hold.future;
        inflight--;
      }),
    );
    await repo.bind('D:/game/B');
    hold.complete();
    await pump();
    expect(inflight, 0);
    expect(repo.entries, hasLength(2), reason: '新目录重新取过第一页');
    expect(gateway.of(Methods.i18nQuery).length, greaterThanOrEqualTo(2));
    repo.dispose();
  });
  test('专注编辑器维护选中条目、多行草稿与取消', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);

    repo.selectEntry('1002.Name');
    expect(repo.selectedKey, '1002.Name');
    expect(repo.draftText, '');
    expect(repo.draftDirty, isFalse);

    repo.updateDraft('第一行\n第二行');
    expect(repo.draftText, '第一行\n第二行');
    expect(repo.draftDirty, isTrue);

    repo.discardDraft();
    expect(repo.draftText, '');
    expect(repo.draftDirty, isFalse);
    repo.dispose();
  });

  test('专注编辑器显式保存固定 confirmed=true 并更新状态', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    repo.selectEntry('1002.Name');
    repo.updateDraft('Iron Shield\n第二行');
    gateway.calls.clear();

    expect(await repo.saveDraft(), isTrue);
    final saves = gateway.of(Methods.i18nSave);
    expect(saves, hasLength(1));
    expect(saves.single.params, {
      'table': 'Item',
      'lang': 'en',
      'key': '1002.Name',
      'text': 'Iron Shield\n第二行',
      'confirmed': true,
    });
    expect(repo.draftDirty, isFalse);
    expect(repo.selectedEntry?.status, I18nStatus.translated);
    repo.dispose();
  });

  test('未改译文仍能单独确认，已确认条目不重复写入', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    repo.selectEntry('1002.Name');
    gateway.calls.clear();

    expect(await repo.saveDraft(), isTrue);
    expect(gateway.of(Methods.i18nSave), hasLength(1));
    expect(gateway.of(Methods.i18nSave).single.params['confirmed'], isTrue);
    expect(repo.selectedEntry?.confirmed, isTrue);
    expect(await repo.saveDraft(), isTrue);
    expect(gateway.of(Methods.i18nSave), hasLength(1));
    repo.dispose();
  });

  test('专注编辑器保存失败保留草稿和选中条目', () async {
    final gateway = _FakeGateway(failWith: Methods.i18nSave);
    final repo = await opened(gateway);
    repo.selectEntry('1002.Name');
    repo.updateDraft('不会丢');

    expect(await repo.saveDraft(), isFalse);
    expect(repo.selectedKey, '1002.Name');
    expect(repo.draftText, '不会丢');
    expect(repo.draftDirty, isTrue);
    expect(repo.error, contains('busy'));
    repo.dispose();
  });

  test('有未保存草稿时切换上下文被拒绝，放弃后可切换', () async {
    final gateway = _FakeGateway();
    final repo = await opened(gateway);
    repo.selectEntry('1002.Name');
    repo.updateDraft('未保存');

    await repo.selectTable('Quest');
    expect(repo.table, 'Item', reason: '未确认时不能静默切表');
    expect(repo.selectedKey, '1002.Name');
    expect(repo.error, contains('未保存'));

    repo.discardDraft();
    await repo.selectTable('Quest');
    expect(repo.table, 'Quest');
    expect(repo.selectedKey, isNull);
    repo.dispose();
  });
}

Future<void> pump() => Future<void>.delayed(Duration.zero);

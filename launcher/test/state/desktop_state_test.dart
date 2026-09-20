import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:flutter_test/flutter_test.dart';

/// 桌面状态查询（native-flutter-workbench 任务 4.5/4.8）：
/// 有界日志分页、模块/级别筛选、任务问题按需分页、关闭通知，以及旧工作区竞态守卫。
class _Call {
  _Call(this.method, this.params, this.root);
  final String method;
  final Map<String, Object?> params;
  final String root;
}

class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final List<_Call> calls = [];
  final Map<String, Object? Function(_Call)> replies = {};
  final Map<String, String> ids = {};

  /// 日志分页脚本：按游标返回一页结果。
  Map<String, Object?>? Function(_Call)? logsByCall;
  bool failAppendOnce = false;
  String? holdRoot;
  final Map<String, Completer<void>> gates = {};

  @override
  WorkerStatus status = WorkerStatus.ready;

  @override
  String? failureReason;

  @override
  String? lastWorkspaceId;

  Map<String, Object?>? logsPage(_Call call) {
    final page = call.params['page']! as Map<String, Object?>;
    final cursor = page['cursor'] as String?;
    final generator = logsByCall;
    if (generator == null) return null;
    if (cursor != null && failAppendOnce) {
      failAppendOnce = false;
      throw WorkerRequestException(
        const ErrorBody(code: 'stale-page', message: '分页令牌已过期，请整页重查'),
      );
    }
    return generator(call);
  }

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    final call = _Call(method, params, workspaceRoot ?? '');
    calls.add(call);
    if (holdRoot != null && call.root == holdRoot) {
      await gates.putIfAbsent(call.root, Completer<void>.new).future;
    }
    lastWorkspaceId = ids[call.root];
    switch (method) {
      case Methods.logsList:
        return logsPage(call);
      case Methods.historyList:
        return replies[method]!(call);
      case Methods.tasksList:
        return replies[method]!(call);
      case Methods.tasksIssues:
        return replies[method]!(call);
      case Methods.tasksDismiss:
        return replies[method]!(call);
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

Map<String, Object?> logRow(
  String module,
  String message, {
  String level = 'info',
}) => {
  'ts': '2026-09-18T10:00:00Z',
  'module': module,
  'level': level,
  'message': message,
  'requestId': 7,
};

void main() {
  const aRoot = 'D:/game/a';
  const bRoot = 'D:/game/b';

  /// 默认脚本：A 工作区两页日志、一条历史、一个任务（带 2 个问题）。
  _FakeGateway scripted({_FakeGateway? override}) {
    final gw = _FakeGateway();
    gw.ids[aRoot] = 'ws-aaa';
    gw.ids[bRoot] = 'ws-bbb';
    gw.logsByCall = (call) {
      // B 工作区返回空页，便于区分「A 的迟到回包」与「B 自己的数据」。
      if (call.root == bRoot) {
        return {'entries': <Object?>[], 'revision': 12};
      }
      final page = call.params['page']! as Map<String, Object?>;
      final first = page['cursor'] == null;
      final filtered = call.params.containsKey('module');
      return first
          ? {
              'entries': [logRow('export', '第一页 1'), logRow('i18n', '第一页 2')],
              'revision': 11,
              'nextCursor': filtered ? null : 'cursor-2',
            }
          : {
              'entries': [logRow('export', '第二页 1')],
              'revision': 11,
            };
    };
    gw.replies[Methods.historyList] = (call) => {
      'entries': [
        {
          'time': '2026-09-18T10:00:00Z',
          'scope': 'all',
          'result': 'success',
          'tables': 3,
          'elapsed': 1.5,
          'forced': false,
          'error': '',
        },
        {
          'time': '2026-09-17T09:00:00Z',
          'scope': 'table:Item',
          // 旧状态码：界面必须归一显示而不是猜
          'result': 'ok',
          'tables': 1,
          'elapsed': 0.2,
          'forced': true,
          'error': '历史写失败',
        },
      ],
    };
    gw.replies[Methods.tasksList] = (call) => {
      'tasks': [
        {
          'id': 'task-1',
          'requestId': 7,
          'method': 'export',
          'status': 'success',
          'message': '',
          'startedAt': 1760000000.0,
          'dismissed': false,
        },
      ],
    };
    gw.replies[Methods.tasksIssues] = (call) => {
      'issues': [
        {
          'code': 'bad-ref',
          'message': '引用不存在',
          'resource': 'table:Item',
          'fieldPath': 'Owner',
          'excelRow': 12,
        },
      ],
      'revision': 11,
      'nextCursor': 'issues-2',
    };
    gw.replies[Methods.tasksDismiss] = (call) => {'outcome': 'dismissed'};
    return override ?? gw;
  }

  test('bind 一次拉齐日志/历史/任务三张表', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    expect(
      gw.calls.map((c) => c.method).toList(),
      containsAll(<String>[
        Methods.logsList,
        Methods.historyList,
        Methods.tasksList,
      ]),
    );
    expect(state.logs.length, 2);
    expect(state.tasks.single.method, 'export');
    expect(state.history.length, 2);
    expect(state.workspaceRoot, aRoot);
    expect(state.error, isNull);
    expect(state.logsHasMore, isTrue, reason: '内核给了游标');
    expect(state.logsTruncated, isTrue);
    state.dispose();
  });

  test('加载更多走下一页游标，末页之后不再可加载', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    await state.loadMoreLogs();
    expect(state.logs.map((e) => e.message).toList(), [
      '第一页 1',
      '第一页 2',
      '第二页 1',
    ]);
    expect(state.logsHasMore, isFalse);
    final before = gw.calls.length;
    await state.loadMoreLogs();
    expect(gw.calls.length, before, reason: '没有游标时不得再发请求');
    state.dispose();
  });

  test('模块/级别筛选回到第一页并带上参数', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    await state.setLogFilter(module: 'export', level: 'warn');
    final call = gw.calls.lastWhere((c) => c.method == Methods.logsList);
    expect(call.params['module'], 'export');
    expect(call.params['level'], 'warn');
    expect((call.params['page']! as Map)['cursor'], isNull);
    expect(state.logModule, 'export');
    expect(state.logLevel, 'warn');
    expect(state.logsHasMore, isFalse, reason: '筛选页不再给游标');
    state.dispose();
  });

  test('翻页遇到 stale-page 自动整页重查，不谎报丢事件', () async {
    final gw = scripted()..failAppendOnce = true;
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    await state.loadMoreLogs();
    expect(state.error, isNull, reason: state.error ?? '');
    expect(state.logs.map((e) => e.message).toList(), ['第一页 1', '第一页 2']);
    final methods = gw.calls
        .where((c) => c.method == Methods.logsList)
        .map((c) => (c.params['page']! as Map).containsKey('cursor'))
        .toList();
    expect(methods, [false, true, false], reason: '带游标失败后应回首页重查');
    state.dispose();
  });

  test('任务问题按需分页；关闭通知后重读任务列表', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    expect(state.issuesOf('task-1'), isNull, reason: '未点问题不得预取明细');

    await state.loadIssues('task-1');
    final page = state.issuesOf('task-1')!;
    expect(page.issues.single.code, 'bad-ref');
    expect(page.issues.single.excelRow, 12);
    expect(page.revision, 11);
    expect(page.nextCursor, 'issues-2');

    await state.dismiss('task-1');
    final dismiss = gw.calls.lastWhere((c) => c.method == Methods.tasksDismiss);
    expect(dismiss.params['taskId'], 'task-1');
    expect(
      gw.calls.where((c) => c.method == Methods.tasksList).length,
      greaterThan(1),
      reason: '关闭后必须重读任务列表以确认状态',
    );
    state.dispose();
  });

  test('切换工作区后旧回包与旧事件都不进当前视图', () async {
    final gw = scripted()..holdRoot = aRoot;
    final state = DesktopStateRepository(worker: gw);
    final first = state.bind(aRoot);
    await state.bind(bRoot);
    expect(state.logs, isEmpty);

    gw.gates[aRoot]!.complete();
    await first;
    await Future<void>.delayed(Duration.zero);
    expect(state.logs, isEmpty, reason: 'A 的回包必须被丢弃');
    expect(state.workspaceRoot, bRoot);
    expect(state.generation, 2);

    var repaints = 0;
    state.addListener(() => repaints++);
    await state.onWorkerEvent(
      const LogEvent(
        requestId: 1,
        workspaceId: 'ws-aaa',
        seq: 1,
        module: 'export',
        level: 'info',
        message: '旧工作区事件',
      ),
    );
    expect(repaints, 0, reason: '旧 workspaceId 的事件不得进入当前视图');
    state.dispose();
  });

  test('当前工作区的终态事件触发任务与历史重查', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    final tasks = gw.calls.where((c) => c.method == Methods.tasksList).length;
    await state.onWorkerEvent(
      const ResultMessage(
        requestId: 9,
        workspaceId: 'ws-aaa',
        seq: 3,
        payload: {'outcome': 'succeeded'},
      ),
    );
    expect(
      gw.calls.where((c) => c.method == Methods.tasksList).length,
      greaterThan(tasks),
    );
    expect(
      gw.calls.where((c) => c.method == Methods.historyList).length,
      greaterThan(1),
    );
    state.dispose();
  });

  test('实时日志事件按当前工作区追加进有界列表', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind(aRoot);
    final before = state.logs.length;
    await state.onWorkerEvent(
      const LogEvent(
        requestId: 9,
        workspaceId: 'ws-aaa',
        seq: 4,
        module: 'export',
        level: 'info',
        message: '实时行',
      ),
    );
    expect(state.logs.length, before + 1);
    expect(state.logs.last.message, '实时行');
    state.dispose();
  });

  test('未绑定工作区时不发任何请求', () async {
    final gw = scripted();
    final state = DesktopStateRepository(worker: gw);
    await state.bind('');
    expect(gw.calls, isEmpty);
    expect(state.logs, isEmpty);
    state.dispose();
  });
}

/// 工作台壳接真实内核数据（native-flutter-workbench 任务 2.3 的界面侧证据）。
///
/// 数据来源是 [WorkbenchRepository]（假网关提供内核回包），验证：资源列表/总览/只读预览
/// 全部来自内核应答；切换工作区后旧工作区的迟到回包不会回到界面上。
library;

import 'dart:async';

import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Call {
  _Call(this.method, this.root, this.params);
  final String method;
  final String root;
  final Map<String, Object?> params;
}

class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final Map<String, Object? Function(_Call call)> replies = {};
  final Map<String, String> ids = {};
  final List<_Call> calls = [];
  String? holdRoot;
  final Map<String, Completer<void>> gates = {};

  @override
  WorkerStatus status = WorkerStatus.ready;

  @override
  String? failureReason;

  @override
  String? lastWorkspaceId;

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    final call = _Call(method, workspaceRoot ?? '', params);
    calls.add(call);
    if (holdRoot != null && call.root == holdRoot) {
      await gates.putIfAbsent(call.root, Completer<void>.new).future;
    }
    lastWorkspaceId = ids[call.root];
    return replies['$method@${call.root}']!(call);
  }
}

Map<String, Object?> _snapshot(
  int revision, {
  int tables = 1,
  int records = 0,
  int enums = 0,
}) => {
  'revision': revision,
  'status': 'ready',
  'recovery': {'needed': false, 'journals': <String>[]},
  'tables': tables,
  'records': records,
  'enums': enums,
};

Map<String, Object?> _resources(List<List<String>> rows) => {
  'revision': 1,
  'resources': rows
      .map((r) => {'name': r[0], 'kind': r[1], 'sourcePath': r[2]})
      .toList(),
};

Map<String, Object?> _preview(int revision, List<List<Object?>> rows) => {
  'revision': revision,
  'columns': [
    {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
    {'name': 'Name', 'typeExpr': 'string', 'role': null},
  ],
  'rows': rows,
};

Future<void> pumpLive(WidgetTester tester, WorkbenchRepository repo) async {
  tester.view.physicalSize = const Size(1400, 900);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      theme: buildCtTheme(),
      home: WorkbenchScreen(
        data: repo,
        refresh: repo,
        onResourceSelected: repo.loadPreview,
        workspaceKey: 'live-test',
        bannerLabel: '已连接原生内核 · 只读',
      ),
    ),
  );
  await tester.pump();
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const aRoot = 'D:/game/gd';
  const bRoot = 'D:/work/other';

  _FakeGateway buildGateway() {
    final gw = _FakeGateway()
      ..ids[aRoot] = 'ws-aaaa'
      ..ids[bRoot] = 'ws-bbbb'
      ..replies.addAll({
        'workspace.open@$aRoot': (_) => _snapshot(7, tables: 1, enums: 1),
        'resources.list@$aRoot': (_) => _resources([
          ['Item', 'table', 'config/schemas/item.yaml'],
          ['Rarity', 'enum', 'config/types/rarity.yaml'],
        ]),
        'table.preview@$aRoot': (_) => _preview(7, [
          [1001, '铁剑'],
          [1002, '铁盾'],
        ]),
        'workspace.open@$bRoot': (_) => _snapshot(12, tables: 1),
        'resources.list@$bRoot': (_) => _resources([
          ['Quest', 'table', 'config/schemas/quest.yaml'],
        ]),
        'table.preview@$bRoot': (_) => _preview(12, [
          [1, 'daily'],
        ]),
      });
    return gw;
  }

  testWidgets('资源列表、总览与只读预览都来自内核回包', (tester) async {
    final gw = buildGateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(aRoot);
    await pumpLive(tester, repo);

    // 资源区：来自 resources.list
    expect(find.textContaining('Item'), findsWidgets);
    expect(find.textContaining('Rarity'), findsWidgets);
    expect(find.textContaining('模拟数据（MOCK）'), findsNothing);
    expect(find.textContaining('已连接原生内核 · 只读'), findsOneWidget);

    // 只读预览：选中表后按 table.preview 渲染
    await tester.tap(find.textContaining('Item').first);
    await tester.pumpAndSettle();
    await repo.loadPreview('Item');
    await tester.pumpAndSettle();
    await tester.tap(find.text('数据预览'));
    await tester.pumpAndSettle();
    // 页脚改成真实分页口径（任务 5.2）：行数 + 内核给的页态。
    expect(find.textContaining('已显示 2 行'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.previewCount')), findsOneWidget);
    expect(find.text('铁剑'), findsWidgets);
    expect(find.text('Id'), findsWidgets);

    // 总览：分类计数取自 resources.list，代次取自 workspace.open
    await tester.tap(find.text('总览'));
    await tester.pumpAndSettle();
    expect(find.text('工作区总览'), findsOneWidget);
    expect(find.textContaining('表 1 · 记录 0 · 枚举 1'), findsOneWidget);
    expect(find.textContaining('schemaRevision 7'), findsOneWidget);
    expect(
      find.textContaining('总览统计当前为模拟数据'),
      findsNothing,
      reason: '真实来源不得再显示样板文案',
    );
    repo.dispose();
  });

  testWidgets('切换工作区后，旧工作区的迟到回包不回到界面', (tester) async {
    final gw = buildGateway()..holdRoot = aRoot;
    final repo = WorkbenchRepository(worker: gw);
    final first = repo.switchWorkspace(aRoot);
    await pumpLive(tester, repo);
    expect(find.textContaining('加载中'), findsNothing);

    await repo.switchWorkspace(bRoot);
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Quest'), findsWidgets);
    expect(find.textContaining('Item'), findsNothing);

    gw.gates[aRoot]!.complete();
    await first;
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Item'), findsNothing, reason: 'A 的回包必须被丢弃');
    expect(find.textContaining('Rarity'), findsNothing);
    expect(find.textContaining('Quest'), findsWidgets);
    repo.dispose();
  });

  testWidgets('打开失败时界面显示内核给出的原因', (tester) async {
    final gw = buildGateway();
    gw.replies['workspace.open@$aRoot'] = (_) =>
        throw StateError('config/global.yaml 缺少 primary_lang');
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(aRoot);
    await pumpLive(tester, repo);
    expect(find.textContaining('读取工作区失败'), findsWidgets);
    expect(find.textContaining('primary_lang'), findsWidgets);
    repo.dispose();
  });
}

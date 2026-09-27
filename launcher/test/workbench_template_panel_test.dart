import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/template_service.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 模板入口界面（任务 3.6）：只给 Table 放按钮，生成永远在预检之后。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.canGenerate = true});

  final bool canGenerate;
  final List<String> methods = [];

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-tpl-ui';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    methods.add(method);
    return switch (method) {
      Methods.workspaceOpen => {
        'revision': 2,
        'status': 'ready',
        'recovery': {'needed': false, 'journals': <String>[]},
        'tables': 1,
        'records': 0,
        'enums': 1,
      },
      Methods.resourcesList => {
        'revision': 2,
        'schemaRevision': 'baseline-tpl',
        'resources': [
          {
            'name': 'Item',
            'kind': 'table',
            'sourcePath': 'config/schemas/item.yaml',
          },
          {
            'name': 'Rarity',
            'kind': 'enum',
            'sourcePath': 'config/types/rarity.yaml',
          },
        ],
      },
      Methods.tablePreview => {
        'revision': 2,
        'columns': const [
          {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
        ],
        'rows': const <Object?>[],
      },
      Methods.templatePlan => {
        'canGenerate': canGenerate,
        'actions': const ['生成空模板（工作簿不存在）'],
        'warnings': const <Object?>[],
        'problems': canGenerate
            ? const <Object?>[]
            : [
                {
                  'code': 'template',
                  'message': 'Item 的 Excel 缺少布局 manifest，无法安全迁移',
                },
              ],
      },
      Methods.templateGenerate => {
        'migratedRows': 0,
        'warnings': const <Object?>[],
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }
}

void main() {
  late _FakeGateway gateway;
  late TemplateService service;

  WorkbenchScreen shell(_FakeGateway gw, TemplateService tpl) =>
      WorkbenchScreen(
        data: StaticWorkbenchData(
          workspaceName: 'gd',
          workspacePath: 'D:/game/A',
          resources: const [
            WorkbenchResource(
              name: 'Item',
              kind: WorkbenchResourceKind.table,
              path: 'config/schemas/item.yaml',
              fields: [
                WorkbenchField(name: 'Id', type: 'int32', role: 'primary'),
              ],
            ),
            WorkbenchResource(
              name: 'Rarity',
              kind: WorkbenchResourceKind.enumType,
              path: 'config/types/rarity.yaml',
            ),
          ],
        ),
        template: tpl,
      );

  Future<void> open(WidgetTester tester, {String? select}) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(theme: buildCtTheme(), home: shell(gateway, service)),
    );
    await tester.pumpAndSettle();
    if (select != null) {
      await tester.tap(
        find.ancestor(of: find.text(select), matching: find.byType(InkWell)),
      );
      await tester.pumpAndSettle();
    }
  }

  TextButton button(WidgetTester tester, String key) =>
      tester.widget<TextButton>(
        find.descendant(
          of: find.byKey(ValueKey(key)),
          matching: find.byType(TextButton),
        ),
      );

  setUp(() {
    gateway = _FakeGateway();
    service = TemplateService(worker: gateway, workspaceRoot: 'D:/game/A');
  });

  tearDown(() => service.dispose());

  testWidgets('通用主次按钮在禁用时都有清晰的颜色变化', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: Column(
            children: [
              CtButton.accent(
                '可生成',
                key: const ValueKey('accentOn'),
                onPressed: () {},
              ),
              const CtButton.accent(
                '不可生成',
                key: ValueKey('accentOff'),
                onPressed: null,
              ),
              CtButton.ghost(
                '可预检',
                key: const ValueKey('ghostOn'),
                onPressed: () {},
              ),
              const CtButton.ghost(
                '不可预检',
                key: ValueKey('ghostOff'),
                onPressed: null,
              ),
            ],
          ),
        ),
      ),
    );
    TextButton inner(String key) => tester.widget<TextButton>(
      find.descendant(
        of: find.byKey(ValueKey(key)),
        matching: find.byType(TextButton),
      ),
    );
    final mainOn = inner('accentOn').style!;
    final mainOff = inner('accentOff').style!;
    expect(mainOn.backgroundColor!.resolve({}), ctAccent);
    expect(mainOff.backgroundColor!.resolve({WidgetState.disabled}), ctBorder);
    expect(mainOn.foregroundColor!.resolve({}), Colors.white);
    expect(
      mainOff.foregroundColor!.resolve({WidgetState.disabled}),
      isNot(Colors.white),
    );
    final secondaryOn = inner('ghostOn').style!;
    final secondaryOff = inner('ghostOff').style!;
    expect(secondaryOn.foregroundColor!.resolve({}), ctInk2);
    expect(
      secondaryOff.foregroundColor!.resolve({WidgetState.disabled}),
      isNot(ctInk2),
    );
    expect(secondaryOff.side!.resolve({WidgetState.disabled})!.color, ctBorder);
  });

  testWidgets('Table 给出预检与生成入口，未预检时生成禁用', (tester) async {
    await open(tester, select: 'Item');
    expect(find.byKey(const ValueKey('wb.templatePanel')), findsOneWidget);
    expect(find.text('未预检'), findsOneWidget);
    final disabledGenerate = button(tester, 'wb.templateGenerate');
    expect(disabledGenerate.onPressed, isNull);
    expect(
      disabledGenerate.style!.backgroundColor!.resolve({WidgetState.disabled}),
      ctBorder,
      reason: '未预检时主按钮不应仍显示为绿色',
    );
    expect(
      disabledGenerate.style!.foregroundColor!.resolve({WidgetState.disabled}),
      isNot(Colors.white),
    );
    expect(button(tester, 'wb.templatePlan').onPressed, isNotNull);
    expect(gateway.methods, isNot(contains(Methods.templateGenerate)));

    await tester.tap(find.byKey(const ValueKey('wb.templatePlan')));
    await tester.pumpAndSettle();
    expect(find.text('将执行：生成空模板（工作簿不存在）'), findsOneWidget);
    expect(find.text('可生成'), findsOneWidget);
    final enabledGenerate = button(tester, 'wb.templateGenerate');
    expect(enabledGenerate.onPressed, isNotNull);
    expect(enabledGenerate.style!.backgroundColor!.resolve({}), ctAccent);
    expect(enabledGenerate.style!.foregroundColor!.resolve({}), Colors.white);

    await tester.tap(find.byKey(const ValueKey('wb.templateGenerate')));
    await tester.pumpAndSettle();
    expect(gateway.methods, contains(Methods.templateGenerate));
    expect(find.textContaining('已生成'), findsOneWidget);
  });

  testWidgets('预检阻塞时生成仍然禁用，并把内核问题原样列出', (tester) async {
    gateway = _FakeGateway(canGenerate: false);
    service = TemplateService(worker: gateway, workspaceRoot: 'D:/game/A');
    await open(tester, select: 'Item');

    await tester.tap(find.byKey(const ValueKey('wb.templatePlan')));
    await tester.pumpAndSettle();
    expect(find.text('被阻塞'), findsOneWidget);
    expect(find.textContaining('缺少布局 manifest'), findsOneWidget);
    expect(button(tester, 'wb.templateGenerate').onPressed, isNull);
    expect(
      gateway.methods.where((m) => m == Methods.templateGenerate),
      isEmpty,
      reason: '阻塞状态下不许发写请求',
    );
  });

  testWidgets('Enum 没有独立 Excel 模板入口', (tester) async {
    await open(tester, select: 'Rarity');
    expect(find.byKey(const ValueKey('wb.templateNotTable')), findsOneWidget);
    expect(find.textContaining('没有独立 Excel 模板'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.templatePlan')), findsNothing);
    expect(find.byKey(const ValueKey('wb.templateGenerate')), findsNothing);
  });
}

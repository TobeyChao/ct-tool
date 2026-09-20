import 'package:ct_launcher/services/exit_guard.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 退出守卫（native-flutter-workbench 任务 4.7）：只在真有未保存草稿或在跑写任务时打断，
/// 结论由调用方执行；关掉对话框等同「留下」。
Future<void> pumpTrigger(
  WidgetTester tester, {
  required bool hasDraft,
  required bool runningTask,
  bool trayResident = false,
  bool draftNotPersisted = false,
  required void Function(ExitDecision) onResult,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: buildCtTheme(),
      home: Builder(
        builder: (context) => Center(
          child: CtButton.accent(
            'go',
            key: const ValueKey('t.go'),
            onPressed: () async {
              onResult(
                await confirmExit(
                  context,
                  hasDraft: hasDraft,
                  runningTask: runningTask,
                  draftNotPersisted: draftNotPersisted,
                  trayResident: trayResident,
                ),
              );
            },
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  test('只有未保存草稿或在跑写任务才需要征询', () {
    expect(needsExitPrompt(hasDraft: false, runningTask: false), isFalse);
    expect(needsExitPrompt(hasDraft: true, runningTask: false), isTrue);
    expect(needsExitPrompt(hasDraft: false, runningTask: true), isTrue);
  });

  testWidgets('无风险时直接放行，不弹确认框', (tester) async {
    ExitDecision? got;
    await pumpTrigger(
      tester,
      hasDraft: false,
      runningTask: false,
      onResult: (d) => got = d,
    );
    await tester.tap(find.byKey(const ValueKey('t.go')));
    await tester.pumpAndSettle();
    expect(got, ExitDecision.exitNow);
    expect(find.byKey(const ValueKey('wb.exitDialog')), findsNothing);
  });

  testWidgets('有草稿时说明风险，选留下就不退出', (tester) async {
    ExitDecision? got;
    await pumpTrigger(
      tester,
      hasDraft: true,
      runningTask: false,
      onResult: (d) => got = d,
    );
    await tester.tap(find.byKey(const ValueKey('t.go')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wb.exitDialog')), findsOneWidget);
    expect(find.textContaining('未保存的 Schema 草稿'), findsOneWidget);
    expect(find.textContaining('写任务正在运行'), findsNothing, reason: '没在跑任务就不要吓人');
    expect(
      find.byKey(const ValueKey('wb.exitTray')),
      findsNothing,
      reason: '没有任务时不提供隐藏托盘',
    );

    await tester.tap(find.byKey(const ValueKey('wb.exitStay')));
    await tester.pumpAndSettle();
    expect(got, ExitDecision.stay);
  });

  testWidgets('写任务在跑时给出隐藏托盘与仍退出两条路', (tester) async {
    final picked = <ExitDecision>[];
    await pumpTrigger(
      tester,
      hasDraft: false,
      runningTask: true,
      trayResident: true,
      onResult: picked.add,
    );
    await tester.tap(find.byKey(const ValueKey('t.go')));
    await tester.pumpAndSettle();
    expect(find.textContaining('有写任务正在运行'), findsOneWidget);
    expect(find.textContaining('安全顺序'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('wb.exitTray')));
    await tester.pumpAndSettle();
    expect(picked, [ExitDecision.hideToTray]);

    await tester.tap(find.byKey(const ValueKey('t.go')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.exitConfirm')));
    await tester.pumpAndSettle();
    expect(picked, [ExitDecision.hideToTray, ExitDecision.exitNow]);
  });

  testWidgets('关掉对话框等同留下，不擅自退出', (tester) async {
    ExitDecision? got;
    await pumpTrigger(
      tester,
      hasDraft: true,
      runningTask: true,
      onResult: (d) => got = d,
    );
    await tester.tap(find.byKey(const ValueKey('t.go')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.exitDialog')), findsOneWidget);

    await tester.tapAt(const Offset(6, 6));
    await tester.pumpAndSettle();
    expect(got, ExitDecision.stay);
    expect(find.byKey(const ValueKey('wb.exitDialog')), findsNothing);
  });
  test('草稿未持久化也要征询：失败落盘不算已保留', () {
    expect(
      needsExitPrompt(
        hasDraft: true,
        runningTask: false,
        draftNotPersisted: true,
      ),
      isTrue,
    );
    expect(
      needsExitPrompt(
        hasDraft: false,
        runningTask: false,
        draftNotPersisted: true,
      ),
      isTrue,
      reason: '没有草稿可丢，但也没保住——同样要问',
    );
  });

  testWidgets('未持久化在提示里单列一条，用户仍可显式退出', (tester) async {
    ExitDecision? got;
    await pumpTrigger(
      tester,
      hasDraft: false,
      runningTask: false,
      draftNotPersisted: true,
      onResult: (d) => got = d,
    );
    await tester.tap(find.byKey(const ValueKey('t.go')));
    await tester.pumpAndSettle();
    expect(find.textContaining('尚未写入用户目录'), findsOneWidget);
    expect(find.textContaining('未保存的 Schema 草稿'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('wb.exitConfirm')));
    await tester.pumpAndSettle();
    expect(got, ExitDecision.exitNow, reason: '警告在先，退出仍是用户的明确选择');
  });
}

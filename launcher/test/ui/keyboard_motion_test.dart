import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/search_picker.dart';
import 'package:ct_launcher/ui/widgets/type_picker.dart';
import 'package:ct_launcher/ui/workbench/workbench_quick_open.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Future<void> mount(
    WidgetTester tester,
    Widget child, {
    required bool reduceMotion,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        builder: (context, app) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(disableAnimations: reduceMotion),
          child: app!,
        ),
        home: Scaffold(body: child),
      ),
    );
  }

  testWidgets('Quick Open 关闭后焦点回到呼出按钮', (tester) async {
    final opener = FocusNode();
    addTearDown(opener.dispose);
    await mount(
      tester,
      TextButton(
        focusNode: opener,
        onPressed: () => showWorkbenchQuickOpen(
          tester.element(find.byType(TextButton)),
          entries: const [QuickOpenEntry(name: 'Item', kindLabel: 'Table')],
          recents: const [],
        ),
        child: const Text('打开'),
      ),
      reduceMotion: false,
    );
    opener.requestFocus();
    await tester.pump();
    expect(opener.hasPrimaryFocus, isTrue);

    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<EditableText>(find.byType(EditableText)).focusNode.hasFocus,
      isTrue,
    );
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(opener.hasPrimaryFocus, isTrue);
  });

  for (final reduceMotion in [false, true]) {
    testWidgets('Quick Open 键盘滚动可见且响应动态效果=$reduceMotion', (tester) async {
      final entries = List.generate(
        30,
        (i) => QuickOpenEntry(
          name: 'Entry${i.toString().padLeft(2, '0')}',
          kindLabel: 'Table',
        ),
      );
      QuickOpenEntry? picked;
      await mount(
        tester,
        TextButton(
          onPressed: () async {
            picked = await showWorkbenchQuickOpen(
              tester.element(find.byType(TextButton)),
              entries: entries,
              recents: const [],
            );
          },
          child: const Text('打开'),
        ),
        reduceMotion: reduceMotion,
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
      final list = tester.state<ScrollableState>(
        find.descendant(
          of: find.byKey(const ValueKey('wb.quickOpen.results')),
          matching: find.byType(Scrollable),
        ),
      );
      for (var i = 0; i < 6; i++) {
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
        await tester.pumpAndSettle();
      }
      final pixels = list.position.pixels;
      expect(pixels, greaterThan(0));
      final chosen = find.byKey(const ValueKey('wb.quickOpen.row.Entry06.6'));
      expect(chosen, findsOneWidget);
      final row = tester.getRect(chosen);
      final viewport = tester.getRect(
        find.byKey(const ValueKey('wb.quickOpen.results')),
      );
      expect(row.top, greaterThanOrEqualTo(viewport.top));
      expect(row.bottom, lessThanOrEqualTo(viewport.bottom));
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
      // 减少动态效果时，滚动在同一次按键里已经落位；普通模式仍有过渡。
      expect(list.position.pixels > pixels, reduceMotion);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(picked?.name, 'Entry07');
    });

    testWidgets('具名类型键盘滚动与减少动态效果=$reduceMotion', (tester) async {
      String? picked;
      await mount(
        tester,
        CtTypePicker(
          value: 'int32',
          namedTypes: List.generate(
            35,
            (i) => 'Record${i.toString().padLeft(2, '0')}',
          ),
          onChanged: (value) => picked = value,
        ),
        reduceMotion: reduceMotion,
      );
      await tester.tap(find.byKey(const ValueKey('ct.type.base')));
      await tester.pumpAndSettle();
      final list = tester.state<ScrollableState>(
        find.descendant(
          of: find.byKey(const ValueKey('ct.type.list')),
          matching: find.byType(Scrollable),
        ),
      );
      for (var i = 0; i < 12; i++) {
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
        await tester.pumpAndSettle();
      }
      final pixels = list.position.pixels;
      expect(pixels, greaterThan(0));
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
      expect(list.position.pixels > pixels, reduceMotion);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(picked, 'Record01');
    });

    testWidgets('搜索选择器键盘滚动与减少动态效果=$reduceMotion', (tester) async {
      String? picked;
      await mount(
        tester,
        CtSearchPicker(
          value: '',
          options: List.generate(
            35,
            (i) => 'Choice${i.toString().padLeft(2, '0')}',
          ),
          onChanged: (value) => picked = value,
          title: '选择项目',
          keyPrefix: 'motion.search',
        ),
        reduceMotion: reduceMotion,
      );
      await tester.tap(find.byKey(const ValueKey('motion.search.picker')));
      await tester.pumpAndSettle();
      final list = tester.state<ScrollableState>(
        find.descendant(
          of: find.byKey(const ValueKey('motion.search.list')),
          matching: find.byType(Scrollable),
        ),
      );
      for (var i = 0; i < 11; i++) {
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
        await tester.pumpAndSettle();
      }
      final pixels = list.position.pixels;
      expect(pixels, greaterThan(0));
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
      expect(list.position.pixels > pixels, reduceMotion);
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(picked, 'Choice11');
    });
  }
}

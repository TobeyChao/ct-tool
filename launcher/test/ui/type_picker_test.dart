import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/type_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('类型选择器可搜索数百个具名类型并用回车确认', (tester) async {
    String? picked;
    final namedTypes = List.generate(
      320,
      (i) => 'Type${i.toString().padLeft(3, '0')}',
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: CtTypePicker(
            value: 'int32',
            namedTypes: namedTypes,
            onChanged: (value) => picked = value,
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('ct.type.base')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('ct.type.dialog')), findsOneWidget);

    await tester.enterText(
      find.byKey(const ValueKey('ct.type.search')),
      'Type299',
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('ct.type.option.Type299')),
      findsOneWidget,
    );

    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(picked, 'Type299');
    expect(find.byKey(const ValueKey('ct.type.dialog')), findsNothing);
  });

  testWidgets('类型搜索无结果时保持可恢复的空态', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: CtTypePicker(
            value: 'string',
            namedTypes: const ['RecordA', 'EnumB'],
            onChanged: (_) {},
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('ct.type.base')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('ct.type.search')),
      'does_not_exist',
    );
    await tester.pumpAndSettle();
    expect(find.text('没有匹配的类型'), findsOneWidget);

    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('ct.type.dialog')), findsNothing);
  });
}

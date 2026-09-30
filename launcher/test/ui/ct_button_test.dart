import 'dart:ui' as ui;

import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final accent in [true, false]) {
    final kind = accent ? 'accent' : 'ghost';
    for (final enabled in [true, false]) {
      testWidgets(
        'CtButton.$kind enabled=$enabled behavior, semantics and colors',
        (tester) async {
          final semantics = tester.ensureSemantics();
          try {
            var calls = 0;
            final VoidCallback? callback = enabled ? () => calls++ : null;
            await tester.pumpWidget(
              MaterialApp(
                theme: buildCtTheme(),
                home: Scaffold(
                  body: Center(
                    child: accent
                        ? CtButton.accent('Test action', onPressed: callback)
                        : CtButton.ghost('Test action', onPressed: callback),
                  ),
                ),
              ),
            );
            final finder = find.byType(TextButton);
            final data = tester.getSemantics(finder).getSemanticsData();
            expect(data.label, 'Test action');
            expect(data.flagsCollection.isButton, isTrue);
            expect(
              data.flagsCollection.isEnabled,
              enabled ? ui.Tristate.isTrue : ui.Tristate.isFalse,
            );
            expect(data.hasAction(ui.SemanticsAction.tap), enabled);

            final style = tester.widget<TextButton>(finder).style!;
            final background = enabled
                ? (accent ? ctAccent : Colors.transparent)
                : (accent ? ctBorder : Colors.transparent);
            final foreground = enabled
                ? (accent ? Colors.white : ctInk2)
                : const Color(0xFF8A958D);
            final border = enabled
                ? (accent ? ctAccent : ctBorderStrong)
                : ctBorder;
            for (final interaction in <Set<WidgetState>>[
              {},
              {WidgetState.hovered},
              {WidgetState.focused},
              {WidgetState.pressed},
            ]) {
              final states = {
                ...interaction,
                if (!enabled) WidgetState.disabled,
              };
              expect(style.backgroundColor!.resolve(states), background);
              expect(style.foregroundColor!.resolve(states), foreground);
              expect(style.side!.resolve(states)!.color, border);
              expect(
                style.overlayColor!.resolve(states),
                enabled
                    ? (accent ? ctAccentHover : ctSurface2)
                    : Colors.transparent,
              );
            }
            // Inspect the rendered colors too: the Material theme must not replace
            // the explicit disabled state with its SDK defaults.
            expect(
              tester
                  .widget<Material>(
                    find
                        .descendant(of: finder, matching: find.byType(Material))
                        .first,
                  )
                  .color,
              background,
            );
            expect(
              tester
                  .renderObject<RenderParagraph>(find.text('Test action'))
                  .text
                  .style!
                  .color,
              foreground,
            );
            await tester.tap(finder);
            await tester.pumpAndSettle();
            expect(calls, enabled ? 1 : 0);
          } finally {
            semantics.dispose();
          }
        },
      );
    }
  }
}

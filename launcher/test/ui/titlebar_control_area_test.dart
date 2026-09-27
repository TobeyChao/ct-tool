import 'package:ct_launcher/ui/widgets/titlebar_control_area.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('macOS registers measured bounds and removes them on disposal', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.macOS;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    const channel = MethodChannel('ct/titlebar_controls');
    final calls = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      calls.add(call);
      return null;
    });
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        null,
      ),
    );
    final position = ValueNotifier<double>(80);
    addTearDown(position.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: ValueListenableBuilder<double>(
          valueListenable: position,
          builder: (context, x, child) => Stack(
            children: [
              Positioned(
                left: x,
                top: 4,
                child: const CtTitlebarControlArea(
                  child: SizedBox(width: 40, height: 32),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    expect(calls.single.method, 'update');
    final initial = Map<Object?, Object?>.from(calls.single.arguments as Map);
    expect(initial['x'], 80);
    expect(initial['y'], 4);
    expect(initial['width'], 40);
    expect(initial['height'], 32);
    // Reposition without changing size; metrics notifications must update it.
    position.value = 100;
    await tester.pump();
    tester.binding.handleMetricsChanged();
    await tester.pump();
    await tester.pump();
    expect((calls.last.arguments as Map)['x'], 100);
    expect((calls.last.arguments as Map)['id'], initial['id']);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(calls.last.method, 'remove');
    expect((calls.last.arguments as Map)['id'], initial['id']);
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('failed native registration retries without a layout change', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.macOS;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    const channel = MethodChannel('ct/titlebar_controls');
    var attempts = 0;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      if (call.method == 'update' && ++attempts == 1) {
        throw PlatformException(code: 'temporarilyUnavailable');
      }
      return null;
    });
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        null,
      ),
    );
    await tester.pumpWidget(
      const MaterialApp(
        home: CtTitlebarControlArea(child: SizedBox(width: 40, height: 32)),
      ),
    );
    await tester.pump();
    expect(attempts, 1);
    // Let the failed platform response complete before advancing the retry timer.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    await tester.pump();
    expect(attempts, 2);
    await tester.pumpWidget(const SizedBox());
    debugDefaultTargetPlatformOverride = null;
  });
}

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Registers a Flutter control's actual bounds with the macOS event dispatcher.
/// AppKit must not interpret this control's clicks as titlebar double clicks.
class CtTitlebarControlArea extends StatefulWidget {
  const CtTitlebarControlArea({super.key, required this.child});

  final Widget child;

  @override
  State<CtTitlebarControlArea> createState() => _CtTitlebarControlAreaState();
}

class _CtTitlebarControlAreaState extends State<CtTitlebarControlArea>
    with WidgetsBindingObserver {
  static const _channel = MethodChannel('ct/titlebar_controls');
  static int _nextId = 0;
  final String _id = 'control-${_nextId++}';
  Rect? _lastBounds;
  bool _updateScheduled = false;
  Timer? _retryTimer;

  bool get _isMacOS => !kIsWeb && defaultTargetPlatform == TargetPlatform.macOS;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeMetrics() => _scheduleUpdate();

  void _scheduleUpdate() {
    if (!_isMacOS || _updateScheduled) return;
    _updateScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      _updateScheduled = false;
      if (!mounted) return;
      final box = context.findRenderObject() as RenderBox?;
      if (box == null || !box.attached || !box.hasSize) return;
      final bounds = box.localToGlobal(Offset.zero) & box.size;
      if (bounds == _lastBounds) return;
      try {
        await _channel.invokeMethod<void>('update', {
          'id': _id,
          'x': bounds.left,
          'y': bounds.top,
          'width': bounds.width,
          'height': bounds.height,
        });
        if (mounted) _lastBounds = bounds;
      } on PlatformException {
        if (mounted) {
          _retryTimer?.cancel();
          _retryTimer = Timer(
            const Duration(milliseconds: 250),
            _scheduleUpdate,
          );
        }
      }
    });
    // A retry or metrics callback can happen without a pending Flutter frame.
    WidgetsBinding.instance.scheduleFrame();
  }

  @override
  void dispose() {
    _retryTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    if (_isMacOS) _channel.invokeMethod<void>('remove', {'id': _id});
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        _scheduleUpdate();
        return widget.child;
      },
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// 跨模块草稿条与导航的快捷键意图（native-flutter-workbench 任务 4.9，5.1 逐键验收）。
///
/// 只用带修饰键的组合（外加 F1），不占单键，避免与中文输入法的直接键位冲突。
class WbQuickOpenIntent extends Intent {
  const WbQuickOpenIntent();
}

class WbSaveDraftIntent extends Intent {
  const WbSaveDraftIntent();
}

class WbUndoStepIntent extends Intent {
  const WbUndoStepIntent();
}

class WbRedoStepIntent extends Intent {
  const WbRedoStepIntent();
}

class WbNetDiffIntent extends Intent {
  const WbNetDiffIntent();
}

class WbHelpIntent extends Intent {
  const WbHelpIntent();
}

/// 一条键位绑定：标签、说明与 activator 同源，「帮助与关于」里的表直接读它，
/// 避免出现"文档写的键和实际绑的键不一样"。
@immutable
class WbShortcutBinding {
  const WbShortcutBinding({
    required this.label,
    required this.description,
    required this.intent,
    required this.activators,
  });

  final String label;
  final String description;
  final Intent intent;
  final List<ShortcutActivator> activators;
}

/// Windows/Linux 走 Ctrl、macOS 走 Cmd：两套都注册，标签统一写 Ctrl/Cmd。
List<WbShortcutBinding> wbShortcutBindings() {
  List<ShortcutActivator> pair(LogicalKeyboardKey key, {bool shift = false}) =>
      [
        SingleActivator(key, control: true, shift: shift),
        SingleActivator(key, meta: true, shift: shift),
      ];
  return [
    WbShortcutBinding(
      label: 'Ctrl/Cmd+P',
      description: 'Quick Open：按名字模糊跳到资源（空查询给最近打开）',
      intent: const WbQuickOpenIntent(),
      activators: pair(LogicalKeyboardKey.keyP),
    ),
    WbShortcutBinding(
      label: 'Ctrl/Cmd+S',
      description: '保存 Schema 草稿（schemaRevision + candidateHash 双守卫）',
      intent: const WbSaveDraftIntent(),
      activators: pair(LogicalKeyboardKey.keyS),
    ),
    WbShortcutBinding(
      label: 'Ctrl/Cmd+Z',
      description: '撤销一步草稿；输入框聚焦时让给文本撤销',
      intent: const WbUndoStepIntent(),
      activators: pair(LogicalKeyboardKey.keyZ),
    ),
    WbShortcutBinding(
      label: 'Ctrl/Cmd+Shift+Z',
      description: '重做一步草稿；输入框聚焦时让给文本重做',
      intent: const WbRedoStepIntent(),
      activators: pair(LogicalKeyboardKey.keyZ, shift: true),
    ),
    WbShortcutBinding(
      label: 'Ctrl/Cmd+Shift+D',
      description: '打开候选净差异（含 ordinal 与 API 名称风险）',
      intent: const WbNetDiffIntent(),
      activators: pair(LogicalKeyboardKey.keyD, shift: true),
    ),
    WbShortcutBinding(
      label: 'F1',
      description: '帮助与关于：内核版本、协议、能力数与本页快捷键',
      intent: const WbHelpIntent(),
      activators: const [SingleActivator(LogicalKeyboardKey.f1)],
    ),
  ];
}

/// 工作台全局快捷键容器：回调为 null 时该键位不动作（样板数据即如此）。
class WorkbenchShortcuts extends StatelessWidget {
  const WorkbenchShortcuts({
    super.key,
    required this.child,
    this.onQuickOpen,
    this.onSaveDraft,
    this.onUndo,
    this.onRedo,
    this.onNetDiff,
    this.onHelp,
  });

  final Widget child;
  final VoidCallback? onQuickOpen;
  final VoidCallback? onSaveDraft;
  final VoidCallback? onUndo;
  final VoidCallback? onRedo;
  final VoidCallback? onNetDiff;
  final VoidCallback? onHelp;

  /// 焦点是否落在可编辑文本里：是则撤销/重做归文本框，草稿游标不动。
  static bool textEditingFocused() {
    final element = FocusManager.instance.primaryFocus?.context;
    if (element == null) return false;
    return element.findAncestorWidgetOfExactType<EditableText>() != null;
  }

  @override
  Widget build(BuildContext context) {
    final bindings = wbShortcutBindings();
    return Shortcuts(
      key: const ValueKey('wb.shortcuts'),
      shortcuts: {
        for (final binding in bindings)
          for (final activator in binding.activators) activator: binding.intent,
      },
      child: Actions(
        actions: <Type, Action<Intent>>{
          WbQuickOpenIntent: CallbackAction<WbQuickOpenIntent>(
            onInvoke: (_) {
              onQuickOpen?.call();
              return null;
            },
          ),
          WbSaveDraftIntent: CallbackAction<WbSaveDraftIntent>(
            onInvoke: (_) {
              onSaveDraft?.call();
              return null;
            },
          ),
          WbUndoStepIntent: CallbackAction<WbUndoStepIntent>(
            onInvoke: (_) {
              if (textEditingFocused()) return null;
              onUndo?.call();
              return null;
            },
          ),
          WbRedoStepIntent: CallbackAction<WbRedoStepIntent>(
            onInvoke: (_) {
              if (textEditingFocused()) return null;
              onRedo?.call();
              return null;
            },
          ),
          WbNetDiffIntent: CallbackAction<WbNetDiffIntent>(
            onInvoke: (_) {
              onNetDiff?.call();
              return null;
            },
          ),
          WbHelpIntent: CallbackAction<WbHelpIntent>(
            onInvoke: (_) {
              onHelp?.call();
              return null;
            },
          ),
        },
        child: Focus(
          // 没有任何输入框聚焦时（刚进工作台、点了不可聚焦的行），
          // 键事件仍要落到本树的祖先链上，否则全局键位整个失灵。
          autofocus: true,
          skipTraversal: true,
          debugLabel: 'wb-shortcut-root',
          child: child,
        ),
      ),
    );
  }
}

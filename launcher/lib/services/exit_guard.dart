import 'package:flutter/material.dart';

import '../theme.dart';
import '../ui/tokens.dart';
import '../ui/widgets/common.dart';

/// 退出决策：留在原地、隐藏到托盘、真的退出。
enum ExitDecision { stay, hideToTray, exitNow }

/// 是否需要打断用户去确认退出（任务 4.7）。
///
/// 只看两件客观事实：有没有未保存草稿、有没有写任务在跑。
/// 两者都没有就不啰嗦，直接退出。
bool needsExitPrompt({
  required bool hasDraft,
  required bool runningTask,
  bool draftNotPersisted = false,
}) => hasDraft || runningTask || draftNotPersisted;

/// 退出前的统一守卫：把风险说清楚，但结论由调用方执行（本函数不改任何状态）。
///
/// 关闭对话框（Esc / 点遮罩）等同「留下」；有任务在跑且托盘常驻时多给一个
/// 「先隐藏到托盘」的选项，让 worker 继续把写任务跑到发布边界。
Future<ExitDecision> confirmExit(
  BuildContext context, {
  required bool hasDraft,
  required bool runningTask,
  required bool trayResident,
  bool draftNotPersisted = false,
}) async {
  if (!needsExitPrompt(
    hasDraft: hasDraft,
    runningTask: runningTask,
    draftNotPersisted: draftNotPersisted,
  )) {
    return ExitDecision.exitNow;
  }
  final risks = <String>[
    if (hasDraft) '有未保存的 Schema 草稿：退出不会自动落盘，下次启动仍能看到草稿。',
    if (draftNotPersisted) '草稿尚未写入用户目录：退出会丢掉这些未持久化的编辑。',
    if (runningTask) '有写任务正在运行：现在退出可能停在发布边界之前，下次启动需要先恢复。',
  ];
  final decision = await showDialog<ExitDecision>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      key: const ValueKey('wb.exitDialog'),
      title: const Text('退出 ct 工作台？'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final risk in risks)
            Padding(
              padding: const EdgeInsets.only(bottom: ctGapSm),
              child: Text(risk, style: ctText(size: ctFontSm)),
            ),
          if (runningTask)
            Text(
              '安全顺序：等任务到发布边界后再退出。',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
        ],
      ),
      actions: [
        if (trayResident && runningTask)
          CtButton.ghost(
            '先隐藏到托盘',
            key: const ValueKey('wb.exitTray'),
            onPressed: () =>
                Navigator.pop(dialogContext, ExitDecision.hideToTray),
          ),
        CtButton.ghost(
          '留下',
          key: const ValueKey('wb.exitStay'),
          onPressed: () => Navigator.pop(dialogContext, ExitDecision.stay),
        ),
        CtButton.accent(
          '仍退出',
          key: const ValueKey('wb.exitConfirm'),
          onPressed: () => Navigator.pop(dialogContext, ExitDecision.exitNow),
        ),
      ],
    ),
  );
  return decision ?? ExitDecision.stay;
}

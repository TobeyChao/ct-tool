import 'package:flutter/material.dart';

import '../../theme.dart';
import '../tokens.dart';

/// 状态徽章语调（任务状态、草稿/冲突提示、资源标记共用）
enum CtBadgeTone { neutral, ok, warn, danger, busy, info }

/// 紧凑状态徽章：小圆点/图标 + 标签，浅底深字。
class CtStatusBadge extends StatelessWidget {
  const CtStatusBadge({
    super.key,
    required this.label,
    this.tone = CtBadgeTone.neutral,
    this.dot = true,
  });

  final String label;
  final CtBadgeTone tone;
  final bool dot;

  (Color, Color) get _colors => switch (tone) {
    CtBadgeTone.neutral => (ctInk2, ctSurface2),
    CtBadgeTone.ok => (ctAccentHover, ctAccentSofter),
    CtBadgeTone.warn => (ctWarn, ctWarnSoft),
    CtBadgeTone.danger => (ctDanger, ctDangerSoft),
    CtBadgeTone.busy => (ctGoldText, ctGoldSoft),
    CtBadgeTone.info => (ctPrimary, ctAccentSofter),
  };

  @override
  Widget build(BuildContext context) {
    final (fg, bg) = _colors;
    return Container(
      constraints: const BoxConstraints(minHeight: 20),
      padding: const EdgeInsets.symmetric(horizontal: ctGapSm, vertical: 1),
      decoration: BoxDecoration(color: bg, borderRadius: ctRadiusSmAll),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (dot) ...[
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(shape: BoxShape.circle, color: fg),
            ),
            const SizedBox(width: 5),
          ],
          Text(
            label,
            style: ctText(size: ctFontXs, color: fg, weight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../../services/settings_store.dart';
import '../../state/workbench_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import 'workbench_models.dart';

/// 草稿持久化与恢复的状态横幅（native-flutter-workbench 任务 3.5）。
///
/// 三种"不该悄悄过去"的情况都要说话：基线冲突、格式不认识的留档、
/// 以及落盘失败；外加旧浏览器草稿的一次性迁移提示。任何一条都不自动改文件。
class WorkbenchDraftBanners extends StatelessWidget {
  const WorkbenchDraftBanners({
    super.key,
    required this.data,
    this.repo,
    this.settings,
  });

  final WorkbenchData data;
  final WorkbenchRepository? repo;
  final SettingsStore? settings;

  @override
  Widget build(BuildContext context) {
    final found = <Widget>[];
    if (data.hasDraftConflict) {
      found.add(
        _banner(
          key: 'wb.draftConflict',
          text:
              '草稿的 Schema 基线已变（${data.conflictReason ?? '基线不符'}）：'
              '原始草稿已保留，编辑和保存已暂停；请先核对并处理该草稿。',
          fg: ctDanger,
          bg: ctDangerSoft,
          action: CtButton.ghost(
            '丢弃该草稿文件',
            key: const ValueKey('wb.draftDiscardStored'),
            onPressed: repo?.discardStoredDraft,
          ),
        ),
      );
    }
    final damaged = data.damagedDraftPath;
    if (damaged != null) {
      found.add(
        _banner(
          key: 'wb.draftDamaged',
          text: '用户目录里的草稿格式不认识，已保留供查看：$damaged；编辑已暂停，请先核对该文件。',
          action: CtButton.ghost(
            '移除该文件',
            key: const ValueKey('wb.draftRemoveDamaged'),
            onPressed: repo?.discardStoredDraft,
          ),
        ),
      );
    }
    if (!data.draftPersisted) {
      found.add(
        _banner(
          key: 'wb.draftNotPersisted',
          text: '草稿尚未落盘（${data.persistError ?? '未知原因'}）：内存编辑仍在，请重试保存。',
          action: CtButton.ghost(
            '重试落盘',
            key: const ValueKey('wb.draftRetryPersist'),
            onPressed: repo?.persistDraft,
          ),
        ),
      );
    }
    final store = settings;
    if (store != null && !store.legacyDraftNoticeSeen) {
      found.add(
        _banner(
          key: 'wb.legacyDraftNotice',
          text:
              '旧版 Web 面板的浏览器草稿（IndexedDB）不会自动迁移：'
              '请先在旧端保存或导出，再清理浏览器数据。',
          action: CtButton.ghost(
            '知道了',
            key: const ValueKey('wb.legacyDraftAck'),
            onPressed: store.acknowledgeLegacyDraftNotice,
          ),
        ),
      );
    }
    if (found.isEmpty) return const SizedBox.shrink();
    return Column(
      key: const ValueKey('wb.draftBanners'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: found,
    );
  }

  Widget _banner({
    required String key,
    required String text,
    required Widget? action,
    Color fg = ctWarn,
    Color bg = ctWarnSoft,
  }) => Container(
    key: ValueKey(key),
    margin: const EdgeInsets.only(bottom: ctGapMd),
    padding: const EdgeInsets.all(ctGapMd),
    decoration: BoxDecoration(color: bg, borderRadius: ctRadiusMdAll),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(
            text,
            style: ctText(size: ctFontSm, color: fg),
          ),
        ),
        const SizedBox(width: ctGapSm),
        action!,
      ],
    ),
  );
}

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import 'workbench_shortcuts.dart';

/// 桌面壳版本：与 `launcher/pubspec.yaml` 的 version 同步（不引入运行时包信息插件）。
const String kWbShellVersion = '0.1.0+1';

/// 外部文档入口：仓库里的使用文档目录。打不开只提示，不影响任何业务操作。
const String kWbDocsUrl =
    'https://github.com/TobeyChao/ct-tool/tree/main/ct/docs';

/// 帮助与关于（native-flutter-workbench 任务 4.9）。
///
/// 版本、协议、能力数都来自 worker 握手回显；快捷键表直接读 `wbShortcutBindings()`，
/// 保证界面写的键位就是实际绑定的键位。业务范围说明逐条对应内核契约，不写做不到的事。
Future<void> showWorkbenchAbout(
  BuildContext context, {
  required List<String> facts,
  required String workspaceLabel,
}) async {
  var docsResult = '未尝试';
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('帮助与关于'),
      content: SizedBox(
        width: 620,
        child: StatefulBuilder(
          builder: (context, setState) => SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'ct 工作台桌面壳 $kWbShellVersion · 工作区 $workspaceLabel',
                  key: const ValueKey('wb.about.title'),
                  style: ctText(size: ctFontMd, weight: FontWeight.w600),
                ),
                const SizedBox(height: ctGapSm),
                for (final fact in facts)
                  Text(
                    fact,
                    key: ValueKey('wb.about.fact.${facts.indexOf(fact)}'),
                    style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk2),
                  ),
                const SizedBox(height: ctGapLg),
                Text(
                  '业务范围',
                  style: ctText(size: ctFontSm, weight: FontWeight.w600),
                ),
                for (final line in kWbScopeLines)
                  Padding(
                    padding: const EdgeInsets.only(top: ctGapXs),
                    child: Text(
                      '· $line',
                      style: ctText(size: ctFontXs, color: ctInk2),
                    ),
                  ),
                const SizedBox(height: ctGapLg),
                Text(
                  '快捷键',
                  style: ctText(size: ctFontSm, weight: FontWeight.w600),
                ),
                for (final binding in wbShortcutBindings())
                  Row(
                    key: ValueKey('wb.about.shortcut.${binding.label}'),
                    children: [
                      SizedBox(
                        width: 150,
                        child: Text(
                          binding.label,
                          style: ctMono.copyWith(fontSize: ctFontXs),
                        ),
                      ),
                      Expanded(
                        child: Text(
                          binding.description,
                          style: ctText(size: ctFontXs, color: ctInk2),
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: ctGapLg),
                Row(
                  children: [
                    CtButton.ghost(
                      '打开外部文档',
                      key: const ValueKey('wb.about.docs'),
                      onPressed: () async {
                        final note = await openWorkbenchDocs();
                        setState(() => docsResult = note);
                      },
                    ),
                    const SizedBox(width: ctGapSm),
                    Expanded(
                      child: Text(
                        '文档：$docsResult',
                        key: const ValueKey('wb.about.docsResult'),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: ctText(size: ctFontXs, color: ctInk3),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('关闭'),
        ),
      ],
    ),
  );
}

/// 与内核契约一一对应的范围说明（不做到的事也写清楚）。
const List<String> kWbScopeLines = [
  'Schema 编辑走草稿：候选与净差异由内核计算，保存同时校验 schemaRevision 与 candidateHash，且只写 YAML。',
  '模板生成、数据校验、导出、翻译同步、部署是各自显式的独立操作，保存与导出都不会自动部署。',
  '导出先过读取/类型/主键/ref 校验闸门再发布；成功账本只在成功后推进，失败由工作区锁与恢复器还原。',
  '类型、主键、ref、枚举 ordinal 等合法性一律以内核回包为准，界面不重复实现第二套业务判断。',
  '草稿存在用户目录（按工作区与基线隔离）：崩溃或异基线重启只提示不套用，也不静默删除。',
];

/// 外部文档入口：侧栏「导出文档」与关于对话框共用同一实现与同一 URL。
Future<String> openWorkbenchDocs() => _openExternalDocs();

Future<String> _openExternalDocs() async {
  final uri = Uri.parse(kWbDocsUrl);
  try {
    final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    return opened ? '已在系统默认浏览器打开' : '系统拒绝打开（浏览器未关联？）';
  } on Object catch (e) {
    return '打开失败：$e（可手动访问 $kWbDocsUrl）';
  }
}

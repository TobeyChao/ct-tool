import 'package:flutter/material.dart';

import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';

/// 控件样板页（native-flutter-workbench 1.2）：
/// 按钮、字段行、状态徽章、焦点与中英文字体样板，供人工检查一致性。
///
/// 本页只用于视觉走查，不接任何业务数据。
class ComponentGallery extends StatelessWidget {
  const ComponentGallery({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(ctGapXl),
      children: const [
        _Section(title: '颜色令牌', child: _ColorSwatches()),
        _Section(title: '字体样板（中文 / English / 数字）', child: _FontSamples()),
        _Section(title: '按钮', child: _ButtonSamples()),
        _Section(title: '字段行与输入', child: _FieldSamples()),
        _Section(title: '状态徽章', child: _BadgeSamples()),
        _Section(title: '焦点（Tab / Shift+Tab 移动检查描边）', child: _FocusDemo()),
        _Section(title: '间距 / 圆角 / 行高', child: _DimSamples()),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: ctGapXl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: ctText(size: ctFontLg, weight: FontWeight.w600),
          ),
          const SizedBox(height: ctGapMd),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(ctGapLg),
            decoration: BoxDecoration(
              color: ctSurface,
              border: Border.all(color: ctBorder),
              borderRadius: ctRadiusMdAll,
            ),
            child: child,
          ),
        ],
      ),
    );
  }
}

class _ColorSwatches extends StatelessWidget {
  const _ColorSwatches();

  static const _entries = <(String, Color)>[
    ('ctBg', ctBg),
    ('ctSurface', ctSurface),
    ('ctSurface2', ctSurface2),
    ('ctBorder', ctBorder),
    ('ctInk', ctInk),
    ('ctInk2', ctInk2),
    ('ctPrimary', ctPrimary),
    ('ctAccent', ctAccent),
    ('ctAccentSoft', ctAccentSoft),
    ('ctAccentSofter', ctAccentSofter),
    ('ctGold', ctGold),
    ('ctGoldSoft', ctGoldSoft),
    ('ctDanger', ctDanger),
    ('ctWarn', ctWarn),
    ('ctLogBg', ctLogBg),
  ];

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: ctGapSm,
      runSpacing: ctGapSm,
      children: [
        for (final (name, color) in _entries)
          Container(
            width: 128,
            height: 58,
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: color,
              borderRadius: ctRadiusSmAll,
              border: Border.all(color: ctBorderStrong),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: ctText(
                    size: ctFontXs,
                    weight: FontWeight.w600,
                    height: 1.2,
                    color: color.computeLuminance() > 0.5
                        ? ctInk
                        : Colors.white,
                  ),
                ),
                Text(
                  '#${color.toARGB32().toRadixString(16).substring(2).toUpperCase()}',
                  style: ctMono.copyWith(
                    fontSize: 10,
                    height: 1.3,
                    color: color.computeLuminance() > 0.5
                        ? ctInk2
                        : Colors.white70,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _FontSamples extends StatelessWidget {
  const _FontSamples();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (label, size) in <(String, double)>[
          ('xxl 26', ctFontXxl),
          ('xl 18', ctFontXl),
          ('lg 14', ctFontLg),
          ('md 13', ctFontMd),
          ('sm 12', ctFontSm),
          ('xs 11', ctFontXs),
        ])
          Padding(
            padding: const EdgeInsets.only(bottom: ctGapSm),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: [
                SizedBox(
                  width: 64,
                  child: Text(
                    label,
                    style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
                  ),
                ),
                Expanded(
                  child: Text(
                    '配表导出工具 Deep Forest 0123456789',
                    style: ctText(size: size),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
          ),
        const Divider(height: ctGapXl),
        Text(
          '等宽：schemas/hero.yaml · hero_skill · 2026-09-17 12:00:00',
          style: ctMono.copyWith(fontSize: ctFontSm),
        ),
        const SizedBox(height: ctGapSm),
        Text(
          '长文混排：这是一段用于验证中英文混排换行效果的样板文字，'
          'mixed with English words like schemaRevision and candidateHash '
          '来观察断词与行高是否一致。',
          style: ctText(size: ctFontSm, color: ctInk2, height: 1.6),
        ),
      ],
    );
  }
}

class _ButtonSamples extends StatelessWidget {
  const _ButtonSamples();

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: ctGapMd,
      runSpacing: ctGapMd,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        CtButton.accent('主要操作', onPressed: () {}),
        const CtButton.accent('主要禁用', onPressed: null),
        CtButton.ghost('次要操作', onPressed: () {}),
        const CtButton.ghost('次要禁用', onPressed: null),
      ],
    );
  }
}

class _FieldSamples extends StatelessWidget {
  const _FieldSamples();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        CtSettingRow(
          label: '工作区',
          child: TextField(
            controller: TextEditingController(text: 'D:/game/gd'),
            style: ctText(size: ctFontMd),
            decoration: ctInputDecoration(),
          ),
        ),
        CtSettingRow(
          label: '端口',
          child: TextField(
            controller: TextEditingController(text: '18123'),
            style: ctText(size: ctFontMd),
            decoration: ctInputDecoration().copyWith(
              errorText: '端口被占用，请更换或停止占用进程',
            ),
          ),
        ),
        CtSettingRow(
          label: '长路径',
          child: TextField(
            controller: TextEditingController(
              text: 'D:/项目/游戏工作区/这是一个非常长的目录名称/config/schemas',
            ),
            style: ctMono.copyWith(fontSize: ctFontSm),
            decoration: ctInputDecoration(),
          ),
        ),
        CtSettingRow(
          label: '禁用态',
          child: TextField(
            enabled: false,
            controller: TextEditingController(text: '导出进行中不可编辑'),
            style: ctText(size: ctFontMd, color: ctInk3),
            decoration: ctInputDecoration(),
          ),
        ),
      ],
    );
  }
}

class _BadgeSamples extends StatelessWidget {
  const _BadgeSamples();

  @override
  Widget build(BuildContext context) {
    return const Wrap(
      spacing: ctGapSm,
      runSpacing: ctGapSm,
      children: [
        CtStatusBadge(label: '运行中', tone: CtBadgeTone.ok),
        CtStatusBadge(label: '已停止', tone: CtBadgeTone.neutral),
        CtStatusBadge(label: '进行中', tone: CtBadgeTone.busy),
        CtStatusBadge(label: '候选冲突', tone: CtBadgeTone.warn),
        CtStatusBadge(label: '失败', tone: CtBadgeTone.danger),
        CtStatusBadge(label: '草稿 · 3', tone: CtBadgeTone.info, dot: false),
        CtStatusBadge(label: '主键', tone: CtBadgeTone.info, dot: false),
        CtStatusBadge(label: '文', tone: CtBadgeTone.busy, dot: false),
      ],
    );
  }
}

/// 焦点描边演示：用焦点令牌（ctAccent 1.5px）自绘，保证非 Material 控件也有一致表现。
class _FocusDemo extends StatefulWidget {
  const _FocusDemo();

  @override
  State<_FocusDemo> createState() => _FocusDemoState();
}

class _FocusDemoState extends State<_FocusDemo> {
  final _node = FocusNode();
  bool _focused = false;

  @override
  void initState() {
    super.initState();
    _node.addListener(() => setState(() => _focused = _node.hasFocus));
  }

  @override
  void dispose() {
    _node.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: ctGapMd,
          runSpacing: ctGapMd,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Focus(
              focusNode: _node,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 100),
                padding: const EdgeInsets.symmetric(
                  horizontal: ctGapLg,
                  vertical: ctGapSm,
                ),
                decoration: BoxDecoration(
                  color: ctSurface,
                  borderRadius: ctRadiusMdAll,
                  border: Border.all(
                    color: _focused ? ctAccent : ctBorderStrong,
                    width: _focused ? ctFocusBorderWidth : ctBorderWidth,
                  ),
                ),
                child: Text('自绘焦点控件', style: ctText(size: ctFontMd)),
              ),
            ),
            CtButton.accent('Material 按钮焦点', onPressed: () {}),
            SizedBox(
              width: 200,
              child: TextField(
                style: ctText(size: ctFontMd),
                decoration: ctInputDecoration().copyWith(hintText: '输入框焦点'),
              ),
            ),
          ],
        ),
        const SizedBox(height: ctGapSm),
        Text(
          '焦点令牌：ctAccent · ${ctFocusBorderWidth}px 描边（输入框由 ctInputDecoration 统一）',
          style: ctText(size: ctFontXs, color: ctInk3),
        ),
      ],
    );
  }
}

class _DimSamples extends StatelessWidget {
  const _DimSamples();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (final (label, v) in <(String, double)>[
              ('xs 4', ctGapXs),
              ('sm 8', ctGapSm),
              ('md 12', ctGapMd),
              ('lg 16', ctGapLg),
              ('xl 24', ctGapXl),
              ('xxl 32', ctGapXxl),
            ])
              Padding(
                padding: const EdgeInsets.only(right: ctGapMd),
                child: Column(
                  children: [
                    Container(width: v, height: v, color: ctAccent),
                    const SizedBox(height: ctGapXs),
                    Text(
                      label,
                      style: ctText(size: ctFontXs, color: ctInk3),
                    ),
                  ],
                ),
              ),
          ],
        ),
        const SizedBox(height: ctGapMd),
        Wrap(
          spacing: ctGapMd,
          children: [
            for (final (label, r) in <(String, double)>[
              ('sm 6', ctRadiusSm),
              ('md 8', ctRadiusMd),
              ('lg 12', ctRadiusLg),
            ])
              Container(
                width: 56,
                height: 36,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: ctSurface2,
                  border: Border.all(color: ctBorderStrong),
                  borderRadius: BorderRadius.circular(r),
                ),
                child: Text(
                  label,
                  style: ctText(size: ctFontXs, color: ctInk2),
                ),
              ),
          ],
        ),
        const SizedBox(height: ctGapMd),
        Text(
          '行高：ctRowSm $ctRowSm（表格/树） · ctRowMd $ctRowMd（导航/面板头） · '
          'ctRowLg $ctRowLg（表单行） · 工具栏 $ctToolbarHeight',
          style: ctText(size: ctFontXs, color: ctInk3),
        ),
      ],
    );
  }
}

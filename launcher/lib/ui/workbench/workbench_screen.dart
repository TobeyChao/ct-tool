import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../theme.dart';
import '../../services/settings_store.dart';
import '../../state/export_runner.dart';
import '../../state/template_service.dart';
import '../../state/translation_repository.dart';
import '../../state/workbench_repository.dart';
import '../../state/desktop_state.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/desktop_title_bar.dart';
import '../widgets/status_badge.dart';
import 'mock/mock_data.dart';
import 'workbench_models.dart';
import 'workbench_schema_editor.dart';
import 'workbench_desktop_panel.dart';
import 'workbench_export_view.dart';
import 'workbench_i18n_view.dart';
import 'workbench_about_dialog.dart';
import 'workbench_draft_banners.dart';
import 'workbench_draft_bar.dart';
import 'workbench_quick_open.dart';
import 'workbench_shortcuts.dart';
import 'workbench_template_panel.dart';
import 'workbench_field_editor.dart';
import 'workbench_settings.dart';

/// 原生工作台壳（native-flutter-workbench 1.3）：
/// 模块导航 + 资源区 + 主编辑区 + 可调属性区。
///
/// 当前仅消费 [MockWorkspaceData] 样板数据，不接真实内核；
/// 所有写操作仅提示，不作为业务验收。面板宽度/折叠态按工作区记忆。
class WorkbenchScreen extends StatefulWidget {
  const WorkbenchScreen({
    super.key,
    required this.data,
    this.refresh,
    this.settings,
    this.kernelSummary = const [],
    this.onWorkspaceChanged,
    this.onRuntimeChanged,
    this.onReloadWorkspace,
    this.desktop,
    this.draft,
    this.runner,
    this.translations,
    this.template,
    this.writeBlockReason,
    this.onExitRequested,
    this.workspaceKey = 'mock-workspace',
    this.bannerLabel = '界面样板 · 模拟数据（MOCK），未连接内核',
    this.bannerTone,
    this.showDesktopTitleBar = false,
    this.windowMaximized = false,
    this.showWindowControls = true,
    this.titleBarLeadingInset = 0,
    this.onWindowMinimize,
    this.onWindowToggleMaximize,
    this.onWindowClose,
  });

  /// 数据来源：界面样板或真实内核仓库均可（契约见 workbench_models.dart）。
  final WorkbenchData data;

  /// 数据源异步到货时用于请求重绘（界面样板场景可为 null）。
  final Listenable? refresh;

  /// 桌面偏好（任务 2.4）：为 null 时设置模块退回占位，避免样板场景依赖偏好存储。
  final SettingsStore? settings;

  /// 内核连接摘要，逐行显示在设置模块里。
  final List<String> kernelSummary;

  final ValueChanged<String>? onWorkspaceChanged;
  final ValueChanged<String>? onRuntimeChanged;
  final VoidCallback? onReloadWorkspace;

  /// 真实草稿仓库：非空时资源区挂上「新建/改名/删除/字段/候选」编辑面板。
  final WorkbenchRepository? draft;

  /// 桌面状态仓库：为日志与历史模块提供数据。
  final DesktopStateRepository? desktop;

  /// 导出运行器（4.4/4.6）：非空时「导出」模块可操作。
  final ExportRunner? runner;

  /// 翻译页数据源（任务 4.1–4.3）：非空时「翻译」模块可用。
  final TranslationRepository? translations;

  /// 模板预检与生成服务（任务 3.6）：选中 Table 时给出模板入口。
  final TemplateService? template;

  /// 写入口禁用原因（内核未就绪/协议不兼容/能力缺失），null 表示可用。
  final String? writeBlockReason;

  /// 显式退出（任务 4.7）：壳层负责退出守卫与安全 shutdown。
  final VoidCallback? onExitRequested;
  final String workspaceKey;
  final String bannerLabel;

  /// 真实应用传入结构化状态，避免从本地化展示文案反推连接状态。
  final CtBadgeTone? bannerTone;

  /// 生产壳在 Windows/macOS 打开自绘标题栏；纯 Widget 测试默认关闭，避免平台通道依赖。
  final bool showDesktopTitleBar;
  final bool windowMaximized;
  final bool showWindowControls;
  final double titleBarLeadingInset;
  final VoidCallback? onWindowMinimize;
  final VoidCallback? onWindowToggleMaximize;
  final VoidCallback? onWindowClose;

  @override
  State<WorkbenchScreen> createState() => _WorkbenchScreenState();
}

class _WorkbenchScreenState extends State<WorkbenchScreen> {
  static const double _wName = 160;
  static const double _wType = 230;
  static const double _wRole = 80;
  static const double _wConstraint = 130;
  static const double _wDefault = 110;
  static const double _wDesc = 260;
  static const double _tableMinWidth =
      _wName + _wType + _wRole + _wConstraint + _wDefault + _wDesc;

  static const _modules = <(IconData, String, String)>[
    (Icons.dashboard_outlined, '总览', ''),
    (Icons.table_chart_outlined, 'Schema', ''),
    (Icons.translate, '翻译', ''),
    (Icons.rocket_launch_outlined, '导出', ''),
    (Icons.receipt_long_outlined, '日志', ''),
    (Icons.history, '历史', ''),
    (Icons.settings_outlined, '设置', ''),
  ];

  int _module = 1;
  double _resourceWidth = ctResourcePanelDefault;
  double _inspectorWidth = ctInspectorDefault;
  bool _resourceCollapsed = false;
  bool _inspectorCollapsed = false;
  bool _layoutLoaded = false;

  /// 折叠意图：用户手动动过的区不再被断点覆盖；其余按整窗宽度同帧决定
  final Map<String, bool> _userCollapse = {};
  double _lastWidth = 0;
  bool _sidebarCollapsed = false;
  bool _resizingResource = false;
  bool _resizingInspector = false;
  String _query = '';

  /// Quick Open 的最近打开清单，按工作区键持久化（任务 3.7）。
  final List<String> _recentResources = [];

  /// 类型/ref 跳转的来源栈：跳过去还能跳回来（任务 3.7）。
  final List<String> _navBack = [];
  String? _selectedResource;
  int _selectedField = -1;

  @override
  void initState() {
    super.initState();
    widget.refresh?.addListener(_onDataChanged);
    // 首屏优先展示主编辑器：有资源时预选首个。
    final resources = widget.data.resources;
    if (resources.isNotEmpty) {
      _selectedResource = resources.first.name;
    }
    _loadLayout();
  }

  void _onDataChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.refresh?.removeListener(_onDataChanged);
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant WorkbenchScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.refresh, widget.refresh)) {
      oldWidget.refresh?.removeListener(_onDataChanged);
      widget.refresh?.addListener(_onDataChanged);
    }
    if (_currentResource == null) {
      _selectedResource = null;
      _selectedField = -1;
    }
  }

  /// 内核来源的资源分类计数（表/记录/枚举）——全部取自 resources.list。
  String _kernelResourceBreakdown(WorkbenchData d) {
    int count(WorkbenchResourceKind kind) =>
        d.resources.where((r) => r.kind == kind).length;
    return '表 ${count(WorkbenchResourceKind.table)} · '
        '记录 ${count(WorkbenchResourceKind.record)} · '
        '枚举 ${count(WorkbenchResourceKind.enumType)}';
  }

  List<String> _referenceTargets() {
    final targets = <String>[];
    for (final resource in widget.data.resources) {
      if (resource.kind != WorkbenchResourceKind.table) continue;
      for (final field in resource.fields) {
        if (field.role != 'primary') continue;
        targets.add('${resource.name}.${field.name}');
        break;
      }
    }
    return targets;
  }

  String get _prefsKey => 'wb.${widget.workspaceKey}';

  Future<void> _loadLayout() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    final k = _prefsKey;
    setState(() {
      _resourceWidth = prefs.getDouble('$k.resourceWidth') ?? _resourceWidth;
      _inspectorWidth = prefs.getDouble('$k.inspectorWidth') ?? _inspectorWidth;
      _rememberCollapse('resource', prefs.getBool('$k.resourceCollapsed'));
      _rememberCollapse('inspector', prefs.getBool('$k.inspectorCollapsed'));
      _recentResources
        ..clear()
        ..addAll(prefs.getStringList('$k.recents') ?? const []);
      _layoutLoaded = true;
    });
  }

  Future<void> _saveLayout() async {
    if (!_layoutLoaded) return;
    final prefs = await SharedPreferences.getInstance();
    final k = _prefsKey;
    await prefs.setDouble('$k.resourceWidth', _resourceWidth);
    await prefs.setDouble('$k.inspectorWidth', _inspectorWidth);
    await prefs.setBool(
      '$k.resourceCollapsed',
      _userCollapse['resource'] ?? _resourceCollapsed,
    );
    await prefs.setBool(
      '$k.inspectorCollapsed',
      _userCollapse['inspector'] ?? _inspectorCollapsed,
    );
    await prefs.setStringList('$k.recents', _recentResources);
  }

  /// 折叠态在**同一帧**决定（design 决策 1）。旧实现走 postFrame，窄窗口首帧会先溢出
  /// 再折叠（实测报过 RenderFlex overflow）；用户手动动过的区不再被断点覆盖。
  void _applyBreakpoints(double width) {
    _sidebarCollapsed = _userCollapse['sidebar'] ?? width < 740;
    _resourceCollapsed = _userCollapse['resource'] ?? width < 980;
    _inspectorCollapsed = _userCollapse['inspector'] ?? width < 1180;
  }

  void _rememberCollapse(String zone, bool? value) {
    if (value != null) {
      _userCollapse[zone] = value;
    }
  }

  void _setCollapse(String zone, bool collapsed) {
    setState(() {
      _userCollapse[zone] = collapsed;
      _applyBreakpoints(_lastWidth);
    });
    _saveLayout();
  }

  MockResource? get _currentResource {
    for (final r in widget.data.resources) {
      if (r.name == _selectedResource) return r;
    }
    return null;
  }

  void _selectResource(MockResource r) {
    // 真实数据源按需拉只读预览由 _gotoResource 统一触发。
    _gotoResource(r.name, rememberRecent: true);
  }

  void _setResourceWidth(double w) {
    setState(() {
      _resourceWidth = w.clamp(ctResourcePanelMin, ctResourcePanelMax);
    });
    _saveLayout();
  }

  void _setInspectorWidth(double w) {
    setState(() {
      _inspectorWidth = w.clamp(ctInspectorMin, ctInspectorMax);
    });
    _saveLayout();
  }

  @override
  Widget build(BuildContext context) {
    return WorkbenchShortcuts(
      onQuickOpen: _openQuickOpen,
      onSaveDraft: _saveViaBar,
      onUndo: () => widget.draft?.undoDraft(),
      onRedo: () => widget.draft?.redoDraft(),
      onNetDiff: _showNetDiff,
      onHelp: _showHelp,
      child: Scaffold(
        backgroundColor: ctSurface2,
        body: Column(
          children: [
            if (widget.showDesktopTitleBar) _buildDesktopTitleBar(),
            Expanded(
              child: LayoutBuilder(
                builder: (context, box) {
                  _lastWidth = box.maxWidth;
                  _applyBreakpoints(box.maxWidth);
                  return Row(
                    children: [
                      _buildModuleRail(),
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.all(ctGapSm),
                          child: Container(
                            clipBehavior: Clip.antiAlias,
                            decoration: BoxDecoration(
                              color: ctBg,
                              borderRadius: ctRadiusLgAll,
                              border: Border.all(color: ctBorder),
                            ),
                            child: Column(
                              children: [
                                // 全局草稿条只属于内容区，没有草稿时自己收成 0 高度。
                                WorkbenchDraftBar(
                                  data: widget.data,
                                  repo: widget.draft,
                                  onSave: _saveViaBar,
                                  onQuickOpen: _openQuickOpen,
                                ),
                                Expanded(child: _buildModuleBody()),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDesktopTitleBar() {
    final firstStatusPart = widget.bannerLabel.split('·').first.trim();
    return CtDesktopTitleBar(
      title: widget.data.workspaceName.isEmpty
          ? 'ct 配表工作台'
          : widget.data.workspaceName,
      subtitle: _modules[_module].$2,
      statusLabel: firstStatusPart.isEmpty
          ? widget.bannerLabel
          : firstStatusPart,
      statusTone: widget.bannerTone ?? CtBadgeTone.neutral,
      onQuickOpen: _openQuickOpen,
      isMaximized: widget.windowMaximized,
      showWindowControls: widget.showWindowControls,
      leadingInset: widget.titleBarLeadingInset,
      onMinimize: widget.onWindowMinimize,
      onToggleMaximize: widget.onWindowToggleMaximize,
      onClose: widget.onWindowClose,
    );
  }

  // ---- 全局草稿条 / Quick Open / 帮助（任务 4.9、3.7） ----

  /// Ctrl/Cmd+P：资源清单取自内核 resources.list，空查询给最近打开。
  Future<void> _openQuickOpen() async {
    final entries = [
      for (final r in widget.data.resources)
        QuickOpenEntry(name: r.name, kindLabel: r.kind.label, path: r.path),
    ];
    if (entries.isEmpty) {
      showCtToast(context, '工作区还没有资源：先在 Schema 模块新建');
      return;
    }
    final picked = await showWorkbenchQuickOpen(
      context,
      entries: entries,
      recents: _recentResources,
    );
    if (picked == null || !mounted) return;
    _gotoResource(picked.name, rememberRecent: true);
  }

  /// 选中并跳到某资源：[fromLink] 时把当前资源压进来源栈，工具条出现返回。
  void _gotoResource(
    String name, {
    bool rememberRecent = false,
    bool fromLink = false,
  }) {
    final matches = widget.data.resources.where((r) => r.name == name).toList();
    if (matches.isEmpty) return;
    if (fromLink && _selectedResource != null && _selectedResource != name) {
      _navBack.add(_selectedResource!);
    }
    setState(() {
      _module = 1;
      _selectedResource = name;
      _selectedField = -1;
      if (rememberRecent) {
        _recentResources
          ..remove(name)
          ..insert(0, name);
        while (_recentResources.length > 8) {
          _recentResources.removeLast();
        }
      }
    });
    _saveLayout();
  }

  void _backToSource() {
    if (_navBack.isEmpty) return;
    final name = _navBack.removeLast();
    _gotoResource(name);
  }

  Future<void> _saveViaBar() async {
    final draft = widget.draft;
    if (draft == null) return;
    await _saveDraft(draft);
  }

  Future<void> _showHelp() => showWorkbenchHelp(context);

  Future<void> _showNetDiff() async {
    final draft = widget.draft;
    if (draft == null) {
      showCtToast(context, '样板数据没有内核候选，接内核后才能看净差异');
      return;
    }
    await showWorkbenchDraftSheet(context, data: widget.data, repo: draft);
  }

  Future<void> _showAbout() async {
    await showWorkbenchAbout(
      context,
      facts: widget.kernelSummary,
      workspaceLabel: widget.data.workspacePath.isEmpty
          ? '未绑定工作区'
          : widget.data.workspaceName,
    );
  }

  // ---- 模块导航 ----

  /// 文字侧栏（对齐 web 的 `.ct-sidebar`：236px、「模块」分组、图标+名称行、底部固定三项）。
  Widget _buildModuleRail() {
    return _AnimatedCollapse(
      animate: true,
      alignment: Alignment.centerLeft,
      child: _sidebarCollapsed ? _buildIconRail() : _buildExpandedModuleRail(),
    );
  }

  Widget _buildExpandedModuleRail() {
    return Container(
      key: const ValueKey('wb.sidebar'),
      width: ctSidebarWidth,
      decoration: const BoxDecoration(
        color: ctSurface2,
        border: Border(right: BorderSide(color: ctBorder)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                ctGapMd,
                ctGapMd,
                ctGapMd,
                ctGapSm,
              ),
              children: [
                _sectionLabel('工作流'),
                for (var i = 0; i < 4; i++)
                  _railItem(i, _modules[i].$1, _modules[i].$2),
                const SizedBox(height: ctGapMd),
                _sectionLabel('记录'),
                for (var i = 4; i < 6; i++)
                  _railItem(i, _modules[i].$1, _modules[i].$2),
              ],
            ),
          ),
          const Divider(
            key: ValueKey('wb.settingsDivider'),
            height: 1,
            thickness: 1,
            color: ctBorder,
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
              ctGapMd,
              ctGapSm,
              ctGapMd - 1,
              ctGapMd,
            ),
            child: SizedBox(
              width: double.infinity,
              child: _railItem(6, _modules[6].$1, _modules[6].$2, bottomGap: 0),
            ),
          ),
        ],
      ),
    );
  }

  /// 窄窗口的 56px 图标栏：只留图标与 tooltip，顶部给展开按钮。
  Widget _buildIconRail() {
    return Container(
      key: const ValueKey('wb.iconRail'),
      width: ctNavRailWidth,
      decoration: const BoxDecoration(
        color: ctSurface2,
        border: Border(right: BorderSide(color: ctBorder)),
      ),
      child: Column(
        children: [
          const SizedBox(height: ctGapMd),
          _iconBtn(
            Icons.chevron_right,
            '展开侧栏',
            () => _setCollapse('sidebar', false),
            key: const ValueKey('wb.expand.sidebar'),
          ),
          const SizedBox(height: ctGapSm),
          for (var i = 0; i < 4; i++)
            Tooltip(
              message: _modules[i].$2,
              child: _railItem(
                i,
                _modules[i].$1,
                _modules[i].$2,
                compact: true,
              ),
            ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: ctGapMd),
            child: Divider(height: ctGapLg, color: ctBorder),
          ),
          for (var i = 4; i < 6; i++)
            Tooltip(
              message: _modules[i].$2,
              child: _railItem(
                i,
                _modules[i].$1,
                _modules[i].$2,
                compact: true,
              ),
            ),
          const Spacer(),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: ctGapMd),
            child: Divider(
              key: ValueKey('wb.settingsDivider.compact'),
              height: ctGapLg,
              thickness: 1,
              color: ctBorder,
            ),
          ),
          Tooltip(
            message: _modules[6].$2,
            child: _railItem(
              6,
              _modules[6].$1,
              _modules[6].$2,
              compact: true,
              bottomGap: 0,
            ),
          ),
          const SizedBox(height: ctGapMd),
        ],
      ),
    );
  }

  Widget _sectionLabel(String label) => Padding(
    padding: const EdgeInsets.fromLTRB(ctGapSm + 3, ctGapSm, 0, ctGapXs),
    child: Text(
      label,
      style: ctText(
        size: 11,
        color: ctInk3,
        weight: FontWeight.w700,
      ).copyWith(letterSpacing: 1.1),
    ),
  );

  Future<void> _openDocs() async {
    final note = await openWorkbenchDocs();
    if (!mounted) return;
    showCtToast(context, note);
  }

  Widget _railItem(
    int index,
    IconData icon,
    String label, {
    bool compact = false,
    double bottomGap = 2,
  }) {
    final selected = _module == index;
    return Padding(
      padding: EdgeInsets.only(bottom: bottomGap),
      child: Material(
        key: ValueKey('wb.nav.$label'),
        color: selected ? ctAccentSofter : Colors.transparent,
        borderRadius: ctRadiusMdAll,
        child: InkWell(
          key: ValueKey('wb.navTap.$label'),
          onTap: () => setState(() => _module = index),
          borderRadius: ctRadiusMdAll,
          child: Container(
            constraints: const BoxConstraints(minHeight: 40),
            padding: compact
                ? const EdgeInsets.symmetric(vertical: ctGapSm + 4)
                : const EdgeInsets.symmetric(
                    horizontal: ctGapSm + 3,
                    vertical: ctGapSm + 2,
                  ),
            child: Row(
              mainAxisAlignment: compact
                  ? MainAxisAlignment.center
                  : MainAxisAlignment.start,
              children: [
                if (!compact) ...[
                  AnimatedContainer(
                    duration: ctMotionFast,
                    curve: ctMotionCurve,
                    width: 3,
                    height: 18,
                    decoration: BoxDecoration(
                      color: selected ? ctAccent : Colors.transparent,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                  const SizedBox(width: ctGapSm),
                ],
                Icon(icon, size: 16, color: selected ? ctPrimary : ctInk3),
                if (!compact) ...[
                  const SizedBox(width: ctGapSm + 2),
                  Expanded(
                    child: Text(
                      label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: ctText(
                        size: ctFontMd,
                        color: selected ? ctPrimary : ctInk2,
                        weight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildModuleBody() {
    if (_module == 0) return _buildOverview();
    if (_module == 1) return _buildSchemaBody();
    if (_module == 2 && widget.translations != null) {
      return WorkbenchI18nView(
        key: const ValueKey('wb.i18nModule'),
        repo: widget.translations!,
        tables: [
          for (final r in widget.data.resources)
            if (r.kind == WorkbenchResourceKind.table) r.name,
        ],
        busyElsewhere: widget.data.loadError ?? widget.writeBlockReason,
      );
    }
    if (_module == 3 && widget.runner != null) return _buildExport();
    if (_module == 4 && widget.desktop != null) {
      return WorkbenchLogView(
        key: const ValueKey('wb.logModule'),
        state: widget.desktop!,
      );
    }
    if (_module == 5 && widget.desktop != null) {
      return WorkbenchHistoryView(
        key: const ValueKey('wb.historyModule'),
        state: widget.desktop!,
      );
    }
    if (_module == 6 && widget.settings != null) {
      return _buildSettings();
    }
    final (_, label, planned) = _modules[_module];
    return _PlaceholderModule(label: label, planned: planned);
  }

  // ---- 导出模块（任务 4.4/4.6） ----

  Widget _buildExport() {
    return WorkbenchExportView(
      key: const ValueKey('wb.exportModule'),
      runner: widget.runner!,
      blockReason:
          widget.data.loadError ??
          widget.writeBlockReason ??
          (widget.data.busy ? '内核有写任务在跑，等它结束再提交' : null),
    );
  }

  // ---- 设置（真实偏好，任务 2.4） ----

  Widget _buildSettings() {
    return WorkbenchSettingsPanel(
      key: const ValueKey('wb.settingsPanel'),
      settings: widget.settings!,
      workspacePath: widget.data.workspacePath,
      kernelSummary: widget.kernelSummary,
      onWorkspaceChanged: widget.onWorkspaceChanged,
      onRuntimeChanged: widget.onRuntimeChanged,
      onUseInferredRuntime: widget.onReloadWorkspace,
      onReload: widget.onReloadWorkspace,
      onExit: widget.onExitRequested,
      onOpenDocs: _openDocs,
      onShowHelp: _showHelp,
      onShowAbout: _showAbout,
    );
  }

  // ---- 总览（数据来源可为样板或内核） ----

  Widget _buildOverview() {
    final d = widget.data;
    final workspaceLabel = d.workspacePath.isEmpty
        ? '未绑定工作区 · 请在设置中选择配表目录'
        : d.workspacePath;
    final workspaceState = d.loadError != null
        ? '异常'
        : d.busy
        ? '忙碌'
        : '就绪';
    final workspaceStateHint = d.loadError != null
        ? '请查看上方提示'
        : d.busy
        ? '写操作正在进行'
        : d.sampleData
        ? '界面样板'
        : '可浏览与编辑';
    return CtPageContent(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CtPageHeader(title: '工作区总览', subtitle: workspaceLabel),
          const SizedBox(height: ctGapLg),
          LayoutBuilder(
            builder: (context, box) {
              final columns = box.maxWidth >= 680
                  ? 3
                  : box.maxWidth >= 440
                  ? 2
                  : 1;
              final cardWidth =
                  (box.maxWidth - ctGapMd * (columns - 1)) / columns;
              return Wrap(
                spacing: ctGapMd,
                runSpacing: ctGapMd,
                children: [
                  SizedBox(
                    width: cardWidth,
                    child: CtStatCard(
                      number: '${d.resources.length}',
                      label: '资源',
                      sub: d.sampleData
                          ? 'Table / Record / Enum'
                          : _kernelResourceBreakdown(d),
                      icon: Icons.table_chart_outlined,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: CtStatCard(
                      number: '${d.draftCount}',
                      label: '未保存草稿',
                      sub: 'Schema 版本 ${d.schemaRevision}',
                      icon: Icons.edit_note,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: CtStatCard(
                      number: workspaceState,
                      label: '工作区状态',
                      sub: workspaceStateHint,
                      icon: Icons.health_and_safety_outlined,
                    ),
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: ctGapLg),
          if (d.recoveryNeeded) _recoveryBanner(d),
          WorkbenchDraftBanners(
            key: const ValueKey('wb.draftBannersHost'),
            data: d,
            repo: widget.draft,
            settings: widget.settings,
          ),
          if (d.sampleData)
            const _HintBanner(text: '当前为界面样板，统计来自模拟数据。')
          else if (d.loadError case final error?)
            _HintBanner(text: error),
        ],
      ),
    );
  }

  /// 异常退出后的发布事务恢复入口（任务 4.7）：结论来自内核 workspace.open。
  Widget _recoveryBanner(WorkbenchData d) {
    final journals = d.recoveryJournals;
    return Container(
      key: const ValueKey('wb.recoveryBanner'),
      margin: const EdgeInsets.only(bottom: ctGapMd),
      padding: const EdgeInsets.all(ctGapMd),
      decoration: BoxDecoration(
        color: ctWarnSoft,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorderStrong),
      ),
      child: Row(
        children: [
          const Icon(Icons.replay, size: 16, color: ctWarn),
          const SizedBox(width: ctGapSm),
          Expanded(
            child: Text(
              journals.isEmpty
                  ? '上次退出留下未完成的发布事务（内核未给出日志名）：恢复前先还原旧文件，再允许新的写入。'
                  : '上次退出留下未完成的发布事务（${journals.join('、')}）：恢复前先还原旧文件，再允许新的写入。',
              key: const ValueKey('wb.recoveryJournals'),
              style: ctText(size: ctFontSm),
            ),
          ),
          CtButton.ghost(
            '恢复',
            key: const ValueKey('wb.recover'),
            onPressed: widget.draft == null
                ? null
                : () => widget.draft!.recover(),
          ),
        ],
      ),
    );
  }

  // ---- Schema 模块：资源区 + 主编辑区 + 属性区 ----

  Widget _buildSchemaBody() {
    return Row(
      children: [
        _AnimatedCollapse(
          animate: !_resizingResource,
          alignment: Alignment.centerLeft,
          child: _resourceCollapsed
              ? _CollapsedStrip(
                  key: const ValueKey('wb.strip.resource'),
                  title: '资源',
                  icon: Icons.chevron_right,
                  tooltip: '展开资源区',
                  end: false,
                  onExpand: () {
                    _setCollapse('resource', false);
                    _saveLayout();
                  },
                )
              : SizedBox(
                  key: const ValueKey('wb.resourcePanel'),
                  width: _resourceWidth,
                  child: _buildResourcePanel(),
                ),
        ),
        if (!_resourceCollapsed)
          _ResizeHandle(
            handleKey: const ValueKey('wb.handle.resource'),
            onDragStart: () => setState(() => _resizingResource = true),
            onDragEnd: () => setState(() => _resizingResource = false),
            onDrag: (dx) => _setResourceWidth(_resourceWidth + dx),
          ),
        Expanded(child: _buildEditorArea()),
        if (!_inspectorCollapsed)
          _ResizeHandle(
            handleKey: const ValueKey('wb.handle.inspector'),
            onDragStart: () => setState(() => _resizingInspector = true),
            onDragEnd: () => setState(() => _resizingInspector = false),
            onDrag: (dx) => _setInspectorWidth(_inspectorWidth - dx),
          ),
        _AnimatedCollapse(
          animate: !_resizingInspector,
          alignment: Alignment.centerRight,
          child: _inspectorCollapsed
              ? _CollapsedStrip(
                  key: const ValueKey('wb.strip.inspector'),
                  title: '属性',
                  icon: Icons.chevron_left,
                  tooltip: '展开属性区',
                  end: true,
                  onExpand: () {
                    _setCollapse('inspector', false);
                    _saveLayout();
                  },
                )
              : SizedBox(
                  key: const ValueKey('wb.inspectorPanel'),
                  width: _inspectorWidth,
                  child: _buildInspector(),
                ),
        ),
      ],
    );
  }

  // ---- 资源区 ----

  Widget _buildResourcePanel() {
    final d = widget.data;
    final query = _query.trim().toLowerCase();
    final filtered = query.isEmpty
        ? d.resources
        : d.resources
              .where((r) => r.name.toLowerCase().contains(query))
              .toList(growable: false);
    return Container(
      color: ctSurface,
      child: Column(
        children: [
          _panelHeader('资源', [
            _iconBtn(Icons.add, '新建资源（样板）', () {
              showCtToast(context, '界面样板未连接原生内核，无法新建资源');
            }),
            _iconBtn(Icons.chevron_left, '折叠资源区', () {
              _setCollapse('resource', true);
              _saveLayout();
            }, key: const ValueKey('wb.collapse.resource')),
          ]),
          Padding(
            padding: const EdgeInsets.fromLTRB(
              ctGapMd,
              ctGapSm,
              ctGapMd,
              ctGapSm,
            ),
            child: TextField(
              style: ctText(size: ctFontSm),
              decoration: ctInputDecoration().copyWith(
                hintText: '搜索资源…',
                hintStyle: ctText(size: ctFontSm, color: ctInk3),
                prefixIcon: const Icon(Icons.search, size: 16, color: ctInk3),
                prefixIconConstraints: const BoxConstraints(
                  minWidth: 32,
                  minHeight: 20,
                ),
              ),
              onChanged: (v) => setState(() => _query = v),
            ),
          ),
          if (widget.draft case final repo?) ...[
            WorkbenchSchemaEditor(
              key: const ValueKey('wb.schemaEditor'),
              repo: repo,
              selected: _selectedResource,
              onResourceSelected: (name) {
                if (name == null) {
                  setState(() => _selectedResource = null);
                } else {
                  _gotoResource(name);
                }
              },
            ),
            const Divider(height: 1),
          ],
          Expanded(
            child: filtered.isEmpty
                ? _buildResourceEmpty()
                : ListView(
                    padding: const EdgeInsets.only(bottom: ctGapSm),
                    children: [
                      for (final kind in MockResourceKind.values)
                        ..._resourceGroup(kind, filtered),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildResourceEmpty() {
    if (_query.isNotEmpty) {
      return Center(
        child: Text(
          '没有匹配「$_query」的资源',
          style: ctText(size: ctFontSm, color: ctInk3),
        ),
      );
    }
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(ctGapLg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.inventory_2_outlined, size: 28, color: ctInk3),
            const SizedBox(height: ctGapSm),
            Text(
              '工作区还没有任何资源',
              style: ctText(size: ctFontSm, color: ctInk2),
            ),
            const SizedBox(height: ctGapMd),
            CtButton.ghost(
              '新建资源',
              onPressed: () {
                showCtToast(context, '界面样板未连接原生内核，无法新建资源');
              },
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _resourceGroup(MockResourceKind kind, List<MockResource> all) {
    final items = all.where((r) => r.kind == kind).toList(growable: false);
    if (items.isEmpty) return const [];
    return [
      Padding(
        padding: const EdgeInsets.fromLTRB(ctGapMd, ctGapSm, ctGapMd, 2),
        child: Text(
          '${kind.label} · ${items.length}',
          style: ctText(size: ctFontXs, color: ctInk3, weight: FontWeight.w600),
        ),
      ),
      for (final r in items) _resourceItem(r),
    ];
  }

  IconData _kindIcon(MockResourceKind kind) => switch (kind) {
    MockResourceKind.table => Icons.grid_on,
    MockResourceKind.record => Icons.view_agenda_outlined,
    MockResourceKind.enumType => Icons.list_alt,
  };

  Widget _resourceItem(MockResource r) {
    final selected = r.name == _selectedResource;
    return InkWell(
      onTap: () => _selectResource(r),
      child: Container(
        height: ctRowSm,
        color: selected ? ctAccentSofter : null,
        padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
        child: Row(
          children: [
            Icon(
              _kindIcon(r.kind),
              size: 14,
              color: selected ? ctPrimary : ctInk3,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                r.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: ctText(
                  size: ctFontSm + 0.5,
                  color: selected ? ctPrimary : ctInk,
                  weight: FontWeight.w500,
                ),
              ),
            ),
            if (r.dirty)
              Container(
                width: 6,
                height: 6,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  color: ctGold,
                ),
              ),
          ],
        ),
      ),
    );
  }

  // ---- 主编辑区 ----

  Widget _buildEditorArea() {
    final res = _currentResource;
    return Container(
      color: ctBg,
      child: Column(
        children: [
          _buildEditorToolbar(res),
          if (widget.data.candidateExpired) _conflictBanner(),
          if (widget.data.busy) _busyBanner(),
          Expanded(child: _buildEditorBody(res)),
        ],
      ),
    );
  }

  Widget _buildEditorToolbar(MockResource? res) {
    final d = widget.data;
    final draft = widget.draft;
    // 真实草稿：能不能保存由内核结论决定（必须已有无阻塞问题的候选）。
    final canSave = draft == null
        ? d.draftCount > 0 && !d.busy && !d.candidateExpired && res != null
        : draft.canSave;
    return Container(
      height: ctToolbarHeight,
      padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
      decoration: const BoxDecoration(
        color: ctSurface,
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: Row(
        children: [
          const Icon(Icons.table_chart_outlined, size: 15, color: ctInk3),
          const SizedBox(width: ctGapSm),
          Flexible(
            child: Text(
              res?.path ?? '未选择资源',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: ctMono.copyWith(fontSize: ctFontSm, color: ctInk2),
            ),
          ),
          if (_navBack.isNotEmpty)
            _iconBtn(
              Icons.arrow_back,
              '返回来源（${_navBack.length} 级）',
              _backToSource,
              key: const ValueKey('wb.navBack'),
            ),
          // 全局草稿动作（撤销/重做/差异/放弃/保存）只在顶部草稿条出现一次；
          // 样板模式没有内核草稿条，页面内保留一个禁用保存占位，避免"看起来能点"。
          if (res != null &&
              res.kind == WorkbenchResourceKind.enumType &&
              draft != null) ...[
            const SizedBox(width: ctGapSm),
            CtButton.ghost(
              '加成员',
              key: const ValueKey('wb.enumAddItem'),
              onPressed: () => _addEnumMember(draft, res),
            ),
            const SizedBox(width: ctGapSm),
            if (MediaQuery.sizeOf(context).width < 1180)
              const Tooltip(
                message: '成员顺序即 ordinal：重排或删除会改变既有数据的 wire 值',
                child: Icon(Icons.info_outline, size: 14, color: ctWarn),
              )
            else
              Flexible(
                child: Text(
                  '成员顺序即 ordinal：重排或删除会改变既有数据的 wire 值',
                  key: const ValueKey('wb.enumOrdinalRisk'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: ctText(size: ctFontXs, color: ctWarn),
                ),
              ),
          ],
          // 接了内核就只保留顶部草稿条那一个保存入口；样板模式没有草稿条，页面内留占位
          if (draft == null) ...[
            const SizedBox(width: ctGapSm),
            CtButton.accent(
              '保存',
              key: const ValueKey('wb.save'),
              onPressed: !canSave
                  ? null
                  : () => showCtToast(context, '界面样板未连接原生内核，无法保存'),
            ),
          ],
        ],
      ),
    );
  }

  /// 双守卫保存：成功提示新基线，被拒时明确「草稿已保留」。
  Future<void> _saveDraft(WorkbenchRepository draft) async {
    final result = await draft.saveDraft();
    if (!mounted) return;
    if (result != null) {
      showCtToast(
        context,
        '已保存 YAML（仅改 schema 文件），新基线 ${result.schemaRevision.characters.take(12).join()}…',
      );
      return;
    }
    showCtToast(context, draft.saveError ?? '保存被拒绝，草稿已保留');
  }

  /// 候选与净差异：与全局草稿条共用同一份实现，内容全部取自内核回包。

  Widget _conflictBanner() {
    final d = widget.data;
    return Container(
      width: double.infinity,
      color: ctWarnSoft,
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapMd,
        vertical: ctGapSm,
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, size: 16, color: ctWarn),
          const SizedBox(width: ctGapSm),
          Expanded(
            child: Text(
              '候选已过期：schemaRevision ${d.schemaRevision} → ${d.schemaRevision + 1}'
              '（工作区被外部修改），保存已锁定。草稿仍保留，可对比差异后处理。',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: ctText(size: ctFontSm),
            ),
          ),
          CtButton.ghost(
            '放弃并重载',
            onPressed: () {
              showCtToast(context, '样板未接入内核');
            },
          ),
          const SizedBox(width: ctGapSm),
          CtButton.accent(
            '查看差异',
            onPressed: () {
              showCtToast(context, '样板未接入内核');
            },
          ),
        ],
      ),
    );
  }

  Widget _busyBanner() {
    return Container(
      width: double.infinity,
      color: ctAccentSofter,
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapMd,
        vertical: ctGapSm,
      ),
      child: Row(
        children: [
          const Icon(Icons.sync, size: 16, color: ctAccent),
          const SizedBox(width: ctGapSm),
          Expanded(
            child: Text(
              '导出进行中 · Schema 写入口已临时锁定，可继续浏览资源与日志。',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: ctText(size: ctFontSm),
            ),
          ),
          CtButton.ghost('查看导出', onPressed: () => setState(() => _module = 3)),
        ],
      ),
    );
  }

  List<String> _memberNames(MockResource res) => [
    for (final f in res.fields) f.name,
  ];

  /// 枚举成员追加：内核只有整表改写，界面按「现有成员 + 新成员」发命令。
  Future<void> _addEnumMember(
    WorkbenchRepository repo,
    MockResource res,
  ) async {
    final name = await _askEnumItemName(_memberNames(res));
    if (name == null || name.isEmpty || !mounted) return;
    repo.setEnumValues('enum:${res.name}', [..._memberNames(res), name]);
    setState(() {});
  }

  Future<String?> _askEnumItemName(List<String> existing) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('追加枚举成员'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const ValueKey('wb.enumItemField'),
              controller: controller,
              autofocus: true,
            ),
            Text(
              '现有 ${existing.length} 个成员，新成员追加为 ordinal ${existing.length}。',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            key: const ValueKey('wb.enumItemConfirm'),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('加入草稿'),
          ),
        ],
      ),
    );
    return ok == true ? controller.text.trim() : null;
  }

  /// 枚举重排/删除只能整表改写：内核 move_field、delete_field 不适用于 Enum。
  void _rewriteEnumMembers(
    WorkbenchRepository repo,
    MockResource res, {
    int? dropIndex,
    int? moveTo,
    int? moveToIndex,
  }) {
    final next = _memberNames(res);
    if (next.isEmpty) return;
    if (dropIndex != null) {
      if (dropIndex < 0 || dropIndex >= next.length) return;
      next.removeAt(dropIndex);
    } else if (moveTo != null && moveToIndex != null) {
      if (moveToIndex < 0 || moveToIndex >= next.length) return;
      final item = next.removeAt(moveToIndex);
      next.insert(moveTo.clamp(0, next.length), item);
    } else {
      return;
    }
    repo.setEnumValues('enum:${res.name}', next);
  }

  /// 3.7：类型/ref 能对上内核资源名时做成链接，点击切主区并留返回栈。
  String? _namedResource(String text, {required String except}) {
    var name = text.trim();
    if (name.isEmpty) return null;
    // ref 形态是 `Table.Primary`：跳转目标是表本身，先去掉主键段再匹配。
    final dot = name.indexOf('.');
    if (dot > 0) name = name.substring(0, dot);
    if (name.isEmpty || name == except) return null;
    return widget.data.resources.any((r) => r.name == name) ? name : null;
  }

  Widget _buildEditorBody(MockResource? res) {
    final d = widget.data;
    if (d.loadError != null) return _buildLoadError(d.loadError!);
    if (res == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.table_chart_outlined, size: 32, color: ctInk3),
            const SizedBox(height: ctGapSm),
            Text(
              '从左侧选择资源，或新建 Table / Record / Enum',
              style: ctText(size: ctFontMd, color: ctInk2),
            ),
            const SizedBox(height: ctGapMd),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CtButton.ghost(
                  '新建表',
                  onPressed: () {
                    showCtToast(context, '界面样板未连接原生内核，无法修改资源');
                  },
                ),
                const SizedBox(width: ctGapSm),
                CtButton.ghost(
                  '新建记录',
                  onPressed: () {
                    showCtToast(context, '界面样板未连接原生内核，无法修改资源');
                  },
                ),
                const SizedBox(width: ctGapSm),
                CtButton.ghost(
                  '新建枚举',
                  onPressed: () {
                    showCtToast(context, '界面样板未连接原生内核，无法修改资源');
                  },
                ),
              ],
            ),
          ],
        ),
      );
    }
    return Column(
      children: [
        Container(
          height: ctRowMd,
          padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
          decoration: const BoxDecoration(
            color: ctSurface,
            border: Border(bottom: BorderSide(color: ctBorder)),
          ),
          child: Row(
            children: [
              const Icon(Icons.view_list_outlined, size: 15, color: ctInk3),
              const SizedBox(width: ctGapSm),
              Text(
                '字段 · ${res.fields.length}',
                style: ctText(
                  size: ctFontSm,
                  color: ctInk2,
                  weight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: Column(
            children: [
              Expanded(child: _buildFieldsTable(res)),
              if (widget.template != null)
                WorkbenchTemplatePanel(
                  service: widget.template!,
                  resource: res,
                  blockReason: widget.data.loadError ?? widget.writeBlockReason,
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildLoadError(String message) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 32, color: ctDanger),
            const SizedBox(height: ctGapSm),
            const Text(
              '资源加载失败',
              style: TextStyle(fontSize: ctFontLg, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: ctGapMd),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(ctGapMd),
              decoration: BoxDecoration(
                color: ctDangerSoft,
                borderRadius: ctRadiusMdAll,
                border: Border.all(color: ctDanger.withValues(alpha: 0.3)),
              ),
              child: Text(
                message,
                style: ctMono.copyWith(fontSize: ctFontSm, color: ctInk),
              ),
            ),
            const SizedBox(height: ctGapMd),
            CtButton.accent(
              '重试',
              onPressed: () {
                showCtToast(context, '样板未接入内核');
              },
            ),
          ],
        ),
      ),
    );
  }

  // ---- 字段表 ----

  Widget _buildFieldsTable(MockResource res) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final extra = constraints.maxWidth > _tableMinWidth
            ? constraints.maxWidth - _tableMinWidth
            : 0.0;
        final descWidth = _wDesc + extra;
        final tableWidth = _tableMinWidth + extra;
        return SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: SizedBox(
            width: tableWidth,
            child: Column(
              children: [
                _fieldsHeader(descWidth),
                Expanded(
                  child: ListView.builder(
                    itemCount: res.fields.length,
                    itemBuilder: (context, i) => _fieldRow(res, i, descWidth),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _fieldsHeader(double descWidth) {
    return Container(
      height: ctRowSm + 4,
      decoration: const BoxDecoration(
        color: ctSurface2,
        border: Border(bottom: BorderSide(color: ctBorderStrong)),
      ),
      child: Row(
        children: [
          _hCell('名称', _wName),
          _hCell('类型', _wType),
          _hCell('角色', _wRole),
          _hCell('约束', _wConstraint),
          _hCell('默认值', _wDefault),
          _hCell('描述', descWidth),
        ],
      ),
    );
  }

  Widget _fieldRow(MockResource res, int index, double descWidth) {
    final f = res.fields[index];
    final selected = _selectedField == index;
    return InkWell(
      onTap: () => setState(() => _selectedField = index),
      child: Container(
        height: ctRowSm + 2,
        decoration: BoxDecoration(
          color: selected ? ctAccentSofter : ctSurface,
          border: const Border(bottom: BorderSide(color: ctBorder)),
        ),
        child: Row(
          children: [
            _tCell(
              f.name,
              _wName,
              style: ctText(
                size: ctFontSm + 0.5,
                weight: FontWeight.w500,
                color: selected ? ctPrimary : ctInk,
              ),
            ),
            _linkCell(
              f.type,
              _wType,
              _namedResource(f.type, except: res.name),
              ctMono.copyWith(fontSize: ctFontSm, color: ctInk2),
            ),
            _roleCell(f),
            _linkCell(
              f.constraints,
              _wConstraint,
              _namedResource(f.constraints, except: res.name),
              ctText(size: ctFontSm, color: ctInk2),
            ),
            _tCell(
              f.defaultValue.isEmpty ? '—' : f.defaultValue,
              _wDefault,
              style: ctMono.copyWith(fontSize: ctFontSm, color: ctInk2),
            ),
            _tCell(
              f.description,
              descWidth,
              style: ctText(size: ctFontSm, color: ctInk2),
            ),
          ],
        ),
      ),
    );
  }

  Widget _roleCell(MockField f) {
    final badges = <Widget>[
      if (f.role == '主键')
        const CtStatusBadge(label: '主键', tone: CtBadgeTone.info, dot: false),
      if (f.localized)
        const CtStatusBadge(label: '文', tone: CtBadgeTone.busy, dot: false),
    ];
    if (badges.isEmpty) {
      return _tCell(
        f.role.isEmpty ? '—' : f.role,
        _wRole,
        style: ctText(size: ctFontSm, color: ctInk2),
      );
    }
    return SizedBox(
      width: _wRole,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Row(
          children: [
            for (var i = 0; i < badges.length; i++) ...[
              if (i > 0) const SizedBox(width: 4),
              badges[i],
            ],
          ],
        ),
      ),
    );
  }

  // ---- 属性区 ----

  Widget _buildInspector() {
    final res = _currentResource;
    MockField? field;
    if (res != null &&
        _selectedField >= 0 &&
        _selectedField < res.fields.length) {
      field = res.fields[_selectedField];
    }
    final roleText = field == null
        ? ''
        : [
            if (field.role.isNotEmpty) field.role,
            if (field.localized) '本地化',
          ].join(' · ');
    // 真实草稿来源才给编辑能力；样板场景保持只读展示。
    if (widget.draft != null) {
      return _draftInspector(res, field);
    }
    return Container(
      color: ctSurface,
      child: Column(
        children: [
          _panelHeader('属性', [
            _iconBtn(Icons.chevron_right, '折叠属性区', () {
              _setCollapse('inspector', true);
              _saveLayout();
            }, key: const ValueKey('wb.collapse.inspector')),
          ]),
          Expanded(
            child: field == null && res == null
                ? Center(
                    child: Text(
                      '选择字段或资源查看属性',
                      style: ctText(size: ctFontSm, color: ctInk3),
                    ),
                  )
                : ListView(
                    children: [
                      if (field != null) ...[
                        _propRow('字段名', field.name, mono: true),
                        _propRow('类型', field.type, mono: true),
                        _propRow('角色', roleText.isEmpty ? '普通字段' : roleText),
                        _propRow(
                          '约束',
                          field.constraints.isEmpty ? '—' : field.constraints,
                        ),
                        _propRow(
                          '默认值',
                          field.defaultValue.isEmpty ? '—' : field.defaultValue,
                          mono: true,
                        ),
                        _propRow(
                          '描述',
                          field.description.isEmpty ? '—' : field.description,
                          multiline: true,
                        ),
                      ] else ...[
                        _propRow('名称', res!.name, mono: true),
                        _propRow('类别', res.kind.label),
                        _propRow('路径', res.path, mono: true, multiline: true),
                        _propRow('字段数', '${res.fields.length}'),
                      ],
                    ],
                  ),
          ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(
              horizontal: ctGapLg,
              vertical: ctGapSm,
            ),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: ctBorder)),
            ),
            child: Text(
              '界面样板为只读 · 连接原生内核后可编辑',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
          ),
        ],
      ),
    );
  }

  /// 属性区的草稿编辑（任务 3.2）：改动只落草稿命令，问题取内核候选。
  Widget _draftInspector(WorkbenchResource? res, MockField? field) {
    final repo = widget.draft!;
    final disabledReason = repo.saving
        ? '保存进行中，暂不可修改'
        : repo.loading
        ? '正在加载工作区，暂不可修改'
        : null;
    final kindWire = switch (res?.kind) {
      WorkbenchResourceKind.record => 'record',
      WorkbenchResourceKind.enumType => 'enum',
      _ => 'table',
    };
    final owner = '$kindWire:${res?.name ?? ''}';
    final ordinal = res == null || field == null
        ? null
        : res.fields.indexOf(field);
    return Container(
      color: ctSurface,
      child: Column(
        children: [
          _panelHeader('属性', [
            _iconBtn(Icons.chevron_right, '折叠属性区', () {
              _setCollapse('inspector', true);
              _saveLayout();
            }, key: const ValueKey('wb.collapse.inspector')),
          ]),
          Expanded(
            child: res == null
                ? Center(
                    child: Text(
                      '选择字段或资源查看属性',
                      style: ctText(size: ctFontSm, color: ctInk3),
                    ),
                  )
                : WorkbenchFieldEditor(
                    key: ValueKey('wb.editor.$owner${field?.name ?? ''}'),
                    resource: res,
                    ownerId: owner,
                    field: field,
                    fieldOrdinal: ordinal,
                    namedTypes: [
                      for (final r in widget.data.resources)
                        if (r.kind != WorkbenchResourceKind.table &&
                            r.name != res.name)
                          r.name,
                    ],
                    referenceTargets: _referenceTargets(),
                    problems: repo.problemsFor(owner, fieldName: field?.name),
                    disabled: disabledReason != null,
                    disabledHint: disabledReason,
                    onSetType: field == null
                        ? null
                        : (text) => repo.setFieldType(owner, field.name, text),
                    onSetProperty: field == null
                        ? null
                        : (property, value) => repo.setFieldProperty(
                            owner,
                            field.name,
                            property,
                            value,
                          ),
                    onSetIndexes: (kinds) => repo.setTableIndexes(owner, kinds),
                    onMoveField: field == null
                        ? null
                        : (to) => res.kind == WorkbenchResourceKind.enumType
                              ? _rewriteEnumMembers(
                                  repo,
                                  res,
                                  moveTo: to,
                                  moveToIndex: ordinal,
                                )
                              : repo.moveField(owner, field.name, to),
                    onDeleteField: field == null
                        ? null
                        : () => res.kind == WorkbenchResourceKind.enumType
                              ? _rewriteEnumMembers(
                                  repo,
                                  res,
                                  dropIndex: ordinal,
                                )
                              : repo.deleteField(owner, field.name),
                    onRenameEnumItem: field == null
                        ? null
                        : (newName, ordinal) => repo.renameEnumItem(
                            owner,
                            field.name,
                            newName,
                            ordinal,
                          ),
                  ),
          ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(
              horizontal: ctGapLg,
              vertical: ctGapSm,
            ),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: ctBorder)),
            ),
            child: Text(
              '改动只进草稿；候选与保存均由内核裁决（草稿 ${widget.data.draftCount} 条）',
              key: const ValueKey('wb.inspectorNote'),
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
          ),
        ],
      ),
    );
  }

  Widget _propRow(
    String label,
    String value, {
    bool mono = false,
    bool multiline = false,
  }) {
    final style = mono
        ? ctMono.copyWith(fontSize: ctFontSm, color: ctInk)
        : ctText(size: ctFontSm, color: ctInk);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapLg,
        vertical: ctGapSm + 2,
      ),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 56,
            child: Text(
              label,
              style: ctText(size: ctFontSm, color: ctInk2),
            ),
          ),
          const SizedBox(width: ctGapSm),
          Expanded(
            child: Text(
              value,
              style: style,
              maxLines: multiline ? 6 : 2,
              overflow: TextOverflow.ellipsis,
              softWrap: true,
            ),
          ),
        ],
      ),
    );
  }

  // ---- 共享小部件 ----

  Widget _panelHeader(String title, List<Widget> actions) {
    return Container(
      height: ctRowMd,
      padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: Row(
        children: [
          Text(
            title,
            style: ctText(
              size: ctFontSm,
              color: ctInk2,
              weight: FontWeight.w600,
            ),
          ),
          const Spacer(),
          ...actions,
        ],
      ),
    );
  }

  Widget _iconBtn(
    IconData icon,
    String tooltip,
    VoidCallback? onPressed, {
    Key? key,
  }) {
    return IconButton(
      key: key,
      icon: Icon(icon, size: 18),
      tooltip: tooltip,
      onPressed: onPressed,
      splashRadius: 18,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
      visualDensity: VisualDensity.compact,
      color: ctInk2,
    );
  }

  Widget _hCell(String text, double width) {
    return SizedBox(
      width: width,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(
            text,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: ctText(
              size: ctFontSm,
              color: ctInk2,
              weight: FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }

  Widget _linkCell(String text, double width, String? target, TextStyle style) {
    if (text.isEmpty || target == null) {
      return _tCell(text.isEmpty ? '-' : text, width, style: style);
    }
    return SizedBox(
      width: width,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Align(
          alignment: Alignment.centerLeft,
          child: InkWell(
            key: ValueKey('wb.refLink.$text'),
            onTap: () =>
                _gotoResource(target, rememberRecent: true, fromLink: true),
            child: Row(
              children: [
                Flexible(
                  child: Text(
                    text,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: style.copyWith(
                      color: ctAccent,
                      decoration: TextDecoration.underline,
                    ),
                  ),
                ),
                const Icon(Icons.link, size: 12, color: ctAccent),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _tCell(String text, double width, {TextStyle? style}) {
    return SizedBox(
      width: width,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(
            text,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: style ?? ctText(size: ctFontSm),
          ),
        ),
      ),
    );
  }
}

/// 折叠/展开使用与 ZCode 同口径的 200ms ease-out；拖拽调宽时即时跟手。
class _AnimatedCollapse extends StatelessWidget {
  const _AnimatedCollapse({
    required this.animate,
    required this.alignment,
    required this.child,
  });

  final bool animate;
  final Alignment alignment;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final disableAnimations =
        MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    return AnimatedSize(
      duration: animate && !disableAnimations
          ? ctMotionStandard
          : Duration.zero,
      curve: ctMotionCurve,
      alignment: alignment,
      clipBehavior: Clip.hardEdge,
      child: child,
    );
  }
}

/// 面板折叠后的窄条（资源区/属性区）。
class _CollapsedStrip extends StatelessWidget {
  const _CollapsedStrip({
    super.key,
    required this.title,
    required this.icon,
    required this.tooltip,
    required this.end,
    required this.onExpand,
  });

  final String title;
  final IconData icon;
  final String tooltip;
  final bool end;
  final VoidCallback onExpand;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: ctCollapsedStripWidth,
      decoration: BoxDecoration(
        color: ctSurface,
        border: Border(
          right: end ? BorderSide.none : const BorderSide(color: ctBorder),
          left: end ? const BorderSide(color: ctBorder) : BorderSide.none,
        ),
      ),
      child: Column(
        children: [
          const SizedBox(height: ctGapXs),
          IconButton(
            icon: Icon(icon, size: 18),
            tooltip: tooltip,
            onPressed: onExpand,
            splashRadius: 20,
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
            color: ctInk2,
          ),
          const SizedBox(height: ctGapXs),
          Expanded(
            child: Center(
              child: RotatedBox(
                quarterTurns: 3,
                child: Text(
                  title,
                  style: ctText(size: ctFontXs, color: ctInk3),
                ),
              ),
            ),
          ),
          const SizedBox(height: ctGapSm),
        ],
      ),
    );
  }
}

/// 面板拖拽手柄（5px 命中区 + 1px 分隔线，悬停高亮）。
class _ResizeHandle extends StatefulWidget {
  const _ResizeHandle({
    required this.onDrag,
    this.onDragStart,
    this.onDragEnd,
    this.handleKey,
  });

  final ValueChanged<double> onDrag;
  final VoidCallback? onDragStart;
  final VoidCallback? onDragEnd;
  final Key? handleKey;

  @override
  State<_ResizeHandle> createState() => _ResizeHandleState();
}

class _ResizeHandleState extends State<_ResizeHandle> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.resizeColumn,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        key: widget.handleKey,
        behavior: HitTestBehavior.opaque,
        onHorizontalDragStart: (_) => widget.onDragStart?.call(),
        onHorizontalDragEnd: (_) => widget.onDragEnd?.call(),
        onHorizontalDragUpdate: (d) => widget.onDrag(d.delta.dx),
        child: Container(
          width: 5,
          height: double.infinity,
          color: _hover ? ctAccentSoft : Colors.transparent,
          alignment: Alignment.center,
          child: Container(width: 1, height: double.infinity, color: ctBorder),
        ),
      ),
    );
  }
}

/// 未接入模块占位。
class _PlaceholderModule extends StatelessWidget {
  const _PlaceholderModule({required this.label, required this.planned});

  final String label;
  final String planned;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.construction_outlined, size: 28, color: ctInk3),
          const SizedBox(height: ctGapSm),
          Text(
            planned.isEmpty
                ? '「$label」模块需要接上内核数据源'
                : '「$label」模块将在$planned接入内核',
            style: ctText(color: ctInk2),
          ),
          const SizedBox(height: ctGapXs),
          Text(
            '当前为界面样板（MOCK）',
            style: ctText(size: ctFontXs, color: ctInk3),
          ),
        ],
      ),
    );
  }
}

/// 样板提示条（总览等处的数据来源说明）。
class _HintBanner extends StatelessWidget {
  const _HintBanner({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapMd,
        vertical: ctGapSm,
      ),
      decoration: BoxDecoration(
        color: ctAccentSofter,
        borderRadius: ctRadiusMdAll,
      ),
      child: Text(
        text,
        style: ctText(size: ctFontSm, color: ctInk2),
      ),
    );
  }
}

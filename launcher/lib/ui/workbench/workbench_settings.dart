import 'package:file_selector/file_selector.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../services/auto_launch.dart';
import '../../services/settings_store.dart';
import '../../theme.dart';
import '../../ui/tokens.dart';
import '../widgets/common.dart';

/// 工作台「设置」模块（native-flutter-workbench 任务 2.4）。
///
/// 只保留原生内核用得上的四项偏好：工作区、可选的开发期运行时路径、开机自启、托盘常驻。
/// 旧版的面板端口/监听地址/工具目录已废弃，仅在检测到时提示一次。
class WorkbenchSettingsPanel extends StatefulWidget {
  const WorkbenchSettingsPanel({
    super.key,
    required this.settings,
    required this.workspacePath,
    this.kernelSummary = const [],
    this.onWorkspaceChanged,
    this.onRuntimeChanged,
    this.onUseInferredRuntime,
    this.onReload,
    this.onExit,
    this.onOpenDocs,
    this.onShowHelp,
    this.onShowAbout,
  });

  final SettingsStore settings;

  /// 当前工作台实际绑定的工作区（可能与尚未生效的偏好不同）。
  final String workspacePath;

  /// 内核连接摘要：来源、路径、状态与失败原因，逐行展示。
  final List<String> kernelSummary;

  final Future<void> Function(String)? onWorkspaceChanged;
  final Future<void> Function(String)? onRuntimeChanged;
  final Future<void> Function()? onUseInferredRuntime;
  final VoidCallback? onReload;

  /// 显式退出（任务 4.7）：由壳层走退出守卫与安全 shutdown，不在面板里自己收尾。
  final VoidCallback? onExit;

  /// 文档、快捷键帮助与版本信息统一收进设置页，避免侧栏 footer 堆叠入口。
  final VoidCallback? onOpenDocs;
  final VoidCallback? onShowHelp;
  final VoidCallback? onShowAbout;

  @override
  State<WorkbenchSettingsPanel> createState() => _WorkbenchSettingsPanelState();
}

class _WorkbenchSettingsPanelState extends State<WorkbenchSettingsPanel> {
  bool _autostart = false;
  bool _autostartBusy = false;

  @override
  void initState() {
    super.initState();
    _syncAutostart();
  }

  Future<void> _syncAutostart() async {
    try {
      final enabled = await AutoLaunch.instance.isEnabled;
      if (mounted) setState(() => _autostart = enabled);
    } catch (_) {
      // 平台插件不可用（Linux/测试环境）时保持关闭，不影响其他设置。
    }
  }

  Future<void> _pickWorkspace() async {
    final path = await getDirectoryPath(
      confirmButtonText: '选择',
      initialDirectory: widget.workspacePath.isNotEmpty
          ? widget.workspacePath
          : null,
    );
    if (path == null || path.isEmpty) return;
    await widget.onWorkspaceChanged?.call(path);
  }

  Future<void> _pickRuntime() async {
    final picked = await openFile();
    final path = picked?.path;
    if (path == null || path.isEmpty) return;
    await widget.onRuntimeChanged?.call(path);
  }

  Future<void> _toggleAutostart(bool value) async {
    if (_autostartBusy) return;
    setState(() => _autostartBusy = true);
    if (kDebugMode) {
      if (mounted) {
        setState(() => _autostartBusy = false);
        showCtToast(context, '调试模式不启用开机自启，正式构建下生效');
      }
      return;
    }
    await AutoLaunch.instance.updateStatus(value);
    await widget.settings.setAutoStart(value);
    if (mounted) {
      setState(() {
        _autostartBusy = false;
        _autostart = value;
      });
      showCtToast(context, value ? '已开启开机自启' : '已关闭开机自启');
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.settings;
    return Padding(
      padding: const EdgeInsets.all(ctGapLg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.only(bottom: ctGapLg),
              child: Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 880),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (s.migratedFromLegacy) ...[
                        _settingsGroup(
                          children: [
                            _settingsItem(
                              title: '迁移提示',
                              description: '旧版面板配置已清理，工作区与桌面偏好继续保留。',
                              detail: const Text(
                                '面板端口、监听地址与 Python 工具目录配置不再使用；'
                                '原生内核不监听端口，也不启动解释器。',
                                key: ValueKey('settings.legacyNote'),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: ctGapMd),
                      ],
                      _settingsGroup(
                        key: const ValueKey('settings.workspaceCard'),
                        children: [
                          _settingsItem(
                            title: '配表目录',
                            description: '选择游戏数据目录；外部改动后可重新读取。',
                            detail: Text(
                              widget.workspacePath.isEmpty
                                  ? '未选择'
                                  : widget.workspacePath,
                              key: const ValueKey('settings.workspacePath'),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: ctMono.copyWith(
                                fontSize: ctFontSm,
                                color: ctInk2,
                              ),
                            ),
                            trailing: Wrap(
                              spacing: ctGapSm,
                              children: [
                                CtButton.ghost(
                                  '选择目录…',
                                  key: const ValueKey('settings.pickWorkspace'),
                                  onPressed: _pickWorkspace,
                                ),
                                CtButton.ghost(
                                  '重新读取',
                                  key: const ValueKey(
                                    'settings.reloadWorkspace',
                                  ),
                                  onPressed: widget.onReload,
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: ctGapMd),
                      _settingsGroup(
                        key: const ValueKey('settings.runtimeCard'),
                        children: [
                          _settingsItem(
                            title: '内核状态',
                            description: '以下信息来自 worker 握手回显。',
                            detail: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                for (final line in widget.kernelSummary)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 3),
                                    child: Text(
                                      line,
                                      key: const ValueKey(
                                        'settings.kernelSummary',
                                      ),
                                      style: ctMono.copyWith(
                                        fontSize: ctFontSm,
                                        color: ctInk2,
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                          _settingsItem(
                            title: '运行时管理',
                            description: '指定开发期 ct 可执行文件，或恢复自动推断。',
                            trailing: Wrap(
                              spacing: ctGapSm,
                              children: [
                                CtButton.ghost(
                                  '指定 ct 可执行文件…',
                                  key: const ValueKey('settings.pickRuntime'),
                                  onPressed: _pickRuntime,
                                ),
                                CtButton.ghost(
                                  '用自动推断',
                                  key: const ValueKey(
                                    'settings.inferredRuntime',
                                  ),
                                  onPressed: () async {
                                    await widget.onUseInferredRuntime?.call();
                                  },
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: ctGapMd),
                      _settingsGroup(
                        key: const ValueKey('settings.desktopCard'),
                        children: [
                          _settingsItem(
                            title: '开机自启',
                            description: '登录系统后自动启动 ct 工作台。',
                            trailing: CtSwitch(
                              key: const ValueKey('settings.autostart'),
                              value: _autostart,
                              onChanged: _autostartBusy
                                  ? null
                                  : _toggleAutostart,
                              tooltip: '开机自启',
                            ),
                          ),
                          _settingsItem(
                            title: '托盘常驻',
                            description: '关闭窗口时隐藏到托盘，而不是退出应用。',
                            trailing: CtSwitch(
                              key: const ValueKey('settings.trayResident'),
                              value: s.trayResident,
                              tooltip: '托盘常驻',
                              onChanged: (value) async {
                                final messenger = ScaffoldMessenger.of(context);
                                await s.setTrayResident(value);
                                messenger
                                  ..clearSnackBars()
                                  ..showSnackBar(
                                    SnackBar(
                                      content: Text(
                                        value ? '关闭窗口将隐藏到托盘' : '关闭窗口即退出',
                                      ),
                                      backgroundColor: ctPrimary,
                                      behavior: SnackBarBehavior.floating,
                                      duration: const Duration(
                                        milliseconds: 1600,
                                      ),
                                    ),
                                  );
                              },
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: ctGapMd),
                      _settingsGroup(
                        key: const ValueKey('settings.helpCard'),
                        children: [
                          _settingsItem(
                            title: '使用文档',
                            description: '查看安装、CLI 与配表工作流说明。',
                            trailing: CtButton.ghost(
                              '打开文档',
                              key: const ValueKey('settings.docs'),
                              onPressed: widget.onOpenDocs,
                            ),
                          ),
                          _settingsItem(
                            title: '帮助与快捷键',
                            description: '查看支持范围、实际键位与反馈入口。',
                            trailing: CtButton.ghost(
                              '查看帮助',
                              key: const ValueKey('settings.help'),
                              onPressed: widget.onShowHelp,
                            ),
                          ),
                          _settingsItem(
                            title: '关于 ct 工作台',
                            description: '查看版本、协议、内核能力与当前工作区。',
                            trailing: CtButton.ghost(
                              '查看版本',
                              key: const ValueKey('settings.about'),
                              onPressed: widget.onShowAbout,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: ctGapMd),
                      _settingsGroup(
                        children: [
                          _settingsItem(
                            title: '退出应用',
                            description: '退出前会确认未保存草稿与运行中的写任务。',
                            trailing: CtButton.ghost(
                              '退出',
                              key: const ValueKey('wb.exit'),
                              onPressed: widget.onExit,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: ctGapLg),
                      CtFooterHint(
                        child: Text(
                          '保存 Schema、生成模板、翻译、导出与部署均由原生内核执行；'
                          '本面板不需要 Python 相关配置。',
                          style: TextStyle(fontSize: ctFontSm, color: ctInk2),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _settingsGroup({Key? key, required List<Widget> children}) {
    return CtGroupCard(key: key, children: children);
  }

  Widget _settingsItem({
    required String title,
    required String description,
    Widget? detail,
    Widget? trailing,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: ctText(
                  size: ctFontMd,
                  color: ctInk,
                  weight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: ctGapXs),
              Text(
                description,
                style: ctText(size: ctFontXs, color: ctInk3, height: 1.4),
              ),
              if (detail != null) ...[
                const SizedBox(height: ctGapSm),
                DefaultTextStyle.merge(
                  style: ctText(size: ctFontXs, color: ctInk2),
                  child: detail,
                ),
              ],
            ],
          ),
        ),
        if (trailing != null) ...[
          const SizedBox(width: ctGapXl),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: trailing,
          ),
        ],
      ],
    );
  }
}

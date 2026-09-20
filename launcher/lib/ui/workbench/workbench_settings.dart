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
/// 旧版的面板端口/监听地址/Python 工具目录已随内核迁移废弃，仅在检测到时提示一次。
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
  });

  final SettingsStore settings;

  /// 当前工作台实际绑定的工作区（可能与尚未生效的偏好不同）。
  final String workspacePath;

  /// 内核连接摘要：来源、路径、状态与失败原因，逐行展示。
  final List<String> kernelSummary;

  final ValueChanged<String>? onWorkspaceChanged;
  final ValueChanged<String>? onRuntimeChanged;
  final VoidCallback? onUseInferredRuntime;
  final VoidCallback? onReload;

  /// 显式退出（任务 4.7）：由壳层走退出守卫与安全 shutdown，不在面板里自己收尾。
  final VoidCallback? onExit;

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
    widget.onWorkspaceChanged?.call(path);
    if (mounted) {
      showCtToast(context, '已切换工作区，正在从内核重新读取');
    }
  }

  Future<void> _pickRuntime() async {
    // 不限制扩展名：Linux/macOS 上运行时是裸可执行文件。
    final picked = await openFile();
    final path = picked?.path;
    if (path == null || path.isEmpty) return;
    widget.onRuntimeChanged?.call(path);
    if (mounted) {
      showCtToast(context, '已改用指定运行时并重连内核');
    }
  }

  Future<void> _toggleAutostart(bool value) async {
    if (_autostartBusy) return;
    setState(() => _autostartBusy = true);
    if (kDebugMode) {
      // 调试构建不写登录项，避免污染系统（对齐 FlClash）。
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
    return SingleChildScrollView(
      padding: const EdgeInsets.all(ctGapXl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('设置', style: ctPageTitleStyle),
          const SizedBox(height: ctGapXs),
          Text(
            '偏好即时生效；重启后仍保留。',
            style: TextStyle(fontSize: ctFontSm, color: ctInk3),
          ),
          const SizedBox(height: ctGapLg),
          if (s.migratedFromLegacy)
            _card(
              title: '已迁移旧配置',
              icon: Icons.update,
              children: [
                const Text(
                  '旧版的面板端口/监听地址与 Python 工具目录配置已废弃并被清除：'
                  '原生内核不监听端口，也不启动解释器。工作区与桌面偏好已保留。',
                  key: ValueKey('settings.legacyNote'),
                  style: TextStyle(fontSize: ctFontMd),
                ),
              ],
            ),
          _card(
            title: '配表工作区',
            icon: Icons.folder_outlined,
            children: [
              CtSettingRow(
                label: '路径',
                child: Text(
                  widget.workspacePath.isEmpty ? '未选择' : widget.workspacePath,
                  key: const ValueKey('settings.workspacePath'),
                  style: ctMono.copyWith(fontSize: ctFontSm),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              CtSettingRow(
                label: '',
                child: Wrap(
                  spacing: ctGapSm,
                  children: [
                    CtButton.ghost(
                      '选择目录…',
                      key: const ValueKey('settings.pickWorkspace'),
                      onPressed: _pickWorkspace,
                    ),
                    CtButton.ghost(
                      '重新读取',
                      key: const ValueKey('settings.reloadWorkspace'),
                      onPressed: widget.onReload,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: ctGapMd),
          _card(
            title: '原生内核运行时',
            icon: Icons.memory,
            children: [
              for (final line in widget.kernelSummary)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
                  child: Text(
                    line,
                    key: const ValueKey('settings.kernelSummary'),
                    style: ctMono.copyWith(fontSize: ctFontSm),
                  ),
                ),
              CtSettingRow(
                label: '',
                child: Wrap(
                  spacing: ctGapSm,
                  children: [
                    CtButton.ghost(
                      '指定 ct 可执行文件…',
                      key: const ValueKey('settings.pickRuntime'),
                      onPressed: _pickRuntime,
                    ),
                    CtButton.ghost(
                      '用自动推断',
                      key: const ValueKey('settings.inferredRuntime'),
                      onPressed: () async {
                        await s.useInferredRuntimePath();
                        widget.onUseInferredRuntime?.call();
                      },
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: ctGapMd),
          _card(
            title: '桌面偏好',
            icon: Icons.tune,
            children: [
              CtSettingRow(
                label: '开机自启',
                child: Switch(
                  key: const ValueKey('settings.autostart'),
                  value: _autostart,
                  onChanged: _autostartBusy ? null : _toggleAutostart,
                ),
              ),
              CtSettingRow(
                label: '托盘常驻',
                child: Switch(
                  key: const ValueKey('settings.trayResident'),
                  value: s.trayResident,
                  onChanged: (value) async {
                    // 先取 messenger，避免跨异步间隙使用 BuildContext。
                    final messenger = ScaffoldMessenger.of(context);
                    await s.setTrayResident(value);
                    messenger
                      ..clearSnackBars()
                      ..showSnackBar(
                        SnackBar(
                          content: Text(value ? '关闭窗口将隐藏到托盘' : '关闭窗口即退出'),
                          backgroundColor: ctPrimary,
                          behavior: SnackBarBehavior.floating,
                          duration: const Duration(milliseconds: 1600),
                        ),
                      );
                  },
                ),
              ),
            ],
          ),
          const SizedBox(height: ctGapMd),
          _card(
            title: '会话',
            icon: Icons.logout,
            children: [
              CtSettingRow(
                label: '退出',
                child: Row(
                  children: [
                    CtButton.ghost(
                      '退出应用',
                      key: const ValueKey('wb.exit'),
                      onPressed: widget.onExit,
                    ),
                    const SizedBox(width: ctGapSm),
                    Text(
                      '退出前会确认未保存草稿与运行中的写任务',
                      style: ctText(size: ctFontXs, color: ctInk3),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: ctGapLg),
          CtFooterHint(
            child: Text(
              '写操作（保存 Schema、模板、导出、翻译、部署）将在任务 3.x/4.x 逐项接入；'
              '本面板不提供任何 Python 相关配置。',
              style: TextStyle(fontSize: ctFontSm, color: ctInk2),
            ),
          ),
        ],
      ),
    );
  }

  Widget _card({
    required String title,
    required IconData icon,
    required List<Widget> children,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: ctSurface,
        border: Border.all(color: ctBorder),
        borderRadius: BorderRadius.circular(ctRadiusLg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
            child: Row(
              children: [
                Icon(icon, size: 16, color: ctPrimary),
                const SizedBox(width: ctGapSm),
                Text(
                  title,
                  style: TextStyle(
                    fontSize: ctFontMd,
                    fontWeight: FontWeight.w600,
                    color: ctInk,
                  ),
                ),
              ],
            ),
          ),
          ...children,
          const SizedBox(height: ctGapSm),
        ],
      ),
    );
  }
}

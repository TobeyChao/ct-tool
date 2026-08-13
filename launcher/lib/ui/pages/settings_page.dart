import 'package:file_selector/file_selector.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../services/auto_launch.dart';
import '../../services/panel_service.dart';
import '../../services/settings_store.dart';
import '../../theme.dart';
import '../widgets/common.dart';

/// 设置页：工作区 / 端口 / 开机自启 / 托盘常驻
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.settings, required this.panel});

  final SettingsStore settings;
  final PanelService panel;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool _autostartBusy = false;
  bool _autostartSwitch = false;
  late final TextEditingController _wsController;
  late final TextEditingController _portController;

  @override
  void initState() {
    super.initState();
    _wsController =
        TextEditingController(text: widget.settings.workspacePath);
    _portController = TextEditingController(text: '${widget.settings.port}');
    widget.panel.addListener(_onPanelChanged);
    _syncAutostart();
  }

  @override
  void dispose() {
    widget.panel.removeListener(_onPanelChanged);
    _wsController.dispose();
    _portController.dispose();
    super.dispose();
  }

  void _onPanelChanged() {
    if (mounted) setState(() {});
  }

  /// 面板服务运行中（含正在启动）：工作区/端口不可修改，需先停止。
  bool get _serviceActive =>
      widget.panel.status == PanelStatus.running ||
      widget.panel.status == PanelStatus.starting;

  Future<void> _syncAutostart() async {
    try {
      final enabled = await AutoLaunch.instance.isEnabled;
      if (mounted) setState(() => _autostartSwitch = enabled);
    } catch (_) {
      // 平台插件不可用时保持默认关闭，不影响设置页其他功能。
    }
  }

  Future<void> _pickWorkspace() async {
    final path = await getDirectoryPath(
      confirmButtonText: '选择',
      initialDirectory: widget.settings.workspacePath.isNotEmpty
          ? widget.settings.workspacePath
          : null,
    );
    if (path == null || path.isEmpty) return;
    _wsController.text = path;
    await widget.settings.setWorkspacePath(path);
  }

  Future<void> _toggleAutostart(bool value) async {
    if (_autostartBusy) return;
    setState(() => _autostartBusy = true);
    if (kDebugMode) {
      // 对齐 FlClash：debug 构建不写登录项，避免开发时污染系统。
      if (!mounted) return;
      setState(() => _autostartBusy = false);
      showCtToast(context, '调试模式不启用开机自启，正式构建下生效');
      return;
    }
    await AutoLaunch.instance.updateStatus(value);
    await widget.settings.setAutoStart(value);
    if (mounted) {
      setState(() {
        _autostartBusy = false;
        _autostartSwitch = value;
      });
      showCtToast(context, value ? '已开启开机自启' : '已关闭开机自启');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(26, 20, 26, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('设置', style: ctPageTitleStyle),
          const SizedBox(height: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _buildSettingsCard(),
                const Spacer(),
              ],
            ),
          ),
          const SizedBox(height: 8),
          CtFooterHint(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '工作区与端口需在面板停止时修改；其他设置即时生效',
                  style: TextStyle(fontSize: 12, color: ctInk3),
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Icon(Icons.info_outline, size: 14, color: ctInk3),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        widget.settings.trayResident
                            ? '关闭窗口不会退出应用：点击系统托盘的 ct 图标可快速启动 / 暂停 / 退出'
                            : '开启“托盘常驻”后，关闭窗口不会退出应用，可从系统托盘图标恢复',
                        style: const TextStyle(fontSize: 12, color: ctInk3),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSettingsCard() {
    return Container(
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: ctBorder),
      ),
      child: Column(
        children: [
          CtSettingRow(
            label: '工作区',
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _wsController,
                    style: ctMono.copyWith(fontSize: 12),
                    decoration: ctInputDecoration(),
                    enabled: !_serviceActive,
                    onChanged: (v) {
                      widget.settings.setWorkspacePath(v.trim());
                    },
                  ),
                ),
                const SizedBox(width: 8),
                CtButton.ghost(
                  '浏览…',
                  onPressed: _serviceActive ? null : _pickWorkspace,
                ),
              ],
            ),
          ),
          if (_serviceActive)
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 0, 16, 10),
              child: Text(
                '面板服务运行中：请先停止服务再修改工作区 / 端口',
                style: TextStyle(fontSize: 12, color: ctInk3),
              ),
            ),
          CtSettingRow(
            label: '端口',
            child: Row(
              children: [
                SizedBox(
                  width: 90,
                  child: TextField(
                    controller: _portController,
                    style: ctMono.copyWith(fontSize: 12),
                    decoration: ctInputDecoration(),
                    enabled: !_serviceActive,
                    onChanged: (v) {
                      final p = int.tryParse(v.trim());
                      if (p != null && p > 0 && p < 65536) {
                        widget.settings.setPort(p);
                      }
                    },
                  ),
                ),
                const SizedBox(width: 8),
                const Text(
                  '被占用时自动 +1',
                  style: TextStyle(fontSize: 12, color: ctInk3),
                ),
              ],
            ),
          ),
          CtSettingRow(
            label: '开机自启',
            child: Row(
              children: [
                Switch(
                  value: _autostartSwitch,
                  onChanged: _autostartBusy ? null : _toggleAutostart,
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '登录系统后自动启动并运行面板',
                    style: TextStyle(fontSize: 12, color: ctInk3),
                  ),
                ),
              ],
            ),
          ),
          CtSettingRow(
            label: '托盘常驻',
            child: Row(
              children: [
                Switch(
                  value: widget.settings.trayResident,
                  onChanged: widget.settings.setTrayResident,
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '关闭窗口时最小化到托盘，服务不中断',
                    style: TextStyle(fontSize: 12, color: ctInk3),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

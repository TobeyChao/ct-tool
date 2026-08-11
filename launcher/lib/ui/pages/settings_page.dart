import 'package:file_selector/file_selector.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../services/auto_launch.dart';
import '../../services/settings_store.dart';
import '../../theme.dart';
import '../widgets/common.dart';

/// 设置页：工作区 / 端口 / 开机自启 / 托盘常驻
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.settings});

  final SettingsStore settings;

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
    _syncAutostart();
  }

  @override
  void dispose() {
    _wsController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<void> _syncAutostart() async {
    final enabled = await AutoLaunch.instance.isEnabled;
    if (mounted) setState(() => _autostartSwitch = enabled);
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
                  '修改后立即生效，无需重启启动器',
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
                    onChanged: (v) {
                      widget.settings.setWorkspacePath(v.trim());
                    },
                  ),
                ),
                const SizedBox(width: 8),
                CtButton.ghost('浏览…', onPressed: _pickWorkspace),
              ],
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

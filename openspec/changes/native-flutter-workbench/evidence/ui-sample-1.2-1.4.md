# 界面样板证据（任务 1.2 / 1.3 / 1.4）

日期：2026-09-17 · 范围：native-flutter-workbench 第 1 阶段界面部分。

## 交付物

| 内容 | 位置 |
|---|---|
| 设计令牌（间距/字号/圆角/行高/焦点/面板尺寸/窗口约束） | `launcher/lib/ui/tokens.dart` |
| 状态徽章控件（neutral/ok/warn/danger/busy/info 六调） | `launcher/lib/ui/widgets/status_badge.dart` |
| 控件样板页（颜色/字体/按钮/字段行/徽章/焦点/间距圆角行高） | `launcher/lib/ui/dev/component_gallery.dart` |
| 工作台四区壳（模块导航+资源区+主编辑区+可调属性区+底部任务区） | `launcher/lib/ui/workbench/workbench_screen.dart` |
| 模拟数据（明确标识 MOCK，含六种场景） | `launcher/lib/ui/workbench/mock/mock_data.dart` |
| 样板运行入口（场景/缩放/窗口尺寸切换） | `launcher/lib/dev/main_dev.dart` |
| 组件测试（11 项：四区渲染/联动/折叠/拖拽/布局记忆/五态/溢出） | `launcher/test/workbench_test.dart` |
| 截图矩阵 golden（17 张） | `launcher/test/goldens/` |

## 1.2 令牌与控件样板

- 颜色沿用既有深林绿令牌（`theme.dart`），新增数值令牌集中在 `tokens.dart`，焦点统一为 ctAccent 1.5px 描边。
- 控件样板页覆盖按钮（主要/次要/禁用）、字段行（正常/错误/长路径/禁用）、状态徽章全语调、自绘焦点控件与中英文字体样板（26/18/14/13/12/11 + 等宽 + 长文混排）。
- 运行检查：`flutter run -d windows -t lib/dev/main_dev.dart` → 「控件样板」页签。

## 1.3 工作台壳

- 四区布局：左侧模块导航（56px）、资源区（默认 240，180-380 可拖）、主编辑区（字段表/数据预览双页签，表内横向滚动且表头对齐）、属性区（默认 300，240-440 可拖）、底部任务区（默认 190，140-320 可拖、可折叠）。
- 资源区/属性区显式折叠为窄条；窄窗口（<1180/<980）首帧自动折叠，用户手动展开后不再自动折叠；布局按工作区键持久化（shared_preferences）。
- mock 标识：顶部常驻金色「界面样板 · 模拟数据（MOCK），未连接内核」条；数据文件头注明接入内核后整体删除；所有写操作仅 toast 提示并标注接入任务号。

## 1.4 状态与截图矩阵

- 场景：正常 / 空工作区 / 加载失败 / 长文本 / 导出忙碌（写入口锁定）/ 候选冲突（保存锁定，保留草稿入口）。
- 矩阵：1440×900、1280×800、1024×700 × 100%/125%/150%（9 张）+ 六场景（6 张）+ 1024 展开辅助区长文本（1 张）+ 控件样板（1 张）。
- 缩放用 `TextScaler` 模拟：只放大文字不放大盘面，比真机整体等比缩放更严格；真机 100/125/150 复核列入任务 5.5。
- 修复记录：任务行与状态徽章改 `minHeight` 自适应缩放；色板加高；预选首个资源让首屏展示字段表。

## 验证

- `flutter test test/workbench_test.dart` → 11/11 通过。
- `flutter test test/workbench_golden_test.dart` → 17/17 通过（golden 可复现）。
- `flutter analyze` → 0 error（余 1 条 panel_service_test 历史 info）。
- 已知限制：flutter_tester 无 CJK 字体，golden 中中文为占位方块，仅验证布局/对齐/溢出；中文渲染一致性以真机为准（任务 5.1）。
- 预存在的平台相关失败（非本次引入）：`panel_service_test.dart` 的「venv ct 真实启动」断言 Unix 路径 `../ct/.venv/bin/ct`，在 Windows 上不存在。

# Quick Open 与定向视觉验收

环境：macOS 27.0 / Flutter 3.47.0 / Dart 3.13.0；工具链与验收基线详见 [acceptance.md](acceptance.md)。

- 全链夹具启用真实桌面标题栏，使用 `ct.titleBar.quickOpen`，状态栏文案按实际壳使用 `原生内核已连接 · 截图证据` 分段。覆盖翻译模块→空查询最近资源→选中 Item→进入 Schema，完整命令/cursor 保持；不恢复旧草稿条入口。
- `CtButton` 四项 enabled/disabled accent/ghost 测试覆盖点击回调、语义启用态及 tap action、交互状态颜色和实际 Material/Text 渲染。产品颜色/布局未改。
- 原有导航增加 Cmd/Ctrl+P、资源区关闭、搜索、Esc 与焦点恢复验证。真实 worker 二进制为当前工作区构建的 `native/target/debug/ct`。
- 定向更新命令：`flutter test --no-pub --reporter expanded test/workbench_golden_test.dart --update-goldens --name '^(workbench scenario (empty|loadError|busy|conflict)|component gallery)$'`。
- 之后不带 update 标志运行完整 golden：17/17 通过。UI 按钮、导航、标题栏和真实 worker 全链测试共 20/20 通过。

## 像素与人工审阅

使用 AppKit 解码旧 Git 图像和新图像，逐像素比较 RGBA；四张场景图均仅更改右上禁用按钮。component gallery 仅更改禁用 accent/ghost 示例。已读取五张新图像审阅，灰色禁用态符合既有 WidgetState.disabled 代码；布局、错误/忙碌/冲突区域未变化。

| 图像 | 改变像素数 | 改变区域（含端点） |
|---|---:|---|
| workbench_scenario_empty_macos | 1872 | (1156,18)–(1215,50) |
| workbench_scenario_loadError_macos | 1872 | (1156,18)–(1215,50) |
| workbench_scenario_busy_macos | 1872 | (1156,18)–(1215,50) |
| workbench_scenario_conflict_macos | 1872 | (1156,18)–(1215,50) |
| component_gallery_macos | 3495 | (136,676)–(412,708) |

运行前后 SHA-256 对照：34 张基线中仅上述 5 张改变，其余 29 张（包括其他平台基线及 12 张正常 macOS 基线）逐字节相同。像素容差和 CI 验证方式不变；未在 CI 添加期望值生成步骤。测试中的 CJK 占位字体限制保留，不代表真实中文字体验收。

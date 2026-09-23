## 1. 翻译草稿与选中状态

- [x] 1.1 在 `TranslationRepository` 增加选中条目、草稿文本、dirty 状态及选中/取消/重置生命周期；验证单测覆盖选中条目、切换表/语言清空、筛选刷新保留或清理选中项
- [x] 1.2 增加专注编辑器专用的显式保存/取消接口，复用 `saveRow` 并固定提交 `confirmed=true`；验证单测覆盖成功回包、失败保留草稿、未修改不写盘
- [x] 1.3 明确未保存草稿在切换条目、表、语言或筛选时的保存/放弃/取消分支；验证状态测试不会静默丢失草稿

## 2. 专注编辑器界面

- [x] 2.1 重构 `WorkbenchI18nView`，保留表/语言/状态筛选、列显隐和分页，同时让条目选择与专注编辑器共享仓库选中状态；验证 widget 测试可以从列表选中条目并显示键、表、语言、原文、译文
- [x] 2.2 用多行 `TextField` 和只读原文区域替换长文本只读对照弹窗，展示 dirty 状态及保存、取消操作；验证 widget 测试确认多行内容、换行、失焦不提交和取消恢复
- [x] 2.3 使用局部 `LayoutBuilder` 实现宽窗口导航与编辑区并存、窄窗口上下布局或全屏编辑回退；验证 1500×1100、1280×800、1024×700 与 150% 缩放下无溢出且选中/草稿保留

## 3. 键盘与中文输入法

- [x] 3.1 在专注编辑器局部注册 `Ctrl/Cmd+Enter` 保存、`Esc` 取消，并保持 `Enter`/`Shift+Enter` 为换行；验证 widget 测试检查保存请求数量、`confirmed=true` 和取消不写盘
- [x] 3.2 在快捷键入口检查 `TextEditingController.value.composing.isValid`，组合态让输入法优先处理；验证组合态快捷键不触发 `i18n.save` 或草稿恢复
- [x] 3.3 确认翻译编辑器不注册 `Ctrl/Cmd+S`，全局 Schema 草稿快捷键语义不变；验证 widget/捷径测试

## 4. 回归与验收

- [x] 4.1 更新 `workbench_i18n_view_test.dart` 与 `translation_repository_test.dart`，运行 `flutter test test/workbench_i18n_view_test.dart test/state/translation_repository_test.dart` 通过
- [x] 4.2 在 `launcher/` 运行 `flutter analyze`、`dart format --output=none --set-exit-if-changed .` 和完整 `flutter test`，确认无回归
  - 2026-09-23 结果：`flutter analyze` 无问题，`dart format` 0 changed，完整 `flutter test` 331 例全绿；同时修正旧的 `workbench_live_test.dart` 以按当前自绘标题栏断言内核连接状态
- [x] 4.3 运行 `openspec validate polish-native-i18n-editor --strict` 与 `git diff --check`，确认规划与实际行为一致

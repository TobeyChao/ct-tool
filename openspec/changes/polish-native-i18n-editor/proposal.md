## Why

原生翻译页当前把译文编辑塞进固定宽度的单行 `TextField`：Enter 触发保存，无法自然输入多行；长文本的“对照”弹窗又只有只读文本。对包含换行、段落或中文输入法组合文本的条目，这条编辑路径既不完整也不稳定。本变更把多行编辑作为一个明确的原生桌面能力补上，避免继续依赖 Web 对照实现。

## What Changes

- 在原生翻译页增加“条目导航 + 专注编辑区”：保留现有表/语言/状态筛选、列显隐和分页，选中条目后在编辑区集中编辑原文与译文。
- 专注编辑区按窗口宽度适配：宽窗口使用左右对照，窄窗口退化为上下布局或全屏编辑；原文只读并保留换行，译文使用可滚动多行编辑器。
- 明确键盘与保存语义：`Enter`/`Shift+Enter` 插入换行，`Ctrl/Cmd+Enter` 保存并确认当前条目，`Esc` 取消并恢复进入编辑前的文本；不占用全局 `Ctrl/Cmd+S`。
- 处理中文输入法组合态：compose 期间快捷键让给输入法，不能误保存或误取消。
- 专注编辑区采用显式保存，不使用失焦自动提交；短文本行内编辑仍保留失焦保存。保存失败保留草稿和焦点，成功后再用内核返回的 status 更新条目。
- 保持内核协议和 i18n 数据语义不变：仍通过单条 `i18n.save` 写入，不新增后端 API、模板或导出链路。

## Capabilities

### New Capabilities

- `native-i18n-editor`: 原生桌面翻译页的多行编辑、条目导航、专注编辑区及 IME 安全键盘语义。

### Modified Capabilities

<!-- 无。 -->

## Impact

影响 `launcher/lib/ui/workbench/workbench_i18n_view.dart`、`launcher/lib/state/translation_repository.dart`、`launcher/lib/ui/workbench/workbench_shortcuts.dart` 及对应 Flutter widget/state 测试；不改 `native/` 内核协议、i18n 文件格式或导出行为。搜索增强、术语库、翻译记忆和批量编辑不在本次范围。

## Why

当前 i18n 流程只产出 `strings_source.json`（主语言原文快照），翻译者需要手工创建并维护 `strings_{lang}.json` 译文文件。工具不会为次语言生成骨架、不会标记哪些条目是新增/过期/孤儿，导致：

- 新增 i18n 字段或行时，翻译者不知道要补什么 key
- 主语言改动后，工具不告诉翻译者哪些译文已过期
- Schema 删除字段或行删除后，旧译文残留在 lang 文件里无人清理
- 翻译进度无可视化，CI 无法判断是否翻译完整

需要把 lang 文件提升为工具产出物，并提供清晰的翻译状态机。

## What Changes

- **BREAKING** 重构 i18n 文件目录结构：从 `i18n/strings_source.json` + `i18n/strings_{lang}.json` 改为按表拆分 `i18n/source/{table}.json` + `i18n/{lang}/{table}.json`
- **BREAKING** lang 文件格式改为带状态机的对象：`{source, text, confirmed, status}`
- **BREAKING** source 文件格式简化为扁平 `{ "id.field": "text" }`
- **BREAKING** key 格式从 `{TABLE}_{FIELD}_{ID}` 改为 `{id}.{field}`（table 由文件名表达）
- **BREAKING** 移除 source 文件中的 `status` 字段（语言状态完全由 lang 文件承载）
- 新增子命令组 `ct i18n sync`：扫描 schema + Excel，写出 source 文件，并为每个 secondary_lang 生成/更新 lang 骨架
- 新增 `ct i18n status`：报告每语言每表的翻译进度（missing/stale/translated/orphan 计数 + 进度条）
- 新增 `ct i18n compact`：物理移除 lang 文件中所有 `status: orphan` 条目
- `ct export` 内部自动调用 sync 逻辑，确保导出前骨架最新
- 新增四态状态机：`missing` / `translated` / `stale` / `orphan`，由 sync 时根据当前 source 与 lang 文件对比自动计算
- 新增 `confirmed` 布尔字段：原文变更时强制重置为 false，翻译者重新翻译并手动设回 true
- JSON 写出格式：每个 key 占一行，值字段紧凑排列，便于翻译者扫读和 diff
- 删除现有 `gd/i18n/strings_en.json`（占位旧文件）

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `i18n-pipeline`: 重构 i18n 文件结构、key 格式、状态机；新增 lang 骨架生成与孤儿清理流程
- `cli-interface`: 新增 `ct i18n sync/status/compact` 子命令组

## Impact

- **代码**：
  - `ct/export/i18n/extractor.py` 重写为按表输出扁平 source
  - `ct/export/i18n/merger.py` 适配新 lang 文件格式
  - `ct/export/i18n/writer.py` 新增 lang 骨架生成 + 孤儿检测
  - 新增 `ct/export/i18n/sync.py` 编排 sync 流程
  - 新增 `ct/export/i18n/status.py` 计算并渲染进度报告
  - 新增 `ct/cli_helpers/i18n_json.py` 紧凑 JSON 写出工具
  - `ct/cli.py` 添加 `i18n` 子命令组（`Typer` app）
  - `ct/config.py` 增加对每语言子目录的解析助手
- **数据**：
  - `gd/i18n/` 目录结构重组（删除老文件，按 sync 重新生成）
  - 现存 `gd/i18n/strings_en.json` 删除（开发期，不做迁移）
- **测试**：新增 `tests/i18n/` 覆盖 sync/status/compact/状态机/紧凑 JSON 写出
- **文档**：`CLAUDE.md` 更新 i18n 章节与 CLI 列表
- **依赖**：无新增第三方依赖
- **兼容性**：处于开发阶段，明确不做向后兼容；旧格式文件不会被自动迁移

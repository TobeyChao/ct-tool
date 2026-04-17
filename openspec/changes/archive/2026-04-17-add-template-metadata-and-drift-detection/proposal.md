## Why

当前 `ct gen-template` 直接 `Workbook()` 全量覆盖 Excel 文件（[ct-tool/ct/excel/template.py:237](ct-tool/ct/excel/template.py#L237)），文件已有数据会被全部清空。但现有 spec（[excel-processing/spec.md:19](openspec/specs/excel-processing/spec.md#L19) 与 [cli-interface/spec.md:34](openspec/specs/cli-interface/spec.md#L34)）已声明"不影响数据行"，实现与 spec 不一致。同时，策划修改 schema 后容易遗忘重建模板，导致继续用旧表头填写数据，数据与 schema 错位却无人察觉。本次修复实现差距并补齐主动检测能力。

## What Changes

- 在 `generate_template` 时向 Excel 的 Custom Document Properties 写入元数据（工具版本、表名、表头行数、schema 哈希、生成时间）。
- 新增 `compute_schema_hash`：对 `TableSchema` 全字段（含注释、含 struct 嵌套）做规范化 JSON 序列化后取 sha256 前 16 字符，作为模板归属标识。
- `ct gen-template` 新增决策分支与两个 flag：
  - `--force`：全量覆盖（数据会丢）
  - `--update-header`：用旧 `ct_header_rows` 跳过表头，保留所有数据行原样追加到新表头之下
  - 默认行为：根据元数据匹配状态决定 `跳过 / 拒绝 / 直接重建`，并给出明确提示
- table_name 不匹配时**任何 flag 都拒绝**，提示用户手动确认归属。
- Legacy 文件（无元数据）按"不可信"处理：拒绝默认操作；`--update-header` 时退化为用新 schema 的 `header_rows` 推断。
- `ct status` 新增"模板已过时"分类输出：当某张表的当前 schema_hash 与文件内元数据 / 缓存中的 hash 不一致时主动列出。

## Capabilities

### New Capabilities
- 无（本次改动通过修改既有能力实现）

### Modified Capabilities
- `excel-processing`：新增模板元数据写入与读取要求；新增 schema 漂移检测；明确"不影响数据行"的行为契约。
- `cli-interface`：`ct gen-template` 新增 `--force` / `--update-header` 选项及决策矩阵；`ct status` 新增模板漂移分类。

## Impact

- **代码**
  - [ct-tool/ct/excel/template.py](ct-tool/ct/excel/template.py)：`generate_template` 写入元数据；新增 `update_template`、`read_template_metadata`、`detect_data_rows`。
  - [ct-tool/ct/schema/models.py](ct-tool/ct/schema/models.py) 或新文件 `ct/schema/hashing.py`：新增 `compute_schema_hash`。
  - [ct-tool/ct/cli.py](ct-tool/ct/cli.py)：`gen_template` 加 flag 与决策分支；`status` 加模板漂移检测。
  - [ct-tool/ct/cache/state.py](ct-tool/ct/cache/state.py)（可选）：缓存中存 `schema_hash` 加速 status 检测，避免每次都打开 Excel。
- **依赖**：无新增（openpyxl 已支持 Custom Document Properties）。
- **向后兼容**：旧 Excel 文件无元数据时按 legacy 处理，不破坏已有工作流。
- **CLI 行为**：默认行为变化（不再静默覆盖），需要在 release notes 中告知。
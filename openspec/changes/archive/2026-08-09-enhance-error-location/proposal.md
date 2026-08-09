## Why

当前校验错误只给出"数据行序号 + 字段名"（如 `[Item.xlsx] 第3行 Price：...`），
行号是跳过空行后的相对序号，策划无法直接对应到 Excel 里的真实单元格；且
列位置、单元格当前值全部丢失。为让策划"照着错误就能改表"（也为后续
网页面板的错误可视化铺路），需要把 Excel 绝对行号、列字母、当前值带进错误。

## What Changes

行为变更：CLI（`ct export` / `ct validate`）的校验错误文本升级为
**Excel 绝对行号 + 列字母 + 当前值**；校验结果模型填充 `excel_row` /
`column` / `value` 字段（Change 1 已建模但未填充）。

- **reader 保留绝对行号**：`read_excel` 返回 `ParsedRows`（`rows` +
  `excel_rows` 平行结构），跳过空行时仍记录真实 Excel 行号；
  数据与行号分离，不泄漏进任何导出产物。
- **校验器穿透行号**：`validate_table` / `validate_refs` 填充
  `ValidationIssue.excel_row`（主键重复、引用错误同样覆盖）。
- **列定位**：按 `_flatten_fields` + `_column_span` 计算叶子字段的
  0-based 列索引，struct 子字段错误定位到具体叶子列；
  `ValidationIssue.column` 填充，渲染时转列字母。
- **错误文本升级**：`ValidationIssue.render()` 输出
  `[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 'abc' → 期望整数类型`；
  `excel_row` 缺失时回退旧格式；`WorkspaceIssue` 文本不变。
- **CLI 同步受益**：export / validate 自动输出新格式（`render()` 升级即可）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `cli-interface`：修改 "Designer-friendly error messages" 需求——错误
  必须包含 Excel 绝对行号、列字母与当前单元格值，而非相对数据行号。
- `data-validation`：修改类型校验 / 主键唯一性 / 引用校验的场景断言，
  错误格式升级为绝对行号 + 列 + 当前值。

## Impact

- **改动代码**：`tool/ct/excel/reader.py`（返回 `ParsedRows`）、
  `tool/ct/validate/types.py` / `refs.py`（接收 excel_rows、填充 column）、
  `tool/ct/validate/errors.py`（`render()` 新格式）、
  `tool/ct/app/validate.py`（适配 `ParsedRows`）、
  `tool/ct/cli.py`（`_read_all_rows_for_sync` 适配 `.rows`）。
- **测试**：更新 `test_issues.py` 旧断言；新增 reader 行号、struct 叶子列、
  CLI 错误输出快照测试。
- **不涉及**：导出产物格式、校验逻辑本身、i18n 流程、schema 加载。

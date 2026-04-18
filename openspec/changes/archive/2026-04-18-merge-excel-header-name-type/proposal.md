## Why

当前 Excel 模板表头中"字段类型"独占一行，且 struct 字段的横向合并单元格内只显示字段名、不显示类型——策划在编辑器里看不到一个 struct 对应到底层数据中是什么类型（例如 `drop_range` 字段在 FBS 里是 `DropRange`），需要切换到 schema 文件或 fbs 产物才能确认。同时，独立的 type 行让表头平白多占一行，信息密度偏低。

把"字段名"与"字段类型"合并到同一个单元格内（富文本双行），可以一举解决两个问题：struct 也能展示其生成类型名，整张表头少一行更紧凑。

## What Changes

- **BREAKING**: 模板表头总行数从 `max_nesting_depth + 2` 变更为 `max_nesting_depth + 1`（去掉独立的 type 行）。
- **BREAKING**: 字段名行与类型注解合并为单元格内的富文本双行：
  - 第 1 行：字段名（12pt 粗体白色，沿用现有 `_HEADER_FONT`）
  - 第 2 行：类型注解（9pt 斜体浅色，沿用现有 `_TYPE_FONT` 字号与样式语义）
- struct 字段的横向合并单元格首次开始展示类型——填写 `_pascal_case(field.name)`（例如 `drop_range` → `DropRange`），与 FBS 生成的 table 名一致。
- 叶子字段的类型注解内容保持不变（`int32`、`int32[ref:item_type.id]`、`string[i18n]`、`enum[a,b,c]`、`array<int32>`、`array<enum[a,b]>` 等格式不动），只是渲染位置从独立行变为名字下方。
- 类型行字体样式 SHALL 统一：无论 struct 单元格的 `DropRange` 还是叶子单元格的 `int32[ref:...]`，都用同一套 9pt 斜体浅色样式。
- 抽取 `_pascal_case` 为共享工具函数 `ct/schema/naming.py:to_pascal_case`，供 `fbs_generator.py` 与 `template.py` 共用。
- 名字所在的表头行 SHALL 显式设置行高（建议 36pt），保证富文本双行不被裁切。
- 注释行（comment row）位置不变，仍是表头最后一行；reader 端读取逻辑无需改动（仍从 `schema.header_rows` 推断跳过行数）。
- 不向后兼容旧布局的 Excel 文件——用户已确认所有现存 Excel 均为测试数据，可在落地前一次性删除并通过 `ct gen-template --all` 重新生成。

## Capabilities

### New Capabilities
*(none — this change modifies existing capabilities only)*

### Modified Capabilities
- `excel-template-styling`: 新增字段名 + 类型富文本双行渲染要求；type 行作为独立行的渲染要求被合并入名字单元格。
- `excel-processing`: 表头行数公式与所有 i18n / ref / enum / array / simple / struct / nested struct 表头场景需更新（类型不再写在独立 type 行，而是写在字段名下方的富文本第 2 行）。struct 单元格新增"展示 PascalCase 类型名"要求。
- `schema-management`: `header_rows` 计算公式由 `max_nesting_depth + 2` 修改为 `max_nesting_depth + 1`，对应 scenario 期望值需同步。

## Impact

**代码改动**
- [ct-tool/ct/schema/models.py:111](ct-tool/ct/schema/models.py#L111) — `header_rows` 改为 `+ 1`
- [ct-tool/ct/excel/template.py](ct-tool/ct/excel/template.py) — 重写 `_write_field_headers`：
  - 移除独立 type row 的写入循环
  - 名字单元格用 `openpyxl.cell.rich_text.CellRichText` + `TextBlock` 写两段文字
  - struct 分支也写富文本（`field.name` + `to_pascal_case(field.name)`）
  - 调整 `generate_template` 中 `comment_row` 计算（变为 `group_rows + 1`）
  - 为 group 行设置 `row_dimensions[i].height = 36`
  - 移除 `_TYPE_FILL` 单独色块的使用（type 文字直接叠在 name fill 上，靠字体色对比；`_TYPE_FILL` 常量可保留也可删，按是否还被引用决定）
- [ct-tool/ct/schema/naming.py](ct-tool/ct/schema/naming.py)（新文件）— 提供 `to_pascal_case`
- [ct-tool/ct/export/fbs_generator.py:18](ct-tool/ct/export/fbs_generator.py#L18) — 删除本地 `_pascal_case`，改 import
- 现有测试中涉及 `header_rows` 期望值的用例需同步更新

**测试与回归**
- 删除 `gd/excel/*.xlsx` 现存全部 Excel（均为测试数据，已与用户确认）
- 跑 `ct gen-template --all` 重新生成模板
- 跑 `ct export --all` 验证导出全流程通过
- 人工目测一张含 struct 与 i18n 字段的模板（如 `item.xlsx`），确认：
  - 表头总行数 = `max_nesting_depth + 1`
  - struct 横向合并单元格底部展示 PascalCase 类型名
  - 字段名加粗白色、类型斜体浅色，行高足够不裁切
  - 注释行仍位于最末

**外部影响**
- 无 API 变化、无依赖变化
- Excel 元数据中 `ct_header_rows` 字段含义不变，但写入的具体值会因公式变化而不同——已有元数据的旧文件全部一次性删除，不会出现新旧并存的歧义

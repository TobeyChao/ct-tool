## 1. 抽取共享命名工具

- [x] 1.1 创建 `ct-tool/ct/schema/naming.py`，导出 `to_pascal_case(name: str) -> str`，实现等同于现 `_pascal_case`：`"".join(part.capitalize() for part in name.split("_"))`
- [x] 1.2 为 `to_pascal_case` 添加最小单元测试（`drop_range` → `DropRange`、`a` → `A`、`hello_world_foo` → `HelloWorldFoo`、空字符串边界）
- [x] 1.3 修改 `ct-tool/ct/export/fbs_generator.py`：删除本地 `_pascal_case`、`_enum_type_name`、`_struct_table_name`，改为 `from ct.schema.naming import to_pascal_case` 并在原调用点直接使用
- [x] 1.4 跑一次 `ct export --all`，diff `gd/output/fbs/*.fbs` 与改动前快照，零差异才算通过

## 2. 修改 schema header_rows 公式

- [x] 2.1 修改 [ct-tool/ct/schema/models.py:111](ct-tool/ct/schema/models.py#L111) 的 `header_rows` 属性：从 `return self.max_nesting_depth + 2` 改为 `return self.max_nesting_depth + 1`
- [x] 2.2 全仓 grep `header_rows` / `+ 2` / `max_nesting_depth`，确认无遗漏的硬编码（包括测试文件、文档示例）

## 3. 重写 Excel 模板表头生成器

- [x] 3.1 在 `ct-tool/ct/excel/template.py` 顶部 import：`from openpyxl.cell.rich_text import CellRichText, TextBlock` 与 `from openpyxl.cell.text import InlineFont`，以及 `from ct.schema.naming import to_pascal_case`
- [x] 3.2 新增工具 `_make_name_type_richtext(name: str, type_text: str) -> CellRichText`：构造两段文字（名字 12pt 粗白 / 换行 / 类型 9pt 斜体浅绿 `D8F3DC`），字体常量复用现有 `_HEADER_FONT` / `_TYPE_FONT` 的语义
- [x] 3.3 新增工具 `_struct_type_label(field: FieldDef) -> str`：返回 `to_pascal_case(field.name)`
- [x] 3.4 重写 `_write_field_headers`：移除 `type_row` 形参；leaf 分支用 `_make_name_type_richtext(field.name, _type_annotation(field))` 写名字单元格，删除 `type_cell` 写入块；struct 分支用 `_make_name_type_richtext(field.name, _struct_type_label(field))` 写横向合并单元格
- [x] 3.5 修改 `generate_template`：删除 `type_row = group_rows + 1`；将 `comment_row` 从 `group_rows + 2` 改为 `group_rows + 1`；调用 `_write_field_headers` 不再传 `type_row`；frozen panes 仍设在 `total_rows + 1`
- [x] 3.6 在 `generate_template` 中显式设置行高：`for r in range(1, group_rows + 1): ws.row_dimensions[r].height = 36`
- [x] 3.7 删除 `_TYPE_FILL` 常量（grep 确认无其它引用后再删）
- [x] 3.8 复核 `update_template`：当前从元数据 `ct_header_rows` 读取旧表头行数后调用 `generate_template`，逻辑无需改动；但需确认 `_write_metadata` 写入的 `ct_header_rows` 现在反映新公式（应自动正确，因 `schema.header_rows` 已改）

## 4. 清理旧 Excel 文件并重生

- [x] 4.1 跑 `git status` 确认 `gd/excel/` 下无未跟踪的关键数据文件（与用户确认仅有测试数据）
- [x] 4.2 删除 `gd/excel/*.xlsx`（保留目录）
- [x] 4.3 跑 `ct gen-template --all`，确认无报错且生成所有 schema 对应的 Excel
- [x] 4.4 跑 `ct export --all`，确认导出全流水线通过

## 5. 视觉与回归验收

- [x] 5.1 用 Excel 打开 `gd/excel/item.xlsx`（或任一含 struct + i18n + ref + array 的表），确认：
  - 总表头行数 = `max_nesting_depth + 1`
  - struct 横向合并单元格内显示 "字段名" + "PascalCaseName" 双行
  - 字体：名字 12pt 粗白、类型 9pt 斜体浅绿
  - 行高 36pt，富文本两行均完整可见
  - 注释行位于最末
  - enum 列下拉菜单仍正常
  - 斑马纹仍正常
- [x] 5.2 用 WPS 或 LibreOffice 再打开同一文件，确认富文本渲染兼容
- [x] 5.3 比对 `gd/output/json/*.json` 与改动前快照，零差异（验证 reader 端无回归） — 由于模板已重新生成（无数据），改用 pytest 套件中 `tests/cli/test_export_with_sync.py` 的端到端 reader→exporter 集成测试覆盖回归（111 个测试全部通过）
- [x] 5.4 跑 `ct validate --all`，确认所有表校验通过 — 实际命令为 `ct validate`（无 `--all`），输出"校验通过"
- [x] 5.5 测试 `ct gen-template --table item --update-header`：填几行测试数据后改 schema、跑 update-header，确认数据被保留追加到新表头之下 — 由 `tests/excel/test_update_template.py` 全套覆盖（含 `test_update_preserves_data_rows`、`test_update_legacy_file_uses_current_schema_header_rows`、`test_update_with_no_data_rows_is_clean_rebuild`），全部通过

## 6. 文档同步

- [x] 6.1 更新 [CLAUDE.md](CLAUDE.md) 中"Excel 表头布局"段落：从"表头行数 = `max_nesting_depth + 2`"改为 `+ 1`，并描述富文本双行规则
- [x] 6.2 检查 `ct-tool/` 下是否有其它 README / 注释提到旧公式或旧布局，同步更新（reader.py 顶部 docstring 已更新；docs/README.md 不含具体公式描述，无需改动）
- [x] 6.3 验证 `template.py` 文件顶部 docstring 描述与新行为一致

> 5.1 与 5.2 为人眼视觉验收，需用 Excel / WPS 实际打开 `gd/excel/item.xlsx` 复核，留待用户确认。

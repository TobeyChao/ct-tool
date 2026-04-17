## 1. Excel 颜色常量重设计

- [x] 1.1 将 `template.py` 顶部颜色常量替换为深绿色系：`_NORMAL_FILL`=`1B4332`、`_STRUCT_FILL`=`40916C`、新增 `_PRIMARY_FILL`=`C9A227`、`_TYPE_FILL`=`D8F3DC`、`_COMMENT_FILL`=`F2F2F2`
- [x] 1.2 新增白色加粗字体常量 `_HEADER_FONT_LIGHT`（白色 + bold + size 11），替换深色表头行原有的黑色字体
- [x] 1.3 将 `_TYPE_FONT` 改为深绿色 `1B4332` 斜体，`_COMMENT_FONT` 改为灰色 `888888`

## 2. 主键字段高亮

- [x] 2.1 在 `_write_field_headers` 函数签名中增加 `primary_key: str` 参数
- [x] 2.2 在叶字段渲染分支中，判断 `field.name == primary_key` 时使用 `_PRIMARY_FILL` 和 `_HEADER_FONT_LIGHT`
- [x] 2.3 在 `generate_template` 调用 `_write_field_headers` 处传入 `schema.primary`

## 3. enum 字段 DataValidation

- [x] 3.1 在 `generate_template` 末尾，收集所有叶字段及其列号（复用 `_column_span` 遍历逻辑）
- [x] 3.2 对每个 `type == "enum"` 的字段，拼接 `formula1` 字符串（`'"v1,v2,v3"'`），超过 255 字符时 `logger.warning` 并跳过
- [x] 3.3 创建 `DataValidation(type="list", formula1=..., showDropDown=False)`，设置范围为该列数据区（`{col_letter}{total_rows+1}:{col_letter}1000`），添加到 `ws`

## 4. Auto-filter

- [x] 4.1 在 `generate_template` 中，表头写完后设置 `ws.auto_filter.ref`，范围为 comment_row 行、第 1 列到最后一列

## 5. 斑马纹条件格式

- [x] 5.1 导入 `openpyxl.formatting.rule.FormulaRule` 和 `openpyxl.styles.PatternFill`
- [x] 5.2 定义偶数行填充 `_ZEBRA_FILL`=`EDF7EE`
- [x] 5.3 添加两条 `ConditionalFormatting` 规则到数据区（`total_rows+1` 行至 1000 行）：奇数行白色、偶数行 `EDF7EE`

## 6. JSON 单行记录格式

- [x] 6.1 在 `json_writer.py` 的 `write_json` 函数中，将 `json.dump(data, f, ensure_ascii=False, indent=2)` 替换为手动拼接：每条记录用 `json.dumps(item, ensure_ascii=False)` 序列化，组合为 `{\n  "root_key": [\n    line1,\n    line2\n  ]\n}` 格式写入文件

## 7. 验证

- [x] 7.1 运行 `ct gen-template --all`，打开生成的 Excel 文件，目视验证颜色层次、主键高亮、enum 下拉、auto-filter、斑马纹
- [x] 7.2 运行 `ct export`，检查 JSON 文件每条记录是否为单行，用 `python -c "import json; json.load(open('...'))"` 验证 JSON 合法性
## Context

`ct gen-template` 通过 `ct/excel/template.py` 生成空白 Excel 模板。当前样式：颜色全部为浅色系（浅绿/浅蓝/浅黄/浅灰），字体均为黑色，视觉层次弱；无 enum 下拉、无 auto-filter、无斑马纹。

`ct export` 通过 `ct/export/json_writer.py` 输出 JSON，使用 `json.dump(..., indent=2)`，一个含 10 个字段的记录展开约 15 行，百条记录的表超过 1500 行。

## Goals / Non-Goals

**Goals:**
- 重设 Excel 模板颜色为深绿色系，建立清晰视觉层次
- 主键字段用暖金色独立标识
- enum 字段添加 DataValidation 下拉菜单
- 表头末行添加 Auto-filter
- 数据区添加斑马纹条件格式（奇白偶浅绿）
- JSON 每条记录输出为单行紧凑格式

**Non-Goals:**
- 不修改 CLI 接口、schema 格式、Excel 读取逻辑
- 不调整列宽（保持固定 16）
- 不添加标题行
- 不修改 FlatBuffers / binary 输出

## Decisions

### D1：Excel 颜色常量全量替换

用命名常量定义新配色，集中在文件顶部，易于后续调整：

| 常量 | 颜色值 | 用途 |
|------|--------|------|
| `_NORMAL_FILL` | `1B4332`（深森林绿）| 普通字段名行背景 |
| `_STRUCT_FILL` | `40916C`（中绿）| struct 名称行背景 |
| `_PRIMARY_FILL` | `C9A227`（暖金色）| 主键字段名行背景 |
| `_TYPE_FILL` | `D8F3DC`（极浅绿）| type 行背景 |
| `_COMMENT_FILL` | `F2F2F2`（浅灰）| comment 行背景 |
| `_HEADER_FONT_LIGHT` | 白色加粗 | 深色背景上的字体 |
| `_TYPE_FONT` | 深绿 `1B4332` 斜体 | type 行字体 |

主键判断：在 `_write_field_headers` 中传入 `primary_key: str` 参数，当 `field.name == primary_key` 时使用 `_PRIMARY_FILL`。

**备选方案考虑**：动态计算颜色层次 → 否决，固定常量更可预测，调色更直接。

### D2：DataValidation 仅对 enum 字段生效

openpyxl 的 `DataValidation` 支持 `type="list"` + `formula1='"v1,v2,v3"'`。在 `generate_template` 函数末尾，遍历所有叶字段，对 `type == "enum"` 的字段：
1. 获取其列号
2. 创建 DataValidation，范围覆盖数据区（从表头后第一行到第 1000 行）
3. 添加到 worksheet

enum 值数量无硬限制，但 Excel DataValidation formula1 字符串上限约 255 字符，超出时跳过（记录 warning 日志）。

### D3：Auto-filter 加在表头最后一行

`ws.auto_filter.ref` 设为从第 1 列到最后一列、仅覆盖表头末行（`comment_row`）的范围。Auto-filter 的展示行是末行，但实际筛选作用于下方数据行，行为与 Excel 原生一致。

### D4：斑马纹用条件格式

使用 openpyxl `ConditionalFormattingList` + `FormulaRule`：
- 奇数行（`MOD(ROW(),2)=1`）：白色背景
- 偶数行（`MOD(ROW(),2)=0`）：`EDF7EE`（极浅绿）背景

范围：数据起始行（`total_rows + 1`）到第 1000 行，全列。条件格式不影响已有的表头样式。

### D5：JSON 手动拼接替代 json.dump indent

```python
lines = [json.dumps(item, ensure_ascii=False) for item in items]
body = ",\n    ".join(lines)
output = f'{{\n  "{root_key}": [\n    {body}\n  ]\n}}'
```

替代 `json.dump(..., indent=2)`。结构一致，内容等价，每条记录占一行。

**备选方案**：自定义 JSONEncoder → 实现复杂，无额外收益。

## Risks / Trade-offs

- **斑马纹与用户自定义格式冲突** → 条件格式优先级低于手动格式，用户覆盖后斑马纹不生效，可接受
- **DataValidation 255 字符限制** → enum 值过多时跳过并 warning，不阻断生成
- **JSON 格式变化影响已有工具链** → 内容等价，仅格式不同；JSON 解析器不受影响，肉眼 review 更友好

## Migration Plan

无需迁移。已生成的 Excel 文件不受影响（只影响新生成的模板）。已生成的 JSON 文件在下次 `ct export` 后自动以新格式覆盖。
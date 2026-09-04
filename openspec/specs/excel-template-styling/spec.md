## Purpose

为生成的 Excel 模板表头定义统一视觉样式（深绿色系、富文本双行渲染、下拉菜单等），提升策划填表体验与可读性。

## Requirements

### Requirement: 深绿色系视觉层次
模板表头各行 SHALL 使用深绿色系配色，形成视觉层次：普通字段名行 `1B4332`（深森林绿）+ 白色加粗字体（名字部分），struct 名称行 `40916C`（中绿）+ 白色加粗字体（名字部分），主键字段名行 `C9A227`（暖金色）+ 白色加粗字体（名字部分），comment 行 `F2F2F2`（浅灰）+ 灰色字体。所有字段名单元格内的"类型注解"部分均使用 9pt 斜体浅绿 `D8F3DC` 字体，叠加在所属单元格底色上。

#### Scenario: 普通字段名单元格渲染
- **WHEN** 生成包含普通字段的模板
- **THEN** 单元格背景色为 `1B4332`，名字部分为白色加粗 12pt，类型部分为浅绿 `D8F3DC` 斜体 9pt

#### Scenario: struct 字段名单元格渲染
- **WHEN** 生成包含 struct 类型字段的模板
- **THEN** 横向合并单元格背景色为 `40916C`，名字部分为白色加粗 12pt，类型部分（PascalCase 类名）为浅绿 `D8F3DC` 斜体 9pt

#### Scenario: 主键字段单元格渲染
- **WHEN** 生成模板且 schema 定义了 primary 字段
- **THEN** 单元格背景色为 `C9A227`，名字部分为白色加粗 12pt，类型部分为浅绿 `D8F3DC` 斜体 9pt

#### Scenario: comment 行渲染
- **WHEN** 生成模板
- **THEN** comment 行背景色为 `F2F2F2`，字体为灰色

### Requirement: 字段名与类型在同一单元格富文本双行渲染
模板表头中每个字段单元格 SHALL 使用 openpyxl 的 `CellRichText` 在同一格内渲染两段文字：第一段为字段名（12pt 粗体白色字体，沿用 `_HEADER_FONT` 风格），第二段为类型注解（9pt 斜体，浅色字 `D8F3DC`），中间用换行分隔。叶子字段的类型注解文本使用 `_type_annotation(field)` 现有规则（例如 `int32`、`int32[ref:item_type.id]`、`string[i18n]`、`enum[a,b,c]`、`array<int32>`、`array<enum[a,b]>`）；struct 字段的类型注解文本使用 `to_pascal_case(field.name)`（与 FBS 生成的 table 名一致）。无论 struct 还是叶子，类型行字体样式 MUST 完全一致。

#### Scenario: 叶子字段渲染
- **WHEN** 生成模板，schema 含一个 `id: int32` 字段
- **THEN** 该字段单元格内为富文本：第一行 "id"（12pt 粗体白），第二行 "int32"（9pt 斜体浅绿 `D8F3DC`）

#### Scenario: 带 ref 的叶子字段渲染
- **WHEN** schema 字段 `item_type_id: int32, ref: item_type.id`
- **THEN** 单元格第一行为 "item_type_id"，第二行为 "int32[ref:item_type.id]"，字体规则同上

#### Scenario: i18n 字段渲染
- **WHEN** schema 字段 `name: string, i18n: true`
- **THEN** 单元格第一行为 "name"，第二行为 "string[i18n]"

#### Scenario: enum 字段渲染
- **WHEN** schema 字段 `rarity: enum, values: [common, rare, epic]`
- **THEN** 单元格第一行为 "rarity"，第二行为 "enum[common,rare,epic]"

#### Scenario: array 字段渲染
- **WHEN** schema 字段 `tags: array, element: int32`
- **THEN** 单元格第一行为 "tags"，第二行为 "array<int32>"

#### Scenario: struct 字段横向合并单元格渲染类型
- **WHEN** schema 含 `drop_range: struct{min: int32, max: int32}`
- **THEN** 横向合并的 struct 单元格内第一行为 "drop_range"（12pt 粗体白），第二行为 "DropRange"（9pt 斜体浅绿 `D8F3DC`），与 FBS 生成的 table 名一致

#### Scenario: 主键字段类型行字体规则不变
- **WHEN** schema primary 为 id（int32）
- **THEN** id 单元格底色仍为 `C9A227` 金色，第一行 "id" 仍为 12pt 粗体白色，第二行 "int32" 字体仍为 9pt 斜体浅绿 `D8F3DC`，与非主键字段在类型字体上完全一致

### Requirement: 名字所在表头行显式设置行高
`generate_template` SHALL 为表头中所有字段名所在的行（即第 1 行至第 `max_nesting_depth` 行）显式设置行高为 36pt，确保富文本两段文字均不被裁切。注释行（最后一行）不设置显式行高，使用 Excel 默认值。

#### Scenario: 浅嵌套表行高
- **WHEN** 表 `max_nesting_depth = 1`，生成模板
- **THEN** 第 1 行行高为 36pt，第 2 行（注释行）使用默认行高

#### Scenario: 深嵌套表行高
- **WHEN** 表 `max_nesting_depth = 3`，生成模板
- **THEN** 第 1、2、3 行行高均为 36pt，第 4 行（注释行）使用默认行高

### Requirement: enum 字段下拉菜单
模板 SHALL 为所有 `type == "enum"` 的叶字段添加 DataValidation，限定合法值为 schema 定义的 `values` 列表，范围覆盖该列数据区（表头后第 1 行至第 1000 行）。

#### Scenario: enum 字段有下拉
- **WHEN** schema 包含 enum 字段且生成模板
- **THEN** 该字段对应列的数据区单元格显示下拉菜单，仅允许输入 schema 中定义的枚举值

#### Scenario: enum 值过长跳过
- **WHEN** enum 所有值拼接后超过 255 字符
- **THEN** 跳过该字段的 DataValidation 并记录 warning 日志，模板正常生成

### Requirement: Auto-filter
模板 SHALL 在表头最后一行（comment 行）对应的整行范围添加 Auto-filter。

#### Scenario: auto-filter 存在
- **WHEN** 打开生成的模板
- **THEN** 表头末行每列显示筛选箭头

### Requirement: 数据区斑马纹
模板 SHALL 通过条件格式为数据区设置斑马纹：奇数行白色背景，偶数行 `EDF7EE`（极浅绿）背景，范围为表头后第 1 行至第 1000 行。

#### Scenario: 斑马纹渲染
- **WHEN** 在生成的模板中填入数据
- **THEN** 奇数数据行背景为白色，偶数数据行背景为极浅绿 `EDF7EE`
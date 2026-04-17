## ADDED Requirements

### Requirement: 深绿色系视觉层次
模板表头各行 SHALL 使用深绿色系配色，形成从深到浅的视觉层次：普通字段名行 `1B4332`（深森林绿）+ 白色加粗字体，struct 名称行 `40916C`（中绿）+ 白色加粗字体，主键字段名行 `C9A227`（暖金色）+ 白色加粗字体，type 行 `D8F3DC`（极浅绿）+ 深绿色斜体，comment 行 `F2F2F2`（浅灰）+ 灰色字体。

#### Scenario: 普通字段名行渲染
- **WHEN** 生成包含普通字段的模板
- **THEN** 字段名所在行背景色为 `1B4332`，字体颜色为白色且加粗

#### Scenario: struct 字段名行渲染
- **WHEN** 生成包含 struct 类型字段的模板
- **THEN** struct 名称行背景色为 `40916C`，字体颜色为白色且加粗

#### Scenario: 主键字段名行渲染
- **WHEN** 生成模板且 schema 定义了 primary 字段
- **THEN** 主键字段名行背景色为 `C9A227`，字体颜色为白色且加粗

#### Scenario: type 行渲染
- **WHEN** 生成模板
- **THEN** type 行背景色为 `D8F3DC`，字体为深绿色斜体

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
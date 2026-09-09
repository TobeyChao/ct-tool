## Purpose

在导出前对工作空间数据做完整校验（字段类型强转、主键唯一、跨表 ref 外键存在性），任一问题即中止落盘，避免脏数据进入产物。

## Requirements

### Requirement: Validate field types against schema
工具 SHALL 检查每行每个字段的值是否符合 schema 声明的类型，并提供
**Excel 绝对行号、列字母和字段名**定位。

#### Scenario: Type mismatch detected with exact location
- **WHEN** schema 声明 `Price: float`，但 Excel 该格（第 6 行，列 C）填写了 `"贵"`
- **THEN** 报错：`[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 '贵' → 期望 float`

#### Scenario: Null in required field
- **WHEN** 非可选字段的 Excel 单元格为空
- **THEN** 报错指明表名、Excel 绝对行号、列字母与字段名

#### Scenario: Primary key uniqueness
- **WHEN** 同一张表中存在重复的主键值
- **THEN** 报错：`[Item.xlsx] Excel 第6行 · 列A (Id) · 当前值 1001 → 主键值 1001 重复（首次出现在第5行）`

### Requirement: Validate cross-table references
工具 SHALL 按拓扑顺序处理，校验 `ref` 字段的值在目标表的主键集合中存在。

#### Scenario: Valid reference
- **WHEN** `Item.ItemTypeId = 3`，且 ItemType 表中 id=3 存在
- **THEN** 校验通过，继续处理

#### Scenario: Invalid reference with exact location
- **WHEN** `Item.ItemTypeId = 99`，但 ItemType 表中无 id=99
- **THEN** 报错：`[Item.xlsx] Excel 第8行 · 列E (ItemTypeId) · 当前值 99 → 值 99 在引用表 ItemType.Id 中不存在`

#### Scenario: Referenced table not yet loaded
- **WHEN** 被引用表的 hash 未变化，从缓存读取其 id 集合
- **THEN** 校验正常进行，无需重新解析被引用表 Excel

### Requirement: Batch error reporting
工具 SHALL 在完成所有行的校验后统一报告全部错误，而非遇到第一个错误就终止。

#### Scenario: Multiple errors in one table
- **WHEN** 同一张表存在 3 处类型错误和 1 处引用错误
- **THEN** 一次性输出全部 4 条错误，方便策划批量修正

### Requirement: Generate type-aware Excel input assistance
模板 SHALL 对最终物理数据列生成类型感知的轻量输入辅助并覆盖至 Excel 第 1,048,576 行；辅助 SHALL NOT 替代 validate/export 的完整校验。定长 vector 的每个槽位 SHALL 继承元素类型辅助，Record SHALL 将辅助施加到后代叶子列。

#### Scenario: Bool uses a portable dropdown
- **WHEN** 模板包含 bool 叶子
- **THEN** 数据列提供 `TRUE/FALSE` 下拉、允许空白并以 Stop 错误拒绝其他手工输入，不使用复选框控件

#### Scenario: Enum uses declared values
- **WHEN** 模板包含 Enum 叶子且内嵌候选公式不超过 255 字符
- **THEN** 数据列提供按声明顺序排列的 Enum 下拉并以 Stop 错误拒绝列表外值

#### Scenario: Numeric leaf constrains input kind
- **WHEN** 模板包含 int32、int64、float 或 double 叶子
- **THEN** int32 提供带类型上下界的整数验证，float/double 提供有限范围十进制数验证；int64 因 Excel 不能精确保存全部 64 位整数而只显示提示，超过 15 位时提示以文本录入；所有类型允许非必填字段为空且 canonical validate/export 负责最终精度与类型校验

#### Scenario: Ref shows its canonical target
- **WHEN** 叶子标记 `ref: ItemType.Id`
- **THEN** 选中数据格时显示目标 `ItemType.Id` 及“最终由 validate/export 校验”的提示，不创建隐藏候选表或声称 Excel 已完成外键校验

#### Scenario: Variable vector shows syntax prompt
- **WHEN** 模板包含无 `excel_columns` 的 vector 叶子
- **THEN** 选中数据格时提示使用 `[...]` 文法及对应元素示例

### Requirement: Validate canonical bracketed vector syntax
数据校验 SHALL 要求无 `excel_columns` 的 vector 使用方括号和固定英文逗号。数字元素不加引号、bool 使用小写 `true/false`、Enum 使用未加引号的合法标识符、string 使用带 JSON 转义的双引号；元素外围空格 SHALL 被忽略，字符串引号内空格 SHALL 保留。旧的无括号或自定义分隔符格式 SHALL 被拒绝。

#### Scenario: Typed vector forms are accepted
- **WHEN** 单元格分别填写 `[1,2]`、`[true,false]`、`[Common,Rare]` 和 `["Sword","Health Potion"]` 且元素类型匹配
- **THEN** 四种 vector 均解析为对应 typed list

#### Scenario: Structural whitespace is ignored
- **WHEN** 单元格填写 `[ 1, 2, 3 ]`
- **THEN** 解析结果为 `[1, 2, 3]`

#### Scenario: String escaping is preserved
- **WHEN** `vector<string>` 填写 `["a,b","line\\nnext"]`
- **THEN** 解析得到两个字符串，其中逗号属于第一项、转义换行属于第二项

#### Scenario: Malformed vector reports exact location
- **WHEN** 单元格填写 `[1,,2]` 或未闭合字符串
- **THEN** 错误包含 Excel 绝对行、列、字段、出错元素或字符位置及原值

### Requirement: Validate fixed vector slot defaults
对于 `vector<T>` 的 N 个展开槽位，校验 SHALL 以最后一个显式填写槽位作为实际长度；该槽位之前的全空槽位 SHALL 合法并合成 T 的默认值，之后的全空槽位 SHALL 忽略。Record 槽位在任一后代叶子非空时视为显式填写，其余空叶子 SHALL 递归补默认值。`None` 与仅含空白的字符串 SHALL 视为空；数字 0、布尔 false 和显式 Enum name SHALL 视为已填。默认值 SHALL 为整数 0、浮点 0.0、bool false、string 空串、Enum 首项 name、vector 空列表，以及递归默认 Record。

#### Scenario: Hole before last scalar slot is valid
- **WHEN** `vector<double>[3]` 填写 `1.0, 空, 3.0`
- **THEN** 校验通过并产生 `[1.0, 0.0, 3.0]`

#### Scenario: All slots empty
- **WHEN** 定长展开 vector 的所有槽位为空
- **THEN** 校验通过并产生空 vector

#### Scenario: Empty Record slot before filled slot is valid
- **WHEN** Slot #1 的所有 Record 叶子为空且 Slot #2 任一叶子非空
- **THEN** Slot #1 合成递归默认 Record，实际 vector 长度为 2

#### Scenario: Explicit false and zero occupy a slot
- **WHEN** fixed bool 或 numeric vector 的末槽分别填写 FALSE 或 0
- **THEN** 该槽位视为显式填写并计入实际 vector 长度

#### Scenario: Blank trailing default-only element is omitted
- **WHEN** expanded `vector<string>` 的末槽为空，或 Record 末槽的所有叶子均为空
- **THEN** 该槽位始终被视为未填写并省略；需要尾部空字符串时仅可在支持的单格变长形式中填写 `[""]`

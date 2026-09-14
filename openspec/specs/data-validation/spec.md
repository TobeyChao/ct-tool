## Purpose

在导出前对工作空间数据做完整校验（字段类型强转、主键唯一、**CodeName 索引键非空且唯一**、跨表 ref 外键存在性），任一问题即中止落盘，避免脏数据进入产物。

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

### Requirement: Validate the CodeName index key
**声明了 codename 索引**的表，其每行的 `CodeName` SHALL 非空且按精确原字符串唯一；违反时校验 SHALL
报错并给出带 Excel 定位的 issue（重复值另附首次出现的行号），错误码 `duplicate_codename`
（空值/字段缺失报 `type`）。**导出与 `ct validate` 两条路径 SHALL 都执行该校验。**

> 为什么这条必须在数据校验层落地：导出器建桶表时对空串跳过、也**不判重**，所以没有这道闸门时，
> 重复的 CodeName 会**静默**导出成功，而运行期 `ByCodeName()` 只命中探测序更靠前的那个 ——
> 另一行永远查不到且毫无提示。语义上 CodeName 就是「这张表按它唯一索引」。
> （约束本身定义在 `schema-editor/query-indexes`，此处负责在数据层执行。）

#### Scenario: Duplicate CodeName detected with exact locations
- **WHEN** 声明了 codename 索引的表里两行 `CodeName` 相同（第 4、5 行）
- **THEN** 报错：表名 + Excel 行号 + 列 + 原始值，并指出首次出现在第几行

#### Scenario: Blank CodeName detected
- **WHEN** 声明了 codename 索引的表里某行 `CodeName` 为空
- **THEN** 报错（该行永远查不到）

#### Scenario: Tables without the index are unaffected
- **WHEN** 表没有声明 codename 索引
- **THEN** 不对 `CodeName` 施加非空/唯一约束（它只是一个普通字段）

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

### Requirement: Validate enum token domain
validate/export SHALL 在读取使用具名 Enum 的字段时校验每个 token（含 scalar、定长 Enum 槽位与变长 Enum vector 的每个元素）属于当前 Enum 声明的 name 集合。未知 token SHALL 报类型错误并定位表、字段、Excel 行与原始值，导出 SHALL NOT 落任何产物；序列化 SHALL NOT 把未知 token 静默映射为任何 ordinal（当前实现会落到 `0`）。

> 为什么必须在数据校验层落地：Binary serializer 用 `names.index(value) if value in names else 0` 解析 Enum，JSON 则原样输出字符串 —— 没有这道闸门时，删除一个仍被数据引用的 Enum item 会让 Binary 静默变成 ordinal 0（JSON 仍显示旧名），两侧产物互相矛盾且没有任何提示。保存侧不读数据，因此这是该约束的唯一执行点。

#### Scenario: Removed enum token blocks export
- **WHEN** 某行 Enum 字段（或 Enum vector 的某个元素）写着已从 schema 删除的旧 token
- **THEN** validate/export 失败并给出表名、字段、Excel 行号与原始值，`output/` 不产生新产物

#### Scenario: Declared tokens still export normally
- **WHEN** 所有 Enum 单元格都是当前声明集合内的 token
- **THEN** 校验与导出照常通过，Binary、JSON、Accessor 的 Enum 语义不变

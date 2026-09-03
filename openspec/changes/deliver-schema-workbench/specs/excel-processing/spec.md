## MODIFIED Requirements

### Requirement: Generate Excel template headers from schema
`ct gen-template` 与 Workspace Apply SHALL 根据 canonical Type Expression 和 Excel 输入布局生成模板头部，头部行数为所需嵌套深度加注释行。Record 与展开 `vector<Record>` SHALL 以稳定字段路径展开，单格 vector SHALL 保持单列；更新模板 SHALL 根据 Change Plan 的路径映射搬移数据，不按旧列位置盲目追加。

#### Scenario: Simple table header (no record)
- **WHEN** Schema 只有 scalar、Enum 和单格 vector，最大深度为 1
- **THEN** 生成字段名+类型富文本行和注释行，列顺序与 Candidate 字段顺序一致

#### Scenario: Record field expands to multiple columns
- **WHEN** 字段引用 `DropRange` Record，包含 Min 与 Max
- **THEN** 模板以该字段路径为父组展开两个叶子列，父级类型注解显示 `DropRange`

#### Scenario: Vector record expands to configured groups
- **WHEN** `Rewards: vector<DropReward>` 使用展开模式且 `excel_columns: 3`
- **THEN** 模板生成三组确定性路径，每组包含 DropReward 的全部叶子列，注解表明运行时类型仍为 `vector<DropReward>`

#### Scenario: Non-record columns merged vertically
- **WHEN** 其他字段导致表头有多个层级而 Id 为 scalar
- **THEN** Id 单元格跨非注释层垂直合并并显示字段名与 `int32`

#### Scenario: i18n field header
- **WHEN** string 字段标记 `i18n`
- **THEN** 类型注解明确显示 i18n 角色且与 Web 编辑器表达一致

#### Scenario: ref field annotation
- **WHEN** 字段约束 `ref: ItemType.Id`
- **THEN** 类型注解显示目标路径并可由模板元数据恢复

#### Scenario: enum field annotation
- **WHEN** 字段引用 ItemRarity Enum
- **THEN** 类型注解显示 `ItemRarity`，允许值来自唯一 Enum 定义而非复制到字段

#### Scenario: vector field annotation
- **WHEN** 字段类型为 `vector<int32>` 且采用单格 separator 模式
- **THEN** 类型注解显示 `vector<int32>`，注释区域说明 separator

#### Scenario: Update header preserves mapped data
- **WHEN** 已有模板通过 Workspace Apply 更新字段顺序、改名或 Record 展开布局
- **THEN** 系统按稳定旧路径、新路径和显式 rename map 搬移数据，未映射的非空值形成阻塞或明确计划项，不静默错列

#### Scenario: Untracked file requires preflight
- **WHEN** Excel 无可信路径元数据且布局变化需要搬移数据
- **THEN** Change Plan 将其标记为需要推断或人工处理，不在无审查的情况下写回文件

### Requirement: Compute schema hash including all template-visible fields
工具 SHALL 对影响模板、读取或生成契约的 canonical Schema 做确定性序列化并计算强 hash；输入 SHALL 包含 Type Expression、命名资源内容、字段顺序、注释、ref/i18n/server_only、Excel 布局和查询索引。hash SHALL 用于漂移与并发检测，但关键查询正确性不得只依赖 hash 相等。

#### Scenario: Field added changes hash
- **WHEN** Schema 新增字段
- **THEN** schema hash 改变

#### Scenario: Referenced record change changes hash
- **WHEN** Table 本身未改但其引用 Record 新增叶子字段
- **THEN** 影响该 Table 模板/输出的 hash 改变

#### Scenario: Excel layout change changes hash
- **WHEN** 仅将 `excel_columns` 从 3 改为 5
- **THEN** 模板 hash 改变且 Change Plan 识别为布局变化

#### Scenario: Hash is deterministic
- **WHEN** 不同进程对同一 canonical workspace 计算 hash
- **THEN** 结果完全一致

### Requirement: Read Excel data with struct and array fields
工具 SHALL 根据 canonical Type Expression 与字段路径读取 Record 和 vector：展开 Record 叶子重组为对象，单格 vector 按 separator 解析，展开 `vector<Record>` 按组读取并忽略全空尾组。解析错误 SHALL 定位到实际 Excel 行、列和 canonical 字段路径。

#### Scenario: Record columns reassembled
- **WHEN** `DropRange.Min=10` 且 `DropRange.Max=20`
- **THEN** 解析结果为对应 DropRange 对象

#### Scenario: Vector parsed with separator
- **WHEN** `vector<int32>` 单元格值为 `1,2,5`
- **THEN** 解析结果为 `[1, 2, 5]`

#### Scenario: Expanded vector record parsed
- **WHEN** 三个可填写组中前两组有数据、第三组全空
- **THEN** 解析结果包含两个 Record 元素且不生成空占位对象

#### Scenario: Vector element error located
- **WHEN** `vector<int32>` 的第二个值为 `abc`
- **THEN** 错误指出 Excel 行列、字段路径和第 2 个元素原值

## ADDED Requirements

### Requirement: Plan Excel data changes by stable paths
Workspace Change Plan SHALL 比较旧/新列路径和显式 rename command，生成可审查映射，并扫描删除、收缩和类型转换位置的非空数据；无法无损处理的数据 SHALL 阻止 Apply。

#### Scenario: Rename retains values
- **WHEN** `Item.Name` 显式改名为 `Item.DisplayName`
- **THEN** 所有旧 Name 单元格映射到 DisplayName，计划显示搬移数量且不创建重复列

#### Scenario: Type conversion failure
- **WHEN** string 字段改为 int32 且存在不可转换值
- **THEN** Change Plan 列出失败行列和原值并阻止 Apply

## RENAMED Requirements

- FROM: `Read Excel data with struct and array fields`
- TO: `Read Excel data with Record and vector fields`

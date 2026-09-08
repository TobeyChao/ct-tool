## ADDED Requirements

### Requirement: 类型化可访问表头配色
模板 SHALL 使用节点类型而非嵌套深度决定表头颜色，并 SHALL 同时以类型文字和边框表达结构，避免颜色成为唯一线索。表头采用中等明度底和深色文字：普通叶子 `E2E8F0/64748B/DCE3EC/475569`，Record `CFE8D8/2F6B4A/DCE3EC/475569`，数组 `D7E6FA/315B9A/DCE3EC/475569`，数组槽位 `E7D9F7/6B4AA1/DCE3EC/475569`，主键 `FBE6A5/8A5A00/DCE3EC/475569`；字段名统一使用 `172033`，保证文字与白色数据区有足够对比度。配色优先级 SHALL 为主键 > 结构节点类型 > 普通叶子；Enum 叶子的类型文字改用 `6B4AA1`，ref 叶子的类型文字改用 `315B9A`，Enum+ref 时 Enum 强调优先。

#### Scenario: Mixed node types are visually distinct
- **WHEN** 同一表头含普通叶子、Record、数组、数组槽位和主键
- **THEN** 各节点使用规定配色，且字段类型文字仍明确包含 Record 类型、`vector<T>[N]`、槽位序号或 `[primary]`

### Requirement: 表头节点边框层级
模板 SHALL 使用 `thin #CBD5E1` 表示普通内部边界、`medium #64748B` 表示兄弟结构节点与数组槽位边界、`medium #1E293B` 表示顶层字段边界、`medium #0F172A` 表示完整表头外框，并在表头与数据区之间使用 `double #334155`。合并节点 SHALL 在完整周界绘制边框且 SHALL NOT 保留合并区域内部竖线。单条边重叠时优先级 SHALL 为数据分隔双线 > 表头外框 > 顶层字段边界 > 兄弟/槽位边界 > 普通内部线。

#### Scenario: Nested boundaries remain legible
- **WHEN** Record、嵌套 Record 和定长 Record vector 同时出现
- **THEN** 用户可由外框、顶层边界、槽位边界和叶子细线识别每个节点的准确跨度

### Requirement: 表头文字对齐
字段名、类型、系统生成的槽位说明及 Schema 注释 SHALL 水平和垂直居中、开启自动换行、禁用 shrink-to-fit、无额外缩进且不旋转。纵向合并叶子 SHALL 在完整合并区域内居中。

#### Scenario: Long nested comment remains readable
- **WHEN** Record 或叶子注释需要换行
- **THEN** 注释从左侧统一起点换行，而其对应字段名和类型仍在节点跨度内居中

### Requirement: Enum 表头悬停 Note
每个 Enum 物理叶子字段格 SHALL 附加传统 Excel Note，Note SHALL 显示 Enum 名称、Enum 类型注释，以及按声明顺序排列的每个 `name: comment`；空项注释只显示 name。Note SHALL 挂在合并区域锚点，使用固定宽度和按行数计算且有上限的高度。它 SHALL 作为辅助信息而非枚举定义的唯一入口。

#### Scenario: Hover enum header shows item comments
- **WHEN** ItemRarity 定义 Common/Rare/Epic 及各自注释
- **THEN** Rarity 表头字段格显示 Note 指示，悬停可按声明顺序读取类型说明和三个枚举项注释

#### Scenario: Fixed enum vector repeats the note
- **WHEN** `vector<ItemRarity>[3]` 展开为三个槽位
- **THEN** 三个 Enum 叶子字段格均附加相同的 ItemRarity Note

### Requirement: Freeze complete generated header
模板 SHALL 冻结全部 `2D` 行表头但 SHALL NOT 默认冻结任何数据列。

#### Scenario: Scroll deep table data
- **WHEN** 用户向下滚动 `D=3` 的工作表
- **THEN** `freeze_panes` 为 `A7`，第 1 至第 6 行保持可见且所有数据列仍可水平滚动

## MODIFIED Requirements

### Requirement: 字段名与类型在同一单元格富文本双行渲染
模板中每个字段格 SHALL 以富文本显示两段：字段名使用 Aptos 11pt `172033` 加粗，类型注解使用 Consolas 9pt 和节点对应强调色，中间以单个换行分隔。普通类型显示 canonical 类型文本；Enum 显示 `<EnumName> [enum]`；Record 显示具名类型；定长展开数组显示 `vector<T>[N]`；槽位显示 `#N` 与元素类型；主键、ref、i18n、server 标记按 `[primary] [ref: T.F] [i18n] [server]` 顺序追加。

#### Scenario: 叶子字段渲染
- **WHEN** 生成 `Id: int32` 主键字段
- **THEN** 字段格第一行显示 Id，第二行显示 `int32 [primary]`

#### Scenario: Named enum is explicit
- **WHEN** Rarity 引用 ItemRarity Enum
- **THEN** 字段格第一行显示 Rarity，第二行显示 `ItemRarity [enum]`

#### Scenario: Record field renders named type
- **WHEN** DropRange 引用 ItemDropRange Record
- **THEN** 横向合并字段格第一行显示 DropRange，第二行显示 ItemDropRange

#### Scenario: Fixed vector exposes maximum slots
- **WHEN** Rewards 为 `vector<DropReward>` 且 `excel_columns: 3`
- **THEN** 数组字段格第二行显示 `vector<DropReward>[3]`，三个槽位分别显示 `#1/#2/#3` 与 DropReward

#### Scenario: 带 ref 的叶子字段渲染
- **WHEN** `ItemTypeId: int32` 标记 `ref: ItemType.Id`
- **THEN** 第一行显示 ItemTypeId，第二行显示 `int32 [ref: ItemType.Id]`，使用同一富文本字体规则

#### Scenario: i18n 字段渲染
- **WHEN** `Name: string` 标记 `i18n: true`
- **THEN** 第一行显示 Name，第二行显示 `string [i18n]`

#### Scenario: enum 字段渲染
- **WHEN** Rarity 引用 ItemRarity Enum
- **THEN** 第一行显示 Rarity，第二行显示 `ItemRarity [enum]`，Enum 类型文字使用节点对应的浅紫强调色

#### Scenario: array 字段渲染
- **WHEN** Tags 为 `vector<int32>`
- **THEN** 第一行显示 Tags，第二行显示 `vector<int32>`；定长展开时另含 `[N]`

#### Scenario: struct 字段横向合并单元格渲染类型
- **WHEN** DropRange 引用 ItemDropRange 且展开为 Min/Max
- **THEN** DropRange 字段格横跨两个后代叶子，第一行显示 DropRange，第二行显示 ItemDropRange

#### Scenario: 主键字段类型行字体规则不变
- **WHEN** Id 为 int32 主键
- **THEN** 使用主键配色，但名字仍为 Aptos 11pt `172033` 加粗，类型仍为 Consolas 9pt 并显示 `int32 [primary]`

### Requirement: 名字所在表头行显式设置行高
模板 SHALL 将每个注释行默认设为 30pt，并根据显式换行及合并跨度总列宽估算的换行数确定性增长、上限 60pt；同一行取所有节点估算值的最大值。每个字段行 SHALL 固定为 38pt。空注释 SHALL 保留注释行高度，任何节点 SHALL NOT 因注释为空而折叠层级。

#### Scenario: 浅嵌套表行高
- **WHEN** `D=1` 且注释无需额外换行
- **THEN** 第 1 行为 30pt 注释行，第 2 行为 38pt 字段行

#### Scenario: 深嵌套表行高
- **WHEN** `D=3`
- **THEN** 三组注释/字段行分别遵循 30pt/38pt，长注释所在行可增长但不超过 60pt

### Requirement: enum 字段下拉菜单
模板 SHALL 为 Enum 的每个物理叶子数据列添加直接内嵌候选值的列表 DataValidation，范围从数据起始行覆盖至 Excel 第 1,048,576 行；候选值 SHALL 保持 Schema 声明顺序。若包含外层引号的完整验证公式超过 255 字符，模板 SHALL 跳过下拉、保留输入提示并产生明确 warning，且 SHALL NOT 创建隐藏 Sheet、辅助列或命名范围。

#### Scenario: enum 字段有下拉
- **WHEN** ItemRarity 候选公式不超过 255 字符
- **THEN** 每个 Rarity 数据格从数据起始行到第 1,048,576 行均可选择按声明顺序排列的合法值

#### Scenario: enum 值过长跳过
- **WHEN** Enum 候选公式超过 255 字符
- **THEN** 模板正常生成、不含该下拉、不创建隐藏数据结构，并报告具体 Enum 的辅助降级 warning

### Requirement: 数据区视觉保持简洁
模板 SHALL NOT 对数据区生成任何条件格式颜色。数据区所有列保持白色底。

#### Scenario: 普通数据区保持简洁
- **WHEN** 打开包含预留空行的模板
- **THEN** 数据列不包含斑马纹或类型辅助色条件格式并保持白色底

## REMOVED Requirements

### Requirement: 深绿色系视觉层次
**Reason**: 单一绿色层级无法区分 Record、数组、槽位和主键，且旧 Record/主键底色与白字对比度不足。
**Migration**: 新模板按节点类型使用 slate/green/indigo/purple/amber 的成对深浅色。

### Requirement: Auto-filter
**Reason**: 多层合并表头不存在适合作为每列唯一标题的统一行，且本工作流不要求模板内筛选。
**Migration**: 不生成 AutoFilter，也不增加额外物理列名行。

### Requirement: 数据区类型辅助色
**Reason**: 用户反馈数据区颜色干扰录入，统一白底更清晰。
**Migration**: 保留数据验证和 Enum Note，但移除 Bool/Enum/ref 条件格式颜色。

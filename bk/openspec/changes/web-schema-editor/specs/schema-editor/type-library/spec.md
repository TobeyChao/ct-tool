## Purpose

全局具名类型库：把 enum/struct 从字段内联定义抽离为 `config/types/*.yaml` 中的可复用具名类型，字段以 `type_ref` 引用，供 web 编辑器、schema 加载、fbs 生成与导出链路共同消费。

## ADDED Requirements

### Requirement: 类型库分模块存储与加载

工具 SHALL 从 `config/types/` 加载所有 `*.yaml`（一文件一模块，文件名即模块名），每个文件含 `types:` 列表；`TypeDef` 模型 SHALL 承载 `name`（全局唯一）、`kind`（enum/struct）、enum 的 `values` 与 `underlying`（整数底层类型，默认 int32）、struct 的 `fields`（递归 FieldDef，字段可带 comment）、类型级 `comment`。跨文件重名 SHALL 报错。

#### Scenario: 加载合法类型库
- **WHEN** `config/types/common.yaml` 含合法 TypeDef 定义（enum Rarity + struct DropRange）
- **THEN** 工具成功解析，`type_map` 提供全局名称 → TypeDef 查询

#### Scenario: 跨模块重名
- **WHEN** 两个模块文件定义同名类型
- **THEN** 加载报错并指明两个模块文件名，终止执行

### Requirement: 字段引用具名类型（type_ref）

字段 SHALL 通过 `type_ref` 引用具名 enum/struct（`FieldDef.type_ref`），vector 元素通过 `element_type_ref`（具名类型）或 `element_type`（标量元素，如 `int32`）引用；`type_ref` / `element_type` / `element_type_ref` SHALL 由**同一解析函数**解析为内部 canonical 模型，FBS / 二进制 / Excel / 访问器 / Web API 只消费该模型。引用目标 SHALL 存在于类型库，不存在则报错。加载时 SHALL 校验 enum 必须有非空 values、struct 必须有非空 fields、enum 底层类型仅限整数标量（int8/16/32/64、uint8/16/32/64）、struct 字段仅限标量或嵌套 struct（FlatBuffers 约束，不得含 string/vector/table）、vector 定长 `fixed_length` 为正整数（>= 1）。注释承载 SHALL 为：类型本身 → `TypeDef.comment`，struct 字段 → `FieldDef.comment`，enum 值 → 无注释（保持 `values: list[str]`）。

#### Scenario: 引用缺失
- **WHEN** 字段 `type_ref` 指向类型库中不存在的类型名
- **THEN** 加载报错指明字段与缺失的类型名

#### Scenario: struct 含非标量字段
- **WHEN** 类型库 struct 定义含 string 或 vector 字段
- **THEN** 加载报错（FlatBuffers struct 仅允许标量或嵌套 struct）

#### Scenario: 标量元素引用
- **WHEN** vector 字段元素为标量（如 `element_type: int32`）
- **THEN** 与具名元素（`element_type_ref`）走同一解析函数，各层消费同一 canonical 模型

### Requirement: 撞名不变量事前校验

类型名 SHALL 不得与任何表内字段名相同；该不变量 SHALL 在「加载 schema + 类型库」时统一校验（从 fbs 生成后检查前移），命中即报错提示改名。

#### Scenario: 类型名撞字段名
- **WHEN** 类型库存在类型 `Rarity` 且某表字段名为 `Rarity`
- **THEN** 加载报错指明冲突的类型与字段，提示改名

#### Scenario: 保存类型时撞名拦截
- **WHEN** 通过 `/api/types` 创建/更新一个与现有字段名冲突的类型名
- **THEN** 接口拒绝并提示撞名（保存/导出报错，R8.7-4）

### Requirement: fbs 真名生成

fbs 输出 SHALL 使用类型真名（`enum Rarity` / `struct DropRange`），无 `Enum`/`Struct`/`Elem` 后缀；`ELEM_SUFFIX` 与 `FbsConvention` 后缀常量 SHALL 退役。全量迁移后 schema 中 SHALL 无内联 enum/struct 残留。

#### Scenario: fbs 使用真名
- **WHEN** 表字段引用类型库 `Rarity` 并导出
- **THEN** 生成的 .fbs 含 `enum Rarity`，不含 `RarityEnum` 等后缀名

#### Scenario: enum 底层类型产出
- **WHEN** 类型库 enum 声明 `underlying: uint16` 并导出
- **THEN** fbs 声明 `enum X : uint16`、二进制按对应宽度序列化、C# 访问器生成枚举底层类型与之一致（不再固定 `: byte`）

#### Scenario: 注释进 Excel 表头
- **WHEN** 类型或 struct 字段带注释并生成 Excel 模板
- **THEN** 表头注释行显示对应注释（类型注释与字段注释均可承载）

### Requirement: 类型库 Web API

`/api/types` SHALL 提供类型 CRUD：`GET /api/types`（列表含模块）、`GET /api/types/<name>`（详情）、`POST /api/types`（创建，含 module 归属）、`PUT /api/types/<name>`（更新，可改 module = 跨文件移动）、`DELETE /api/types/<name>`（删除）；`GET /api/types/modules` SHALL 返回模块列表（扫描 `types/*.yaml` 文件名，供编辑器下拉与页签筛选）。

#### Scenario: 创建类型
- **WHEN** 前端 POST 新类型 `{name, kind, values/fields, module}`
- **THEN** 类型写入对应模块文件，列表接口返回该类型

#### Scenario: 删除被引用类型
- **WHEN** DELETE 一个仍被字段引用的类型
- **THEN** 接口拒绝并返回引用处列表（表名.字段名）

### Requirement: 类型依赖图与环检测

加载阶段 SHALL 建立「表字段 + 类型字段」的全局依赖图与反向索引：struct 嵌套引用构成依赖边，直接/间接 struct 环（递归 struct）SHALL 被拒绝并报错指明环路径；删除/改名类型时 SHALL 依据反向索引给出影响面（删除被引用拒绝、改名原子更新全部引用或拒绝）。

#### Scenario: 递归 struct 环
- **WHEN** 类型 A 的 struct 字段引用类型 B，B 的字段又引用 A
- **THEN** 加载报错指明环路径（A → B → A），终止执行

### Requirement: 现有 schema 迁移（一次性工具，已退役）

**2026-08-31 退役**：一次性迁移脚本（`ct/schema/migration.py` + `ct migrate-types` 命令）已完成历史使命并删除——迁移是一次性工具，不随产品保留（用户确认）。迁移语义记录如下供追溯：将现有内联 enum/struct 抽出写入类型库、字段改为 `type_ref`、`array` 类型改为 `vector`；迁移前类型命名 SHALL 经过全局名称分配（避免与任何字段名冲突，冲突时生成稳定替代名或报错给出可读提示）。当前 `config/types/*.yaml` 与 schema `type_ref` 均已迁移完成。

#### Scenario: 迁移内联类型（历史行为，已执行）
- **WHEN** 对含内联 `Item.DropRange` / `Item.Rarity` 的旧 schema 运行迁移脚本（历史已执行）
- **THEN** 类型写入 `config/types/common.yaml`，字段变为 `type_ref` 引用，导出与迁移前产物一致（仅命名变化）

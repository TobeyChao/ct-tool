# ct Schema / 类型编辑器 UX 调研

> 日期：2026-08-31
> 目的：为新一版 Schema 编辑器原型与 OpenSpec 提供设计依据。旧 `bk` 原型仅作为问题样本和局部交互参考，不作为新界面的骨架。
> 方法：只参考官方规范、官方产品文档或官方项目仓库；以下“适合 ct / 不适合 ct”均为基于这些资料和 ct 现状作出的设计推导。

## 结论摘要

不建议复刻 JSON Schema、GraphQL、Prisma、Hasura 或数据库设计器中的任意一个界面。ct 同时编辑 YAML Schema、Excel 布局、FlatBuffers 二进制契约和 C#/Lua Accessor，现成产品没有完全相同的问题域。

新原型最值得采用的组合是：

1. **GraphQL 的可组合类型表达式**：命名类型与 `vector` 修饰正交，`record` 是普通命名类型，`vector<record>` 不应成为一套特殊分支。
2. **JSON Schema 的定义/引用分离**：类型定义只有一个真源，字段只持有引用；编辑器提供可搜索选择和“转到定义”。
3. **Prisma 的索引独立建模**：CodeName、group index 是表级查询契约，不是字段类型，也不宜继续堆成字段布尔开关。
4. **Strapi 的集中草稿与状态**：允许跨表、跨类型编辑，但在统一“应用变更”前都只是草稿，明确显示 New / Modified / Deleted。
5. **Hasura 的候选配置一致性检查**：先验证完整候选 Workspace，再原子落盘，不能先写某个 YAML 再发现全局引用已经损坏。
6. **Prisma / Atlas 的变更计划与风险分级**：保存不是直接写文件，而是生成可审阅的 Schema / Excel / Binary / Accessor 影响计划。
7. **Directus 的关注点分区**：把存储契约、编辑体验、校验、引用和查询索引分开呈现，避免一行字段塞满所有选项。

建议的新主流程：

```text
编辑草稿
  → 实时局部校验
  → 准备应用
  → 构建完整 Candidate Workspace
  → 生成 Change Plan
      ├─ Schema 差异
      ├─ Excel 列映射与数据扫描
      ├─ 类型/表引用影响
      ├─ FlatBuffers / Accessor 兼容性
      └─ CodeName / group index 数据检查
  → 修复阻塞项或确认可接受风险
  → 原子应用
  → 重新加载与 postcheck
```

## 1. 类型系统：用统一 Type Expression，避免互斥字段组合

### 外部模式

GraphQL 把类型分成命名类型和正交修饰符。对象字段可以引用命名对象，List 与 Non-Null 作为包装层组合，例如 `[Episode!]!`，而不是为“对象数组”发明一种额外类型。[GraphQL：Schemas and Types](https://graphql.org/learn/schema/)

JSON Schema 用 `$defs` 保存可复用定义，用 `$ref` 指向定义；数组的 `items` 本身仍是一份 schema，所以数组元素可以自然地是对象或引用。[JSON Schema：Modular JSON Schema combination](https://json-schema.org/understanding-json-schema/structuring)、[JSON Schema：Array](https://json-schema.org/understanding-json-schema/reference/array)

FlatBuffers 明确支持“vector of any other type”；table 是主要对象结构，可以增加或废弃字段，struct 则只能包含标量/其他 struct、全部字段必填且不能演进。[FlatBuffers：Schema](https://flatbuffers.dev/schema/)

### 适合 ct

后端应统一为递归 Type Expression，而不是继续扩展 `type`、`type_ref`、`element_type`、`element_type_ref` 这组互斥字段。推荐领域模型：

```yaml
type:
  kind: vector
  element:
    kind: named
    name: Reward
```

也可以在 YAML 中采用受控的 `vector<Reward>` 文本，但进入后端后应立即解析成同一个 AST，后续 Excel、FBS、Binary 和生成器只消费 AST。

推荐第一版类型集合：

- scalar：`int8` / `int16` / `int32` / `int64` / 对应 unsigned / `float` / `double` / `bool` / `string`
- enum：具名枚举
- record：生成 FlatBuffers `table`
- vector：包装任意允许的 element；`vector<vector<T>>` 继续禁止，若未来需要可用 record 包一层

界面中类型表达式只需要两个正交动作：

- 选择基础/命名类型；
- 切换“单值 / 列表”。

`record` 与 `vector<record>` 使用同一个选择器和同一个类型引用模型。点击命名类型进入它自己的定义页，不在当前字段行内递归展开整个定义。

### 不适合 ct

- 不采用 JSON Schema 完整关键字体系；`allOf` / `oneOf` / 条件 schema 会远超 ct 导出器能力。
- 不照搬 GraphQL 的 Non-Null 语义；ct 的空值/default 规则要由 Excel reader、validator 和 FlatBuffers writer 共同定义。
- 不把现有“实际生成 table 的 struct”继续叫 struct。FlatBuffers 官方对 struct 的限制很严格，新编辑器应使用 `record`，真正的 native struct 留作未来独立能力。

## 2. 信息架构：资源树 + 主编辑区 + 检查器，替代多层模态

### 外部模式

Strapi 的 Content-Type Builder 把 collection、single type、component 分组列在侧栏；可同时修改多个定义，统一 Save，并为资源/字段显示 New、Modified、Deleted 状态，还提供集中 Undo/Redo 和 Discard All。[Strapi：Content-type Builder](https://docs.strapi.io/cms/features/content-type-builder)

Directus 把字段的存储 Schema、Field 行为、Interface、Display、Validation 分成不同配置区；官方还明确区分底层数据类型与用户实际使用的输入界面。[Directus：Fields](https://directus.com/docs/guides/data-model/fields)

GraphiQL 官方项目提供带搜索的文档浏览器、智能类型提示和实时错误提示，说明“搜索 + 导航到类型定义”比把所有类型内容同时展开更适合大型类型集合。[GraphiQL 官方仓库：Features](https://github.com/graphql/graphiql/blob/main/packages/graphiql/README.md)

Sanity 的数组类型选择菜单支持搜索、分组和 list/grid 视图，并在允许类型超过一定数量时自动启用过滤。[Sanity：Array type](https://www.sanity.io/docs/studio/array-type)

### 适合 ct

建议使用稳定的三栏工作台：

```text
┌──────────────────┬──────────────────────────────────┬────────────────────┐
│ 资源树           │ 主编辑区                         │ 检查器 / 草稿摘要  │
│                  │                                  │                    │
│ 表               │ 当前表或类型的字段表格           │ 当前字段配置       │
│  · Item          │                                  │ 校验问题           │
│  · Quest         │ Name | Type | Ref | Comment      │ 引用来源           │
│ 类型             │ ...                              │ 未保存变更摘要     │
│  · Reward        │                                  │                    │
│  · ItemRarity    │                                  │                    │
└──────────────────┴──────────────────────────────────┴────────────────────┘
```

- 左栏同时容纳“表”和“类型”，支持搜索、模块筛选和错误/已修改徽标。
- 中栏只编辑当前资源；表与 record 使用一致的字段表格，enum 使用值列表编辑器。
- 右栏显示选中字段的低频属性，避免 `i18n`、`server_only`、`ref`、Excel 展开、索引等全部拥挤在字段行。
- 字段行保留最常用信息：名称、类型表达式、简短状态徽标、注释摘要。
- 命名类型点击后在同一主编辑区打开，并保留返回栈/面包屑；不叠加新的全屏 modal。
- 类型选择器是唯一的短生命周期弹层：支持键盘搜索、基础类型/enum/record 分组、当前选择高亮。

### 不适合 ct

- 不再使用“表编辑 modal → 类型 picker modal → 类型查看 modal → 嵌套类型 modal”的层叠结构。它会放大焦点、取消、草稿恢复和 Esc 行为的复杂度。
- 不把 ER 图作为主编辑器。DataGrip 官方把数据库图定位为结构与关系的可视化、查找和导航工具；这适合只读总览，但图节点不适合承载 ct 的 Excel、i18n、server-only、索引和导出属性。[DataGrip：Database diagrams](https://www.jetbrains.com/help/datagrip/creating-diagrams.html)
- 可在后续增加只读“依赖图”，但第一版不是交付前置。

## 3. record 与 vector：编辑“引用”，不要递归复制定义

### 外部模式

Strapi 的 component 是可被多个 content type 复用的独立结构，repeatable component 表达重复结构；component 与 collection 一样在独立区域管理，而不是每次使用都复制一份字段定义。[Strapi：Content-type Builder](https://docs.strapi.io/cms/features/content-type-builder)

Sanity 数组可容纳对象或引用，数组项可以使用独立 preview；同时为数组提供排序、添加、删除、复制等专用动作。[Sanity：Array type](https://www.sanity.io/docs/studio/array-type)

FlatBuffers table 可以作为 vector 元素，struct 才是受限的内联定长结构。[FlatBuffers：Schema](https://flatbuffers.dev/schema/)

### 适合 ct

record 使用应显示为轻量引用：

```text
Rewards   Reward[]   ↗ Reward   [Excel: 展开 5 组]
```

- `Reward[]` 是类型表达式；点击 `Reward` 转到定义。
- “Excel 展开 5 组”是展示/录入布局，建议配置名为 `excel_columns`，不叫运行时 `fixed_length`。
- record 的字段只在 record 定义页编辑；表字段引用它时不可局部覆盖字段结构。
- 使用处可以有与引用无关的属性，例如 comment、server_only、Excel 展开列数。
- 删除/改名 record 时先展示所有使用点；默认阻止删除被引用 record。

vector 不应弹出另一套复杂编辑器。右栏只显示：

- 元素类型（由统一类型选择器决定）；
- Excel 输入模式：单格分隔 / 展开列；
- `excel_columns`（仅展开列模式）；
- separator（仅单格分隔模式，且仅允许 reader 支持的元素）。

### 不适合 ct

- 不支持在使用处匿名定义大型 record；匿名内联定义会让复用、导航、删除保护和 FBS 生成重新复杂化。
- 不采用 Sanity 的异构数组；ct 的 vector 应保持单一 element type，便于 Excel、FlatBuffers 和 Accessor 静态生成。
- 不强制 `vector<record>` 必须“运行时定长”。Excel 展开列数只是输入上限，导出的仍是普通变长 vector。

## 4. 引用导航：显式依赖、反向引用与路径定位

### 外部模式

JSON Schema 用 `$id` 标识 schema、`$ref` 指向定义，并允许用 JSON Pointer 精确定位子 schema；核心思想是“引用具有明确目标，不靠复制内容维持一致”。[JSON Schema：Modular JSON Schema combination](https://json-schema.org/understanding-json-schema/structuring)

Prisma 把实际保存的 scalar foreign-key field 与 relation field 分开，并用 `@relation(fields:, references:)` 显式声明源字段和目标字段。[Prisma：Relational data modeling](https://www.prisma.io/docs/orm/data-modeling/relational-databases)

Hasura 允许通过外键或显式 column mapping 定义关系；删除有依赖的关系时默认报依赖错误，只有显式 cascade 才连带删除。[Hasura：Metadata API Relationships](https://hasura.io/docs/2.0/api-reference/metadata-api/relationship/)

### 适合 ct

需要在候选 Workspace 中统一建立：

- 正向依赖：`Item.Reward -> Reward`、`Item.TypeId -> ItemType.Id`；
- 反向依赖：某类型/字段/表被哪些位置引用；
- 稳定位置：`Table.Field`、`Type.Field`，Excel 迁移时扩展成叶子路径。

UI 行为：

- `ref` 是字段的独立约束，不混入类型选择器。
- 选择 ref 时只列出类型兼容的目标字段，默认主键优先。
- 点击 ref 或 record 名称可以转到目标定义。
- 右栏“被引用于”显示可点击列表。
- 删除类型、表、字段默认阻止，并展示所有引用点；第一版不提供 cascade delete。
- 改名是显式操作，Change Plan 保留 `old_path → new_path`，不能仅从最终快照猜测。

### 不适合 ct

- 不生成 Prisma 式双向虚拟 relation field；ct 的 ref 主要用于校验，不是 ORM 导航模型。
- 不让前端发送 YAML 字符串或自行展开/复制类型。前端只提交结构化 JSON 命令或完整候选模型，YAML 序列化由后端负责。

## 5. 保存模型：集中草稿，不直接落盘

### 外部模式

Strapi 在多资源编辑期间显示 New / Modified / Deleted，统一 Save 后才确认变更，同时提供跨资源 Undo/Redo 和 Discard All。[Strapi：Content-type Builder](https://docs.strapi.io/cms/features/content-type-builder)

Prisma 的迁移流程强调先从契约生成可审阅计划，再执行；新增必填字段但旧数据无值时，生成的计划需要 backfill，再收紧约束。[Prisma：How migrations work](https://www.prisma.io/docs/orm/migrations/how-migrations-work)、[Prisma：Editing a migration](https://www.prisma.io/docs/orm/migrations/editing-a-migration)

Hasura 指出数据库 schema、metadata 或操作失败都可能造成配置不一致，并提供 inconsistency list，而不是把部分成功当作正常状态；官方推荐使用 migrations 管理 schema 和 metadata。[Hasura：Resolving Metadata Inconsistencies](https://hasura.io/docs/2.0/migrations-metadata-seeds/resolving-metadata-inconsistencies/)

### 适合 ct

前端维护 Workspace Draft，右栏持续展示：

- 新增 / 修改 / 删除资源数量；
- 当前校验错误；
- 尚未应用的危险操作；
- 撤销 / 重做 / 丢弃全部。

“保存”建议改名为“审阅并应用”，分两步：

1. `POST /api/workspace/change-plan`：后端用结构化 JSON 构建 candidate，完成全局校验和数据扫描，返回 plan；不修改文件。
2. `POST /api/workspace/apply`：携带 plan id / candidate hash，防止计划后源文件变化；在临时目录生成 YAML、Excel、FBS、Binary、Accessor，通过 postcheck 后原子替换。

错误必须定位到具体资源、字段、Excel 行/列。任一必需产物失败，整个 apply 不落盘。

### 不适合 ct

- Prisma 的长期迁移目录、迁移图和数据库分支能力对本地工具第一版过重。
- ct 第一版只需“可审阅 change plan + 自动备份/临时文件 + 原子应用 + 可重试”，不必建立永久迁移 DSL。
- 不把“编辑某个表”直接等价为“立刻重建 Excel 和重新导出”。编辑草稿与外部副作用必须有清晰边界。

## 6. 危险变更与 Excel 数据迁移预览

### 外部模式

GraphQL 将删除、改名、改字段类型、删除 enum 值等归类为 breaking change，推荐“先增加替代项 → 标记 deprecated 并说明原因 → 迁移 → 最后移除”。[GraphQL：Schema Change Management](https://graphql.org/learn/governance-versioning/)

Atlas 的迁移检查会区分 destructive、data-dependent 和 backward-incompatible 等风险；删除列属于 destructive，增加唯一约束则可能取决于现有数据。[Atlas：Migration Analyzers](https://atlasgo.io/lint/analyzers)、[Atlas：Verifying Migration Safety](https://atlasgo.io/versioned/lint)

FlatBuffers 的兼容规则要求 table 新字段追加到末尾，旧字段不能直接移除而应 deprecated；改名不影响 wire 中的字段位置，但会破坏生成代码和 JSON 使用方。[FlatBuffers：Evolution](https://flatbuffers.dev/evolution/)

Strapi 官方特别提醒：界面上的字段 rename 在数据库层可能等价于新建字段并删除旧字段，原字段数据随后无法从管理界面访问。[Strapi：Content-type Builder](https://docs.strapi.io/cms/features/content-type-builder)

### 适合 ct

Change Plan 至少区分五类风险：

| 风险类别 | ct 示例 | 原型行为 |
|---|---|---|
| 安全新增 | 新增可选字段、增加未引用 record | 绿色摘要，可直接应用 |
| 数据依赖 | 启用 CodeName 唯一、类型收窄、enum 删除值 | 扫描 Excel，显示具体行号和样例值 |
| 数据破坏 | 删除字段、减少 `excel_columns` 且尾部有数据 | 红色阻塞，要求显式迁移/保留备份 |
| 客户端不兼容 | 字段/类型改名、enum wire type 变化 | 展示受影响 FBS、C#、Lua API |
| 依赖破坏 | 删除被引用表、字段或 record | 默认阻止，列出引用链 |

迁移审阅建议使用整页或宽抽屉，不用确认小弹窗：

```text
变更 Item.Rewards：Reward[3] → Reward[5]

Schema        excel_columns 3 → 5
Excel         新增 Rewards[4].*、Rewards[5].* 共 6 列
数据          无丢失；现有 128 行可直接迁移
Binary        wire 类型不变
Accessor      API 不变

                       [返回编辑] [应用变更]
```

字段改名显示明确映射：

```text
Item.Name → Item.DisplayName
自动映射 128 个非空单元格；不会创建第二份数据列
```

类型变化则显示转换统计：成功数、空值数、失败行号与原值。存在失败时禁止应用，不能只给泛化警告。

### 不适合 ct

- 不按旧/新列序号搬数据。
- 不把 rename 猜成 delete + add。
- 不提供“我知道风险，仍覆盖全部”作为常规捷径；无法转换的数据需要先修复或选择明确的数据处理规则。
- GraphQL 数月级 deprecation 生命周期不适合本地配表工具，但“增加 → 迁移 → 删除”的顺序适合高风险 wire/API 变化。

## 7. CodeName、唯一约束与 group index

### 外部模式

Prisma 把 `@unique` / `@@unique` / `@@index` 与字段类型分开；索引还可拥有名称、排序和复合字段配置。这说明索引是模型/查询契约，而不是数据类型的一部分。[Prisma：Indexes](https://www.prisma.io/docs/orm/v7/prisma-schema/data-model/indexes)

Directus 的字段 Schema 配置也把 type、unique、indexed 等属性区分开；校验在客户端运行后仍会由服务端重新执行。[Directus：Fields](https://directus.com/docs/guides/data-model/fields)

Atlas 将“给已有重复数据的列增加唯一约束”视为依赖数据才能确定安全性的变化，适合在计划阶段扫描而非保存后才失败。[Atlas：Migration Analyzers](https://atlasgo.io/lint/analyzers)

### 适合 ct

UI 中应设置独立的“查询与索引”区域，而不是把 CodeName、group_key 塞进类型选择器：

```text
查询与索引

Code lookup
  字段          CodeName
  唯一          是（固定）
  生成 API      ByCode(string)
  数据检查      128 行，0 空值，0 重复

Group lookup
  字段          Category
  唯一          否（固定）
  生成 API      ByGroupKey(Category)
  数据检查      8 个分组，最大组 31 行
```

字段表格中仍可显示只读徽标 `Code` / `Group`，点击徽标定位到表级索引配置。

推荐后端从第一版就使用可扩展的索引模型：

```yaml
indexes:
  - name: code
    fields: [CodeName]
    unique: true
    accessor: ByCode
  - name: group
    fields: [Category]
    unique: false
    accessor: ByGroupKey
```

即使首版产品只允许一个 CodeName 和一个 group index，模型也不必再引入 `code_name: true` / `group_key: true`。这样未来支持多个 group index 或复合索引时不必再次迁移所有 Schema。

Change Plan 中需要分别验证：

- CodeName 字段存在、为 string、非空、表内唯一；
- group 字段属于允许的 scalar/enum 类型；
- 现有 Excel 数据可构建索引；
- Binary writer、C#/Lua generator 对该索引都存在实现；
- hash 索引命中后仍校验原值以保证碰撞正确性。

### 不适合 ct

- 不开放 Prisma 的所有数据库索引选项；ct 第一版不需要排序、access method、部分索引或任意复合索引 UI。
- 不让用户手填 Accessor 名称；Code 与 Group 使用稳定生成约定，避免跨语言命名不一致。
- 不把“唯一性”只做成 Excel 数据验证。浏览器、CLI export、validate 和 Binary 构建都必须执行同一后端规则。

## 8. 推荐的新原型页面

新原型建议覆盖 7 个关键状态，而非把所有功能堆在一张页面：

### P1. Workspace 工作台

- 左侧表/类型资源树、搜索、模块筛选。
- 中间欢迎态或最近编辑资源。
- 右侧 Workspace 健康状态和未应用草稿。

### P2. 表编辑

- 字段表格负责高频编辑。
- 右侧检查器负责 ref、i18n、server_only、comment、Excel 输入方式。
- 顶部单独显示主键与“查询和索引”入口。

### P3. record / enum 类型编辑

- record 与表共用字段表格，但不显示表专属索引。
- enum 显示值、wire type、引用点。
- 顶部有“被引用于 N 处”，可跳转。

### P4. 类型选择器

- 搜索优先；基础类型、enum、record 分组。
- 单值/列表作为正交切换。
- 当前项高亮，键盘可操作。
- 不在选择器内编辑类型定义，只提供“新建类型”跳转。

### P5. 查询与索引

- Code lookup 与 Group lookup 两张配置卡。
- 直接显示将生成的 C#/Lua API 和数据预检结果。
- 字段选择器自动过滤不合法类型。

### P6. 变更审阅

- 按安全新增、数据依赖、数据破坏、客户端不兼容、依赖破坏分组。
- 每一项同时展示 Schema、Excel、Binary、Accessor 影响。
- 支持点击问题返回到具体字段。

### P7. Excel 迁移详情

- 左右展示旧/新列布局，使用字段路径连接映射。
- 展示受影响行数、失败行号、样例值。
- rename、vector 展开、删除字段分别有专用说明。

## 9. 推荐的交互状态模型

```text
WorkspaceSnapshot（已落盘）
        │
        ├── edit commands ──► WorkspaceDraft
        │                       │
        │                       ├── undo / redo
        │                       ├── local validation
        │                       └── discard
        │
        └──────── prepare ───► CandidateWorkspace
                                │
                                ├── global validation
                                ├── data preflight
                                └── ChangePlan + candidateHash
                                         │
                                         └── atomic apply + postcheck
```

关键约束：

- UI 路由/选中资源不是领域状态；切换页面不会丢草稿。
- modal 只用于短生命周期选择/确认，不承载嵌套编辑导航。
- 所有编辑以 command 记录，尤其 rename，保证 Excel 可以获得明确映射。
- Change Plan 基于 snapshot hash；源文件变化后旧 plan 失效，需要重新生成。
- Apply 是 Workspace 级事务，不是逐 YAML 文件写入。

## 10. 对旧 `bk` 原型的取舍

可作为局部参考：

- 类型搜索与分组；
- 字段状态徽标；
- 引用删除保护；
- 草稿快照和返回路径的需求意识；
- 紧凑字段列表的视觉密度。

不建议继承为新骨架：

- 多层 modal 和 modal 内导航栈；
- `struct` 名称与实际 table 语义不一致；
- 类型引用/向量使用多组互斥字段表达；
- CodeName / group_key 作为字段布尔开关；
- `fixed_length` 同时暗示 Excel 列数和运行时长度；
- 保存当前资源后立即写 YAML 的局部提交模型；
- 只显示泛化风险，不展示 Excel 行号、列映射与生成 API 影响。

## 11. 进入 OpenSpec 前应锁定的设计决策

1. 领域模型使用递归 Type Expression；YAML 是结构化对象还是受控字符串仅影响序列化，不影响 AST。
2. 复合类型正式命名为 `record`，生成 FlatBuffers table；native struct 不在本 change 内。
3. `vector<record>` 是第一版端到端能力；`excel_columns` 只控制 Excel 展开上限。
4. CodeName / group lookup 采用表级 `indexes` 模型；首版 UI 可限制各一个。
5. 编辑器使用三栏工作台和同页资源导航，不使用嵌套编辑 modal。
6. 所有编辑先进入 Workspace Draft；应用前必须生成 Candidate Workspace 与 Change Plan。
7. 字段 rename 是显式 command；Excel 迁移按字段路径和 rename map，不按列位置。
8. 删除被引用资源默认阻止；第一版无 cascade delete。
9. Apply 必须覆盖 YAML、Excel、FBS、Binary、Accessor 全链路，并以原子替换/postcheck 结束。
10. 原型至少覆盖 P1-P7 七个关键状态，再据此编写全新 OpenSpec proposal。

## 官方来源索引

- [FlatBuffers Schema](https://flatbuffers.dev/schema/)
- [FlatBuffers Evolution](https://flatbuffers.dev/evolution/)
- [JSON Schema：Modular JSON Schema combination](https://json-schema.org/understanding-json-schema/structuring)
- [JSON Schema：Array](https://json-schema.org/understanding-json-schema/reference/array)
- [GraphQL：Schemas and Types](https://graphql.org/learn/schema/)
- [GraphQL：Schema Change Management](https://graphql.org/learn/governance-versioning/)
- [GraphiQL 官方仓库](https://github.com/graphql/graphiql/blob/main/packages/graphiql/README.md)
- [Prisma：Relational data modeling](https://www.prisma.io/docs/orm/data-modeling/relational-databases)
- [Prisma：Indexes](https://www.prisma.io/docs/orm/v7/prisma-schema/data-model/indexes)
- [Prisma：How migrations work](https://www.prisma.io/docs/orm/migrations/how-migrations-work)
- [Prisma：Editing a migration](https://www.prisma.io/docs/orm/migrations/editing-a-migration)
- [Hasura：Metadata API Relationships](https://hasura.io/docs/2.0/api-reference/metadata-api/relationship/)
- [Hasura：Resolving Metadata Inconsistencies](https://hasura.io/docs/2.0/migrations-metadata-seeds/resolving-metadata-inconsistencies/)
- [Atlas：Migration Analyzers](https://atlasgo.io/lint/analyzers)
- [Atlas：Verifying Migration Safety](https://atlasgo.io/versioned/lint)
- [Directus：Fields](https://directus.com/docs/guides/data-model/fields)
- [Strapi：Content-type Builder](https://docs.strapi.io/cms/features/content-type-builder)
- [Sanity：Array type](https://www.sanity.io/docs/studio/array-type)
- [DataGrip：Database diagrams](https://www.jetbrains.com/help/datagrip/creating-diagrams.html)

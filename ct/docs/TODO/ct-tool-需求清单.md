# ct-tool 需求清单（TODO）

> 状态：待办（未实施）
> 日期：2026-08-28
> 来源：fabulous-game 项目 `Docs/TODO/` 下的分析与设计（`配表Schema演进.md`、`Config性能优化-最终修改方案.md`、`Config重构性能实测报告-综合.md`）
> 目的：本清单是 ct-tool 侧的**独立需求清单**，供 ct-tool 工作区单独开会话实施。**本文档自包含**——每项含背景、现状、设计、落点、验收标准，实施时不需要参考 fabulous-game 的对话。

---

## 需求总览

| # | 需求 | 模块 | 优先级 | 状态 |
|---|---|---|---|---|
| R1 | web 端结构化 schema 编辑器（字段/配表增删改查，不暴露 YAML） | web 前端 + 后端 | 高 | 待办 |
| R2 | 类型名对齐 flatbuffers（`array` → `vector` 完全改名） | schema 全局 | 高 | 待办 |
| R3 | 定长数组展开（`fixed_length`，Excel 表头展开多列） | schema + excel + template | 中 | 待办 |
| R4 | `array<struct>` 支持（真数组可遍历，flatbuffers 原生 vector<struct>） | schema + binary + 生成器 | 中 | 待办 |
| R5 | struct 修正为真 struct（从 table 改内联定长） | binary_writer | 中 | 待办（R4 前置） |
| R6 | 补标量类型（int8/int16/uint8/uint16/uint32/uint64） | schema + binary + 生成器 | 低 | 待办 |
| R7 | 字符串池去重（`CreateString` → `CreateSharedString`） | binary_writer | ✅ 已完成 | 已实施 |
| R8 | 类型系统结构化（全局具名类型库，enum/struct 抽离为可复用类型） | schema + repository + fbs + web | 高 | 待办 |
| R9 | 字段编辑器需求全集（字段类型 + 特殊属性 code_name/group_key + Excel 列规则 + 表头注解优化） | schema + excel + web | 高 | 待办 |

> R1/R2/R8/R9 属于「配表 Schema 演进」方向（替代原 .fbs 化方案）；R3-R6 属于「类型系统增强」（对齐 flatbuffers 原生）；R7 已完成。
> **R2（改名）会影响 R1/R3/R4/R6/R9 的所有代码**——建议 R2 先做（成本窗口：现有 schema 仅 1 处 array，表少时便宜），或至少先定改名方案再动其他。
> **R8 是 R1 的前置**：enum/struct 全量迁入类型库、字段 type_ref 引用后，web 编辑器才需要「引用类型下拉 + 类型库面板」（见文末 R8 节）。
> **R9 是 R1 的前置需求定义**：字段类型 + 特殊属性（code_name/group_key）+ Excel 列规则（bool ✓/✗ + 唯一性）+ 表头注解优化，见文末 R9 节。

---

## R1：web 端结构化 schema 编辑器（高）

### 背景
ct-tool 已有 web 端（`ct/src/ct/web/`，Flask 后端 + Vue 前端）。schema 编辑当前是「YAML 明文文本框」形态，策划要手写 YAML 语法、无类型补全/校验、易出错。目标：**结构化界面做字段/配表增删改查，不暴露 YAML 明文**。

### 现状（已核实）
- **后端已基本具备**（`ct/src/ct/web/app.py`）：
  - `GET /api/schemas`（列表）、`GET /api/schemas/<table>`（详情）
  - `POST /api/schemas`（创建）、`PUT /api/schemas/<table>`（更新）、`DELETE /api/schemas/<table>`（删除）
  - `_build_schema(data)`（`app.py:117`）：**入参是 `fields_yaml`（YAML 字符串）**，用 `yaml.safe_load` 解析成 list of dict → `TableSchema(fields=fields)` 构建 → 写 YAML 文件
    - ⚠️ **注意**：`_build_schema` 接收的是 YAML 文本不是 JSON dict。但 YAML 解析后就是「list of 字段 dict」，所以前端传结构化字段时，只需把字段数组序列化成 YAML 文本（或直接传 yaml 结构）——**后端模型不需要改**，只是入参形态是 YAML 字符串
    - 校验：`TableSchema` 的 pydantic 校验（类型/命名/约束）在构建时生效，错误经 `_schema_error_text` 返回
  - `_field_dict(f)`（`app.py:96`）：FieldDef → dict（**当前缺 `fixed_length`（R3）、`element_struct`（R4）字段，实施 R3/R4 后要补**）
- **前端已部分实现**（`ct/src/ct/web/static/app.js` 906 行 + `index.html`）：
  - schema 列表、详情、创建、编辑、删除 UI 已有
  - **缺口**：编辑形态是 YAML 文本——`serializeFields(d.fields)`（`app.js:3`）把字段序列化成 YAML 塞进 `<textarea v-model="form.fieldsYaml">`（`index.html:851/878`）；`saveSchema`（`app.js:358`）提交 `fields_yaml` 字符串

### 设计目标（已与需求确认）
- ✅ **配表（schema 表）增删改查**：整个 YAML（表结构）的增删改查
- ✅ **字段增删改查**：结构化 UI 增删字段、改字段类型/属性
- ❌ **不做数据行编辑**：Excel 行数据仍走 Excel，不做 web 数据行编辑
- ✅ **存储仍用 YAML 文件**：编辑 UI 背后不变，只是 UI 不暴露 YAML 明文

### 字段类型模型（编辑器要精确对应 `ct/src/ct/schema/models.py` 的 FieldDef）
```
基本类型（6）: int32  int64  float  double  bool  string
复合类型（3）: enum  struct  vector（R2 后；现名 array）

FieldDef 属性:
  name: str
  type: Literal[...]  # 8 种
  # enum
  values: list[str] | None
  # struct
  fields: list[FieldDef] | None    # 递归
  # array/vector
  element: str | None              # 元素类型
  element_values: list[str] | None # vector<enum> 时
  separator: str = ","             # 分隔符（变长 vector 用）
  fixed_length: int | None         # R3 定长（规划中）
  # flags
  i18n: bool = False               # 仅 string
  ref: str | None                  # 如 "ItemType.Id"
  server_only: bool = False
  comment: str = ""
```

**类型约束（编辑器必须内建，来自 `models.py:31-83` 的 `_validate_field`）**：
- enum：必须有非空 `values`；值必须是合法标识符（`isidentifier`）
- struct：必须有非空 `fields`；**struct 内不允许嵌套 vector/array**（`models.py:56`）
- vector/array：必须有 `element`；`element` 不能是 struct（当前禁，R4 放开）；`vector<enum>` 必须提供 `element_values`；element 必须是基本类型或 enum
- i18n：仅 string 可标记；**i18n 与 server_only 禁止同时**（`models.py:38`）
- 主键：仅 int32/int64（`models.py:120-124`）；表主键必须在字段列表里

### 改造点

**前端（`static/app.js` + `index.html`）——把 YAML 文本框升级为结构化字段编辑器**：
1. **字段编辑器组件**（递归）：
   - 字段行：字段名输入 + 类型下拉（8 种）
   - 字段增/删/上移/下移
   - 类型下拉选 enum → 内联「标签输入区」编辑 values（chip + 添加框，校验标识符）
   - 类型下拉选 struct → 可折叠展开 → 递归字段列表（缩进）+ 添加子字段
   - 类型下拉选 vector/array → element 下拉 + （enum→element_values 标签区）+ separator
2. **字段属性行**：
   - i18n 开关（仅 string 可勾选，非 string 禁用）
   - server_only 开关（与 i18n 互斥，冲突时提示+撤销）
   - ref 下拉（列出所有表的主键，如 "ItemType.Id"、"Item.Id"）——避免拼错引用
   - comment 输入
3. **表单对接**：`openEdit`/`saveSchema` 改造为传结构化字段数组（替代 `serializeFields`/`fields_yaml`）
4. **校验**：前端保存前做基础校验（必填、类型合法、enum 标识符），错误即时显示；后端 `_build_schema` 校验兜底（双保险）

**后端（`app.py`）——模型基本不用改，但 `_field_dict` 要补 future 字段**：
- `_build_schema` 已能处理（接收 fields_yaml YAML 文本 → 解析 → TableSchema 校验）
- **`_field_dict`（详情接口返回用）需补充 `fixed_length`（R3）、`element_struct`（R4）字段**——否则 web 编辑器读回详情时丢失这些属性
- 校验错误返回，前端展示（pydantic 错误经 `_schema_error_text`）

**可选增强**：
- 保存后自动触发 `POST /api/export`（保持「改表即同步」体验）
- 编辑器友好中文标签（策划看「数组」「定长数组」，不接触技术类型名）

### 落点文件
- `ct/src/ct/web/static/app.js`（字段编辑器组件、表单改造）
- `ct/src/ct/web/static/index.html`（编辑面板 UI）
- `ct/src/ct/web/app.py`（若需新增校验错误返回结构）

### 验收标准
- [ ] 策划通过 web 界面完成：新建表、加字段（含 enum/struct/vector）、改字段属性、删字段、删表——全程不接触 YAML 文本
- [ ] enum/struct/vector 的嵌套编辑可用（struct 递归、enum 标签、vector element）
- [ ] 校验错误即时显示（如 enum 空、i18n 非 string、主键非 int32）—— ✅ 设计稿已覆盖（2026-08-29：字段名空/重名行内错误 + 保存汇总错误条 + 主键删除保护 + i18n 互斥/类型联动，见 R9.5）
- [ ] 保存后 YAML 文件正确生成，重新导出成功，C#/Lua accessor 正确生成
- [ ] 后端 `_build_schema` 校验兜底生效（前端绕过时后端仍报错）

---

## R2：类型名对齐 flatbuffers（`array` → `vector` 完全改名）（高）

### 背景
当前 YAML 用 `array` 表示「变长数组」，但 flatbuffers 里 `array` 是「定长数组 `[T:N]`」，`vector` 才是变长数组。**名字冲突导致概念混乱**（如「我们的 array = flatbuffers vector」）。决策：完全改名对齐 flatbuffers。

### 改名映射
| 旧（YAML） | 新（YAML） | 说明 |
|---|---|---|
| `array` | **`vector`** | 变长数组 = flatbuffers vector |
| （未来定长） | `array` | flatbuffers 原生定长 `[T:N]`（预留名，R3 用） |
| 其余 | 不变 | int32/int64/float/double/bool/string/enum/struct 本就对应 |

### 影响面（已评估）
- **现有 schema**：仅 `Config/gd/config/schemas/Item.yaml:32` 的 `Tags: type: array` → `type: vector`（1 处）
- **代码**：18 处字符串 `"array"`、10 个文件（机械替换 + 校验微调）：
  - `ct/src/ct/schema/models.py`：`ALL_FIELD_TYPES`（:10）、`Literal`（:16-17）、struct 内禁 array 校验（:56）、array 分支（:60）
  - `ct/src/ct/schema/type_traits.py`：`OFFSET_TYPES`（:24）、类型判断（:282/:326）、`FieldTraits` 表（:429）
  - `ct/src/ct/schema/repository.py`：array<enum> 分支（:102）
  - `ct/src/ct/export/binary_writer.py`：`_OFFSET_BUILDERS`（:189）
  - `ct/src/ct/export/csharp_accessor_generator.py`：array 分支（:55/:80/:124）
  - `ct/src/ct/export/lua_accessor_generator.py`：array 分支（:127）
  - `ct/src/ct/excel/reader.py`：array 判断（:113/:114）
  - `ct/src/ct/validate/refs.py`：array 判断（:35）
  - `ct/src/ct/web/app.py`：类型判断（:109）
  - `ct/src/ct/web/static/app.js`：类型判断（:15/:443）

### 改名顺序（建议）
1. `models.py` 类型集合 + 校验（`array` → `vector`）
2. `type_traits.py` / `binary_writer.py` / 两个生成器 / reader / refs / web 的类型分支
3. 前端 `app.js` 类型判断 + 友好标签
4. 迁移 `Item.yaml`（`array` → `vector`）
5. 重新导表 + 测试全绿（golden 更新）
6. 文档同步（fabulous-game 方案文档「定长数组展开」里的 array 描述同步）

### 注意
- `ARRAY_ELEMENT_TYPES`（`models.py:11`）→ 改名 `VECTOR_ELEMENT_TYPES`
- `FIELD_TRAITS`/`FieldTraits` 表的 key "array" → "vector"
- golden 测试（`ct/tests/export/test_accessor_golden.py`、`test_binary_golden.py`）需更新（生成代码里的类型名变了）
- 与 R3（定长 array）衔接：改名后 `vector` = 变长、`array` = 定长（flatbuffers 原生），语义清晰

### 验收标准
- [ ] `Item.yaml` 用 `type: vector` 正常导出，二进制与改名前等价（仅名字变，字节兼容）
- [ ] 全部测试通过（golden 已更新）
- [ ] 无残留 `"array"` 类型字符串（除定长 array 语义外的误用）

---

## R3：定长数组展开（`fixed_length`，Excel 表头展开多列）（中）

### 背景
当前数组（vector）在 Excel 里是「单单元格逗号分隔」（如 `Tags` 填 `"101,102"`），策划要记逗号语法。目标：**定长数组在 Excel 表头展开成固定 N 列**（`Tags_1..Tags_N`），每格一个元素，空的留空。

### 设计
```
现状:
  | Tags            |
  | "101,102"       |  ← 单单元格逗号分隔

目标（fixed_length: 5）:
  | Tags_1 | Tags_2 | Tags_3 | Tags_4 | Tags_5 |
  | 101    | 102    |        |        |        |  ← 每格一个，空留空
```

**语义（方案 X）**：按实际填的数量存（空单元格跳过），`fixed_length` 只是「Excel 展开的最大列数」，**不是运行时强制长度**。

| Excel 填法 | 二进制数组 | 运行时 |
|---|---|---|
| 填 2 个，其余空 | `[101, 102]` | Count=2 |
| 填 1 个 | `[201]` | Count=1 |
| 全空 | `[]` | Count=0 |

**关键洞察**：表头由导出器按 `fixed_length` 生成，只有 N 列 → 策划物理上没地方填第 N+1 个 → **运行时天然不超限，无需超限校验**（结构保证，非防御）。

### 改造点
1. **schema**（`models.py`）：`FieldDef` 加 `fixed_length: int | None = None`（仅 vector 类型可用）
2. **表头生成**（`ct/src/ct/excel/template.py`）：
   - `FieldDef.column_span()`（`models.py:91-98`）——vector 带 `fixed_length` 时返回 N（否则 1）
   - `_write_field_headers`（`template.py:141`）生成 `Tags_1`...`Tags_N` 表头
3. **读取**（`ct/src/ct/excel/reader.py`）：
   - 识别 `fixed_length`，从 `Tags_1..Tags_N` 多列读取，空单元格跳过，组装成数组（顺序：按列序）
4. **二进制/运行时/生成器：零改动**：
   - `_vector_int32` 照旧构建普通 vector（values 来自多列读取，产出和现在一样的数组）
   - C# `TagsCount`/`TagsAt(i)`、Lua `#row.Tags`/`pairs` 照常

### 落点文件
- `ct/src/ct/schema/models.py`（FieldDef.fixed_length + column_span）
- `ct/src/ct/excel/template.py`（表头展开）
- `ct/src/ct/excel/reader.py`（多列读取）

### 验收标准
- [ ] `fixed_length: N` 的 vector 字段，Excel 表头生成 N 列（`Tags_1..Tags_N`）
- [ ] 填部分列 → 导出数组按实际数量；全空 → 空数组
- [ ] 无 `fixed_length` 的 vector 保持逗号分隔（向后兼容）
- [ ] 二进制/运行时与「逗号分隔填法」产出一致

---

## R4：`array<struct>` 支持（真数组可遍历）（中）

### 背景
当前 `array<struct>` 被禁（`models.py:63-66`：「请使用独立子表 + ref 实现一对多」）。用户需要**真数组 + 遍历**（如 `Rewards` 是一组 struct，运行时 `for i` 遍历）。**关键原则：用 flatbuffers 原生结构，不自造数据组织。**

### 已实测验证（flatbuffers 原生 vector<struct> 可行）
- 构建：flatbuffers Python 底层 API 构建「真 struct + 内联 vector<struct>」（44 字节）
- 读取：自写读端（模拟 WireReader/gd_native）`vector[i]` **直接算偏移**拿内联 struct，可遍历：
  ```
  Reward[0]: Min=1 Max=5 (addr=...541c)
  Reward[1]: Min=2 Max=3 (addr=...5424)   ← 连续，8 字节/个
  ```
- **结论**：真 struct（内联定长）+ vector<struct>（内联元素）是 flatbuffers 原生能力，自写读端不依赖 flatbuffers 库

### 设计
```
schema（R2 改名后）:
  Rewards: vector<struct RewardDrop{Min:int32, Max:int32}>

flatbuffers 原生表达:
  struct RewardDrop { Min: int32; Max: int32; }   # 真 struct（内联定长）
  table Item { ...; Rewards: [RewardDrop]; }        # vector<struct>（元素内联）

运行时:
  C#:  for i in RewardsCount: row.RewardsAt(i).Min/.Max    # RewardView 复用现有 struct 视图
  Lua: for i = 1, #row.Rewards do row.Rewards[i].Min       # struct userdata（复用）
```

### 改造点
1. **schema**（`models.py`）：
   - `ARRAY_ELEMENT_TYPES` 加 "struct"（R2 改名后 `VECTOR_ELEMENT_TYPES`）
   - 移除 `_validate_field` 里 `element == "struct"` 的禁止（:63-66）
   - `FieldDef` 加 `element_struct: list[FieldDef] | None = None`（vector<struct> 存子字段定义）
   - **约束：vector<struct> 必须配 `fixed_length`（R3）**——变长 vector<struct> 在 Excel 无法表达（单单元格不能逗号分隔复杂结构）；定长展开 N 个 struct 块才可行
2. **二进制**（`ct/src/ct/export/binary_writer.py`）：
   - 新增 `_vector_structs(builder, field, values)`：每个 value 是 dict，用 `_build_struct` 构建 struct table，`StartVector(4, n, 4)` + `PrependUOffsetTRelative`（**注意：见 R5，若 struct 改真 struct 则 vector 元素内联，不是 offset**）
   - `_ELEMENT_VECTOR_WRITERS` 加 "struct" 条目
3. **生成器**：
   - C#（`csharp_accessor_generator.py`）：element=struct → 产出 `XxxCount`/`XxxAt(i)` 返回 struct 视图
   - Lua（`lua_accessor_generator.py`）：element=struct → `GD.Arr` 元素返回 struct userdata（挂 struct meta）
4. **Excel**（R3 的 fixed_length）：定长展开 N 个 struct 块（每个 struct 占其 column_span 列）
5. **编辑器**（R1）：vector<struct> + fixed_length → 渲染 N 个 struct 子编辑器（复用 struct FieldEditor）

### 依赖
- **R5（struct 改真 struct）**：若 struct 仍是 table，vector<struct> 是 `[table]` vector（存 offset）；若改真 struct，是内联 vector（更快、更原生）。**建议先做 R5 再定 vector<struct> 布局**。

### 验收标准
- [ ] vector<struct> + fixed_length 字段：Excel 展开 N 个 struct 块（如 Min_1/Max_1/Min_2/Max_2...）
- [ ] 二进制是 flatbuffers 原生 vector<struct>（内联或 offset，按 R5 定）
- [ ] 运行时 C# `RewardsAt(i)` 返回 struct 视图可遍历；Lua `row.Rewards[i]` 返回 struct userdata
- [ ] 变长 vector<struct>（无 fixed_length）仍被禁止（校验报错）

---

## R5：struct 修正为真 struct（从 table 改内联定长）（中，R4 前置）

### 背景
当前 `_build_struct`（`binary_writer.py:153-171`）用 `StartObject`/`EndObject`（flatbuffers **table** 构建，带 vtable + offset）。所以 DropRange 在 flatbuffers 语义里是 **table**，不是真 struct（内联定长）。这偏离了 flatbuffers 原生，且阻碍 vector<struct> 用原生内联布局。

### 目标
把 struct 从「table 构建」改为「**真 struct（内联定长，无 vtable）**」：
- flatbuffers 官方：struct 内联定长、无 vtable、更快更省（官方文档原话）
- 我们现有 struct（DropRange 纯标量）恰好满足「struct 只能含标量/struct」约束
- 解锁：vector<struct> 内联布局、struct 内定长 array

### 约束（flatbuffers 原生 struct 语义）
- struct 只能含**标量或 struct**（不能含 string/vector/table）
- struct 字段无默认值、不可缺省（必填）
- 构建：就地内联（flatbuffers Python `assertStructIsInline`，`builder.py:576`）——struct 必须在它要写入的位置直接 Prepend 标量字节，不能用独立 offset

### 改造点
- `binary_writer.py` `_build_struct`：从 `StartObject`/`EndObject` 改为「底层 Prepend 标量 + 就地内联」（按字段逆序 Prepend，对齐到 struct 大小）
- `_prepend_slot` 里 struct 字段：从「uoffset 引用」改为「内联写入」（`PrependStructSlot`，`builder.py:702`）
- 生成器：struct 视图从「table 指针」改为「内联 struct 指针 + 定长布局」
- **校验**：models.py 确保 struct 只含标量/struct（当前已近似——struct 内禁 array，需确认禁 string/vector/table）

### 注意
- struct 改为内联后，**字段必须全部存在**（不能缺省）——Excel 填表时 struct 子字段是否允许留空？需与 R3 语义对齐（struct 字段空 → 默认值？还是必填？）
- 需重导所有含 struct 的表 + 更新 golden

### 验收标准
- [ ] struct 在二进制里是内联定长（无 vtable），大小 = 字段数 × 字段大小
- [ ] 读取正确（DropRange.Min/.Max）
- [ ] struct 只含标量/struct 的校验生效（string/vector/table 进 struct 报错）
- [ ] 与 R4 配合：vector<struct> 用内联布局

---

## R6：补标量类型（int8/int16/uint8/uint16/uint32/uint64）（低）

### 背景
flatbuffers 原生支持这些标量（`int8/uint8/int16/uint16/int32/uint32/int64/uint64/float/double/bool`），我们只用了 int32/int64/float/double/bool/string。补齐对齐 flatbuffers。

### 改造点（每个类型 = 纯增量）
1. `models.py`：`BASIC_TYPES` 加新类型；`Literal` 加
2. `type_traits.py`：`TYPE_MAP`（YAML → flatbuffers 类型）、`FieldTraits` 表、C# 类型映射（`_CSHARP_TYPE_MAP`）
3. `binary_writer.py`：`_slot_int8/uint16...`、`_vector_int8/uint16...`、slot writers 表、vector writers 表
4. `WireReader`（fabulous-game 侧）：I8/I16/U16... 读取 —— **注意：这跨到 fabulous-game 仓库，需两仓库协同**
5. 生成器：C# 返回类型映射、Lua element tag
6. Excel：类型标注

### 落点
- ct-tool：`models.py` / `type_traits.py` / `binary_writer.py` / `csharp_accessor_generator.py` / `lua_accessor_generator.py` / `template.py`
- fabulous-game：`Client/Assets/Scripts/Config/Native/WireReader.cs`（新增读取方法）

### 验收标准
- [ ] 新标量类型在 schema 可用、导出二进制正确、运行时读取正确
- [ ] C#/Lua 两侧类型映射正确
- [ ] 现有类型不受影响（回归）

---

## R7：字符串池去重（✅ 已完成，2026-08-27）

### 状态
**已实施**：`binary_writer.py` 4 处 `builder.CreateString(...)` → `builder.CreateSharedString(...)`（:71/:138/:286/:323）。

### 说明
- `CreateSharedString`（flatbuffers Python 内置）：dict 查重，相同内容复用 offset——**表内去重**（每表一个 builder 实例，dict 实例级，实测确认跨表不去重）
- 收益：包体变小（高重复场景实测省 59%）；**不解决热路径性能**（Lua intern 已按内容去重、C# 分配靠缓存）
- 当前数据重复率低，导表后 bin 大小不变（符合预期）
- **测试**：ct-tool 4 个测试全过（格式兼容）

### 不做的事（已决策）
- **跨表去重不做**：flatbuffers 每表独立 buffer + 相对偏移，跨表引用无效（技术障碍根本性）。详见 fabulous-game `Docs/TODO/Config性能优化-最终修改方案.md` 的「决策记录：跨表字符串去重」。

---

## 需求间依赖关系

```
R2（改名 array→vector）  ← 建议最先做（影响所有代码，表少时便宜）
  ├─ 影响 R1（编辑器类型名）R3（fixed_length 用在 vector）R4（vector<struct>）R6（类型集合）
R5（struct 改真 struct） ← R4 的前置（决定 vector<struct> 是内联还是 offset）
  └─ R4（vector<struct>）依赖 R5 + R3（fixed_length）
R3（定长数组展开）← 被 R4 依赖（vector<struct> 必须定长）
R6（补标量）独立
R7 已完成
```

**建议实施批次**：
- 批 1：R2（改名）+ R7（已完成，验证）
- 批 2：R5（struct 真 struct）→ R3（定长展开）→ R4（vector<struct>）
- 批 3：R6（补标量，跨仓库）
- 批 4：R1（web 编辑器，依赖改名后的类型名）

## 关联文档（fabulous-game 侧，供参考）

- `fabulous-game/Docs/TODO/配表Schema演进.md` —— schema 演进方向、web 编辑器设计、字段类型体系、改名方案
- `fabulous-game/Docs/TODO/Config性能优化-最终修改方案.md` —— 8 个性能改动（含 ct-tool 部分：i18n 同序、字符串缓存生成器、哈希索引导出）、设计记录（定长数组展开）、决策记录（跨表去重不做）
- `fabulous-game/Docs/TODO/Config重构性能实测报告-综合.md` —— 性能决策证据库
- `fabulous-game/Docs/TODO/references/config-table-load-patch-flow.md` —— harmony 参考原文

---

# 行动方案（逐项评审 + 批次实施计划）

> 状态：评审完成，待实施
> 日期：2026-08-28
> 方式：对 R1-R7 逐项评审；关键性能/布局论断用 **flatbuffers 25.12.19（ct/.venv）实测** + **官方文档**双向核实；批次计划在原清单基础上细化。
> 本文档自包含，实施时以本节为准，不必回查 fabulous-game 对话。

---

## 0. 实测环境与结论速览

**环境**：`ct/.venv/bin/python`，flatbuffers 25.12.19（Python，无 flatc，符合 AGENTS.md 描述的现状）。

**核心性能结论（本轮实测确认）**：

| 论断 | 自测证据 | 官方文档佐证 |
|---|---|---|
| 真 struct 内联定长、无 vtable | 单 struct 字段（Min/Max）：**内联 24 B vs table 40 B，省 16 B/字段** | flatbuffers.dev/schema：「Structs use less memory than tables and are even faster to access (always stored in-line in parent, no virtual table)」 |
| vector\<struct\> 元素内联、可遍历 | 2 个 8 字节 struct：**24 B**（4 头 + 16 数据 + 4 root），元素按 `(1,5),(2,3)` 顺序读回 ✓ | flatbuffers.dev/internals：「Structs are always stored inline in their parent (a struct, table, **or vector**)」 |
| 新标量类型全部可用 | int8/uint8/int16/uint16/uint32/uint64 向量构建+读回全对（尺寸 1/1/2/2/4/8 B/元素） | flatbuffers.dev/schema 标量表（byte/ubyte/short/ushort/int/uint/long/ulong + 别名） |
| vector / string 不能内联进 struct | （见 R5 评审） | flatbuffers.dev/internals：「Neither [strings/vectors] is stored inline in their parent, but are referred to by offset」 |

> **R2 字节兼容断言**（改名不改变二进制）：本方案不依赖它，但实施 R2 后建议跑 `pytest` golden + 对拍一次改名前后的 `data_zh.bin`，见 R2 评审。

---

## 1. 逐项评审

### R2：类型名对齐 flatbuffers（array → vector）—— **✅ 可立即实施，实测确认影响面**

**代码核实**（2026-08-28 全文核对）：
- `"array"` 字符串：9 个 `.py` 共 18 处 + `web/static/app.js` 2 处（`:15` `:443`）= **10 个文件**，与清单一致 ✓
- 关键位置：`schema/models.py:10/11/16-17/56/60-76`（`ALL_FIELD_TYPES`/`ARRAY_ELEMENT_TYPES`/struct 内禁 array/array 分支）；`schema/type_traits.py`、`binary_writer.py`、两生成器、`excel/reader.py`、`validate/refs.py`、`web/app.py:109`。
- schema 现状：`gd/config/schemas/Item.yaml:32` 仅 1 处 `type: array`（其余表未用）✓

**影响面补充**（清单之外，实施时要覆盖）：
- 除 `Item.yaml` 外，建议 `grep -r "type: array" gd/config/schemas/` 全库兜底（现仅 Item 一处，但别只盯单文件）。
- `ct/tests/` 的 golden 文件与测试夹具可能硬编码 `array`（`test_accessor_golden.py`、`test_binary_golden.py`，以及 schema fixture）。实施时 `grep -rn "array" ct/tests/` 一并确认。
- 改名是**纯文本语义替换**，不触碰序列化逻辑 → **字节兼容**（R2 验收点 1 成立，且导出行为不变）。

**实施步骤**：
1. `models.py`：`ALL_FIELD_TYPES` / `ARRAY_ELEMENT_TYPES`(→`VECTOR_ELEMENT_TYPES`) / `Literal` / 校验消息全换 `vector`
2. 其余 8 个 `.py` 的类型分支机械替换（`array`→`vector`，保留 `element`/`element_values`/`separator` 属性名不变——它们是 FieldDef 属性，不涉及类型字符串）
3. `app.js:15/443` 类型判断换 `vector` + 中文标签（顺带为 R1 铺路）
4. `Item.yaml`：`type: array` → `type: vector`
5. 重新导表 + `pytest` 全绿 + golden 更新
6. 文档同步（fabulous-game 侧方案文档里 `array` 描述）

**风险**：低。机械替换、无行为变化；唯一注意点是**别把「array 语义」字样（如报错文案、注释）误换成 vector 之外的含义**——建议 grep 时区分 `"array"`（类型字符串）与 `array`（语义描述）。

**验收**：`Item.yaml` 用 `vector` 正常导出；`pytest` 全过；`grep '"array"' ct/src -r` 除文档外无残留。

---

### R5：struct 修正为真 struct（table → 内联定长）—— **✅ 实测可行，收益明确，前置决策待定**

**实测确认**（本轮）：
- 构建 API 齐全：`PrependStructSlot` / `assertStructIsInline` / `PrependInt32/8/16...` 均在（25.12.19）。
- 尺寸对比：父 table 含 1 个 `{Min:int32, Max:int32}` 字段 → **内联 24 B vs table 40 B，省 16 B/字段**；内联数据在父 table 数据区内直接可读（`Min=1, Max=5`），无二级 uoffset 指针。
- flatbuffers 官方原话（schema 页）：struct「always stored in-line in their parent, and use no virtual table」。

**实施关键（比清单更细）**：
1. `binary_writer.py:_build_struct`（:153）：从 `StartObject/EndObject` 改为「就地内联」——**字段逆序 Prepend 标量**，写入前 `Prep(align)` 对齐到 struct 大小；struct 内子字段若为 struct 递归处理。
2. `_prepend_slot` 的 struct 分支：从 `uoffset` 引用改 `PrependStructSlot`（须满足 `assertStructIsInline`：struct 构建时机必须紧贴写入位置）。
3. **struct 内字段类型约束收紧**：flatbuffers 原生 struct **只能含标量或 struct**（官方明确），因此当前 `models.py` 的 struct 校验要从「禁 array」升级为「禁 string/vector/table/所有非标量」（R5 验收点 3 的完整版）。当前 struct 全是纯标量（如 DropRange），满足约束，但校验要先加。
4. 生成器：C# 视图从「table 指针」改「内联 struct 指针 + 定长布局」（读端直接按固定 offset 读字段，不走 vtable）；Lua 同理。
5. 重导含 struct 的表 + golden 更新。

**⚠️ 前置决策（实施前必须定，清单已留白）**：struct 内联后**字段必须全部存在**。Excel 中 struct 子字段留空的行为要明确：
- 方案 A（推荐，对齐 flatbuffers 原生）：标量留空 → 填 `0`/`false`，不报错（flatbuffers 内联 struct 无缺省概念，就是 0）。
- 方案 B：留空报校验错误（更严格，但策划体验差、且与「空数组=0 个」的宽容哲学不一致）。
- 建议按 A 实施，并在方案文档里写明「struct 子字段留空 = 0」；这同时与 R3 的「空留空」语义自然衔接。

**风险**：中。行为变化点=struct 字段不再可缺省；需全量回归所有含 struct 的表 + 读端（fabulous-game WireReader/gd_native）同步改读法。

**验收**：struct 二进制为内联定长（无 vtable）、大小=字段数×字段大小；`DropRange.Min/.Max` 读回正确；struct 含非标量字段时 schema 校验报错；R4 的 vector<struct> 用内联布局。

---

### R3：定长数组展开（fixed_length）—— **✅ 设计成立，独立可做，可提前**

**评审**：设计（方案 X：按实际填的数量存，fixed_length 只是 Excel 展开列数上限）**自洽且正确**。关键洞察「表头只有 N 列 → 物理上无法填第 N+1 个」成立，无需运行时超限校验（结构保证）。

**实测补充**：R3 的目标产物「按实际数量存的 vector」正是 flatbuffers 原生 vector（长度前缀 + 连续元素），与「逗号分隔填法」产出的二进制**完全等价**（都是 `vector<int32>`），因此「二进制/运行时零改动」（清单 R3 改造点 4）成立——差异只在 Excel 读取阶段。

**实施要点**：
1. `FieldDef.fixed_length: int | None = None`（仅 vector 可用，pydantic 校验加：非 vector 配 fixed_length → 报错）。
2. `column_span()`（models.py:91）：vector 带 fixed_length 返回 N，否则 1。
3. `template.py:_write_field_headers`：vector 带 fixed_length → 生成 `Tags_1..Tags_N` N 列表头。
4. `reader.py`：识别 fixed_length，从 N 列读取、空格跳过、按列序组装。
5. 无 fixed_length 的 vector 保持逗号分隔（向后兼容）。

**优先级建议**：**不依赖 R5**，可单独先做（策划立刻不用写逗号）。若要「快速见效」，把 R3 从批 2 提到批 1.5。

**验收**：fixed_length:N 生成 N 列表头；填部分列→按实际；全空→空数组；无 fixed_length 保持逗号分隔；二进制与逗号填法等价。

---

### R4：vector\<struct\> 支持 —— **✅ 实测可行，依赖 R5 定布局**

**实测确认**（本轮，直接复现清单「已实测验证」）：
- 内联 vector<struct> 构建成功：2 个 8 字节 struct（`{Min,Max}`）= **24 B**（4 长度 + 16 数据 + 4 root），元素按序读回 `(1,5),(2,3)` ✓。
- 元素确实内联（无 uoffset 指针）：数据区连续 16 字节就是两个 struct。
- flatbuffers 官方：`CreateVectorOfStructs()` 语义 + internals 页确认 struct 内联进 vector。

**布局决策（关键）**：
- 若 R5 做了（真 struct）：vector<struct> = **内联元素**（`StartVector(8, n, 4)` + 逆序内联 struct），元素 `Count`/`At(i)` 直接算偏移。**这是首选路径，性能最优**（无二级指针、cache 友好、官方推荐）。
- 若 R5 不做（struct 保持 table）：vector<struct> 退化为 vector<table>（元素是 uoffset），C#/Lua 读端要走「offset → table → vtable」两级。**建议锁定 R5 后再实现 R4 的生成器**，避免写两套读端。

**实施要点**（基于 R5 完成）：
1. `models.py`：`VECTOR_ELEMENT_TYPES` 加 "struct"；移除 `_validate_field` 里 array<struct> 禁止；`FieldDef.element_struct: list[FieldDef] | None = None`；**约束 vector<struct> 必须配 fixed_length**（Excel 无法表达变长复杂结构）。
2. `binary_writer.py`：`_vector_structs(builder, field, values)`：每个 value 是 dict → 内联构建 struct（复用 R5 的 struct 内联构建）→ 逆序写入 vector。
3. 生成器：C# `RewardsCount/RewardsAt(i)` 返回 struct 视图；Lua `row.Rewards[i]` 返回 struct userdata。
4. Excel：fixed_length 展开 N 个 struct 块（每个 struct 占其 column_span 列）。
5. 编辑器（R1）：vector<struct> + fixed_length 渲染 N 个 struct 子编辑器。

**风险**：中。主要风险在生成器读端与 R5 的联动（布局二选一必须一次定对）。

**验收**：vector<struct>+fixed_length 字段 Excel 展开 N 个 struct 块；二进制为原生内联 vector<struct>；C# `RewardsAt(i)`/Lua `row.Rewards[i]` 可遍历；变长 vector<struct>（无 fixed_length）仍被禁止。

---

### R6：补标量类型 —— **✅ 实测全通过，纯增量，跨仓库**

**实测确认**（本轮）：int8/uint8/int16/uint16/uint32/uint64 **全部构建+读回成功**，向量尺寸正确（1/1/2/2/4/8 B/元素）。flatbuffers 官方标量表确认这些类型 + 别名（`uint8`=`ubyte` 等）。

**实施要点**（纯增量，每类型独立）：
1. `models.py`：`BASIC_TYPES` 加 6 个新类型；`Literal` 加。
2. `type_traits.py`：`TYPE_MAP`（YAML→flatbuffers 类型名）、`FieldTraits` 表、`_CSHARP_TYPE_MAP`。
3. `binary_writer.py`：`_slot_*` / `_vector_*` 各 6 个新 slot/vector writers + 查表注册。
4. 生成器：C# 返回类型映射（`sbyte/byte/short/ushort/uint/ulong`）、Lua element tag。
5. `template.py`：Excel 类型标注（int8→...）。
6. **fabulous-game 侧**（跨仓库协同）：`WireReader.cs` 新增 `ReadI8/ReadU8/ReadI16/ReadU16/ReadU32/ReadU64` 及 vector 读法。

**验收**：新标量在 schema 可用、导出二进制正确、C#/Lua 两侧类型映射正确；现有类型回归。

---

### R1：web 结构化 schema 编辑器 —— **✅ 可行，工作量最大，放最后**

**代码核实**（2026-08-28）：
- 后端 `app.py`：schema CRUD 完整（GET/POST/PUT/DELETE）；`_build_schema`（:117）接收 **YAML 文本**（`fields_yaml`）→ `yaml.safe_load` → `TableSchema` → 写文件；pydantic 校验兜底 ✓。
- 前端 `static/app.js`：`serializeFields`（:3）、`saveSchema`（:358，提交 `fields_yaml`）、`openEdit`（:346）存在。
- **一处行号修正**：清单写 `index.html:851/878` 的 textarea，实际在 **`app.js:851/878`**（Vue 模板字符串内嵌在 app.js）；`static/index.html` 只是壳。改 UI 时改 app.js 内模板即可。

**评审要点**：
- `_build_schema` 接收 YAML 文本、但 YAML 解析后即 list-of-field-dict → 前端传结构化字段时**序列化成 YAML 文本提交即可，后端模型零改动**（清单判断正确）。
- `_field_dict`（:96）详情返回需补 `fixed_length`（R3）/`element_struct`（R4）——**R1 必须等 R3/R4 的类型模型落地后读回才完整**，这是「R1 放最后」的实质理由（不是改名依赖，而是字段模型完备性）。
- 前端组件改造（字段行/递归 struct/enum 标签/vector element/属性行）工程量最大，是 R1 主体。

**实施建议**：R1 的后端「补 `_field_dict` future 字段」可与 R3/R4 同期做；前端结构化编辑器放在所有类型能力（R2-R6）定型后一次到位，避免 UI 做两遍。

**验收**：策划全程不碰 YAML 完成建表/加字段（enum/struct/vector 嵌套）/改属性/删字段/删表；校验即时显示；保存后 YAML 正确、导出成功、accessor 正确；后端校验兜底生效。

---

## 2. 批次计划（在原清单基础上细化）

```
批 1：R2（改名）+ R7（已完成，验证）
       └ R3 可提前（独立，不依赖 R5，策划收益直接）→ 拆成「批 1.5」
批 2：R5（struct 真 struct，含 struct 内非标量禁入校验）
       └ R4（vector<struct>，锁 R5 布局后实现生成器）
批 3：R6（补标量，跨仓库：ct-tool + fabulous-game WireReader 协同）
批 4：R1（web 编辑器；后端 _field_dict 补字段可与 R3/R4 同期）
```

**前置决策清单（实施前锁定）**：
1. R5：struct 子字段 Excel 留空语义（推荐 A：留空=0，不报错）
2. R4：vector<struct> 布局（推荐：R5 后走内联，首选路径）
3. R2/R3 衔接：改名后 `vector`=变长、`array` 名预留（future 定长——注意官方 array 仅支持在 struct 内，R3 的 fixed_length vector 不等同于官方 array，是「Excel 展开 + 普通 vector」的便利语法，文档要写明避免误读）

## 3. 本轮实测留档

- 环境：`ct/.venv/bin/python` + flatbuffers 25.12.19
- 关键读数：vector<struct> 内联 24 B；内联 struct vs table 40 B（省 16 B/字段）；新标量 7 种全部读回正确
- 官方依据：https://flatbuffers.dev/schema/ · https://flatbuffers.dev/internals/
- 实测脚本：本轮会话 `/tmp/fb_selftest*.py`（临时，未入库；如需留档可整理进 `ct/docs/TODO/`）

---

# 类型系统结构化（R8：全局具名类型库）

> 状态：设计已闭环，待实施
> 日期：2026-08-28
> 背景：R1（web 结构化 schema 编辑器）讨论中，用户拍板把 enum/struct 从「内联在字段上」升级为「全局具名可复用类型」。
> 原则：**贴合现有架构，不引入新模式**；复用 `YamlSchemaRepository` 的「glob + 全局去重 + pydantic」链路，类型库是它的兄弟组件而非附加层。

---

## R8.1 核心决策（已确认）

| # | 决策 | 说明 |
|---|---|---|
| 1 | **全量迁移，单一真理来源**（方案 A） | enum/struct 定义全部搬进类型库，字段一律 `type_ref` 引用；**不再保留内联 values/fields**。现有 schema 做一次性迁移。 |
| 2 | **一模块一文件** | `config/types/<module>.yaml`，文件内 `types:` 列表；模块 = 文件名。不采用「一类型一文件」（类型小而密，会文件爆炸）。 |
| 2b | **模块动态新增**（2026-08-29 review 补充） | 编辑器「所属模块」= 已有模块下拉 + 「+ 新增模块」（切输入框，确认后加入下拉并同步页签筛选 pill）。新模块首次保存类型时自动创建 `types/<module>.yaml`。 |
| 3 | **全局唯一类型名** | 重名跨模块文件一律禁止（复用 `seen_names` 去重，重名抛 `ValueError`）。模块只是目录/文件名，不是命名空间。 |
| 4 | **`/api/types` 独立资源** | 与 `/api/schemas` 完全同构的 CRUD。 |
| 5 | **注释支持** | 类型本身 + struct 字段都支持注释；enum 值不做单独注释（保持 `values: list[str]`）。 |
| 6 | **fbs 用真名，不再加后缀** | 类型用真名（`enum Rarity`、`struct DropRange`），撞名不变量从「生成后检查」前移为「schema/类型校验时显式拦截」。 |
| 7 | **enum 底层类型可配**（2026-08-29 review 补充） | flatbuffers 枚举必须声明整数底层类型（默认 byte），现有实现固定 `: byte`。类型库化后加 `underlying` 字段（默认 int32），决定二进制宽度与 C# 生成类型。 |
| 8 | **struct 字段类型约束**（2026-08-29 review 补充） | FlatBuffers struct 只允许标量或嵌套 struct（不能 string/vector/table）。编辑器子字段类型下拉只列标量 + 具名 struct 引用。 |
| 9 | **类型模态导航栈**（2026-08-29 确认；2026-08-31 修订为纯 Vue 响应式） | struct 嵌套导致「类型查看/编辑内再进入子类型」：**不用嵌套模态叠加**（UX 反模式：Back/Esc 混乱、上下文丢失），改为**类型模态内导航栈 + 面包屑**——下钻（pushTypeView）在同一模态内切换内容，顶部面包屑（类型库 / A / 嵌套:B）逐级可点返回，每层保留 view/edit 模式；关闭只关最顶层回到来源页。参考 Hackolade 面包屑层级回溯。架构详见 `docs/design/modal-stack-architecture.md`（状态模型 routes[]+index / 命令式 API / 纯响应式导航 / 焦点管理）。**取消/保存语义（2026-08-29 用户确认；2026-08-31 统一「回上一级只读查看」）**：「取消」非底层只回退一层（链保留、父层编辑态不丢），单层编辑态下取消/保存都回到该类型**只读查看态**（不再关闭整个模态），查看态才关闭；「保存类型」保存当前层后按上述规则回退；create（新建）保存后关闭；**模态无右上角 ✕**（footer 统一取消/关闭）。**浏览器 History 已弃用（2026-08-31）**：早期 History 状态机（pushState/back/go + popstate）在多态来回跳转时触发死循环，改为纯 Vue 响应式（`typeNav.routes[]+index` + `typeSnapshots` 草稿），不写浏览器历史、不监听 popstate。 |

---

## R8.2 存储布局

```
config/
├── schemas/            # 现有：一表一文件
│   ├── Item.yaml
│   └── ...
└── types/              # 新增：全局类型库，按模块分文件
    ├── common.yaml     # 模块：通用
    ├── combat.yaml     # 模块：战斗
    └── ui.yaml         # 模块：界面
```

每个模块文件：

```yaml
# config/types/combat.yaml
types:
  - name: DamageRange
    kind: struct
    fields:
      - {name: Min, type: int32}
      - {name: Max, type: int32}
    comment: 伤害区间
  - name: DamageType
    kind: enum
    values: [physical, magic, true]
    comment: 伤害类型
```

## R8.3 数据模型

```python
# models.py 新增 TypeDef
class TypeDef(BaseModel):
    name: str                        # 全局唯一
    kind: Literal["enum", "struct"]
    # enum
    values: list[str] | None = None
    underlying: str = "int32"        # enum 底层整数类型（flatbuffers 必须；默认 int32）
    # struct
    fields: list[FieldDef] | None = None   # 复用 FieldDef（递归，天然带 comment）
    comment: str = ""                # 类型本身注释

# FieldDef 增加
type_ref: str | None = None          # 类型名引用（type 为 enum/struct 时）
```

**注释承载**：
- 类型本身 → `TypeDef.comment`
- struct 字段 → `FieldDef.comment`（已存在，直接复用）
- enum 值 → 无（决策 5：保持 `values: list[str]`）

**校验约束**：
- `TypeDef`：enum 必须有非空 values；struct 必须有非空 fields（对齐现有 `_validate_field` 约束）
- **enum 底层类型**：仅限整数标量（int8/int16/int32/int64/uint8/uint16/uint32/uint64），默认 int32；决定 fbs `enum X : <type>` 声明、二进制宽度与 C# 生成枚举底层类型。现有实现固定 `: byte`（repository.py:55），类型库化后需补该字段
- **struct 字段类型**：仅标量或嵌套 struct（FlatBuffers 约束：struct 不能含 string/vector/table）；嵌套 struct 用 `type_ref` 引用具名类型
- **撞名不变量（决策 6）**：类型名不得与任何表内字段名相同。从「fbs 生成后 `_check_name_collisions` 检查」前移为「加载 schema + 类型库时统一校验」，命中即报错提示改名。现有 `conventions.py` 的不变量逻辑保留，检查时机前移。

## R8.4 与现有架构的对接（不破坏结构）

```
config.py: GlobalConfig 增加 types_dir: str = "config/types"
workspace.py: Workspace 增加 types: list[TypeDef] + type_map: dict[str, TypeDef]
repository.py: 新增 TypeRepository（YamlSchemaRepository 同款模式）:
    load_all() → glob("types/*.yaml") → pydantic 解析 list[TypeDef] → seen_names 全局去重
repository.py: create_type_repository(types_dir, fmt)（与 create_repository 对称）
schema/loader.py: sort_schemas 时解析字段 type_ref → 查 type_map，校验引用存在 + 撞名
export/repository.py(_schema_fbs_text):
    从「内联生成 _generate_enum/_generate_struct_table」改为「查 type_map 取真名定义」
    fbs: enum Rarity / struct DropRange（真名，无后缀）
web/app.py: 新增 /api/types CRUD（与 /api/schemas 同构）:
    GET /api/types                # 列表（含 module）
    GET /api/types/<name>         # 详情
    POST /api/types               # 创建：{name, kind, ..., module: "combat"}
    GET  /api/types/modules       # 模块列表（扫描 types/*.yaml 文件名；供编辑器下拉 + 页签筛选）
    PUT /api/types/<name>         # 更新（可改 module = 跨文件移动）
    DELETE /api/types/<name>      # 删除（被字段引用则拒绝 + 列出引用处）
web/static/app.js + index.html: 新增「类型库」区块；字段编辑器 enum/struct 分支
    从内联编辑改为「引用类型下拉 + [+ 新建] [编辑↗]」
```

**fbs 后缀移除的影响面**：
- `_generate_enum`（repository.py:50）不再拼 `{field.name}Enum`
- `_generate_struct_table`（repository.py:58）不再拼 `{field.name}Struct`
- `ELEM_SUFFIX`（array<enum> 的 `{name}Elem`）同步处理
- `FbsConvention.ENUM_SUFFIX/STRUCT_SUFFIX/ELEM_SUFFIX` 常量可退役（撞名改为事前校验）
- golden 测试（test_binary_golden.py / test_accessor_golden.py）需更新（生成代码里的类型名变了）

## R8.5 现有 schema 迁移

| 现状（内联） | 迁移到 |
|---|---|
| `Item.DropRange` struct {Min,Max} | `config/types/common.yaml` → `DropRange` |
| `Item.Rarity` enum {common,rare,epic} | `config/types/common.yaml` → `Rarity` |
| `UIConfig.Layer` enum {Page,Modal,Panel,Overlay} | `config/types/ui.yaml` → `Layer` |

字段改为 `type: struct, type_ref: DropRange` / `type: enum, type_ref: Rarity`。
迁移可用脚本一次性完成（读现有 schema → 抽出内联类型写入类型库 → 字段改 type_ref）。

## R8.6 与 R2-R6 的关系

- **R2**（array→vector）：type_ref 化后的字段类型判断仍基于类型名，R2 的 vector 改名不受影响
- **R3**（fixed_length）：vector 字段的 fixed_length 属性不变，与类型库正交
- **R4**（vector\<struct\>）：天然解决「struct 定义在哪」——类型库里的具名 struct 作为 element 引用；`element: struct` + `type_ref` 引用具名 struct
- **R5**（struct 真 struct）：类型库化后 fbs 用真名 `struct DropRange`，R5 的「table 改真 struct」只动生成器布局，命名已就绪
- **R6**（补标量）：与类型库正交

## R8.7 验收标准

- [ ] 类型库支持分模块多文件存储，重名跨文件报错
- [ ] 字段用 type_ref 引用具名类型，全量迁移后无内联 enum/struct 残留
- [ ] fbs 输出用真名（`enum Rarity` / `struct DropRange`），无 `Enum`/`Struct`/`Elem` 后缀
- [ ] 撞名不变量事前拦截（类型名 == 字段名 → 保存/导出报错）
- [ ] 类型和 struct 字段注释可编辑、进 Excel 表头注释
- [ ] web 端类型库 CRUD + 字段引用编辑可用，全程不碰 YAML
- [ ] 模态导航栈：嵌套 struct 下钻 → 面包屑逐级返回；每层编辑态保持；单层编辑保存/取消回只读查看态；模态无 ✕（footer 统一关闭）
- [ ] 现有表导出、C#/Lua accessor 正确（golden 已更新）

## R8.8 实施批次建议

并入 R1（web 编辑器）所在的批 4，作为其前置子项「类型系统结构化」：

```
批 4a：类型库（TypeDef 模型 + TypeRepository + 迁移脚本（一次性，2026-08-31 已退役删除）+ fbs 真名 + 撞名事前校验 + /api/types + 前端类型库面板）
批 4b：web 字段编辑器升级为 type_ref 引用（引用下拉 + 新建/编辑入口）
```

**前置依赖**：R2（vector 改名）先做，避免类型库字段类型判断同时碰 array/vector 两套名；其余 R3/R5/R6 与类型库正交，可并行。

## R8.9 关联

- 设计讨论来源：2026-08-28 ct-tool 会话（R1 编辑器设计细化，6 条决策已确认）
- 与 fabulous-game `Docs/TODO/配表Schema演进.md` 的「web 编辑器设计」衔接

---

# R9：字段编辑器需求全集（字段类型 + 特殊属性 + Excel 列规则 + 表头注解）

> 状态：需求已定稿（2026-08-28 探索）
> 目的：R1（web 字段编辑器）的前置需求定义 + 新增的 Excel 体验需求。**先定需求，再定 UI 边界**。
> 来源：基于 `models.py` / `type_traits.py` / `validate/refs.py` / `accessor_model.py` / `excel/template.py` 真实代码穷举 + 用户逐项确认。
> 关联：fabulous-game `Docs/TODO/Config性能优化-最终修改方案.md` 改动 8（哈希索引）定义了 `code_name` / `group_key` 字段标记。

---

## R9.1 字段类型（9 种）→ 编辑内容

```
基本类型（6）:  int32  int64  float  double  bool  string
复合类型（3）:  enum  struct  vector（R2 改名后，原 array）
```

| 类型 | 字段行形态 | ⚙ 展开内容 |
|---|---|---|
| 标量（int32/64, float, double, bool, string） | 名称 + 类型 | 仅属性行 |
| enum | 名称 + 类型 + 引用下拉（选具名 enum） | 引用类型只读预览（值在类型库） |
| struct | 名称 + 类型 + 引用下拉 | 引用类型只读预览（子字段在类型库） |
| vector | 名称 + 类型 + 元素类型选择 | 元素详情 + 属性行 |

## R9.2 字段特殊属性（完整穷举）

### 表级（编辑器要感知，不在字段上编辑）
| 属性 | 语义 | 约束 |
|---|---|---|
| `primary` | 主键字段名 | 仅 int32/int64；必须是字段之一；生成 byId 索引 |

### 字段级（⚙ 展开区编辑）

| 属性 | 编辑器显示 | 谁能用 | 校验 | 产出影响 |
|---|---|---|---|---|
| `ref` | ref（**下拉选表名**，目标固定主键 id） | 任意类型 | 值存在于目标表 id 集 | Excel 表头标注；跨表引用校验 |
| `i18n` | i18n | **仅 string** | 非 string 禁；与 server_only 互斥 | i18n 流程 |
| `server_only` | server_only | 任意类型 | 与 i18n 互斥 | 客户端 Binary/accessor/fbs 排除 |
| `comment` | 注释 | 所有类型 | 无 | Excel 表头注释行 |
| **`code_name`** | **按 Code 查询（字段名 = CodeName 自动成为 code，非 checkbox）** | **仅 string（CodeName）** | **导出时校验唯一**；保存时可给 Excel 列加唯一性规则 | 生成 ByCode() + nameHash 索引 |
| **`group_key`** | **按品类查询** | 任意类型 | 无 | 生成 ByGroupKey() + groupHash 索引 |
| `values` | enum 值 | 仅 enum | 非空 + 合法标识符 | 在类型库编辑（R8） |
| `element` | vector 元素类型 | 仅 vector | 必填；非 struct | fbs |
| `element_values` | vector\<enum\> 值 | 仅 vector\<enum\> | 必填 | 在类型库编辑（R8） |
| `separator` | （不展示） | 仅 vector | 默认 "," | 固定隐藏，不可编辑（已确认） |

**用户确认的关键决策**：
- `ref`：编辑器只列**表名**下拉（最终填的肯定是目标主键 id），不列目标字段
- `code_name` 唯一性：**导出时必校验**；保存时若可做则给 Excel 列加唯一性规则
- `group_key` 进编辑器（与 code_name 并列）
- **`server_only` 保留（2026-08-28 确认）**：虽然当前无服务器，但 1) 现有 `Item.yaml:38` 的 `IsActive` 已标记 server_only；2) server_only 的实际语义是「不进客户端包体」（省客户端内存/带宽），不只服务端用。编辑器保留该选项，后端排除能力不动。若未来确认不需要，再做独立清理。
- **主键命名锁定（2026-08-28 确认）**：主键**必须在建表时就有**、不能删、类型限制 int32/int64，字段名固定 `Id`。编辑器里主键字段显示 `🔒 主键` 锁定标记，无改名/删除入口。
- **code 命名锁定（2026-08-28 确认）**：code 字段固定名 `CodeName`（不能换），字段编辑器里显示 `🔒 CodeName` 锁定标记。**「按 Code 查询」不是 checkbox**——由「字段名 = CodeName」天然决定（字段名唯一 → 全表唯一），去掉属性行里的 code checkbox。
- **去掉 JSON 键（2026-08-28 确认）**：编辑表模态的「JSON 键（可选）」输入框去掉（json_key 默认 `{表名}s` 即可，无需配置）。
- **精简 fe-meta（2026-08-28 确认）**：字段行的 `fe-meta` 小标签（主键/i18n/ref/按 Code 查询）全是重复信息（锁定标记/展开区 checkbox/ref 下拉已有），**整体去掉**，字段行更干净。
- **自定义下拉（2026-08-28 确认）**：原生 select 弹出层是系统级灰色，风格割裂。改为**自定义浮层下拉**（参考 deepseek-harness ui-primitives Menu：白底圆角卡片、阴影、hover 高亮、选中打勾 ✓、亮暗主题用 CSS 变量预留 `[data-theme]`）。设计稿已实现 `dsh-select` 组件替换全部原生 select。
- **vector 元素可选 struct（2026-08-28 确认）**：vector 元素下拉含 struct；元素选 struct 时长度模式**强制定长**（变长禁用），符合 R4「vector<struct> 必须配 fixed_length」。
- **文本不折行（2026-08-28 确认）**：短标签（变长/定长/属性名）加 `white-space: nowrap`，属性行两字标签不折行。

## R9.3 Excel 列规则（数据校验，统一在 `excel/template.py` 的 DataValidation 循环）

| 字段类型/属性 | Excel 列规则 | 现状 |
|---|---|---|
| enum | 下拉（值列表） | ✅ 已有（`template.py:385-404`） |
| **bool** | **下拉 ✓/✗**（默认不填 = false；0/1 也可识别） | ❌ 新增 |
| **code_name** | **唯一性校验**（COUNTIF 自定义公式） | ❌ 新增 |

**bool ✓/✗ 完整设计（已确认）**：
- Excel 下拉选项：`✓ / ✗`（配表人选）
- 默认不填 = false（None 视为 false，不报「值不能为空」）
- 表头注解：`bool`（不提示 ✓/✗）
- `vector<bool>`：支持 ✓/✗，`0/1` 也识别

**落地改动**：
```python
# 1. type_traits.py: _coerce_bool 增加 ✓/✗（0/1 已支持）
_BOOL_TRUE  = frozenset({..., "✓"})
_BOOL_FALSE = frozenset({..., "✗"})

# 2. type_traits.py: validate_field_value 加 bool 分支（None → false，不报错）
if field.type == "bool" and value is None:
    return []        # 默认不填 = false

# 3. excel/template.py: bool 列下拉 "✓,✗"
dv = DataValidation(type="list", formula1='"✓,✗"', allow_blank=True)
```
> ✓/✗ 只是 Excel 输入层友好表示——内部 coerce 后是 bool，JSON/二进制导出仍是标准 `true/false`，产物不受影响。

## R9.4 Excel 表头类型注解优化（type_traits.py annotation 函数）

| 字段 | 现状注解 | 目标注解 | 说明 |
|---|---|---|---|
| ref 字段（如 ItemTypeId） | `int32[ref:ItemType.Id]` | **`ref:ItemType`** | 不写目标字段（固定是主键 id），就当「是一个 ItemType 类型」 |
| enum 字段（如 Rarity） | `enum[common,rare,epic]` | **`Rarity`** | 直接显示类型名（值列表在类型库） |
| vector 字段（如 Tags） | `array<int32>` | **`int32[]`** | 与编辑器类型表达式统一（2026-08-30 确认：编辑器显示 `int32[]`，表头注解同语言） |

**落地改动**（`type_traits.py`）：
- `_annotation_scalar`：ref 时取表名 `field.ref.split('.')[0]`
- `_annotation_enum`：返回 `field.name`（R8 后返回 type_ref 类型名）
- `_annotation_array`：`array<...>` → `{element}[]`（如 `int32[]`、`DropRange[]`）

**依赖**：R2（改名 array→vector）先做；R8 后 enum 注解衔接 type_ref 类型名。

## R9.5 字段编辑器 UI 边界（基于需求定稿）

```
表元信息区:
  [表名] [主键字段]        ← 主键固定 Id（建表时就有，不能删）；无 JSON 键

表格管理页签（表列表行）:
  [表名 + excel 文件] [N 字段 · i18n M] [状态徽章] [编辑] [删除]
  删除 → 确认模态（"将删除 X 的 schema 定义与 Excel 模板，不可恢复；已导出产物与翻译文件不受影响"）

字段行（默认，一行）:
  [类型胶囊▾ 固定宽] [可编辑字段名] [状态 tags] [查看↗] [↑][↓][⚙][✕]
  类型胶囊（2026-08-30 确认）: 固定长度类型名（非下拉）+ pick 按钮（✎），一组整体（圆角矩形容器，与字段平级）
              点击 pick 打开「类型 pick 模态」；具名类型胶囊显示类型名（ref 样式 accent 粗体）
  类型 pick 模态（2026-08-30 确认）: 分组展示（基础类型 / 类型库 enum / 类型库 struct）+ 搜索过滤 +
              「标记为数组类型」开关（勾选 → 元素选择，显示「元素[]」，如 int32[] / DropRange[]）
  布局决策（2026-08-30 确认，类型+字段名对齐调研结论）: 类型胶囊固定宽（116px）每行同位全对齐；
  字段名左边缘全行一致（含 Id/CodeName 锁定行）；「查看↗」在右侧 ops 区（右对齐，不推字段名）；
  操作按钮统一右对齐
  tags（只读徽章，不可交互）: 🔒主键(gold) / 🔒CodeName(accent) / 🌐i18n / 🖥server_only / 🗂按品类 / 🔗ref:表名
              —— 属性 tag 是 ⚙ 展开区 checkbox/ref 下拉的「状态镜像」，只显示已开启项
  注: 无 fe-meta 小标签；主键/code 锁从字段名内徽章迁移为独立 tag

⚙ 展开「字段详情」（统一浅灰虚线区）:
  ├─ 类型专属结构（enum/struct 引用只读预览 / vector 元素+长度模式）
  ├─ 分隔线
  └─ 通用属性行:
     [i18n] [server_only] [按品类查询] [ref:表名▾] [注释:__]
     （按 Code 查询不是 checkbox——字段名 CodeName 自动成为 code）
```

**交互细节**：
- 字段名 inline edit（普通字段点击变输入框，失焦/回车保存）；Id/CodeName 锁定（🔒 标记，无编辑入口）
- 下拉全部用**自定义浮层下拉**（dsh-select，参考 deepseek-harness Menu：白底圆角、阴影、hover 高亮、选中打勾 ✓）
- **类型胶囊 + pick 模态（2026-08-30 确认，对齐调研第二轮结论；2026-08-31 补落地细节）**：行内类型不再用下拉——固定宽度类型名 + pick 按钮一组；pick 打开**类型模态**。**数组标记联动（2026-08-30 确认，依赖控件模式，参考 WHATWG dependent form controls）**：勾选数组 = 当前选中类型直接变数组（`类型[]`），无独立元素选择器（2026-08-30 确认）。**类型库可扩展（2026-08-30 确认，命令面板式，参考 Nuxt UI Command Palette / Figma 样式选择器）**：基础类型固定网格（6 个），类型库为**可滚动列表**（每行类型名 + kind + **注释**（截断省略）+ 模块，max-height 滚动）+ **模块筛选 pills（全部/common/ui，2026-08-30 确认）** + 搜索过滤（含模块名匹配）；「**最近使用**（去重置顶 5 个）」为设计稿体验项，**2026-08-31 暂未落地（待决策）**。**2026-08-31 落地补**：pick 打开时**按需加载类型库**（未访问类型页签也显示）+ **当前类型默认高亮**（基础 chip `.chip.active`、具名行 `.fe-row.active`，footer 显示「将设为：当前选择」）。**查看类型 = tag-link（2026-08-30 确认）**：具名类型胶囊的类型名本身是 link（点击打开类型查看，hover 下划线），移除行级查看按钮，减少样式。**ref 没有第二个下拉**——外键是属性，⚙ 展开区 ref 下拉编辑、行级 🔗 tag 镜像
- 数组元素是具名 struct → 长度模式强制定长（变长禁用）
- 短标签 white-space: nowrap 防折行
- **字段名左对齐（2026-08-30 修复）**：`.fe-name` 统一 padding（锁定行/可编辑行左边缘一致）；「查看↗」改为类型胶囊 tag-link；类型胶囊固定宽
- **新增字段空名可再编辑（2026-08-30 修复）**：添加字段后失焦留空 → 字段名显示「未命名字段」占位（灰字，`.name-text.empty`，min-width 保证可点区域），点击仍可进入编辑，不再丢失编辑入口
- **校验错误即时显示（2026-08-29 确认，R1 验收项 3 落点）**：字段名空 → 行红框（`.fe-row.invalid`）+ 行内「⚠ 字段名必填」；与现有字段重名 → 「⚠ 与字段 X 重复」；主键行删除按钮受保护（「主键字段不可删除」）；「保存 Schema」全量校验 → 模态顶部 `error-inline` 汇总「存在 N 处校验问题（…），请修复后再保存」；重新打开模态时错误态复位
- **属性互斥联动（2026-08-29 确认）**：i18n ⇄ server_only 互斥（勾一个自动禁另一个，`attr-lock` 置灰）；i18n 仅 string（类型切非 string → i18n 禁用置灰 + 清勾选）
- **状态 tag 镜像（2026-08-30 确认）**：i18n / server_only / 按品类 / ref 的 tag 由 ⚙ 展开区 checkbox / ref 下拉驱动显隐（只读，不可点击）

**校验规则（编辑器内建，对齐模型）**：
- `code_name`：仅字段名 = CodeName 的 string 字段自动是 code（字段名唯一 → 天然唯一）
- `group_key`：任意类型
- `i18n`：仅 string；与 server_only 互斥
- `ref`：下拉只列表名（目标主键 id）

## R9.7 设计优化（design-taste audit，2026-08-30）

> 用 design-taste-frontend 技能审计设计稿（声明：内部工具面板属技能 Out-of-Scope 类，仅借用产品 UI 适用规则；硬约束「与 web 公共类逐字对齐」全程保持）。参考：Supabase Design System Empty states（[supabase.com](https://supabase.com/design-system/docs/ui-patterns/empty-states)）、Dense-UI 密集工具组件库（[github.com/codejupiter/Dense-UI](https://github.com/codejupiter/Dense-UI)，density-first + keyboard-first）。

| 优化项 | 做法 | 依据 |
|---|---|---|
| 空态（3 类） | 表格管理空态「暂无表 + 新增表 CTA」；类型库空态「暂无类型 + 新建类型 CTA」；pick 搜索/模块筛选空态「未找到匹配的类型（"关键词" · 模块 X）」。均与列表同构（虚线框，避免布局跳动） | Supabase：Initial state 引导型 + Zero results 同构型 |
| 焦点可见性 | icon-btn/link-btn/btn/pill/radio-opt/tp-item/tp-lib-item/tab/crumb-item + schema-row/type-row（tabindex）统一 `:focus-visible` 环（0 0 0 3px accent-soft，键盘才显示、鼠标不干扰）。**2026-08-31**：modal-close ✕ 按钮已全部移除，从焦点控件清单中去掉 | Dense-UI keyboard-first；WCAG 2.4.7 |
| 按压反馈 | 上述控件 `:active { transform: translateY(1px) }`（与 .btn 同语言） | 技能 tactile feedback |
| 模态过渡 | 新增 `.modal-anim` 类：mask fade + modal pop（160ms cubic-bezier(0.16,1,0.3,1)）；`prefers-reduced-motion` 禁用。**不动公共类**（.modal-mask/.modal 保持 web 逐字） | 低 motion（工具面板 MOTION_INTENSITY 2） |
| 对比度修复 | tag-lock.pk `#8a6d12`→`#7A6214`（对齐 web `.pk-cell`，对比度 4.22→5.03 达标 AA） | WCAG AA 4.5:1 |
| 注释可读性 | tp-cmt（类型库条目注释）ink-3→ink-2（设计稿新增样式，非公共类） | 小字 11px 对比度 3.12→6.14 |
| 键盘优先 | pick 模态打开自动聚焦搜索框；可点击行 schema-row/type-row 加 tabindex | Dense-UI keyboard-first |

**对齐保证**：全部改动不触碰 web 公共类基础定义（复查 117 类，唯一例外 .modal-mask 的 animation 已改挂 .modal-anim 新类恢复逐字对齐）；新增类均带 `fe-`/`tp-`/`tag-`/`list-` 前缀。新增截图 10-表格管理-空态.png、11-类型pick-搜索空态.png。

## R9.6 验收标准

- [ ] 字段编辑器支持 9 种类型的结构化编辑（标量/enum/struct/vector）
- [ ] 字段特殊属性完整可编辑：ref（表名下/下拉）、i18n、server_only、comment、code_name（按 Code 查询）、group_key（按品类查询）
- [ ] code_name 唯一性：导出时校验重复；保存时给 Excel 列加唯一性规则（可做则做）
- [ ] bool 类型 Excel 下拉 ✓/✗，默认不填=false，0/1 可识别，vector\<bool\> 支持
- [ ] Excel 表头注解优化：`ref:ItemType` / `Rarity` / `int32[]`（与编辑器类型表达式一致）
- [ ] 与 R1/R2/R8 衔接（字段编辑器在类型库 + 改名后实现）

# ct-tool 需求清单评审

> 评审日期：2026-08-30
> 评审范围：`ct-tool-需求清单.md`、`modal-stack-architecture.md`，并对照当前 schema、Excel 模板和 Web 实现核实。
> 结论：整体演进方向合理；在实施 R1/R4/R8/R9 前，必须先补齐下述 P0/P1 设计决策，避免 schema 不可迁移、Excel 数据错列或模态导航回退异常。

## 问题清单

| 优先级 | 问题 | 影响 | 建议决策 |
|---|---|---|---|
| P0 | R8 要求类型名不得与任意字段同名，但迁移示例又将 `Item.Rarity` 迁为 `Rarity`、`UIConfig.Layer` 迁为 `Layer`。这会触发现有 FBS 的类型名/字段名冲突不变量。 | 类型库迁移无法通过校验，FBS 无法生成。 | 二选一并写入迁移脚本：保留 `Enum`/`Struct` 后缀，或使用 `ItemRarity`、`UiLayer` 等全局且不与字段冲突的类型名。 |
| P1 | `vector<具名 enum/struct>` 没有明确、可持久化的数据模型。`type_ref` 仅定义给 enum/struct 字段，R4 却需要 vector 的元素引用类型。 | API、YAML、FBS、二进制、Excel 与编辑器会各自猜测字段含义。 | 在 R8 前建立统一类型表达式。最小改动方案：顶层 enum/struct 使用 `type_ref`，vector 使用 `element_type` + `element_type_ref`；所有层复用同一解析/校验函数。 |
| P1 | 现有 `update_template()` 按旧列序直接追加数据。vector 单列改为 `fixed_length` 多列、struct 展开变化或中间插入字段时，旧数据会静默错列。 | 用户选择 `--update-header` 时可能损坏 Excel 数据语义。 | 布局变化时默认拒绝保留数据更新；后续如需支持，按稳定字段路径重映射，并为单列 vector → 多列 vector 提供显式转换。 |
| P1 | 模态栈把取消、面包屑返回也实现为 `pushState`，关闭又不消费 history 条目。关闭后按浏览器返回会重新打开模态，取消后的 Back/Forward 也会绕回子页面。 | Back、Esc、关闭按钮行为不可预测，和设计目标相反。 | 仅“下钻”执行 `pushState`；取消/关闭执行 `history.back()`；草稿等不应新增历史的状态使用 `replaceState`。补齐来源切换、取消、关闭、Back/Forward 的端到端测试。 |
| P1 | `code_name`、`group_key` 目前只存在于 TODO 和 mockup；当前 `FieldDef`、schema hash、校验、生成器、API 都没有承载或消费。 | R9 所称的 ByCode/ByGroupKey、唯一性和模板规则没有可验证的端到端契约。 | 先锁定 schema 表达：推荐显式 `group_key: bool`；`code_name` 则明确采用严格约定 `CodeName: string`，或也采用显式标记。之后再同时实现校验、hash、Excel、访问器和迁移测试。 |
| P1 | 类型库只描述“引用存在”，没有类型到类型的依赖图、循环检测、删除/改名的级联策略。递归 struct 对内联 FlatBuffers 不成立。 | 可能生成非法 FBS；删除或改名类型会留下失效引用。 | 在 Workspace 加载阶段建立表字段和类型字段的全局依赖图与反向索引：拒绝直接/间接 struct 环；删除时列出引用点；改名要么拒绝，要么原子更新全部引用。 |
| P2 | R5 的验收“struct 大小 = 字段数 × 字段大小”忽略 FlatBuffers 对齐、padding 与嵌套 struct。 | 测试会对合法布局产生错误断言。 | 改为按 FlatBuffers 对齐规则验证 size/alignment，并覆盖混合宽度标量和嵌套 struct。 |
| P2 | `fixed_length` 未定义正整数约束；R5 的“struct 子字段留空=0”仍是建议，未成为实施前置契约。 | 可能出现零列 vector，或 reader/validator/binary writer 对空值行为不一致。 | 模型层强制 `fixed_length >= 1`；将 struct 空值策略正式定为 `0`/`false`（或统一报错），并为两种行为增加解析和导出测试。 |

## 关键设计澄清

### 类型命名与 FBS 冲突

现有 FBS 生成器用 `RarityEnum`、`DropRangeStruct` 等后缀避免“类型名等于字段名”。因此“真实类型名”策略不能直接使用当前字段名作为类型名。迁移脚本必须在写入 `config/types/` 前执行全局名称分配，并在冲突时给出可读报错或生成稳定替代名。

### 类型引用的统一契约

建议将以下内容作为 R8 的第一项交付：

```yaml
# 标量
- name: Level
  type: int32

# 具名 enum/struct
- name: Rarity
  type: enum
  type_ref: ItemRarity

# vector 标量 / 具名类型
- name: Tags
  type: vector
  element_type: int32
  fixed_length: 5
- name: Rewards
  type: vector
  element_type: struct
  element_type_ref: RewardDrop
  fixed_length: 3
```

字段名、字段类型、类型引用与 vector 元素引用应由同一解析器转成内部 canonical 模型；FBS、二进制、Excel、访问器和 Web API 都只消费该模型，避免各模块重复判断 `type_ref` 的含义。

### Excel 模板更新安全性

`--update-header` 目前的“保留数据”定义仅适用于列顺序和列数不变、仅表头样式/注释等变更。将 vector/struct 改为不同列布局属于数据迁移，不应伪装成表头更新。

决策（2026-08-30，用户确认）：**列布局变化一律不拒绝**——`update_template` 始终保留数据行（整行 append），列表头/列数/列序变化导致的错列风险由用户自行核对与转移；占行数（header_rows）变化时数据行由 append 语义自动落到新表头（new header_rows + 1）之后（实测不错行）。长期策略：为每列持久化稳定字段路径，按旧路径到新路径映射数据；该能力需单独需求和测试矩阵（未做）。

### 模态 History 状态机

“模态内导航”与“浏览器历史”应有明确的一对一关系：

1. 打开根模态：push 一条根路由状态。
2. 下钻：push 一条子路由状态。
3. 取消或保存后返回父层：调用浏览器 back，由 `popstate` 恢复父状态。
4. 关闭根模态：调用浏览器 back，回到打开前页面状态。
5. 更新同一路由的草稿、焦点或滚动位置：replace 当前 state，不新增历史。

这样浏览器的 Back/Forward 与 UI 的返回/前进方向一致，避免重复路由和已关闭模态“复活”。

**2026-08-31 最终修订（弃用 History 状态机）**：上述「push/back/go + popstate」实现落地后，在多态间来回跳转（编辑 → 下钻 → 返回 → 再编辑）时，popstate 反复触发恢复与 Vue 响应式渲染叠加，触发**死循环**（模态关不掉/回跳异常）。结论：类型模态内导航**完全由 Vue 响应式状态驱动**（`typeNav.routes[]+index` + `typeSnapshots` 草稿快照），**不写浏览器历史、不监听 popstate**；浏览器物理返回键不参与模态内导航，关闭模态不污染历史、无复活问题。见 `docs/design/modal-stack-architecture.md` 第 4 节。

## 调整后的实施顺序

1. **设计收口**：锁定类型命名、类型表达式、struct 空值语义、`code_name/group_key` schema 契约，以及布局变化时的模板更新策略。
2. **R2 + R3**：完成 `array → vector`，实现 `fixed_length` 与 Excel 列展开；同时增加模板布局变化保护。
3. **R5 → R4**：先落地真 struct、对齐/空值测试和运行时读取，再实现 `vector<struct>`。
4. **R8 后端与迁移**：TypeDef/Repository、全局依赖图和反向索引、FBS 真名生成、一次性迁移工具、全量回归与 golden 更新。
5. **R9 领域能力**：落地 bool 输入、code/group 校验与生成器输出，确保每个字段属性均有 YAML → 校验 → 产物的闭环测试。
6. **R1 与模态架构**：最后实现结构化编辑器、类型库界面和修订后的 History 行为。

## 建议验收补充

- 类型迁移：冲突名称、跨模块重名、类型重命名、删除被引用类型、间接 struct 环均有测试。
- 模板迁移：列数变化、字段重排、struct 展开变化必须验证不会静默错列。
- vector：`fixed_length` 为 0/负数、部分填值、全空、vector<bool>、vector<struct> 都有读取与二进制对拍。
- Web：关闭后 Back 不重开模态；取消后 Back/Forward 路径正确；焦点恢复到实际触发元素。
- 新字段属性：`code_name/group_key` 既有模型/哈希/API 测试，也有生成 accessor 的行为测试。

---

## 落点追踪（2026-08-30）

> 评审后各问题的处理状态。设计稿/文档层已完成项即时落实；后端项待实施批次。

| 优先级 | 问题 | 状态 | 落点 |
|---|---|---|---|
| P0 | 类型名与字段名冲突（Rarity/Layer 迁移触发 FBS 不变量） | 待实施（设计已定） | 需求清单 R8 决策 6「撞名事前校验」已定；迁移脚本需全局名称分配（保留后缀或 `ItemRarity`/`UiLayer`），实施时落实 |
| P1 | vector<具名类型> 无持久化数据模型 | 待实施（契约已定） | 评审建议 `element_type` + `element_type_ref`（见上「统一类型契约」）；设计稿 pick 模态「标记数组」= `元素[]` 表达式与之对应，实施时入 R8 第一项 |
| P1 | `--update-header` 静默错列 | ✅ 已决策（2026-08-30） | 用户确认：**列布局变化（列表头变化）一律不拒绝**——`update_template` 始终保留数据（整行 append，错列风险由用户自行核对转移）；占行数（header_rows）变化时数据行由 append 语义自动落到新表头之后（已实测验证不错行）。长期路径重映射未做 |
| P1 | 模态 History 状态机（pushState 膨胀 / 关闭后复活） | ✅ 已修订（2026-08-30）→ ✅ 最终弃用（2026-08-31） | 2026-08-30：`modal-stack-architecture.md` 第 4 节重写为「仅前进 push，回退/关闭用 back」。2026-08-31：该 History 状态机在多态来回跳转时触发 popstate 死循环，**彻底弃用**——类型模态改纯 Vue 响应式（`typeNav.routes[]+index` + `typeSnapshots`），删 popstate 监听/history 依赖，不写浏览器历史；另按用户要求统一「保存/取消回上一级只读查看」、模态 ✕ 全部移除改 footer 取消/关闭 |
| P1 | code_name/group_key 无端到端契约 | 部分覆盖 | 设计稿已锁定（CodeName 命名约定 + 🔒 锁定 + 按品类 tag）；后端模型/哈希/生成器实现时统一落 |
| P1 | 类型依赖图 / 环检测 / 删除改名级联 | 部分覆盖 | 设计稿已有引用计数 + 删除保护提示；Workspace 加载阶段依赖图与环检测入 R8 实施 |
| P2 | R5 struct 大小断言忽略对齐/padding | 待实施 | 验收改为按 FlatBuffers 对齐规则验证，入 R5 批次 |
| P2 | fixed_length 无正整数约束 / struct 空值语义 | 待实施 | 模型层强制 `fixed_length >= 1`；struct 空值 = 0/false 契约入 R3/R5 批次 |

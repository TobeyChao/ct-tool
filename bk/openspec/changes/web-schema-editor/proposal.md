## Why

策划目前通过 web 面板编辑 schema 时接触的是 **YAML 明文文本框**（`app.js` 的 `serializeFields` 把字段序列化成 YAML 塞进 textarea），无类型补全、无校验、易出错。R8/R9 又引入全局具名类型库（enum/struct 抽离为可复用类型）与字段特殊属性全集，YAML 明文形态无法承载。目标：把 schema 编辑升级为**结构化编辑器**，策划全程不碰 YAML，同时落地类型库。

## What Changes

- **web 编辑器结构化**（R1）：表格管理页签支持表增删改查（删除带确认模态、空态引导）；字段编辑器支持 9 种类型（6 标量 + enum/struct/vector）的结构化编辑，字段增删/上移/下移/重命名；属性行（i18n / server_only / 按品类查询 group_key / ref 表名下拉 / 注释）；保存前即时校验（字段名空/重名、i18n 仅 string、i18n⇄server_only 互斥、主键锁定），后端 `_build_schema` 校验兜底；全程不暴露 YAML 明文。
- **类型库**（R8）：新增 `config/types/*.yaml` 分模块存储全局具名类型（enum/struct）；`TypeDef` 模型（kind/values/underlying/fields/comment/module）；enum `underlying` 产出链路（fbs `enum X : <type>` / 二进制宽度 / C# 底层类型）；类型与 struct 字段注释进 Excel 表头注释行；全局唯一类型名 + **撞名事前校验**（类型名不得与字段名相同，时机从 fbs 生成后前移到加载时）；字段以 `type_ref` 引用具名类型，全量迁移后无内联 enum/struct 残留；fbs 输出真名（`enum Rarity` / `struct DropRange`，无 Enum/Struct/Elem 后缀）；`/api/types` CRUD + `/api/types/modules`；类型依赖图与环检测（递归 struct 拒绝）；删除被引用类型保护（列出引用处）。
- **字段属性端到端**（评审 P1）：`group_key` 进 FieldDef 模型与 schema hash、校验、accessor 生成（ByGroupKey + groupHash）；`code_name` 唯一性导出校验 + Excel COUNTIF 列规则。
- **字段编辑器 UI**（R9，按设计稿定稿）：行内**类型胶囊**（固定宽类型名 + pick 按钮一组整体）+ **类型 pick 模态**（基础类型/类型库分组 + 搜索 + 模块筛选 + 数组标记联动：勾选数组 = 当前类型变 `元素[]`；**2026-08-31 落地**：按需加载类型库 + 当前类型默认高亮）；字段名后**只读状态 tags**（🔒主键 / 🔒CodeName / 🌐i18n / 🖥server_only / 🗂按品类 / 🔗ref）；类型表达式语言与 Excel 表头注解统一（`int32[]` / `Rarity` / `ref:ItemType`）；字段名左对齐（锁定行与可编辑行一致）；vector 元素为具名 struct 时强制定长。最近使用列表为设计稿体验项（未落地，待决策）。
- **类型模态导航栈**：类型查看/编辑内嵌套 struct 下钻用**单模态内导航栈 + 面包屑**（Hackolade 模式），每层独立 view/edit/create 模式。**2026-08-31 修订：弃用 History 状态机**——原「History 按评审 P1：仅打开根/下钻 pushState，取消/保存返回父层与关闭走 `history.back()`（popstate 恢复）」落地后在多态来回跳转时触发 popstate 死循环，改为**纯 Vue 响应式**（`typeNav.routes[]+index` + `typeSnapshots` 草稿），不写浏览器历史；并按用户要求统一「保存/取消回上一级只读查看」、模态 ✕ 全部移除改 footer 取消/关闭。
- **设计优化**（R9.7）：空态（表格/类型库/搜索无结果）、键盘焦点可见性（`:focus-visible`）、按压反馈（`:active`）、模态过渡（低 motion + reduced-motion 降级）、对比度 AA 达标；公共类与现有 web 面板逐字对齐（不跳变）。
- **BREAKING**：字段类型名 `array` → `vector`（R2）同步落地——含代码层全面改名（models/type_traits/binary_writer/accessor 生成器/reader/refs/web 类型判断）与现有 schema 迁移；现有内联 enum/struct schema 经一次性迁移脚本迁入类型库（类型命名按评审 P0：全局名称分配避免与字段名冲突）。**2026-08-31**：迁移脚本已完成使命并删除（一次性工具，`migration.py` + `ct migrate-types` 退役），schema/types 均已迁移到位。
- **Excel 列规则与表头注解**（R9.3 + R9.4）：bool 列 Excel 下拉 ✓/✗（默认不填 = false，0/1 可识别，vector\<bool\> 支持）；code_name 列 COUNTIF 唯一性校验（导出时校验重复）；表头注解统一为 `ref:表名` / 类型名 / `元素[]`（与编辑器类型表达式一致，bool 注解不提示 ✓/✗）。
- **模态焦点管理**：类型模态与编辑器各模态打开移入焦点、下钻进入新层、关闭恢复触发元素（架构文档第 6 节，实施时落实项）。

## Capabilities

### New Capabilities

- `schema-editor/web-editor`: web 端结构化 schema 编辑器主体——表格管理页签（表 CRUD/删除确认/空态）、字段编辑器结构化交互、保存与校验、与既有 `/api/schemas` 对接、不暴露 YAML。
- `schema-editor/type-library`: 全局具名类型库——`TypeDef`/`TypeRepository`/`config/types/*.yaml` 分模块存储、`/api/types` CRUD、撞名事前校验、类型依赖图与环检测、删除引用保护、fbs 真名、迁移脚本。
- `schema-editor/field-editor`: 字段编辑器需求全集——类型胶囊 + pick 模态（分组/搜索/模块筛选/最近使用/数组标记联动）、状态 tags、类型表达式语言、字段名对齐、inline edit、空名占位、空态。

### Modified Capabilities

- `web-panel`: 表格管理页签的 schema 编辑形态从 YAML 明文文本框升级为结构化编辑器；面板新增「类型库」页签（全局类型查看/编辑/新建，入口与字段引用联动）。
- `schema-management`: schema 加载链路扩展——新增类型库加载（`types/*.yaml`）、字段 `type_ref`/vector `element_type_ref` 解析与校验、类型名撞名不变量前移到加载时校验、依赖图扩展到「表字段 + 类型字段」并拒绝递归 struct 环。

## Impact

- 后端：`ct/src/ct/schema/models.py`（TypeDef、FieldDef.type_ref/element_type_ref）、`repository.py`（TypeRepository、fbs 真名生成）、`loader.py`（类型依赖图/拓扑）、`config.py`（types_dir）、`web/app.py`（/api/types）、`conventions.py`（撞名校验前移）；R2 改名波及 `type_traits.py` / `binary_writer.py` / csharp/lua accessor 生成器 / `excel/reader.py` / `validate/refs.py`；R9.3/R9.4 波及 `type_traits.py`（_coerce_bool/annotation）与 `excel/template.py`（DataValidation）。
- 前端：`ct/src/ct/web/static/app.js` + `index.html`（结构化字段编辑器、类型库页签、类型 pick 模态、模态导航栈、状态 tags、空态/焦点/过渡）。
- 数据：`config/types/*.yaml` 新增；`config/schemas/*.yaml` 迁移（内联 enum/struct → type_ref，`array` → `vector`）。
- 测试：golden 更新（生成代码类型名变化）、迁移/撞名/环检测/引用保护测试。
- 设计依据：`ct/docs/design/schema-editor-mockup.html`（设计稿）、`ct/docs/design/modal-stack-architecture.md`（模态栈）、`ct/docs/TODO/ct-tool-需求清单.md` R1/R8/R9、`ct/docs/TODO/ct-tool-需求清单-评审.md`（P0/P1/P2 落点）。

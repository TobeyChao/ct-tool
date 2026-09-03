## Context

见 proposal.md（Why）。现有基础：后端 `/api/schemas` CRUD 已完备，`_build_schema` 接收 YAML 文本（字段数组序列化成 YAML 即可复用，模型不改）；前端 `app.js`（Vue 3 全局脚本，无构建）+ `index.html` 已有面板页签，schema 编辑为 YAML 文本框（`serializeFields`/`fields_yaml`）。设计已定稿：`ct/docs/design/schema-editor-mockup.html`（设计稿，交互可演示）、`ct/docs/design/modal-stack-architecture.md`（模态栈架构，2026-08-31 修订为纯 Vue 响应式、弃用 History 状态机）。需求清单 R1/R8/R9 与评审文档 P0/P1/P2 落点为行为契约来源。

## Goals / Non-Goals

**Goals:**
- 后端类型库（TypeDef/TypeRepository/API/依赖图；迁移脚本已完成使命退役）作为独立可测试单元先落地（R8 后端 → R9 领域能力 → R1 前端）
- 前端结构化编辑器与类型库面板按设计稿落地（公共类逐字对齐，不破坏既有面板）
- 模态导航栈（纯 Vue 响应式，D4）按架构文档实现；保存/取消回上一级只读查看（D9）

**Non-Goals:**
- 数据行编辑（Excel 行数据仍走 Excel，web 不做行编辑）
- 亮暗双主题切换（设计稿仅 CSS 变量预留 `[data-theme]`，web 面板保持亮色）
- R3 fixed_length 的 Excel 列展开、R4 vector<struct> 二进制、R5 真 struct、R6 新标量——这些是既有/另立 change 的 schema/导出改造，本 change 只要求编辑器能表达它们（向量长度模式、元素选择），不实现其布局/二进制链路
- 说明：R9.3/R9.4（bool ✓/✗ Excel 下拉、code_name 唯一性、表头注解）属于 R9 领域能力（评审 P1 落点），纳入本 change，与上述 R3-R6 排除不冲突

## Decisions

**D1. 类型库后端先行，前端对接**：先实现 TypeDef/TypeRepository/`/api/types`/依赖图（迁移脚本为一次性工具，2026-08-31 已退役删除），再改前端。理由：设计稿的引用语义依赖类型库真实存在；避免前端先写死演示数据。备选（前端先行）被否：无法端到端验证引用。

**D2. `element_type` + `element_type_ref`（评审 P1）**：vector 用 `element_type`（标量）或 `element_type_ref`（具名类型）表达元素，所有层（YAML/FBS/二进制/Excel/API/编辑器）复用同一解析函数。备选（复用 `type_ref` 表达元素）被否：语义混乱。

**D3. 类型命名 = 全局名称分配（评审 P0）**：迁移（已完成，脚本已退役）不直接采用原字段名做类型名；先扫描全部表字段名，冲突时生成稳定替代名（如 `ItemRarity`）或报错。撞名不变量在加载时统一校验（`conventions.py` 检查时机前移）。

**D4. 模态导航栈：纯 Vue 响应式（2026-08-31 修订，弃用 History 状态机）**：按 `modal-stack-architecture.md` 实现 `routes[]+index` 状态模型与命令式 API（openTypeModal/pushTypeView/goCrumb/goBackType/cancelTypeModal/saveType/closeTypeModal）。**修订**：原「History 按评审 P1：仅打开根/下钻 pushState，取消/保存返回与关闭走 `history.back()`，面包屑 `history.go(n)`，草稿 replaceState」已弃用——多态间来回跳转时 popstate 反复恢复与响应式渲染叠加触发死循环（模态关不掉/回跳异常）。改为类型模态完全由 Vue 响应式状态驱动（`typeNav.routes[]+index` 单一数据源），不写浏览器历史、不监听 popstate；草稿快照经 `typeSnapshots` 存于 data。浏览器物理返回键不参与模态内导航，关闭模态不污染历史。

**D5. 类型胶囊 + pick 模态（设计稿定稿）**：行内类型控件 = 固定宽类型名（具名类型即 link，点击打开类型查看模态）+ pick 按钮一组；pick 模态分组（基础 6 网格 / 类型库可滚动列表含注释与模块）/ 搜索 / 模块筛选 / 数组标记联动（勾选 = `元素[]`，无独立元素选择器；元素为具名 struct 强制定长）。**2026-08-31 补**：pick 打开时按需加载类型库（`if (!this.types.length) this.loadTypes()`，从 schema/类型编辑直接进入无需先访问类型页签）；当前类型默认高亮（基础类型 chip 高亮靠 `.chip.active`，具名类型行靠 `.fe-row.active`）。备选（下拉两级菜单）被用户否决（类型多下拉不好选、宽度不齐）。

**D6. 状态 tags 只读镜像**：行级 tag（🔒主键/🔒CodeName/🌐i18n/🖥server_only/🗂按品类/🔗ref）由 ⚙ 展开区 checkbox/ref 下拉驱动显隐，tag 不可交互；i18n⇄server_only 互斥、i18n 仅 string 在前端与后端都约束。

**D7. API 对接**：`_field_dict` 补 `type_ref`/`element_type_ref`/`fixed_length`（R3 预留）字段；`_build_schema` 入参保持 YAML 文本（前端把结构化字段数组序列化传回），后端 pydantic 校验兜底；新增 `/api/types` CRUD 与 `GET /api/types/modules`（与 `/api/schemas` 同构）。

**D8. 设计语言一致性**：新增组件类全部带 `fe-`/`tp-`/`tag-`/`list-` 前缀，公共类与 web 面板逐字对齐（`.modal-mask` 等不得改写基础定义，动画挂 `.modal-anim` 新类）；焦点环/按压反馈/模态过渡/空态按设计稿 R9.7 实现，`prefers-reduced-motion` 降级。

**D9. 保存/取消统一回上一级只读查看 + 模态无 ✕ 按钮（2026-08-31 用户要求）**：
- 编辑界面（类型编辑 / 编辑表）若从只读查看界面进入（表详情、类型查看态），保存与取消都应回到该只读查看界面，而非关闭整个链路/模态
- 类型模态：view 态 footer `[关闭, 编辑]`，edit 态 `[取消, 保存类型]`；单层编辑态取消/保存都回只读查看态（`r.mode='view'` + 重载最新），嵌套层回退一层，create 保存后关闭；**无 ✕ 右上角按钮**
- 编辑表：`editFromDetail` 记录是否从表详情（只读查看）进入；保存（`saveSchema`）与取消（`cancelEdit`）都回表详情并重载（`_reloadSchemaDetail`），直接编辑（列表行「编辑」）保存/取消才关闭
- **全部 7 处模态 ✕ 按钮移除**（类型 / 选择翻译表 / 进度 / compact / 表详情 / 类型 pick / 删除表），统一 footer 取消/关闭；Esc 走 `closeTopModal` 统一关闭栈

## Risks / Trade-offs

- [fbs 真名生成影响 golden 测试与已部署产物] → 迁移（一次性，已完成）与 golden 更新同步做，导出产物命名变化明确为 BREAKING（proposal 已标）
- [类型库迁移冲突（P0）] → 全局名称分配先于写入；冲突报错给可读提示（迁移已退役，语义由加载时撞名校验承接）
- ~~[History 状态机跨浏览器差异（popstate 时序）]~~ **2026-08-31 已消除**：History 状态机已弃用（死循环），类型模态改纯 Vue 响应式，不涉及浏览器历史/popstate 时序；模态内导航以 CDP 真实操作路径验收
- [前端结构化编辑器改动面大（app.js 906 行）] → 分页签增量落地：先类型库页签（独立），再表格管理编辑模态改造；公共类不改动控制回归面
- [`--update-header` 布局变化静默错列（评审 P1）] → 本 change 仅要求编辑器保存后触发模板重建遵循既有决策矩阵；布局迁移安全属 R3 批次，非本 change 范围

## Migration Plan

0. **R2 改名前置**：`array` → `vector` 代码层全面改名（tasks group 1）+ golden 更新
1. 后端类型库（models/repository/loader/api）+ 测试 → `config/types/*.yaml` 生成；**一次性迁移脚本（migration.py + `ct migrate-types`）已执行并退役（2026-08-31 删除，一次性工具不保留）**
2. 现有 schema 迁移（内联 enum/struct → type_ref）→ fbs/accessor golden 更新；R9.3/R9.4（bool/code_name Excel 列规则与表头注解）
3. 前端类型库页签（/api/types 对接）→ 字段编辑器结构化改造（类型胶囊/pick/tags/校验）→ 表格管理页签升级
4. 回滚：schema/types 可回退到 git 基线；前端按页签灰度（类型库页签可独立上线）

## Open Questions

- 类型改名（R8 决策表）的 UI 交互（原子更新 vs 拒绝）：可推迟到 apply 阶段按实施反馈定，不影响 specs 行为契约
- 最近使用列表持久化（localStorage vs 会话内）：仅体验细节，实施时选择

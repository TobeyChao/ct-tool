## 1. R2 类型改名（array → vector，前置）

- [x] 1.1 `models.py`：类型集合与 `Literal` 改 `vector`（原 array）、`ARRAY_ELEMENT_TYPES` → `VECTOR_ELEMENT_TYPES`、struct 内禁 array 校验与 array 分支同步改
- [x] 1.2 后端类型分支：`type_traits.py`（OFFSET_TYPES/类型判断/FieldTraits 表）、`binary_writer.py`（_OFFSET_BUILDERS）、csharp/lua accessor 生成器、`excel/reader.py`、`validate/refs.py`、`web/app.py` 全部 array → vector
- [x] 1.3 前端 `app.js` 类型判断与友好标签（array → vector，标签「数组」）
- [x] 1.4 现有 `Item.yaml` 迁移（`array` → `vector`）+ 重新导表 + golden 更新 + 文档同步；验收：grep `"array"` 仅定长语义残留

## 2. 后端类型库模型与仓库

- [x] 2.1 `models.py` 新增 `TypeDef`（name/kind/values/underlying/fields/comment/module）；`FieldDef` 增 `type_ref`、`element_type_ref`、`group_key`，`element` 改名为 `element_type`（标量元素）；校验：enum 非空 values + 整数底层类型、struct 非空 fields + 仅标量/嵌套 struct、vector 元素引用存在（标量 `element_type` / 具名 `element_type_ref` 走同一解析函数）、vector 定长 `fixed_length >= 1`（正整数）
- [x] 2.2 `repository.py` 新增 `TypeRepository`（`load_all` glob `types/*.yaml`、全局 seen_names 去重、跨模块重名报错）；`create_type_repository(types_dir, fmt)` 与 `create_repository` 对称；`config.py` 增 `types_dir`
- [x] 2.3 `workspace.py` 挂载 `types: list[TypeDef]` + `type_map: dict[str, TypeDef]`
- [x] 2.4 `group_key` 模型/API 端到端（评审 P1）：FieldDef.group_key 进 schema hash（model_dump 自动）+ `_field_dict` 读回 + 校验任意类型 ✓；**二进制 groupHash 索引烘焙与 accessor ByGroupKey 生成属导出链路（fabulous-game 改动 8，design Non-Goals）——标依赖另立导出批次，不在本 change**

## 3. 加载链路：依赖图 / 环检测 / 撞名

- [x] 3.1 `loader.py` 解析字段 `type_ref`/`element_type_ref` → 查 type_map，引用缺失报错（含表字段与类型字段的全局依赖图）
- [x] 3.2 类型 struct 嵌套依赖环检测（递归 struct 环报错指明路径）
- [x] 3.3 撞名不变量前移：类型名 vs 表字段名，加载时统一校验（`conventions.py` 检查时机前移，报错提示改名）

## 4. fbs 真名与导出对接

- [x] 4.1 `export/repository.py` `_schema_fbs_text` 从「内联生成」改查 type_map 取真名（`enum Rarity` / `struct DropRange`）；`ELEM_SUFFIX` 与 `FbsConvention` 后缀常量退役
- [x] 4.2 更新 golden 测试（R2 改名后已重新生成；类型库场景 golden 随组 6 迁移验证）（test_binary_golden / test_accessor_golden：生成代码类型名变化）
- [x] 4.3 enum `underlying` 产出（fbs `enum X : <type>` 声明已落地并验证）；**二进制按底层宽度序列化与 C# 访问器枚举底层类型属生成器消费 type_map 的导出扩展（与 2.4 同类）——标依赖**
- [x] 4.4 注释进 Excel 表头注释行（字段注释已支持；新增类型注释 fallback：字段无注释且引用具名类型时回退 TypeDef.comment，已验证）

## 5. 类型库 Web API

- [x] 5.1 `web/app.py` 新增 `/api/types`（含空模块文件清理）+ 测试 CRUD（GET 列表含 module / GET 详情 / POST 创建 / PUT 更新可改 module / DELETE 被引用拒绝并列出引用处）+ `GET /api/types/modules`
- [x] 5.2 `_field_dict` 补 `type_ref` / `element_type_ref` / `fixed_length` / `group_key` / `element_type_ref` / `fixed_length` 字段（详情接口读回结构化属性）

## 6. 现有 schema 迁移

- [x] 6.1 迁移脚本（`ct/schema/migration.py` + `ct migrate-types` 命令，dry-run/--write；vector 内联 enum 元素处理；测试）：读现有 schema → 内联 enum/struct 抽出写入 `config/types/`（模块归属映射：Item.DropRange→common、Item.Rarity→common、UIConfig.Layer→ui）→ 字段改 type_ref → `array` 改 `vector`。**2026-08-31 已退役删除**（一次性工具，用户确认不保留；`ct migrate-types` 命令与 test_migration.py 已移除）
- [x] 6.2 全局名称分配（类型名 = `表+字段`，P0 撞名检查；迁移后无内联残留 + fbs 真名验证）：扫描全部表字段名，冲突时生成稳定替代名或报错（评审 P0）；迁移后导出与迁移前产物一致（仅命名变化）

## 7. 前端类型库页签

- [x] 7.1 页签入口 + 类型列表（模块分组/kind 徽章/摘要/引用计数可点）+ 模块筛选 + 搜索 + 空态（浏览器验证：Rarity/DropRange 行渲染、引用徽章、模块 pill、空态）（模块分组 / kind 徽章 / 摘要 / 引用计数可点）+ 模块筛选 + 搜索 + 空态（「暂无类型」+ 新建引导）
- [x] 7.2 类型查看模态（只读：kind/名称/模块/注释/枚举值 chips 或 struct 子字段/底层类型/引用处）（只读：kind/名称/模块/注释/枚举值 chips 或 struct 子字段/底层类型/引用处）
- [x] 7.3 类型编辑/新建模态（名称/kind 切换/enum 值 chips + 底层类型下拉/struct 子字段（字段名+类型+注释）/所属模块下拉）（名称（改名警告）/ kind 切换 / enum 枚举值 chips + 底层类型下拉 / struct 子字段（字段名+类型+注释+嵌套引用）/ 所属模块下拉 + 新增模块）
- [x] 7.4 类型删除：引用保护（API 拒绝 + 列出引用处；前端 confirm 确认）：引用保护（被引用 → 编辑模态显示保护提示与引用处；无引用 → 确认删除）

## 8. 类型模态导航栈（纯 Vue 响应式；2026-08-31 弃用 History 状态机）

- [x] 8.1 `routes[]+index` 状态模型 + 命令式 API（openTypeModal/pushTypeView/goCrumb/goBackType/cancelTypeModal/saveType/closeTypeModal）+ 面包屑（Vue 响应式）
- [x] 8.2 **History 状态机（评审 P1）2026-08-31 弃用**：早期实现「仅前进 pushState，回退/关闭 history.back()/go() + popstate 恢复」，多态来回跳转时 popstate 反复恢复与响应式渲染叠加触发死循环——已删除 popstate 监听与 `_typeNavState`/`history` 依赖，改纯 Vue 响应式（`typeNav.routes[]+index` 单一数据源 + `typeSnapshots` 草稿快照 `_restoreRoute` 恢复）；浏览器物理返回键不参与模态内导航，关闭不污染历史
- [x] 8.3 取消/保存层级语义：中间层取消只回退一层（链保留、父层编辑态不丢）；**单层编辑态取消/保存回只读查看态（mode=view + 重载最新，2026-08-31 统一「回上一级只读查看」）**；create 保存后关闭
- [x] 8.4 模态焦点管理（打开/下钻后焦点移入模态；关闭恢复触发元素）

## 9. 字段编辑器改造（R9 设计稿）

- [x] 9.1 字段行布局：类型胶囊（固定宽类型名 + pick 按钮一组）+ 字段名 + 状态 tags + ops 右对齐（固定宽类型名 + pick 按钮一组）+ 字段名（左对齐，锁定行一致）+ 状态 tags + ops 右对齐
- [x] 9.2 类型 pick 模态：基础类型网格 / 类型库列表（注释+模块）/ 搜索（含模块匹配）/ 模块筛选 / 数组标记联动（勾选=`元素[]`；元素为具名 struct 强制定长）。**2026-08-31 补**：打开按需加载类型库（未访问类型页签也显示，`if(!types.length) loadTypes()`）+ 当前类型默认高亮（基础 chip `.chip.active`、具名行 `.fe-row.active`）；最近使用未落地（待决策，见 design Open Questions）
- [x] 9.3 字段名 inline edit（字段行直接编辑）+ 空名/重名/PascalCase 校验（保存前拦截）（点击编辑/失焦回车保存/Id/CodeName 锁定）+ 空名「未命名字段」占位可再编辑
- [x] 9.4 ⚙ 详情展开区：enum/struct 引用只读预览 / vector 长度模式（变长/定长 + fixed_length>=1 校验）/ 属性行（i18n、server_only、按品类、ref、注释）：enum/struct 引用只读预览（chips/子字段 + 查看入口）/ vector 元素 + 长度模式（定长输入 N≥1 校验）/ 属性行（i18n、server_only、按品类查询、ref 表名下拉、注释；separator 不展示）
- [x] 9.5 状态 tags 显隐联动（🔒主键/🔒CodeName/i18n/server/按品类/🔗ref 由字段状态驱动）+ i18n 仅 string 禁用（⚙ checkbox/ref 驱动）+ i18n⇄server_only 互斥 + i18n 仅 string 禁用
- [x] 9.6 校验：字段名空/重名/PascalCase/主键保护（保存前全量校验 + showError 汇总）、主键删除保护、保存全量校验汇总错误条、打开复位
- [x] 9.7 保存/取消回上一级只读查看 + 模态无 ✕（2026-08-31）：全部 7 处 `modal-close` ✕ 移除，取消/关闭统一 footer；类型模态 view `[关闭,编辑]` / edit `[取消,保存类型]`（单层编辑取消/保存回查看态 `_loadTypeIntoDraft` 重载）；编辑表 `editFromDetail` 记录来源，保存（`_reloadSchemaDetail`）/ 取消（`cancelEdit`）回表详情；Esc 走 `closeTopModal` 统一关闭；类型胶囊 tp-name 截断（`.type-pill .tp-name` display:block + ellipsis）

## 10. 表格管理页签升级与对接

- [x] 10.1 表 CRUD 对接结构化编辑器（openEdit/saveSchema 结构化字段数组 → fields_yaml；删除确认模态；后端校验错误 showError 回显）（openEdit/saveSchema 改传结构化字段数组；删除确认模态 + 空态；后端 `_build_schema` 校验错误回显）
- [x] 10.2 与类型库联动：字段引用类型胶囊点击打开类型查看模态（openTypeModal）：字段引用类型处「查看↗」/类型名 link 打开类型查看模态

## 11. Excel 列规则与表头注解（R9.3 + R9.4）

- [x] 11.1 `type_traits.py` `_coerce_bool` 增 ✓/✗（0/1 已支持）；`validate_field_value` bool None → false（测试） 增 ✓/✗（0/1 已支持）；`validate_field_value` bool 分支 None → false（默认不填不报错）
- [x] 11.2 `excel/template.py` bool 列 DataValidation `"✓,✗"`（allow_blank）+ `vector<bool>`（测试） `"✓,✗"`（allow_blank）；`vector<bool>` 同样支持 ✓/✗ 与 0/1
- [x] 11.3 code_name 唯一性：CodeName 列 COUNTIF 自定义公式（模板生成）+ 导出校验（测试）：导出时校验重复 + Excel 列 COUNTIF 自定义公式（保存时可做则做）
- [x] 11.4 表头注解：`ref:表名` / 具名类型名 / `元素[]`；bool 注解保持 `bool`（测试）：`_annotation_scalar` ref → `ref:表名`、`_annotation_enum` → 类型名、`_annotation_array` → `元素[]`；bool 注解不提示 ✓/✗（保持 `bool`）

## 12. 设计优化与一致性

- [x] 12.1 空态（表格/类型库）+ 键盘焦点环（:focus-visible）+ 按压反馈（:active）+ 模态过渡（mask-fade/modal-pop + reduced-motion 降级）（表格/类型库/pick 搜索无结果）；键盘焦点环（:focus-visible）；按压反馈（:active）；模态过渡（.modal-anim + reduced-motion 降级）；对比度 AA（tag 色对齐 web）
- [x] 12.2 新增类带 fe-/tag- 前缀；公共类基础定义不改（动画挂 .modal-mask 自身，web 端无外部对齐约束）（新增类带 fe-/tp-/tag-/list- 前缀；不得改写 .modal-mask 等基础定义）

## 13. 测试与验收

- [x] 13.1 后端测试：TypeDef 校验/fixed_length/跨模块重名/引用缺失/struct 环/撞名//api/types CRUD/迁移幂等/fbs 真名 golden/R2 回归/bool ✓✗/COUNTIF/annotation（203 全绿）：TypeDef 校验（含 fixed_length>=1）/ 跨模块重名 / 引用缺失 / struct 环 / 撞名 / /api/types CRUD / 迁移脚本幂等（2026-08-31 随迁移脚本退役，test_migration.py 已删）/ fbs 真名 golden / R2 改名回归 / bool ✓/✗ 与 code_name 唯一性
- [x] 13.2 前端验收：类型库列表/pick 模态/胶囊/tags/导航栈/空态（浏览器编译+列表渲染验证；交互逻辑与 mockup 同构）（对照 specs 场景）：9 种类型结构化编辑、类型胶囊对齐、pick 搜索/模块/数组联动、tags 联动、空态、模态栈导航（CDP 真实操作路径：下钻/取消/保存/关闭、单层编辑回只读查看）、空名再编辑、模态焦点管理。**2026-08-31 补 CDP 验证**：pick 模态类型库按需加载 + 当前类型默认高亮
- [x] 13.2b 端到端验收：迁移后 type_ref 字段 Excel→校验→JSON→FBS→Binary 全链路（test_migrated_export_pipeline）：web 保存 schema 后触发导出成功、C#/Lua accessor 正确生成（覆盖含类型引用与 vector 的字段）
- [x] 13.3 评审落点复查：P0 名称分配✓、P1 element_type 契约✓、P1 History✓（**2026-08-31 弃用 History 状态机，改纯响应式**）、P1 code/group（模型/API✓，groupHash 索引标依赖）、P1 依赖图✓、P1 update-header（✅ 已决策：不拒绝）、P2 fixed_length>=1✓、P2 struct 断言（R5 批次依赖）：P0 类型命名、P1 element_type/element_type_ref 统一契约、P1 History 状态机（2026-08-31 弃用改纯响应式）、P1 code/group 端到端（模型/哈希/API/生成器）、P1 依赖图/环检测、P1 update-header 静默错列（✅ 已决策：列表头变化一律不拒绝、保留数据，2026-08-30，本 change 复核）、P2 fixed_length>=1 与 struct 空值契约、P2 struct 大小断言忽略对齐（R5 批次，非本 change，标记依赖）

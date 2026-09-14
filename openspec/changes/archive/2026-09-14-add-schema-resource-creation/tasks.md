## 1. 前置与命令契约

- [x] 1.1 确认 simplify-schema-yaml-save 已完成并采用其 candidate/save、Schema revision 和共享发布入口；以相关保存回归测试通过、旧计划链路不再被本功能调用为验收。
- [x] 1.2 实现三类 add_resource 的结构化 JSON 解码与领域模型转换，统一 candidate/save 路径；用真实 API JSON 测试三类成功输入及未知 kind、未知键、缺失内容、非法类型、非对象 Enum 项的定位错误。
- [x] 1.3 接通 reducer 的资源新增和 Table 索引初始化；通过重放、重复新增拒绝、撤销重做以及新增后编辑索引的单元测试。

## 2. 候选、净差异与保存

- [x] 2.1 完整候选纳入新资源依赖与名称校验；测试同草稿 Enum→Record→Table、对新 Table 的 ref、缺失引用、依赖环、跨类别重名和生成名称冲突。
- [x] 2.2 完善新增→编辑→改名、新增→删除以及已有资源引用新增资源的净差异；验证最终新增计数、最终文件名、归零 no-op 不写文件且保留历史。
- [x] 2.3 将新资源路径绑定配置 schemas/types 目录，补充路径和大小写碰撞、Table Excel 目标冲突及发布前目标存在性校验；验证自定义目录保存与重新加载，冲突不覆盖外部文件。
- [x] 2.4 验证多资源新增经共享事务保存和恢复：FilePublisher 已在 `_restore` 中删除本次新建目标（`publication.py` 的 `entry.existed == False` 分支）并支持 `OP_DELETE`，因此本任务只需接入并验证，不必新建回滚语义；注入首个新文件发布后的异常与进程中断，断言旧文件恢复、新文件无残留、恢复幂等及无业务范围外文件变化。

## 3. 创建表单与资源视图

- [x] 3.1 增加头部、分组及空状态创建入口，统一三类表单；浏览器验证折叠面板和空工作区可用，Table 固定 Id，Record/Enum 无有效首项不可提交。
- [x] 3.2 接通类型选择、注释、局部校验与服务端预检，防重复提交和旧响应回写；验证非法名称/冲突保留输入、取消不增加命令、成功只增加一次创建命令。
- [x] 3.3 统一资源树、计数、过滤、Quick Open、类型/ref 选择与反向引用的候选来源；浏览器验证无需中间保存即可创建并引用三类资源，Table 不作为具名类型出现。
- [x] 3.4 接通选中新资源、过滤可见性和失效选择回退，复用 IndexedDB 历史与 cursor；验证撤销创建、重做、改名、删除、刷新恢复以及不支持命令时保留草稿。

## 4. 保存后流程与闭环验收

- [x] 4.1 接通新 Table 保存后模板状态与针对该表的生成入口；验证未保存禁止生成、Record/Enum 无独立模板操作、模板失败与保存成功分别显示且可以重试。**完成**：未保存 Table 显示「…尚未保存：保存后才能生成模板」且无模板按钮；保存后按服务端状态给「更新模板」入口；模板失败走独立 `templateError` 横幅（带「重试」），不回滚已保存的 YAML。测试：`tests/web/test_schema_create_browser.py::test_unsaved_table_explains_template_requires_save`、`::test_record_and_enum_have_no_template_entry`。
- [x] 4.2 **完成**：`tests/app/test_add_resource_workflow.py::test_create_related_resources_then_template_data_and_export` —— 真实 API 建 Enum→Record→Table 并保存；已有表 Item 引用新增 Enum 后**导出被读取闸门拒绝且 manifest/产物/账本均未变**；显式 gen-template + 写数据 → `canonical_validate` 干净 → 导出成功；断言 JSON 精确值（含嵌套 Record）、`types.fbs` 的 `enum ItemRarity : byte`/`table DropReward`、Bundle 内新表 bytes 解码值（Id=1/ordinal=1/Reward{3,5}）、C#/Lua Accessor 与共享 Enums 文件。
- [x] 4.3 **完成**：`::test_unreferenced_types_reload_and_export_gate`（未被引用的 Record/Enum 保存后重载可见且不影响既有表导出）；`::test_new_table_regressions_ref_i18n_server_only_and_codename`（新表同时带 CodeName 索引 + i18n + server_only + ref：server_only 不进客户端 FBS、次语言包只有 `Quest_i18n` 稀疏表、Accessor 含 `ByCodeName`；外键越界导出失败且 manifest/产物/账本逐字节不变）。模板缺失/不兼容拒绝导出见 4.2 与 `tests/app/test_add_resource_paths.py`；已有 Excel 无损预检见 `::test_existing_workbook_for_a_new_table_is_reported_as_a_note`。
- [x] 4.4 **完成**：`tests/web/test_schema_create_browser.py`（11 例）覆盖空工作区创建、分组预选、三类最小表单、预检失败保留输入、双击只加一条命令、跨资源创建与引用、选中/撤销回退/刷新恢复；`::test_create_flow_keyboard_and_narrow_viewport` 在 390×844 纯键盘走完入口→表单→Esc 取消→创建，断言初始焦点在名称框、取消不留命令、无横向溢出。既有尺寸/缩放矩阵由 `tests/web/test_matrix_browser.py`、`test_browser_baseline.py`、`test_shell_browser.py`、`test_module_pages_browser.py` 覆盖（本轮全绿）。
- [x] 4.5 **完成**：`ct/docs/README.md` 新增「Schema 工作台：新增资源与保存」（草稿→保存→模板→导出的边界表 + 三类 add_resource 命令、`/candidate` 预检、`/save` 与 `/gen-template` 示例），并修正「Schema 编辑与导出发布不是同一事务协议」这条**已被 simplify 变更改写**的陈述。**测试结果**：`pytest tests -m "not browser"` → 687 passed；browser 标记 21 passed；schema 编辑器 + 创建浏览器用例 47 passed；`gd/` 哈希前后一致；`openspec validate add-schema-resource-creation --strict` 通过；归档合并演练（/tmp 副本）成功（ADDED-only）。

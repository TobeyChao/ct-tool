## 1. Schema 基线与净差异

- [x] 1.1 建立独立 Schema revision，覆盖配置原始字节、实际资源路径与目录成员，读取前后复核；测试外部 YAML 新增/删除/格式修改及配置变更导致冲突，Excel/i18n 变化不改变基线。
- [x] 1.2 实现基线到最终候选的规范化净差异与 rename 身份追踪；测试 CodeName 往返、重复属性编辑、A→B→C/A→B→A、增后删、引用连带修改及 Enum 顺序，断言资源数和最终摘要。
- [x] 1.3 统一 candidate 结构校验、candidateHash 与净差异响应；测试非法角色/依赖环/引用声明阻塞，命令次数不影响 dirty，默认值和对象键序不制造差异。

## 2. YAML 保存事务与 API

- [x] 2.1 抽取复用工作区锁/恢复入口，恢复先于 Schema 加载，统一 save/export/deploy busy 行为；以并发请求和发布中断后重新加载测试验证，无嵌套加锁。
- [x] 2.2 实现差异 YAML 文件集合及 FilePublisher 发布，使用资源来源和配置目录处理新增、删除、重命名和引用更新；测试自定义目录/来源文件名、重命名目标冲突、删除旧文件及未变文件字节/mtime 保留。
- [x] 2.3 实现 save API 的基线/candidateHash 复核、结构校验、no-op 和新 snapshot 响应；测试伪造候选、外部变化、错误重试及 schema 成功但 Excel 缺失/脏数据不阻塞保存。
- [x] 2.4 验证保存发布的边界与失败原子性；快照比对 Excel、manifest、i18n、output、成功账本不变，注入多文件新增/替换/删除中断并验证完整恢复与草稿错误响应。
- [x] 2.5 增加隔离的旧 Apply journal 检测/恢复适配；测试 committed 收尾、未完成但材料完整的恢复及信息不足时阻止写入且保留材料，旧 apply.lock 不作为永久忙碌依据。

## 3. 前端草稿与保存体验

- [x] 3.1 升级 IndexedDB 草稿格式以存储 cursor 和 Schema 基线；浏览器测试刷新后撤销/重做分支一致、数据变化不丢草稿、冲突和旧格式保留查看入口、持久化失败警告持续可见。
- [x] 3.2 草稿条切换净变化资源数、最终差异摘要和「保存变更」；浏览器测试 CodeName 来回切换与 rename 往返归零仍可撤销，无历史时隐藏，净变化为零时保存禁用。
- [x] 3.3 接入单次 save，淘汰迟到候选响应并冻结保存期间的草稿修改，使用成功 snapshot 更新基线；测试忙碌、失败保留草稿、成功清空本次历史、状态刷新失败不误报保存失败。
- [x] 3.4 移除强制计划弹窗、TTL、产物重建清单和嵌套删除预览，保留删除/放弃确认与结构警告；检查键盘焦点、移动布局以及所有旧「审查并应用」用户文案引用。

## 4. Excel 独立操作边界

- [x] 4.1 在共享 preparation 接入读取兼容性检查，覆盖可信 manifest、受管工作簿表头与当前 layout；测试相同类型列重排、字段改名、嵌套深度/vector 槽位改变、manifest 缺失或与工作簿不符时读前失败。
- [x] 4.2 接通 validate/export 及其 ref 依赖表的同一闸门；测试过滤导出也检查实际读取依赖、失败不刷新 manifest/产物/成功账本，注释或索引变化且读取结构兼容时仍可校验，额外尾列维持警告。
- [x] 4.3 将数据迁移预检归属明确为显式 gen-template，补齐无可靠 rename 映射时的拒绝行为；用已保存 A→C 且旧 A 非空的工作簿证明不猜测、不写回，既有稳定路径无损更新测试继续通过。
- [x] 4.4 保存后刷新受影响模板状态并展示独立更新入口；浏览器验证只读状态刷新不触发模板重建、无漂移不虚报、源 YAML 删除不会删除 Excel 或旧产物。
- [x] 4.5 在共享数据校验新增 Enum token 域闸门（scalar、定长槽位与变长 vector 元素），并让 Binary serializer 不再把未知 token 落到 ordinal 0；测试已删除 token 在 validate/export 被拒且不落产物、位置定位到行列与原始值、合法 token 与未使用 Enum 的表不受影响。

## 5. 切换与整体验收

- [x] 5.1 前后端同步删除 change-plan/prepare-apply/apply 的创建与执行链路、旧计划 TTL 和重复锁发布逻辑，只保留必要的旧事务恢复适配；搜索确认无正常调用路径残留并验证旧端点不再执行写入。
- [x] 5.2 更新 Schema 编辑、API、模板更新与操作说明；检查文档明确「保存只改 YAML」「历史不等于净差异」「模板更新独立且不猜测迁移」，不再承诺全链路 Apply。核对本变更涉及的 11 个能力：归档后主规格不得再出现 `Change Plan`/`Apply`/`变更计划`/`应用变更` 等指向已删除机制的措辞（`cli-interface` 的「迁移计划」指 gen-template 无损预检，保留）。
- [x] 5.2b 归档后手工修正 `openspec/specs/schema-editor/workspace-draft/spec.md` 的 Purpose（工具会忽略已有规格的 delta Purpose，这一处只能直接改主规格）。**完成**：2026-09-14 归档后已改写为「Workspace Draft、候选工作区与 YAML-only 事务化保存」；`grep` 复核 21 份主规格已无 `Change Plan`/`Apply`/`变更计划`/`应用应用` 残留（`cli-interface` 的「迁移计划」指 gen-template 无损预检，保留）。
- [x] 5.2c 编写 delta 时保留每个 MODIFIED requirement 的**全部现有场景名**：归档会核对该 requirement 的场景集合，缺失任意场景名会直接失败（`current spec contains scenario(s) not present in the modified block`）。需要改名的场景只能走 REMOVED + ADDED 换 requirement。
- [x] 5.3 跑完整 pytest 与相关 Playwright 浏览器测试，串联编辑→保存 YAML→模板不兼容拒绝导出→显式处理模板→导出成功；记录结果，并确认无真实 gd 工作簿被测试改写。
- [x] 5.4 运行 OpenSpec strict 校验并核对全部场景对应测试或操作验证；交付回滚说明及旧事务材料处置说明。**结果**：`openspec validate --changes --strict` → add-schema-resource-creation ✓、simplify 已归档；`openspec validate --specs --strict` → 19/21 通过，仅剩 `i18n-pipeline`、`json-single-line-records` 两个**改动前就存在**的失败（本变更顺带修好了 `incremental-export` 的旧失败）；`openspec validate --archived` → 本变更任务全勾。回滚与材料处置说明：`ct/docs/schema-save-migration.md`。场景→测试对照：读取闸门/依赖闭包/尾列警告 → `tests/app/test_reading_compat.py`；Enum token 域 → `tests/app/test_enum_token_gate.py`；净差异与 rename 身份 → `tests/app/test_schema_net_diff.py`；差异发布与失败原子性 → `tests/app/test_schema_save.py`、`test_schema_save_atomicity.py`；save API 冲突/忙碌/重试 → `tests/web/test_schema_save_api.py`；草稿 v2 与草稿条净差异 → `tests/web/test_schema_editor_browser.py`；旧材料处置 → `test_schema_save_atomicity.py`；编辑→保存→闸门→显式更新→导出 → `tests/app/test_schema_save_workflow.py`。全量：pytest 640 passed（非 browser）+ 21 浏览器标记用例 + 36 schema 编辑器浏览器用例，且 `gd/` 文件哈希前后一致。

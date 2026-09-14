# schema-editor/workspace-draft Specification

## Purpose
定义 Schema 编辑从已落盘快照到 Workspace Draft、候选工作区与 YAML-only 事务化保存的事务边界：命令历史可逐步撤销/重做，未保存状态按原始结构与最终候选的净差异判断，保存只在共享工作区事务内发布实际变化的资源 YAML，并保证失败时不会留下部分更新的工作区。

## Requirements

### Requirement: Workspace-scoped draft commands
所有 Schema 编辑 SHALL 先记录为 Workspace Draft command，不立即写 YAML、Excel 或导出产物；Draft SHALL 支持逐步 undo、redo、撤销当前字段修改和放弃全部，并独立于页面与 pane 生命周期。操作历史 SHALL 保留用户步骤，未保存状态 SHALL 根据原始结构与当前候选的最终语义差异判断，不按命令数量判断。

#### Scenario: Undo a resource rename
- **WHEN** 用户改名 Record 后执行 undo
- **THEN** Record 名称及该 command 引起的引用更新一起恢复，其他未撤销 command 保留

#### Scenario: Switch resources with pending changes
- **WHEN** Item 有未保存修改且用户切换到 Quest
- **THEN** 修改继续存在于工作区草稿，摘要显示最终受影响资源

#### Scenario: CodeName round trip
- **WHEN** CodeName 原本关闭，用户开启后又关闭
- **THEN** 两步历史可逐步撤销，最终差异为零且无需保存

#### Scenario: Rename chain is summarized by final identity
- **WHEN** 用户对同一字段连续执行 A→B→C
- **THEN** 历史保留两步，净差异显示 A→C；再改回 A 时该字段差异归零

#### Scenario: Added resource is deleted before save
- **WHEN** 用户新建资源后删除该资源且最终工作区与基线一致
- **THEN** 净差异为零，不写任何业务文件，历史仍可撤销/重做

### Requirement: Durable browser draft persistence
Web Panel SHALL 将带格式版本、Schema 基线、完整命令历史和 undo cursor 的 Draft 存入 IndexedDB，并按工作区隔离；localStorage SHALL 只存小型偏好。持久化失败 SHALL 保留当前内存 Draft 并显示持续警告。Schema 基线冲突或旧格式无法可靠恢复时 SHALL 保留可查看的草稿并明确提示，不静默丢弃或应用。

#### Scenario: Restore a matching draft after refresh
- **WHEN** 页面刷新且工作区、格式及 Schema 基线匹配
- **THEN** 恢复原命令、cursor、净差异和重做分支，不重新执行已撤销步骤

#### Scenario: Browser storage quota fails
- **WHEN** 写入 Draft 因配额、权限或数据库错误失败
- **THEN** 当前编辑保留在内存且草稿区持续显示警告

#### Scenario: External data does not invalidate draft
- **WHEN** Excel 或翻译文件变化而 Schema 基线未变化
- **THEN** 草稿仍可恢复和保存，不被自动清空

#### Scenario: Incompatible draft is preserved for inspection
- **WHEN** 旧草稿不含可恢复 cursor 或 Schema 基线已冲突
- **THEN** 显示恢复限制并保留草稿查看入口，禁止静默按全部命令应用

### Requirement: Candidate workspace validation
保存变更 SHALL 对完整候选执行名称、类型、字段角色、索引声明、依赖环及引用声明等 Schema 校验。保存 SHALL NOT 读取 Excel 数据进行主键、外键值或转换校验，也 SHALL NOT 调用导出生成器；局部编辑合法不替代完整结构校验。

#### Scenario: Cross-resource validation failure
- **WHEN** 单个字段合法但完整候选形成资源依赖环
- **THEN** 保存失败并显示循环路径，不修改 YAML，草稿保留

#### Scenario: Missing or invalid data does not block structural save
- **WHEN** 候选结构合法但 Excel 缺失、被占用或包含无效外键值
- **THEN** YAML 可保存，Excel 不被读取校验或修改，数据问题留给独立操作

### Requirement: YAML-only transactional save
保存 SHALL 只新增、修改或删除配置指定目录内实际变化的资源 YAML；资源重命名及引用更新 SHALL 一起提交。未变化 YAML SHALL 保持字节与 mtime，Excel、layout manifest、翻译文件、导出产物及成功账本 SHALL 保持不变。必要的私有锁、暂存和恢复材料不属于业务写入。保存成功 SHALL 返回新快照及净变化摘要；零差异请求 SHALL 不改业务文件。

#### Scenario: Rename and delete are reflected on disk
- **WHEN** 用户保存资源重命名和删除
- **THEN** 新 YAML、引用更新和旧 YAML 删除一起发布，旧 Excel 和产物不被删除

#### Scenario: Configured source paths are honored
- **WHEN** 工作区使用自定义 Schema 目录或现有资源来源文件名
- **THEN** 保存使用实际配置和资源文件路径，不在默认目录创建重复资源

#### Scenario: Save succeeds without generator execution
- **WHEN** 修改一份合法 YAML 并保存
- **THEN** 仅实际变化 YAML 更新；生成器未执行，其他业务文件字节与 mtime 不变

#### Scenario: No-op does not rewrite YAML
- **WHEN** 最终候选与基线语义相同
- **THEN** 保存返回无变化，原 YAML 排版和 mtime 不变

### Requirement: Schema save concurrency and recovery
保存 SHALL 验证调用方 Schema 基线和候选内容与实际读取输入一致；基线 SHALL 覆盖源配置及资源文件内容和目录成员，不包含 Excel/i18n/output。冲突 SHALL 拒绝覆盖并保留草稿。保存与同工作区导出/部署 SHALL 互斥，并在加载工作区前恢复未完成发布；失败或恢复后不得留下长期混合版本。不能可靠恢复的旧事务 SHALL 阻止新写入并保留材料。

#### Scenario: Schema changes before save
- **WHEN** 另一进程新增、删除、修改 YAML 或变更源配置后用户保存旧草稿
- **THEN** 返回冲突，不覆盖外部修改、不丢弃草稿

#### Scenario: Candidate hash mismatch
- **WHEN** 提交的候选标识与服务器从命令构建的候选不一致
- **THEN** 保存被拒绝，不写任何 YAML

#### Scenario: Concurrent workspace mutation
- **WHEN** 同一工作区正在导出或部署时另一个请求保存 YAML
- **THEN** 返回工作区忙碌，不同时发布两套文件

#### Scenario: Process interruption during publish
- **WHEN** 保存新增、替换和删除多个 YAML 时进程中断
- **THEN** 恢复到完整旧版本或完整已提交新版本后再加载，不残留半次新增或删除

#### Scenario: Failed save preserves editing history
- **WHEN** 保存因校验、冲突、权限或发布失败
- **THEN** 错误持续可见，命令、cursor 及净差异保留供修正或重试

### Requirement: Structured resource creation commands
新增资源 SHALL 使用可 JSON 序列化的 `add_resource` 草稿命令，明确区分 Table、Record、Enum，服务端 SHALL 验证类别、内容、字段类型及枚举项对象结构并拒绝未知属性和非法输入，返回可定位问题而非内部异常。新增命令 SHALL 支持确定性重放、undo/redo 和按工作区、Schema 基线及 cursor 恢复。

#### Scenario: Reject malformed creation payload
- **WHEN** API 收到未知类别、缺失内容、非法类型表达式或字符串形式的 Enum 值列表
- **THEN** 返回结构化客户端错误和对应命令/字段位置，不写文件，不返回由模型解码缺失引起的 500

#### Scenario: Restore creation after refresh
- **WHEN** 用户创建资源并修改其字段，撤销最后一条修改后刷新页面且 Schema 基线未变
- **THEN** 新资源、命令历史与 cursor 一致恢复，被撤销修改不重新执行

### Requirement: Validate creation against the entire candidate
在 `simplify-schema-yaml-save` 的完整候选结构校验之上（该变更负责名称、类型、字段角色、索引声明、依赖环与引用声明的通用校验），新增资源 SHALL 额外覆盖跨类别重名、生成名称冲突与重复命令不产生同名副本：保存前 SHALL 在整个候选资源集中校验名称唯一性、生成名称冲突、具名类型、ref、索引、字段约束和依赖环，包括新增资源与已有资源之间的引用以及同一草稿内新资源之间的引用。不合法候选 SHALL 不可保存，浏览器草稿保留以供修复；本变更不重复定义通用校验规则，只声明新增资源必须满足的额外约束。

#### Scenario: Save related additions together
- **WHEN** 新 Table 引用同一草稿新 Record，而该 Record 引用同一草稿新 Enum，全部结构合法
- **THEN** 三者可在同一次保存中落盘并重新加载为正确资源图，不要求提前逐个保存依赖

#### Scenario: Missing or cyclic dependency
- **WHEN** 新字段引用不存在的类型或候选 Record 之间形成循环
- **THEN** 保存被阻止，问题定位到相关资源/字段并展示循环路径或缺失目标，已有文件不变

### Requirement: Creation net differences follow final resource state
草稿净差异 SHALL 将新增及后续编辑归为同一个新增资源，将新增后的连续显式重命名归为最终名称的新增；新增后删除且没有其他净修改 SHALL 归零，保留撤销重做历史。已有资源引用新增类型的修改 SHALL 单独计入变化资源。

#### Scenario: Create rename and save
- **WHEN** 用户新增 Reward、添加字段后改名 DropReward 并保存
- **THEN** 摘要只显示最终新增 DropReward，磁盘只创建最终路径，引用保持一致

#### Scenario: Create then delete
- **WHEN** 用户创建后删除同一资源且候选恢复原始结构
- **THEN** 显示无未保存修改，保存禁用，直接请求无变化保存不创建 YAML，历史仍可撤销重做

### Requirement: Safe transactional creation of YAML resources
新增资源 SHALL 遵守 YAML-only 保存协议和共享恢复事务，Table 写入配置的 schemas 目录，Record/Enum 写入配置的 types 目录，文件名由合法资源名称生成。保存 SHALL 校验目标路径、目录成员变化及目标文件冲突，禁止路径逃逸、覆盖未纳入本次合法变更的已有文件或制造不区分大小写平台上的路径碰撞；失败 SHALL 保留草稿并恢复一致文件集，包括撤销本事务已发布的新文件。

#### Scenario: Save to configured directories
- **WHEN** schemas/types 使用自定义目录且用户保存三类新增资源
- **THEN** 仅在对应目录创建各自 YAML，重新加载内容一致，既有未修改文件字节与 mtime 保持不变，Excel、manifest、i18n、output 和成功账本不变

#### Scenario: Concurrent target creation
- **WHEN** 草稿创建后另一个进程添加了同名目标 YAML
- **THEN** 保存返回冲突且不覆盖外部文件，不静默改变资源名称，草稿保留

#### Scenario: Path and case collision
- **WHEN** 请求包含越界名称或目标与另一资源路径仅大小写不同
- **THEN** 校验拒绝请求并定位冲突，不能在不同操作系统产生不同的覆盖结果

#### Scenario: Failure after publishing one new resource
- **WHEN** 保存多个新增资源时在首个新文件发布后失败或进程中断
- **THEN** 恢复在工作区重新加载前完成；恢复旧版本时删除本事务新增文件并还原已有文件，不留下半套新资源，重复恢复结果一致

## ADDED Requirements

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

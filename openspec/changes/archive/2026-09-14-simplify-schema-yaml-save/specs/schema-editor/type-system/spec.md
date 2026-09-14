## MODIFIED Requirements

### Requirement: Named reference integrity
系统 SHALL 为 named 类型与跨表 `ref` 建立正向依赖和反向引用；删除被引用资源或字段默认阻止，改名 SHALL 作为显式命令原子更新所有引用，并在净差异摘要中按最终身份保留旧名到新名映射及生成 API 影响。

#### Scenario: Delete a referenced record
- **WHEN** 用户尝试删除仍被 Item.Rewards 与 Quest.Rewards 引用的 DropReward
- **THEN** 系统阻止删除并返回两个可定位的引用路径，不提供 cascade delete

#### Scenario: Rename a named enum
- **WHEN** 用户将 ItemRarity 显式改名为 RarityCode
- **THEN** Candidate Workspace 原子更新所有引用，净差异摘要按最终身份显示旧名到新名映射及生成 API 影响

### Requirement: Type and name constraints
资源名、字段名和生成的 FlatBuffers 类型名 SHALL 在候选工作区中执行确定性校验；Record 与 Enum 名称不得造成生成器的类型/字段撞名，错误 SHALL 在保存前报告完整冲突位置。

#### Scenario: Generated name collides with field
- **WHEN** 新 Enum 的生成类型名会与同作用域字段名冲突
- **THEN** Candidate Workspace 校验失败并列出资源、字段和冲突的生成名称，不写入任何文件

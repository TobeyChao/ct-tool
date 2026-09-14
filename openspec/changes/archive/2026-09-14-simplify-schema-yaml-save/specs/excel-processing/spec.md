## MODIFIED Requirements

### Requirement: Plan Excel data changes by stable paths
Excel 迁移预检 SHALL 仅在用户显式更新模板时执行，不属于 YAML 保存。预检 SHALL 比较可信旧布局与新布局的稳定路径，扫描删除、收缩和类型转换处的数据；无法证明无损时 SHALL 在写回前停止并保留原 Excel 与 manifest。保存后的重命名 SHALL NOT 仅凭同列位置或名称相似性推断映射，本变更不要求持久化跨保存迁移映射。

#### Scenario: Rename retains values
- **WHEN** 用户显式更新模板，涉及重命名的数据已经由用户另行处理且可按可信 manifest 稳定路径无损映射
- **THEN** 可映射数据被保留，不产生重复数据列；无法证明重命名映射时适用拒绝自动迁移场景

#### Scenario: Rename without a proven mapping
- **WHEN** YAML 中 A 已改为 C，旧 A 列有数据且模板更新没有可靠映射
- **THEN** 更新拒绝自动搬移并报告无法映射的位置，原工作簿与 manifest 不变

#### Scenario: Type conversion failure
- **WHEN** 用户显式更新 string→int32 模板且旧列含不可转换值
- **THEN** 更新列出失败位置和值并停止；之前独立保存的 YAML 不被回滚

## ADDED Requirements

### Requirement: Verify reading compatibility before data preparation
validate/export SHALL 在按当前 Schema 读取实际参与校验的工作簿（含引用依赖表）前，验证可信 manifest、工作簿受管表头结构与当前读取布局兼容。表头行数、字段路径、列顺序、类型及展开槽位不匹配，或无法可靠确定兼容性时 SHALL 阻止读取并定位需更新模板的表；SHALL NOT 通过导出刷新 manifest 掩盖不匹配。额外未受管尾列仍可警告并忽略。

#### Scenario: Same-type columns are reordered
- **WHEN** YAML 交换两个同类型字段，Excel 与 manifest 仍是旧顺序
- **THEN** validate/export 在数据解释前拒绝，不能按新顺序静默交换值

#### Scenario: Nested layout changes
- **WHEN** Record 嵌套深度或 vector 展开数量改变但模板未更新
- **THEN** validate/export 报告读取布局不兼容，导出产物、manifest 和成功账本不变

#### Scenario: Cosmetic drift remains readable
- **WHEN** 仅注释等展示内容变化且完整读取结构仍可证明兼容
- **THEN** 模板可提示 drifted，但 validate/export 不因完整 schema hash 不同而拒绝，仍执行正常数据校验

#### Scenario: Referenced workbook is incompatible
- **WHEN** 过滤导出选中表依赖的外键目标表模板不兼容
- **THEN** 闸门同样拒绝该依赖表的读取，不允许只检查显式选中表

#### Scenario: Manifest cannot prove compatibility
- **WHEN** manifest 缺失、损坏或与真实受管表头不符
- **THEN** 拒绝猜测读取并提示独立处理模板，不修改工作簿

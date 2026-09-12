## Purpose

为 ct 导出定义可恢复的文件发布边界，确保生成失败不会留下半套新产物，并明确中断恢复、取消、同工作区并发和成功账本的行为，使 CLI 与 Web 在保留各自部署策略时具有一致的本地可靠性保证。

## ADDED Requirements

### Requirement: Generation completes before publication

系统 SHALL 在选中范围的解析校验、所有产物生成及产物结构检查成功后，才修改正式输出和本次导出产生的布局 manifest。完整发布集合 SHALL 包括新增、覆盖及按原有全量清理规则应删除的文件。生成缓存与私有暂存文件不属于正式产物。

#### Scenario: Late generator failure
- **WHEN** JSON 已生成到暂存区，但随后 FBS 检查或 Bundle 生成失败
- **THEN** 正式输出和布局 manifest 的内容及 mtime 均保持原样，成功账本不变，导出失败

#### Scenario: Cancellation before publication
- **WHEN** 用户在正式发布开始前取消导出
- **THEN** 导出标记为取消，正式产物和成功账本不变

### Requirement: Publication can recover complete file sets

系统 SHALL 在可恢复的文件写入/删除错误后恢复发布前的完整集合，包括恢复旧文件、保留其 mtime、恢复被删文件和移除本次新建文件。若即时恢复失败，系统 SHALL 保留恢复材料并阻止后续 export/deploy 继续使用未恢复的集合。进程中断后，下次 export/deploy SHALL 先恢复：本地提交标记之前恢复旧集合，之后保留新集合并完成清理。恢复 SHALL 幂等；无法识别或损坏的恢复记录 SHALL 报错并保留材料。

#### Scenario: Failure after a new file was installed
- **WHEN** 发布新增了某个 accessor，随后替换另一个文件失败，存储仍允许回滚
- **THEN** 新 accessor 被删除，其他正式文件恢复到发布前状态，账本不变

#### Scenario: Crash during stale file deletion
- **WHEN** 全量导出删除部分陈旧产物后、提交标记前进程中断
- **THEN** 下次 export/deploy 先恢复包括已删产物在内的旧集合，再执行本次请求

#### Scenario: Crash after local commit
- **WHEN** 本地产物已标记提交，进程在清理或成功记账之前中断
- **THEN** 下次恢复保留完整新产物，清理恢复材料，不自动推进成功账本或重做部署

#### Scenario: Corrupt recovery record
- **WHEN** 尚有未完成发布的恢复记录但内容损坏
- **THEN** export/deploy 失败并给出恢复材料位置，不静默删除记录后继续发布

### Requirement: Read-only commands report without recovering

`ct validate` 与 `ct status` SHALL NOT 执行恢复写入或产生持久文件。存在未完成或损坏的发布恢复记录时，`ct validate` SHALL 以工作区级问题非零退出并指出恢复材料位置，`ct status` SHALL 在输出中报告该状态；两者 SHALL NOT 静默报告正常或删除记录。

#### Scenario: validate with a pending publication
- **WHEN** 存在未完成或损坏的发布恢复记录，用户执行 `ct validate`
- **THEN** 校验以工作区级问题非零退出并给出恢复材料位置，不修改任何文件

#### Scenario: status surfaces the pending publication
- **WHEN** 存在未完成或损坏的发布恢复记录，用户执行 `ct status`
- **THEN** 输出报告该未完成发布，不执行恢复写入

### Requirement: Publication respects export scope and reuse

系统 SHALL 保留当前过滤规则、局部 Bundle 内容和共享产物范围。非强制导出时未变文件 SHALL 保留 mtime；强制导出 SHALL 重写全部选中产物。只有未限定表和语言的完整导出 SHALL 清理陈旧产物，且删除 SHALL 与发布一并可恢复。

#### Scenario: Unchanged export
- **WHEN** 输入、输出和缓存均未变化，执行默认导出
- **THEN** 正式产物与布局 manifest 不被无意义替换，mtime 保持不变

#### Scenario: Filtered export
- **WHEN** 对合法单表执行过滤导出
- **THEN** 仍生成该过滤集合对应的 Bundle，未选中范围文件不因陈旧清理而删除

### Requirement: Concurrent export and deploy are coordinated

系统 SHALL 阻止同一规范化工作区的多个 export/deploy 同时执行；正在运行的操作继续，后来的冲突请求 SHALL 以可理解的工作区占用错误失败。进程异常退出后 SHALL 不因残留锁文件而永久阻塞后续请求。不同工作区且物理目标不重叠的操作 SHALL 可独立执行。该保证不覆盖外部编辑器及其他工作区写入用例。

#### Scenario: Web export conflicts with CLI deploy
- **WHEN** Web 正在导出，同一工作区的 CLI 发起 deploy
- **THEN** CLI 报工作区占用并以非零状态退出，不同步发布中的文件

#### Scenario: Process exits while holding the lock
- **WHEN** 持锁导出进程异常退出后重新发起导出
- **THEN** 新请求可以获得执行权，先处理未完成发布再开始新工作

### Requirement: Input fingerprints describe the data actually exported

系统 SHALL 从捕获的输入内容生成所有本次产物，成功账本中的 Excel hash SHALL 对应实际解析的字节。捕获过程中或发布前复核发现相关输入新增、删除或修改时，系统 SHALL 在正式发布前以输入已变化错误中止。外部程序在最终复核后的写入不属于排他保证，但系统 SHALL NOT 把稍后重读的源文件 hash 冒充本次已导出的输入。

#### Scenario: Excel changes while building
- **WHEN** Excel 捕获完成后、发布前被修改
- **THEN** 导出以输入变化错误失败，正式产物和成功账本不变

#### Scenario: New schema appears while building
- **WHEN** 构建期间 schemas/types 中新增资源文件
- **THEN** 发布前复核检测到成员变化并中止，不发布混合输入集合

#### Scenario: Source changes after final input check
- **WHEN** 外部程序在最终复核后修改已捕获的 Excel 且本次导出成功
- **THEN** 成功账本仍记录捕获版本的 hash，后续 status 能发现当前 Excel 的变化

### Requirement: Completion follows the entry point policy

CLI export SHALL 在本地发布后执行已配置部署，部署成功后才更新成功账本；Web export SHALL 不部署并在本地发布后更新成功账本。独立 deploy SHALL 不更新该账本。发布开始后到本次完成之间的取消请求 SHALL 不把已提交产物误报为已取消。部署或记账失败 SHALL 报整体失败；不要求回滚已完整发布的本地产物或外部 Unity 目标。

#### Scenario: CLI deployment fails
- **WHEN** 本地发布成功但 Unity 同步失败
- **THEN** CLI 非零退出，完整本地产物保留，成功账本不变

#### Scenario: Web succeeds with deploy configured
- **WHEN** 配置开启 deploy 且 Web 导出完成
- **THEN** 成功账本更新，Unity 目标没有部署写入

#### Scenario: Late cancellation
- **WHEN** 取消到达时正式发布已开始，随后发布与完成策略全部成功
- **THEN** 最终状态为成功，成功账本与已导出输入一致

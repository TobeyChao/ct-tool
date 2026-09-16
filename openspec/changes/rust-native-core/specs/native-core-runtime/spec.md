## Purpose

定义可独立分发的本地配表运行时和桌面通信契约，使命令行与原生客户端共用相同业务规则，保持既有游戏数据格式、诊断与可恢复发布保证，并以可复现的基准证明导出性能收益。

## ADDED Requirements

### Requirement: Standalone cross-platform runtime
运行时 SHALL 在 Windows/macOS/Linux 提供无需 Python、浏览器、HTTP 服务或 GUI 的独立 CLI，支持既有 export/validate/status/gen-template/i18n/deploy 命令及过滤/退出码/机器 JSON 契约；同时提供桌面本地 worker 入口。旧 panel 入口不属于新 CLI 支持范围，其调用 SHALL 给出使用原生客户端的明确指引而非启动服务。

#### Scenario: Clean machine CLI
- **WHEN** 在三平台无 Python 环境运行完整业务命令
- **THEN** 命令可用，路径相对工作区解析，JSON 模式 stdout 无日志混入

### Requirement: Compatible business and output behavior
原生核心 SHALL 实现现行 Schema 类型/资源图、草稿候选与 YAML-only 保存、Excel 读取及安全模板迁移、校验、i18n、导出和部署业务。相同合法输入 SHALL 产生与对照基线字节一致的 JSON/FBS/C#/Lua/Binary；模板按单元格/布局/样式与数据迁移语义一致。错误 SHALL 保持问题代码、资源/字段/Excel 行定位及成功失败语义，不能因语言迁移扩大合法输入集合或静默纠正非法数据。

#### Scenario: Complex table compatibility
- **WHEN** 导出包含 Enum、嵌套 Record、固定/变长 vector、ref、索引、uniform 和三语言的夹具
- **THEN** 产物字节与基线一致，并通过独立游戏读取端检查

#### Scenario: Guarded save
- **WHEN** 客户端提交旧 schemaRevision 或错误 candidateHash
- **THEN** 拒绝保存且不修改源文件；合法保存仅改 YAML，不写 Excel、翻译、output 或成功账本

#### Scenario: Template migration blocked
- **WHEN** 已有 Excel 缺少 manifest 或无法证明旧数据可安全迁移
- **THEN** 拒绝覆盖并报告原因，工作簿保持不变

### Requirement: Versioned local worker contract
worker SHALL 通过版本化本地消息协议提供工作区/资源查询、分页预览、Schema 候选/保存、模板预检/生成、validate/export/deploy、翻译查询/编辑/sync/status/compact 与取消/关闭。请求 SHALL 可关联结果、进度和结构化问题；版本不兼容、非法参数和超限消息 SHALL 明确失败且不产生业务写入。协议 SHALL 无精度损失地传递业务整数。

#### Scenario: Protocol mismatch
- **WHEN** 客户端和 worker 不能协商共同版本
- **THEN** 握手失败，业务请求不执行

#### Scenario: Cancellation while busy
- **WHEN** 导出进行中客户端发取消消息
- **THEN** worker 仍可处理控制消息，按发布边界决定取消，正常连接下每个已接受任务至多一个终态

#### Scenario: Large preview and integer
- **WHEN** 查询大表且字段值超出安全 JSON 整数范围
- **THEN** 分页返回并精确保留整数值，不因一次加载整表耗尽通道

### Requirement: Reliable publication and legacy interoperability
原生核心 SHALL 保留 export-publication、workspace-draft 和 unity-deploy 的事务/锁/完成策略；旧 journal 在加载写用例资源前恢复，旧进程与新进程写操作互斥。无法识别的恢复材料 SHALL 保留并阻止写入。CLI export 在配置部署成功后记账；桌面 export 仅本地发布后记账；独立 deploy 不记账。validate/status SHALL 保持只读。

#### Scenario: Legacy interrupted publication
- **WHEN** 工作区存在旧内核未提交事务且用户运行原生写操作
- **THEN** 先恢复旧完整文件集含删除新文件，再开始请求；恢复失败则阻止新写入

#### Scenario: Competing old and new processes
- **WHEN** 旧进程持有工作区写锁而原生进程请求保存或导出
- **THEN** 原生进程返回 busy，不同时修改目标

#### Scenario: Input changes during build
- **WHEN** 捕获输入后相关文件或目录成员发生变化且发布前复核发现
- **THEN** 导出失败，正式文件和成功账本不变

### Requirement: Reproducible performance acceptance
切换生产入口前 SHALL 在固定源码/依赖/硬件和临时夹具上记录 Python 对照与原生 release 的至少五次配对测量，包含冷全量、热缓存、改单表和仅改译文的耗时、峰值内存、阶段与产物摘要。M/L 夹具中位耗时 SHALL 分别不超过基线的 50%/20%/35%/35%，S 回退不超过 max(基线10%, 50ms)，峰值 RSS 不超过基线 1.2 倍；未达标 SHALL 保持迁移未验收，调整门槛需显式修订提案。测量不得使用真实 gd 作为写入夹具。

#### Scenario: Faster but incompatible
- **WHEN** 性能达到门槛但产物或诊断不兼容
- **THEN** 迁移不能验收，不切换默认入口

#### Scenario: Correct but slower
- **WHEN** 兼容通过但某目标场景未达性能门槛
- **THEN** 报告原始结果和限制，不以实现语言作为完成证据

### Requirement: Hashes paths and resource ownership compatibility
核心 SHALL 保留实际配置目录、资源来源路径、excel_file/json_key、layout manifest 和 canonical schema hash 的兼容性；新旧工具对同一未改工作区 SHALL 不因序列化差异报告模板漂移。Schema 保存 SHALL 检查规范化目标、名称/大小写碰撞和 Excel 归属，拒绝两个 Table 认领同一工作簿；结构保存不得读取 Excel 数据进行校验，资源删除仅删除相应 YAML。

#### Scenario: Upgrade without data changes
- **WHEN** 原生工具首次打开旧工具生成且未改动的自定义路径工作区
- **THEN** 识别既有 manifest/hash/state，不假报全表 drifted，也不生成默认目录副本

#### Scenario: Duplicate Excel ownership
- **WHEN** 新 Table 的 excel_file 与已有表路径相同或仅大小写/规范化表达不同
- **THEN** 保存拒绝并定位冲突，不写入 YAML 或 Excel

### Requirement: Legacy Apply recovery and safe reads
核心 SHALL 识别旧 apply-journal/1 与当前发布 journal；已提交旧 Apply 只清理，未提交且材料完整时恢复，缺失备份/未知格式时保留材料并阻止相关写操作。旧 apply.lock 文件存在 SHALL NOT 单独判为 busy。恢复后 SHALL 不继续应用基于恢复前快照的草稿。只读快照查询遇到未恢复事务 SHALL 报 recovery-needed，不返回看似健康的混合资源。显式 workspace.recover SHALL 在共享锁下恢复并返回新基线，不隐式保存草稿、导出或推进账本。

#### Scenario: Incomplete legacy Apply backup
- **WHEN** apply.journal.json 处于 publish 且任一 target 无可信备份
- **THEN** 保留记录和备份并阻止保存，不能把无备份目标当作本次新增后直接删除

#### Scenario: Recovery changes the Schema baseline
- **WHEN** 保存前旧 Apply 被回滚且客户端携带恢复前草稿
- **THEN** 返回恢复/基线冲突，要求重载，不静默执行旧命令

### Requirement: Worker history task and query completeness
worker SHALL 提供历史、模块/级别日志、任务/问题分页查询及通知 dismiss，所有响应按工作区和请求归属。桌面成功导出 SHALL 由核心追加实际 cache_dir 下兼容旧格式的最近五条历史，CLI 保持不追加面板历史；历史失败 SHALL 与已成功业务提交分开报告。分页 SHALL 绑定快照版本，候选 SHALL 回显编辑代次；重复请求标识不得导致写操作重复执行。

#### Scenario: Old success label and history restart
- **WHEN** 历史含旧中文成功状态且 worker 重启
- **THEN** 归一状态后返回原历史，后续成功追加正确裁剪，不依赖 Flutter 本会话内存

#### Scenario: Input changes between pages
- **WHEN** 用户请求下一页前对应数据修订已改变
- **THEN** 返回快照过期而非混合两版数据，客户端可重新查询

#### Scenario: Duplicate write request
- **WHEN** 同一连接重复发送已接受的写请求 requestId
- **THEN** 拒绝重复执行，不再次保存、同步或导出

### Requirement: Excel migration scope and deployed artifacts
Excel 读取 SHALL 保持活跃 Sheet 选择、绝对行坐标、公式缓存值与缺失结果、空白/文本/数值/日期转换的既有行为，不隐式新增公式求值。模板 SHALL 重建规定表头并按稳定路径迁移数据值，覆盖富文本双行、合并边框、冻结、Enum Note 和下拉降级；不承诺任意附加 Sheet/宏/图表的无损编辑。导出 SHALL 保持 server_only 的 JSON/Binary 区别及游戏读取端行为；部署 SHALL 保持 --for-build、内容不变不改 mtime、代码 .meta 保留/删除与既有同步范围。

#### Scenario: Non-first active sheet
- **WHEN** 工作簿活跃表不是第一个 Sheet，且数据含稀疏空行
- **THEN** 读取与旧工具相同的 Sheet，问题仍定位原始 Excel 行号

#### Scenario: Enum validation formula too long
- **WHEN** Enum 下拉公式超过既定 255 字符限制
- **THEN** 模板跳过下拉并报告 warning，不偷偷创建辅助 Sheet/命名范围，Note 和类型提示保留

#### Scenario: For-build deployment
- **WHEN** 执行 ct export --for-build 或 ct deploy --for-build
- **THEN** 常规及 build_targets 均按配置同步，已有代码 .meta 保持 GUID，源目录缺失不能当空目录清空目标


### Requirement: Explicit recovery entry point
桌面所用显式恢复操作 SHALL 区分已恢复、无需恢复与材料不足，返回材料位置与最新可用基线；不能因恢复动作自动重放上次未知结果的写请求。

#### Scenario: Recover after worker reconnect
- **WHEN** 只读查询报告 recovery-needed 且用户执行恢复
- **THEN** 内核持锁恢复后返回结果，客户端重载基线并保留冲突草稿，旧保存/导出请求不自动执行

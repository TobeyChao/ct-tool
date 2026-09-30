# native-web-runtime Specification

## Purpose

定义原生内核面向浏览器的本地服务、业务接口与任务生命周期，使现有 Web 工作台在无需 Python 的环境中保持可验证的功能对等，并保证旧工作区接续、跨入口写入安全及独立发行可用。

## Requirements

### Requirement: Standalone native Web distribution
原生发行包 SHALL 同时提供 CLI、stdio worker 与 Web 面板，Web 的静态资源和 HTTP 服务 SHALL 随包可用。用户运行 SHALL 不依赖 Python、Flask、Node、Flutter 或源码 checkout，SHALL NOT 自动查找或启动 Python 作为回退。

#### Scenario: Start from an isolated release package
- **WHEN** 用户在没有 Python、Node、Flutter 和旧 ct/ 工程的机器解压发行包并启动 panel
- **THEN** 浏览器加载五个模块及全部本地静态资源，真实查询与写操作使用原生内核

### Requirement: Web API preserves authoritative business results
面板 SHALL 提供当前 Web 使用的工作区、Schema、模板、导出、翻译、日志、历史和任务 API；成功响应 SHALL 采用 `{ok:true,data}`，失败 SHALL 提供错误说明与适用的结构化 issues、busy 或 conflict 类型。候选、校验、保存与发布 SHALL 与原生 CLI/worker 共享业务规则，不依赖 Python 或浏览器自行裁定合法性。只读查询 SHALL 不写业务文件或成功账本。

#### Scenario: Complete workspace overview
- **WHEN** 工作区同时包含缺失、数据变化和模板漂移的表
- **THEN** 工作区响应保留各自分类、语言配置及工作区身份，部署 targets 为空

#### Scenario: Schema candidate is authoritative
- **WHEN** 浏览器提交带 schemaRevision、命令历史、cursor 和编辑代次的候选请求
- **THEN** 返回该前缀对应的完整候选资源、净差异、问题和 candidateHash；过期基线拒绝，浏览器丢弃过时代次结果

#### Scenario: Structural validation does not require Excel
- **WHEN** Excel 缺失或数据非法，但用户请求 Schema 候选校验或保存合法结构
- **THEN** 操作不执行 Excel 数据校验；保存保持 YAML-only，并返回新 Schema 快照与实际写入摘要

#### Scenario: Malformed commands have actionable errors
- **WHEN** 收到未知命令、非法资源内容、缺失保存守卫或候选 hash 不匹配
- **THEN** 返回可定位的客户端错误或守卫冲突，不执行部分命令，不变更业务文件

#### Scenario: Large translation table is not silently truncated
- **WHEN** 翻译表超过单次查询的条目上限
- **THEN** 用户仍能访问全部条目且汇总覆盖全部数据；使用分页时不混合不同快照的数据

#### Scenario: Large integers remain exact
- **WHEN** API 返回超出 JavaScript 安全整数范围的整数
- **THEN** 传输与界面使用无损表示，不把该值舍入为另一个整数

### Requirement: Service-owned tasks and safe cancellation
任务 SHALL 由面板服务持有，刷新、模块切换或标签页关闭 SHALL NOT 隐式取消或重放写任务。进度和失败 SHALL 可重新查询；同一服务内已关闭的失败通知 SHALL 不因刷新复活。显式取消和正常关闭 SHALL 遵守发布安全边界；连接丢失或服务重启且终态未知时 SHALL 明确标记待核实，不谎报成功或取消。任务缓冲 SHALL 有界，问题和终态 SHALL 不被进度/日志挤掉。

#### Scenario: Reattach after refresh
- **WHEN** 导出进行中页面刷新或另一标签页访问同一服务
- **THEN** 查询到同一任务及当前状态，不启动第二次导出

#### Scenario: Cancel before publishing
- **WHEN** 用户在发布前请求取消
- **THEN** 后台任务在可取消边界停止并返回取消终态，正式产物与成功账本保持原状

#### Scenario: Cancel during publishing
- **WHEN** 取消请求到达时已进入发布阶段
- **THEN** 界面显示正在完成，任务先完成提交或回滚再报告真实终态，不能将已成功提交描述为未执行

#### Scenario: Shutdown while busy
- **WHEN** 服务收到正常关闭请求且已有写任务
- **THEN** 停止接受新写任务，等待已接受任务到达发布安全边界后退出

#### Scenario: Response is lost
- **WHEN** 写请求超时或服务连接断开，客户端没有收到终态
- **THEN** 客户端不自动重放写请求，通过服务实例、任务和工作区状态重新核实

### Requirement: Cross-entry workspace consistency
面板 Schema 保存、模板、翻译和导出写操作 SHALL 与同工作区 CLI/worker 写操作遵守统一排他规则。恢复 SHALL 先于业务资源加载；发布窗口内读请求 SHALL 取得一致快照或明确报告忙碌/待恢复。Web 导出 SHALL 仅发布本地产物并在成功后记账，不自动部署。

#### Scenario: CLI competes with a Web mutation
- **WHEN** CLI 已持有同一工作区写锁，Web 发起 Schema、模板、翻译或导出写操作
- **THEN** 返回工作区忙碌，不交错写入，用户草稿保留

#### Scenario: Load after interrupted publication
- **WHEN** 存在可识别的未完成发布事务，且配置或资源文件处于部分替换状态
- **THEN** 面板先暴露恢复入口，恢复完成前不展示半套资源或执行新业务写入

### Requirement: Existing browser drafts survive migration
在相同浏览器配置与 origin 下，升级 SHALL 保留已有受支持格式的工作区草稿、完整命令历史和 undo cursor，并以原生候选重新验证。基线冲突或未知格式 SHALL 保留原记录及查看入口，不静默清空或应用。不同 origin 的浏览器存储不可自动访问的限制 SHALL 在升级说明中明确。

#### Scenario: Restore a draft with a redo branch
- **WHEN** 从旧 Web 升级后在原地址打开，草稿格式与 Schema 基线匹配，且 cursor 位于历史中部
- **THEN** 原生面板恢复该命令前缀及重做分支，不执行 cursor 后的命令

#### Scenario: Baseline or draft format is incompatible
- **WHEN** 恢复时发现外部 YAML 变化或草稿格式无法识别
- **THEN** 草稿保留供查看，提示解决冲突，禁止静默覆盖磁盘

### Requirement: Current workspace state migration is safe
升级 SHALL 接续当前支持的 YAML、Excel、翻译、成功账本与 `export-publication/1` 恢复材料，SHALL NOT 通过清空事务或账本来完成启动。未知旧事务 SHALL 保留并阻止写入。可丢弃计算缓存 SHALL 可按版本失效，不影响业务文件。

#### Scenario: Recover a current legacy publication
- **WHEN** 工作区包含由当前 Python 发布器留下的已识别 journal，涉及新增、替换和删除
- **THEN** 原生恢复得到完整旧版本或完整已提交版本，清理本事务新增文件的行为正确，重复恢复幂等

#### Scenario: Unknown old transaction
- **WHEN** 检测到无法可靠解释的旧 Apply 或发布材料
- **THEN** 保留材料、说明阻塞原因且拒绝写入，不启动 Python 修复或自动删除材料

### Requirement: Local HTTP boundary
面板 SHALL 默认绑定 loopback，只托管随包资源及指定工作区 API；SHALL 验证请求目标与写请求来源，不开放任意路径文件读取或跨源写入。显式配置 host SHALL 不改变文件访问边界。超限或非法请求 SHALL 被明确拒绝且服务保持可用。

#### Scenario: Unexpected website attempts mutation
- **WHEN** 非允许 origin 的页面向面板发送写请求
- **THEN** 请求被拒绝，工作区不改变

#### Scenario: Static path escapes resource root
- **WHEN** 请求使用路径穿越尝试读取包外或工作区任意文件
- **THEN** 服务拒绝该访问，不返回文件内容

### Requirement: Feature parity gates Python removal
删除 Python 工程前 SHALL 建立固定 main Web 基线、旧场景到新验收的映射及执行证据。门槛 SHALL 包含真实原生 HTTP/浏览器全流程、草稿与恢复、产物与原生 CLI/worker/Flutter 回归，以及无 Python 的构建、测试、必要夹具再生和发行检查。本轮支持平台 SHALL 为 macOS，panel 与 launcher smoke SHALL 在 macOS 完成；Windows SHALL 标记延后，Linux SHALL 不纳入支持范围。缺少 macOS 或必要独立读取端证据 SHALL 标记未完成，不能用测试跳过或规格校验替代；Windows 延后与 Linux 不支持 SHALL 不被登记成平台验收通过。

#### Scenario: Native kernel tests pass but Web tests are missing
- **WHEN** Rust 内核测试通过，但 Web 编辑、草稿或浏览器布局场景尚无替代验收
- **THEN** Python 删除门槛未通过，不以已有内核能力宣称功能对等

#### Scenario: Clean environment acceptance
- **WHEN** 在不含 Python 和旧 ct/ 的干净 checkout 执行正式构建、验收、夹具再生及发行流程
- **THEN** 所有必要路径完成并留存证据，不因 Python 缺失缩减必需测试

## Purpose

把配表导出产物自动分发到 Unity 工程 Assets 目录，让"导表"与"同步"成为一步操作，并保证配置可见、失败可感知、未配置时可降级。

## ADDED Requirements

### Requirement: deploy 配置可声明且可降级
系统 SHALL 通过项目配置声明 deploy 目标：启用开关、Unity 工程路径（相对项目根或绝对）、targets（source→dest 映射）与构建目标列表。未配置或未启用时，导表行为 MUST 与未引入 deploy 前完全一致。

#### Scenario: 未配置 deploy 时导表不受影响
- **WHEN** 项目未配置 `deploy` 或 `enabled=false`，执行 `ct export`
- **THEN** 导出正常完成，且不产生任何部署动作

#### Scenario: 配置了 deploy 后导表自动部署
- **WHEN** 项目配置 `deploy.enabled=true` 且 targets 指向 Unity 工程，执行 `ct export`
- **THEN** 导出成功后按 targets 把产物同步到各目标目录

### Requirement: 目录同步与产物一致
系统 SHALL 把每个目标目录同步为与对应产物目录完全一致的状态：新增产物写入、变化产物覆盖、多余产物删除。代码文件同步时 MUST 保留目标目录中已存在文件的 `.meta`（GUID 稳定），删除文件时 MUST 连带删除同名 `.meta`；二进制产物 MUST 只做覆盖、不管理 meta。

#### Scenario: 表被删除后目标目录不再残留旧文件
- **WHEN** schema/Excel 中移除某张表并重新导出部署
- **THEN** 目标目录中该表的旧产物文件及其同名 `.meta` 被删除，其余文件保持 GUID 不变

#### Scenario: 重复部署幂等
- **WHEN** 连续两次执行部署且产物未变化
- **THEN** 第二次部署后目标目录内容与第一次一致，已存在文件的 `.meta` 未被改动

### Requirement: 部署失败即导表失败
系统 SHALL 在任一步部署失败时中止并报告错误，导表命令以非 0 退出；失败时 MUST 不提交本次导出缓存。成功时 SHOULD 输出各目标目录的同步结果。

#### Scenario: 目标目录不可写导致失败
- **WHEN** 部署目标目录不存在或不可写，执行导出
- **THEN** 命令以非 0 退出，输出明确错误，且缓存状态未更新

### Requirement: 无变化时仍可部署
系统 SHALL 在增量导出判定"所有表均无变化"时跳过导出，但仍执行部署（日志注明仅部署）。

#### Scenario: fresh 环境无变化表时补齐产物
- **WHEN** 工作区无 schema 变化但目标目录缺少产物，执行 `ct export`
- **THEN** 跳过导出步骤，但产物仍被部署到目标目录

### Requirement: 独立部署命令
系统 SHALL 提供 `ct deploy` 命令，只执行部署不执行导出，行为与导出流程中的部署步骤一致。

#### Scenario: 只部署不导出
- **WHEN** 用户执行 `ct deploy`
- **THEN** 按 targets 部署当前产物，不触发导出，不修改缓存

### Requirement: 构建目标
系统 SHALL 支持 `--for-build` 参数：导出或部署时追加构建目标（如 `Assets/StreamingAssets/Config`），供打包流程使用。

#### Scenario: 打包前生成构建目标产物
- **WHEN** 用户执行 `ct export --for-build`（或 `ct deploy --for-build`）
- **THEN** 常规目标与构建目标都被部署

### Requirement: 部署状态可见
系统 SHALL 在 Web 面板工作区信息与 `ct status` 输出中展示部署配置状态与目标绝对路径；Web 导出进度 SHALL 包含部署步骤。

#### Scenario: Web 面板显示部署配置
- **WHEN** 用户打开 Web 面板并查看工作区信息
- **THEN** 可看到部署开关、Unity 工程路径与各目标绝对路径（未配置时显示未配置）

#### Scenario: CLI 显示部署状态
- **WHEN** 用户执行 `ct status`
- **THEN** 输出中包含部署启用状态与目标路径

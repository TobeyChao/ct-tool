## Purpose

launcher 作为 ct 配表工具的桌面壳，自带冻结的 ct panel 运行时，使用户无需克隆 ct-tool 仓库或安装 Python 即可启动面板服务，同时保留外部工具目录回退以兼容开发环境。

## ADDED Requirements

### Requirement: 内置运行时优先

launcher 启动 panel 服务时 SHALL 优先使用随应用分发的 ct 运行时；当内置运行时不存在时 SHALL 回退到用户在设置中配置的工具目录；两者均不可用时 SHALL 停止启动并报告可操作的错误，不启动任何进程。

#### Scenario: 使用内置运行时启动
- **WHEN** 应用包内存在内置 ct 运行时且用户点击启动
- **THEN** launcher 使用内置运行时启动 `ct panel`，不依赖配置的工具目录

#### Scenario: 内置缺失时回退外部工具
- **WHEN** 应用包内没有内置运行时，但配置的工具目录存在可用的 ct 入口
- **THEN** launcher 使用外部工具目录启动，并提示当前使用外部工具

#### Scenario: 全部缺失时报告错误
- **WHEN** 内置运行时与外部工具目录均不可用
- **THEN** launcher 停止启动，显示包含工具目录配置指引的错误信息，进程不残留

### Requirement: 平台内置运行时布局

内置运行时 SHALL 按平台约定随应用分发：macOS 位于应用包 `Contents/Resources` 内，Windows 位于可执行文件同级目录；launcher SHALL 无需用户配置即可发现该布局。

#### Scenario: macOS 内置布局
- **WHEN** launcher 运行于 macOS 且应用包 `Contents/Resources` 内含内置运行时
- **THEN** 无需任何配置即可发现并使用内置运行时

#### Scenario: Windows 内置布局
- **WHEN** launcher 运行于 Windows 且可执行文件同级目录内含内置运行时
- **THEN** 无需任何配置即可发现并使用内置运行时

### Requirement: 启动行为等价

无论使用内置还是外部运行时，launcher SHALL 以相同参数（`--root`、`--host`、`--port`、`--no-browser`）启动 `ct panel`，日志输出与进程退出处理保持一致。

#### Scenario: 参数一致
- **WHEN** 分别使用内置运行时与外部工具目录启动 panel
- **THEN** 传递给 panel 的命令参数一致（工作区、host、port、no-browser）

#### Scenario: 日志与退出处理
- **WHEN** panel 进程输出日志或退出
- **THEN** launcher 实时显示日志并正确清理进程状态，与外部工具模式行为一致

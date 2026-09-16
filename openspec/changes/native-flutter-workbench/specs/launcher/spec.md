## MODIFIED Requirements

### Requirement: 内置运行时优先

原生桌面客户端 SHALL 使用随安装包分发的原生运行时，不依赖 Python、仓库或外部工具目录。运行时缺失或协议不兼容 SHALL 显示可操作的修复错误并禁用业务写入；开发模式可显式选择兼容运行时但不得自动回退到 Python panel。

#### Scenario: 使用内置运行时启动
- **WHEN** 安装包内运行时存在且兼容
- **THEN** 进入原生工作台并连接运行时，不打开浏览器或启动 Web 服务

#### Scenario: 全部缺失时报告错误
- **WHEN** 正式安装包运行时缺失
- **THEN** 提示修复安装，不执行旧工具目录中的 Python 程序

#### Scenario: 内置缺失时回退外部工具
- **WHEN** 内置运行时缺失但旧设置仍包含外部 Python 工具目录
- **THEN** 不再执行旧回退行为，正式包提示修复安装；仅显式开发模式可选择兼容原生运行时

#### Scenario: 协议不兼容
- **WHEN** 内置运行时协议版本不兼容
- **THEN** 显示版本问题、禁用写操作且不循环重启

### Requirement: 平台内置运行时布局

内置运行时 SHALL 按平台约定随应用分发：macOS 位于应用包 Contents/Resources 内，Windows 位于可执行文件同级目录；客户端 SHALL 无需用户配置即可发现该布局。正式包 SHALL 包含对应 OS/架构的运行时，安装后业务操作不要求联网安装依赖。

#### Scenario: macOS 内置布局
- **WHEN** 用户在没有 Python 或项目源码的 macOS 上启动安装包
- **THEN** 自动发现并连接对应架构运行时

#### Scenario: Windows 内置布局
- **WHEN** 用户在没有 Python 或项目源码的 Windows 上启动安装包
- **THEN** 自动发现运行时，包含中文与空格的安装路径可正常使用

### Requirement: 启动行为等价

内置及显式开发运行时 SHALL 使用相同版本化本地协议和工作区参数，日志与终态处理一致。启动 SHALL 不接受或依赖旧 host/port/no-browser 设置；原工作区选择 SHALL 可迁移保留。退出 SHALL 请求安全关闭并处理任务/草稿，不以强杀替代取消。

#### Scenario: 参数一致
- **WHEN** 分别选择内置和显式开发运行时
- **THEN** 相同工作区与操作形成等价请求，能力不兼容时被拒绝

#### Scenario: 日志与退出处理
- **WHEN** 运行时输出事件或异常退出
- **THEN** 实时展示所属任务日志，清理连接状态，未知写结果不误报成功

#### Scenario: Existing launcher preferences
- **WHEN** 首次启动新客户端并读取旧设置
- **THEN** 保留有效工作区与适用桌面偏好，旧 host/port/Python 路径不用于启动业务

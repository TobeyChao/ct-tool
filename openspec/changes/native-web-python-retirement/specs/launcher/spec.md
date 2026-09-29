## MODIFIED Requirements

### Requirement: 内置运行时优先
launcher SHALL 保留 main 的浏览器面板启动器，优先使用内置原生 ct，缺失时仅使用用户显式配置的原生可执行文件。SHALL NOT 回退到 Python、venv 或旧 Python ct 包装器；不可用时 SHALL 给出原生运行时配置指引且不启动进程。旧工作区、端口、自启和托盘偏好 SHALL 保留，旧工具目录 SHALL 不被误认成有效原生入口。

#### Scenario: 使用内置运行时启动
- **WHEN** 包内存在原生运行时且用户启动服务
- **THEN** launcher 使用内置 ct panel，仍通过浏览器呈现 Web 工作台

#### Scenario: 内置缺失时回退外部工具
- **WHEN** 内置运行时不存在，用户配置了有效原生可执行文件
- **THEN** 使用该原生入口并提示外部运行时，不搜索解释器

#### Scenario: 全部缺失时报告错误
- **WHEN** 原生入口均不可用或只有旧 venv 配置
- **THEN** 显示配置原生运行时的指引，不启动 Python 或残留进程

### Requirement: 启动行为等价
内置与外部原生运行时 SHALL 以相同 root、host、port、no-browser 参数启动 panel；launcher SHALL 在确认就绪后允许打开浏览器，显示实时日志并正确处理退出。正常停止、退出与托盘退出 SHALL 等待原生服务到达发布安全边界，不以固定超时强杀作为正常关闭路径。SHALL 保留 main 的桌面壳，不替换为完整 Flutter 编辑工作台。

#### Scenario: 参数一致
- **WHEN** 分别使用内置与外部原生入口
- **THEN** panel 参数一致，旧工作区和端口偏好继续生效

#### Scenario: 日志与退出处理
- **WHEN** 服务输出日志或退出
- **THEN** 日志实时可见，launcher 收敛进程状态与端口，不留下孤儿进程

#### Scenario: Exit during publication
- **WHEN** 用户在发布期间退出 launcher
- **THEN** 服务先完成提交或回滚再退出，launcher 不因固定短超时强杀服务

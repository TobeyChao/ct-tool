## ADDED Requirements

### Requirement: Native ct panel command
原生 CLI SHALL 提供 `ct panel` 启动本地 Web 服务，支持 `--root`、`--host`、`--port` 和 `--no-browser`；默认 root 为当前目录、host 为 `127.0.0.1`、port 为 `8000`。服务 SHALL 在监听就绪后输出实际地址，并按选项打开浏览器；SHALL 不依赖 Python 或输出 Web 已退役的替代提示。端口冲突或非法参数 SHALL 友好失败且非零退出，不静默改变地址；运行期工作区错误 SHALL 通过可访问的面板诊断呈现。

#### Scenario: Default local startup
- **WHEN** 用户在合法工作区执行 ct panel
- **THEN** 原生服务监听默认地址，浏览器可访问既有 Web 模块，不启动解释器

#### Scenario: Headless explicit startup
- **WHEN** 执行 ct panel --root 指定工作区 --host 127.0.0.1 --port 8123 --no-browser
- **THEN** 只服务该工作区并输出实际地址，不自动打开浏览器

#### Scenario: Port conflict
- **WHEN** 指定端口已被占用
- **THEN** 输出可理解错误并非零退出，不打开错误地址或悄悄换端口

#### Scenario: Invalid workspace diagnostic
- **WHEN** 服务可正常绑定但工作区缺失或配置非法
- **THEN** 面板可访问并显示诊断，业务 API 返回错误，不把空工作区伪装成成功加载

## MODIFIED Requirements

### Requirement: Designer-friendly error messages
所有数据校验错误 SHALL 以中文输出，包含表名、Excel 绝对行号、列字母、字段名、当前单元格值与错误说明；非 Excel 来源的错误 SHALL 提供相应资源/文件位置。面向普通用户的输出 SHALL 不暴露原始实现堆栈。程序员可通过 `--verbose` 获取详细诊断日志，不要求特定语言 traceback。

schema / 配置加载错误 SHALL 以 `[error] <说明>` 友好失败，命令行业务执行退出码非零；`ct export` 可使用 `[export error]`。`ct panel` SHALL 在可访问的诊断面板中呈现工作区错误；`--verbose` 的内部诊断 SHALL 写入日志或 stderr，不污染机器可读 stdout。

#### Scenario: User-friendly validation error with exact location
- **WHEN** Item 表头三行之下第三条数据位于 Excel 第六行，Price 列 C 填写了“贵”
- **THEN** 错误包含 Item.xlsx、第六行、列 C、Price、当前值及期望 float，而非原始异常堆栈

#### Scenario: Absolute row survives blank lines
- **WHEN** 数据区含空行，出错行实际位于 Excel 第七行
- **THEN** 使用绝对行号第七行，不用跳过空行后的相对序号

#### Scenario: Verbose mode for developers
- **WHEN** 发生未预期内部错误且用户使用 verbose
- **THEN** 日志提供详细原生诊断与可用上下文，普通错误仍友好，不启动 Python 获取 traceback

#### Scenario: Schema load error is friendly
- **WHEN** 主键声明为 int64 而模型要求 int32，执行 validate 或 status
- **THEN** 输出包含表名、当前类型与 int32 要求的加载错误并以退出码 1 结束，不显示原始堆栈；详细信息进入诊断日志


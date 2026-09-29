# 旧 Web 契约冻结与原生对照

来源：main `8dc7b81` 的旧 Flask Web、`ct/tests/web/web_helpers.py::build_project`。
`web-http-python.json` 内列出实际源码 SHA-256、12 组 HTTP 请求/响应、保存前 YAML 字节及
保存后文件摘要、旧浏览器 `ct-drafts` 的完整 redo 草稿记录、旧历史文件与读取结果。
原生验收读取此 JSON；测试不会调用旧 Python。捕获只使用临时工作区，不触碰真实 `gd/`。

采集脚本封存在 `source/*.py.txt`，不是活跃构建或测试入口。需追溯时，从仓库根目录
使用 `ct/.venv/bin/python` 并设置 `PYTHONPATH=ct/src:ct/tests/web` 分别执行
`capture-web-http.py.txt` 和 `capture-web-draft-history.py.txt`；后者还需
`CT_CHROMIUM_EXECUTABLE` 指向可运行的 Chromium。journal 的旧实现故障注入
见 `source/capture-python-journals.py.txt` 和 `native/fixtures/journals/README.md`。
旧实现当前仍在仓库，冻结文件的来源 SHA 会在其存在时被验收检查。

路径占位：仅用 `${ROOT}` 代替临时工作区的绝对真实路径；浏览器 origin 里的端口用
`${PORT}` 代替；journal 捕获另外将随机操作 ID 换成 `fixture-operation`。
恢复样例的备份时间戳保留纳秒值。源文件含实际 SHA 和具体请求，清单可独立读取；
不以原生输出重写旧响应或输出摘要。

原生对照入口：`node --test web/tests/frozen-web-contract.test.mjs`。对照允许的
差异有且仅有：原生候选额外回显 `draftGeneration`；保存额外携带空 `changed`；
原生校验额外返回基线/代次并简化未知命令的中文前缀；缺守卫错误文案更精确；
候选 hash 冲突额外附带空 `issues`/可选基线字段；原生服务启动后日志多一条系统
诊断。原生要求候选请求显式带 `schemaRevision` 是提案指定的收紧行为。
其余冻结成功响应、`schemaRevision` 与完整工作区 `revision`、资源 DTO、候选
hash、保存回执和保存后 YAML 摘要均逐项比较。历史样例验证中文旧结果值映射为
`success` 且源文件保留；草稿在真实浏览器测试中恢复命令前缀、cursor 和 redo。

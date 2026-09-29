# Python 发布事务冻结样例

`python-publication.json` 于 2026-09-28 从 main `8dc7b81` 的
`ct/src/ct/storage/publication.py` 实际执行捕获，文件内记录源码 SHA-256。
它是迁移输入与独立预期结果，Rust 测试只读取，不调用 Python，也不以原生
恢复器生成期望值。不要用 native 输出重写此文件。

捕获时使用 `ct/.venv/bin/python`，每个场景建立独立临时目录，在旧发布器
`_write_journal` 原方法落盘后执行 `os._exit(86)`，模拟真实进程中断，避免
异常处理自动回滚。覆盖 prepared、backed_up、publishing 的 0–4 个完成目标、
committed，共 8 个现场。目标包括替换配置、替换产物、新增产物与删除产物。
配置的新内容故意损坏，用于确认恢复发生在配置加载之前；committed 必须
保留已提交内容，随后报告配置错误。

每个现场包含原始 journal、所有文件的字节文本与纳秒 mtime；`after` 由旧
Python `recover()` 实际执行得到，并验证第二次恢复为空操作。仅将临时目录
替换为 `${ROOT}`、操作 ID 替换为 `fixture-operation`，将新文件时间固定；
旧文件与备份使用同一固定纳秒时间。暂存文件名保持原捕获值。路径占位只替换
JSON 字符串，测试时展开为临时工作区绝对路径，不接触真实 `gd/`。

验收入口：`ct-tests-compat --test python_publication`；真实 HTTP 入口：
`ct-cli --test panel` 的 `explicit_http_recovery_consumes_frozen_python_journals_before_loading_config`。

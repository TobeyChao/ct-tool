# 工作区与资源查询冻结样例

`web-resource-query-python.json` 来自 main `8dc7b81` 的旧 Flask `create_app(root).test_client()`，来源文件 SHA-256 写在 JSON 中。采集只在临时工作区进行：将四个 Table/Record/Enum YAML 放到自定义 `data/schemas`、`data/types`，并配置自定义 `data/books`、`data/cache`、`data/i18n`。绝对工作区根目录统一替换为 `${ROOT}`；不含真实 `gd/` 内容。

样例保存了初始 `/api/workspace` 与 `/api/schema-workspace` 全响应、两表模板生成后状态、Item Schema 增加字段后的漂移状态，以及对 Monster 工作簿追加一个可被 ZIP 读取器忽略的字节后的数据变更状态。最后一步只改变文件 hash，不改变可读取列数，用来区分 `changed` 与 `drifted`。资源快照含四种反向引用键、完整 Table/Record/Enum 与两个 revision。

`web/tests/resource-query.test.mjs` 不启动 Python，使用真实原生 HTTP 逐项比对冻结响应；同时检查所有只读请求不改 YAML 字节/mtime 或成功账本。模板生成更新工作簿 hash 与账本采用同一可恢复发布事务；另一项故障测试把自定义账本目标做成目录，验证失败时工作簿、manifest 与账本都不留下半套结果。

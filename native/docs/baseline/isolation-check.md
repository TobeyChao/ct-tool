# 隔离入口验收（rust-native-core 任务 6.9）

由 `node native/tools/bench/isolation-check.mjs` 生成。子进程环境：`PATH` 只有包内 `bin`，
`PYTHONHOME/PYTHONPATH/VIRTUAL_ENV/CONDA_PREFIX` 等变量被删除，工作目录是真实 `gd/`。

- 发行包：`native\dist\ct-native-0.0.0-x86_64-pc-windows-msvc`
- 只读命令：`--version`、`validate`、`status`（都不写缓存、不恢复事务）

| 命令 | 退出码 | stdout（截断） | stderr（截断） |
|---|---|---|---|
| `ct --version` | 0 | ct 0.0.0 |  |
| `ct validate --root .` | 0 | 校验通过 |  |
| `ct status --root .` | 0 | 数据变更（待导出）: /   [changed] ComplexShowcase /   [changed] Item /   [changed] ItemType /   [changed] Quest /   [changed] UIConfig |  |

## 结论

- 真实 `gd/` 未被写入：`git status --porcelain gd` 前后分别 0 / 0 条（均为空）。
- `gd/` 里没有工具文件（扫描 4 层内 `*.py|*.pyc|*.exe|*.dll|__pycache__|.venv`）：0 处。
- 原生发行包不查询 PATH 上的解释器即可完成校验与状态查询；`ct panel` 只剩迁移指引，
  Python 侧 `ct/.venv` 仅作对照测试入口（见 `native/README.md` 的「开发/测试入口」）。

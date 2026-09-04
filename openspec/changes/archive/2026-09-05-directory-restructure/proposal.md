## Why

当前仓库目录按"技术栈"平铺（`python/` + 根级 `tests/` + `docs/`），把 ct 工具这一个自包含项目拆散成三处，导致：pytest 需要 `pythonpath` hack 才能 import 包、venv 随目录移动失效、面板前端资源悬在包外靠 `parents[2]` 魔法路径定位。同时 `BinaryReaderTest` 是历史遗留的 .NET 验证工程，不再维护。需要一次按"项目自包含"原则的目录重组。

## What Changes

- **BREAKING** `python/` 重命名为 `ct/`，并升级为 `src` layout：Python 包移至 `ct/src/ct/`（包名不变，`import ct.*` 全部保持）。
- **BREAKING** 根级 `tests/`、`docs/`、`pytest.ini` 移除：pytest 测试回到 `ct/tests/`，工具文档回到 `ct/docs/`；测试命令改为 `cd ct && pytest`。
- **BREAKING** `tests/BinaryReaderTest/`（.NET 验证工程）整体删除，其 spec `csharp-binary-reader-test` 一并废弃。
- 面板前端资源 `web/static/` 并入 Flask 包：移至 `ct/src/ct/web/static/`，`app.py` 改用 `Path(__file__).parent / "static"` 定位，去掉魔法路径；`pyproject.toml` 增加 `package-data` 使前端随包分发。
- launcher 默认路径推断更新为 `repoRoot/ct` 与 `ct/.venv`；venv 重建（shebang 绝对路径不随目录迁移）。
- 文档引用同步：AGENTS.md、README、`docs/research/flask-vue-stack.md`。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
- `tool-workspace-separation`: 目录结构要求更新（工具源码位于根级 `ct/` 项目、`src` layout、`tests`/`docs` 随项目、根目录不再有 `pytest.ini` 与平铺的 `tests/`/`docs/`）。
- `csharp-binary-reader-test`: 移除（`BinaryReaderTest` 工程删除，该 capability 废弃）。

## Impact

- 代码路径：`python/` → `ct/`（git rename 保留历史）；Flask 静态资源路径；launcher 的 `settings_store._inferDefaults`。
- 构建/测试：`pip install -e ct/`；`cd ct && pytest`；`flutter build`（launcher 不动）；venv 重建。
- 配置：`pyproject.toml`（packages.find `where=["src"]` + package-data）、删除根 `pytest.ini`。
- 文档：AGENTS.md、README.md、flask-vue-stack.md、`docs/design/` 内设计稿归属。

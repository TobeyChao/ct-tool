## Context

当前结构把 ct 工具拆散成 `python/`（源码）、根级 `tests/`、`docs/` 三处，并遗留了根 `pytest.ini`（为跨目录 import 打补丁）、悬在包外的 `python/web/static/`（靠 `parents[2]` 定位）以及不再维护的 `tests/BinaryReaderTest/`。动机见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**
- ct 与 launcher 各自成为"项目自包含"单元：代码、测试、文档、构建配置、`.gitignore`、venv 在一起。
- 消灭一切跨目录 hack：根 `pytest.ini`、`pythonpath`、Flask 的 `parents[2]` 魔法路径。
- 让 venv 的位置随项目稳定（`ct/.venv`），目录迁移不再破坏它。

**Non-Goals:**
- 不改变任何功能行为（导出、校验、i18n、面板、启动器功能完全不变）。
- 不上 Python 包的深层次重构（如拆分模块、改 API）。
- 不引入 monorepo 编排工具（Melos / Nx / Bazel）：仓库只有两个项目且无共享代码，根级平铺自包含即可。

## Decisions

### D1: `ct/` 采用 `src` layout（`ct/src/ct/`）
项目目录名与包名相同是 Python 生态常态，`src/` 就是标准隔离层（Python 官方 CLI 教程、click 均如此）。
- 备选 A：flat layout（`ct/ct/`，typer/rich 风格）——可行但 pytest 官方建议 src，且从项目根跑测试时 cwd 会遮蔽安装包。
- 备选 B：项目目录改别的名字（`core/`、`app/`）——工具本质叫 ct，改名反而失义。
选择 src：包名 `ct` 不变（`import ct.*` 零改动），仅物理位置 + `pyproject` 的 `packages.find` 加 `where=["src"]`。

### D2: 前端静态资源并入 Flask 包（`ct/src/ct/web/static/`）
Flask 的标准做法是静态资源随包分发；`app.py` 用 `Path(__file__).parent / "static"` 定位，删除 `parents[2]`。
- 备选：静态资源留在项目内 `ct/web/static/`（src 之外）——仍需一条相对路径规则，打包时还要单独处理，不如进包干净。
配套：`pyproject.toml` 增加 `[tool.setuptools.package-data] "ct.web" = ["static/*", "static/vendor/*"]`，确保 wheel/editable 都带前端。

### D3: 测试与文档回项目（`ct/tests/`、`ct/docs/`），删除根 `pytest.ini`
editable install 已把包加入环境，`cd ct && pytest` 即可，`pythonpath` 配置不再需要。launcher 设计稿归 `launcher/docs/design/`，面板设计稿归 `ct/docs/design/`。

### D4: 删除 `tests/BinaryReaderTest/` 并废弃 `csharp-binary-reader-test` capability
验证工程已无维护者，其 spec 一并移除（不再承诺任何行为）。

### D5: venv 重建而非移动
venv 内脚本 shebang 是绝对路径，目录迁移后必然失效（本次已踩过）；重建 `ct/.venv` 并 `pip install -e .` 是最可靠做法。

## Risks / Trade-offs

- [git rename 保留历史] → 全程 `git mv`，避免内容级移动。
- [引用遗漏（脚本/CI/文档指向旧路径）] → 迁移后全局 `rg "python/|tool/"` 复查；AGENTS.md / README 同步。
- [Flask 静态路径改错导致面板空白] → 迁移后启动 `ct panel` 并访问 `http://127.0.0.1:8000` 验证首页与 API。
- [launcher 默认路径推断失效] → 更新 `_inferDefaults` 为 `repoRoot/ct`，构建后启动验证能找到 `ct/.venv`。
- [pytest 收集范围变化] → 从 `ct/` 跑全量 187 用例确认全绿；`tests/BinaryReaderTest` 删除不影响 pytest。

## Migration Plan

1. `git mv python ct`；`git mv ct/ct ct/src` 后整理为 `ct/src/ct/`（包目录）。
2. 移动 `ct/web` → `ct/src/ct/web/`（含 static），`ct/tests` → `ct/tests`，`ct/docs` → `ct/docs`。
3. 删除 `tests/BinaryReaderTest/`（git rm）；`git mv tests/<pytest 子目录> ct/tests/` 后删除根 `tests/`。
4. `git mv docs/design/launcher-mockup.html launcher/docs/design/`；`docs/design/panel-mockup.html` → `ct/docs/design/`。
5. 更新 `ct/pyproject.toml`（packages.find where=["src"] + package-data）、删除根 `pytest.ini`。
6. 更新 `launcher/lib/services/settings_store.dart`（`repoRoot/ct`）、AGENTS.md、README.md、`ct/docs/research/flask-vue-stack.md`。
7. 重建 `ct/.venv`（`python3 -m venv .venv && pip install -e .`）。
8. 验证：`cd ct && pytest`（187 全绿）；`ct --help`；`ct panel` 页面可访问；`flutter analyze && flutter build`；启动 launcher 确认路径推断。

## Open Questions

无（全部决策已在探索阶段与用户确认）。

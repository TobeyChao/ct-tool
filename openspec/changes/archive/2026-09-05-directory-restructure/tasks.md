## 1. 目录迁移（git mv 保留历史）

- [x] 1.1 将 `python/` 重命名为 `ct/`，并把 Python 包调整为 `ct/src/ct/`（`git mv python/ct ct/src/ct`，包名 `ct` 不变）
- [x] 1.2 把 `python/web/`（含 `static/`）并入包内为 `ct/src/ct/web/`，更新 `ct/web/app.py` 静态资源定位为 `Path(__file__).parent / "static"`
- [x] 1.3 将 `python/tests/` 移至 `ct/tests/`，`python/docs/` 移至 `ct/docs/`
- [x] 1.4 删除 `tests/BinaryReaderTest/`（`git rm -r`），清理根级 `tests/`、`docs/`、`pytest.ini`
- [x] 1.5 移动设计稿归属：`docs/design/launcher-mockup.html` → `launcher/docs/design/`，`docs/design/panel-mockup.html` + `screenshots/` → `ct/docs/design/`

## 2. 配置与代码更新

- [x] 2.1 更新 `ct/pyproject.toml`：`[tool.setuptools.packages.find]` 加 `where=["src"]`，新增 `[tool.setuptools.package-data] "ct.web" = ["static/*", "static/vendor/*"]`
- [x] 2.2 更新 `launcher/lib/services/settings_store.dart`：默认推断改为 `repoRoot/ct` 与 `ct/.venv`
- [x] 2.3 同步文档引用：AGENTS.md、README.md、`ct/docs/research/flask-vue-stack.md`（旧 `python/`、`tool/` 路径全部替换）
- [x] 2.4 归档时由 `openspec archive` 将 delta 合并到主 specs（`tool-workspace-separation` 更新、`csharp-binary-reader-test` 移除），apply 阶段不改主 specs

## 3. 环境与验证

- [x] 3.1 重建 `ct/.venv`（`python3 -m venv .venv`），`pip install -e .` 安装（含 pytest）
- [x] 3.2 在 `ct/` 下运行 `pytest`，187 用例全绿
- [x] 3.3 验证 `ct --help` 正常；启动 `ct panel` 并访问 `http://127.0.0.1:8000` 确认面板首页与静态资源可访问
- [x] 3.4 运行 `flutter analyze` 与 `flutter build macos --debug`；启动 launcher 确认默认路径推断（`ct/.venv` + `gd`）
- [x] 3.5 全局 `rg "python/|tool/|pytest.ini"` 复查，无旧路径残留

## 4. 收尾

- [x] 4.1 提交目录重组（含 git rename）与文档/配置同步

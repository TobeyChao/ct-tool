# ct — 配表导出工具

将游戏策划数据从 **Excel + YAML Schema** 导出为 **JSON、FlatBuffers Binary 及 C#/Lua Accessor 代码** 的一站式 CLI 工具。

## 快速开始

```bash
# 安装
cd ct
pip install -e .

# 切到数据工作空间，开始导出
cd ../gd
ct export

# 查看所有命令
ct --help
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `ct export` | 全量导出（无增量模式；配置 deploy 后自动同步到 Unity Assets） |
| `ct export --all` | no-op：导出恒全量重建，`--all` 仅为兼容旧流水线保留 |
| `ct export --for-build` | 导出并追加构建目标（如 StreamingAssets/Config） |
| `ct deploy` | 只部署当前产物到 Unity Assets，不触发导出 |
| `ct export --table Item --lang en` | 只导出指定表（单个精确表名）、指定语言 |
| `ct validate` | 只校验不产出（适合 CI） |
| `ct status` | 查看哪些表有变更 / 模板漂移 |
| `ct gen-template --all` | 根据 Schema 生成 Excel 模板 |
| `ct i18n sync` | 刷新翻译骨架 |
| `ct i18n status` | 翻译进度统计 |

## 目录结构

| 目录 | 说明 |
|------|------|
| `ct/` | 配表工具（自包含 Python 项目） |
| `gd/` | 游戏数据工作空间（`--root` 默认目录） |
| `gd/config/` | 全局配置 + 表 Schema 定义 |
| `gd/excel/` | 策划填写的 Excel 数据表 |
| `gd/output/` | 导出产物（JSON / FBS / Binary / C# / Lua） |
| `gd/i18n/` | 国际化翻译文件 |
| `openspec/` | 设计文档和任务列表 |

## 部署到 Unity（deploy）

在 `gd/config/global.yaml` 配置 `deploy:` 后，`ct export` 会按 targets 把产物同步到 Unity 工程 Assets：

```yaml
deploy:
  enabled: true
  unity_project: "../../Client"   # 相对 gd/ 或绝对路径
  targets:
    - source: output/binary
      dest: Assets/Content/Config
    - source: output/generated/csharp
      dest: Assets/Scripts/Config/Gen
    - source: output/generated/lua
      dest: Assets/Scripts/Lua/Config/Gen
  build_targets:                  # ct export/deploy --for-build 时追加
    - source: output/binary
      dest: Assets/StreamingAssets/Config
```

- 路径语义：`source` 相对 `gd/`（项目根），`dest` 相对 `unity_project`。
- 未配置或 `enabled: false` 时导表行为不变（不部署）。
- 部署失败会使导表以非 0 退出；部署状态与目标路径的查询**未实现**（`ct status` 只报数据变更 / 模板漂移 / 缺失文件三类）。

## 依赖

Python >= 3.10。二进制由 `ct/export/canonical_binary.py` 直接构建（无需 flatc）。

详细文档见 [`ct/docs/README.md`](ct/docs/README.md)。

## 待办（Known TODOs）

- **增量导出尚未接线**：`ct/cache/fingerprints.py` 的分层指纹（schema/data/i18n/bundle）与 `decide_artifact_reuse` 已实现，但没有接到 `ct/app/canonical_export.py` 的 `run_canonical_export`，所以导出**恒全量重建**（`--all` 是 no-op）。`cache/state.json` 目前只服务 `ct status` 的「待导出」判断，不参与跳过。

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
| `ct export` | 增量导出：完整校验后默认复用未变更产物（配置 deploy 后自动同步到 Unity Assets） |
| `ct export --all` | 强制重建所有选中产物，跳过增量缓存 |
| `ct export --for-build` | 导出并追加构建目标（如 StreamingAssets/Config） |
| `ct deploy` | 只部署当前产物到 Unity Assets，不触发导出 |
| `ct export --table Item --lang en` | 只导出指定表（单个精确表名）、指定语言 |
| `ct validate` | 只校验不产出（适合 CI） |
| `ct status` | 查看数据变更 / 模板漂移 / 缺失文件及未完成的发布 |
| `ct gen-template --all` | 根据 Schema 生成 Excel 模板 |
| `ct panel` | 启动本地面板（浏览器打开即用） |
| `ct i18n sync` | 刷新翻译骨架 |
| `ct i18n status` | 翻译进度统计 |
| `ct i18n compact` | 物理移除 lang 文件中的 orphan 条目 |

## 目录结构

| 目录 | 说明 |
|------|------|
| `ct/` | 配表工具（自包含 Python 项目） |
| `gd/` | 游戏数据工作空间（`--root` 默认当前目录，通常 cd 到这里运行） |
| `gd/config/` | 全局配置 + 表 Schema 定义 |
| `gd/excel/` | 策划填写的 Excel 数据表 |
| `gd/output/` | 导出产物（JSON / FBS / Binary / C# / Lua） |
| `gd/i18n/` | 国际化翻译文件 |
| `launcher/` | Flutter 桌面启动器（内置 ct 运行时） |
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
- 部署失败会使导表以非 0 退出；部署状态与目标路径的查询**未实现**（`ct status` 报数据变更 / 模板漂移 / 缺失文件及未完成的发布，不含部署状态）。

## 依赖

Python >= 3.10。二进制由 `ct/src/ct/export/canonical_binary.py` 直接构建（无需 flatc）。

详细文档见 [`ct/docs/README.md`](ct/docs/README.md)。

## 待办（Known TODOs）

- 跨项目（fabulous-game 侧 reader / 运行时）的剩余工作见
  [`ct/docs/archive/fabulous-game-对齐清单.md`](ct/docs/archive/fabulous-game-对齐清单.md)
  （ct-tool 侧条目均已完成，该清单已归档）；增量导出语义见 [`ct/docs/README.md`](ct/docs/README.md) 的「`ct export` 的增量语义」。

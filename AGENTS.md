# AGENTS.md

本文件为 Codex 与 Claude Code 提供该目录的工作指南。

---

## 项目概述

本仓库是 `ct`（配表导出工具）的工作空间。功能：将游戏策划数据从 **Excel + YAML Schema** 导出为 **JSON、FlatBuffers Binary 及 C#/Lua Accessor 代码**。

- `ct/` — 配表工具（自包含 Python 项目：src 布局包、web 面板、tests、docs、打包配置）
- `gd/` — 数据工作空间（config、excel、output 等）

> 当前仅 canonical 一套实现；曾经的 legacy 双路径已随 cutover 移除。

### 命名缩写

| 缩写 | 全称 | 说明 |
|------|------|------|
| `ct` | **C**onfig **T**able | 配表导出工具名 |
| `gd` | **G**ame **D**ata | 游戏数据工作空间，CLI 的 `--root` 默认指向这里 |
| `fbs` | **F**lat**B**uffers **S**chema | FlatBuffers schema 文件（`.fbs`） |
| `i18n` | **i**nternationalizatio**n** | 国际化（i 和 n 之间 18 个字母） |
| `cli` | **C**ommand **L**ine **I**nterface | 命令行接口 |

### 目录结构

```
仓库根目录/
├── ct/                   # 配表工具（自包含 Python 项目）
│   ├── src/ct/           #   Python 包 (cli, config, app, schema, excel, export, cache, diagnostics, web)
│   │   └── web/static/   #     面板前端资源（Vue 无构建，随包分发，扁平 static/）
│   ├── tests/            #   pytest 测试
│   ├── docs/             #   工具文档与设计稿
│   ├── pyproject.toml    #   打包配置（src layout + package-data）
│   └── .venv/            #   虚拟环境
├── launcher/             # Flutter 桌面启动器（独立构建单元，运行时经设置指向 ct/.venv）
│   ├── lib/              #   Dart 源码（壳 + 概览/日志/设置三页签）
│   ├── macos|windows/    #   平台工程（macOS Swift 集成 / Windows 构建）
│   └── docs/design/      #   启动器设计稿
├── gd/                   # 游戏数据工作空间 (--root)
│   ├── config/           #   global.yaml + schemas/*.yaml + types/*.yaml
│   ├── excel/            #   策划填写的 Excel 数据表
│   ├── output/           #   导出产物
│   │   ├── json/         #     JSON (按语言分目录)
│   │   ├── fbs/          #     FlatBuffers Schema (含共享 types.fbs)
│   │   ├── binary/       #     Binary Bundle (.bin)
│   │   └── generated/    #     C# / Lua Accessor
│   ├── cache/            #   增量缓存 (自动维护)
│   ├── i18n/             #   翻译文件 (source/ 原文 + {lang}/ 译文)
│   ├── tools/            #   外部工具（flatc 已退役）
│   └── scripts/          #   辅助脚本
├── openspec/             # 设计文档和任务列表
└── test-proj/            # .NET 二进制读取测试工程
```

---

## 安装

**统一使用项目 venv，不要全局安装**（macOS 上 Homebrew Python 是 PEP 668 托管环境，Windows 上全局安装易出现 pydantic 版本错配）。

```bash
cd ct

# macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Windows（PowerShell）
py -3 -m venv .venv
.venv\Scripts\activate
pip install -e .
```

需要 Python >= 3.10（Windows 建议 3.11–3.13）。每次使用前先激活 venv 再运行 `ct` 命令。

**Windows 报错 `pydantic-core` 与 `pydantic` 不匹配：**
- 若 `.venv` 是从 Mac 拷贝来的：先 `Remove-Item -Recurse -Force .venv`，再按上面重建
- 否则在 venv 内重装匹配版本：
  ```powershell
  python -m pip uninstall -y pydantic pydantic-core
  python -m pip install "pydantic==2.13.4"
  ```

---

## 测试

```bash
cd ct

# 运行全部测试
pytest

# 只跑某个子模块的测试
pytest tests/app/
pytest tests/schema/
pytest tests/export/
pytest tests/web/

# 只跑单个测试文件
pytest tests/app/test_canonical_validate.py

# 带详细输出
pytest -v

# 显示警告/日志
pytest -p no:warnings
```

测试使用 `pytest` + `typer.testing.CliRunner`。canonical 测试通过 `_helpers.build_project(tmp_path)` 构造临时项目目录（config/global.yaml + schemas + types + excel），断言校验/导出产物。browser 测试标记 `browser`，需要 Playwright Chromium。

---

## launcher 打包与分发

launcher（Flutter 桌面壳）构建时会把 ct CLI 用 PyInstaller 冻结成独立运行时（onedir）并嵌入应用包，用户无需安装 Python 或拉取本仓库即可使用。

```bash
# macOS（需 Flutter、Xcode + CocoaPods；可用 FLUTTER=/path/to/flutter 指定 SDK）
launcher/tool/build_macos.sh

# Windows（需在 Windows 机器执行，需 Flutter + VS 桌面开发负载）
launcher/tool/build_windows.ps1
```

产物位置：

- macOS：`launcher/build/macos/Build/Products/Release/ct_launcher.app`（内置 `Contents/Resources/runtime/`）
- Windows：`launcher/build/windows/x64/runner/Release/`（`ct_launcher.exe` + 同级 `runtime\`）

launcher 启动优先级：内置运行时 → 设置中的工具目录（venv）→ 报错并引导配置。游戏仓库（如 fabulous-game）消费方式：把编译好的应用放入仓库（如 `Config/launcher-apps/`），用户双击启动后，在设置页把工作区指向 `Config/gd` 即可，无需配置工具目录。

---

## CLI 命令

所有子命令均支持 `--root DIR` 指定项目根目录（默认当前目录，应为 `gd/`）。全部命令走 canonical。

```bash
# 导出（canonical 恒全量重建；--all 等同 default，--table/--lang 缩小范围）
ct export
ct export --all
ct export --table item
ct export --lang en

# 只校验，不输出产物（含跨表 ref 外键校验；适合 CI）
ct validate
ct validate --table quest

# 查看数据变更 / 模板漂移 / 缺失文件
ct status

# 根据 schema 生成 Excel 模板 + layout manifest
ct gen-template --all
ct gen-template --table item

# 任意命令加 --verbose 显示详细日志
ct export --verbose

# 部署当前产物到 Unity Assets（不触发导出）
ct deploy [--for-build]

# i18n 翻译骨架与状态管理
ct i18n sync                          # 刷新 source + 为每语言生成/更新 lang 骨架
ct i18n sync --lang en --table item   # 缩小处理范围
ct i18n status                        # 翻译进度（每语言一行）
ct i18n compact --dry-run             # 预览将被清理的 orphan 条目
ct i18n compact                       # 物理删除所有 orphan 条目
```

`ct export` 在校验闸门通过后写出产物；`ct deploy` 是独立命令，把 `output/` 同步到 Unity Assets。

---

## 架构

### 数据流

```
config/schemas/*.yaml + config/types/*.yaml  ──►  YamlResourceRepository 加载 + 类型解析
        │
        ▼
  resource_graph (named/ref 依赖边 + 拓扑序 + 反向引用)
        │
        ▼
  CanonicalWorkspace (config + 资源图 + table_order + reverse_refs)
        │
        ├─► excel/layout (字段→列稳定映射) ──► excel/canonical_reader (读 Excel → canonical 行)
        │                                          │
        │                                          ▼
        │                              canonical_validate：类型/主键/跨表 ref 外键
        │                                          │
        ▼                                          ▼
  canonical_export 五阶段 ──► export/canonical_{json,fbs,binary,accessor} + deploy
        │
        └─► cache/fingerprints 分层指纹 + schema_workspace 的 Draft→Plan→Apply 守卫
```

### i18n 文件结构与状态机

每张含 `i18n: true` 字段的表会维护两类文件：

- `i18n/source/{table}.json` — 主语言原文快照，扁平 `{"id.field": "text"}` 格式
- `i18n/{lang}/{table}.json` — 每个 secondary 语言的译文骨架，每条目含 `source/text/confirmed/status` 四字段

写出格式紧凑（每个 key 占一行），便于翻译者扫读和 diff。key 排序按 id 数值升序、再按 schema 字段顺序。

**翻译者工作流：**
1. 打开 `i18n/{lang}/{table}.json`
2. 找到 `status: "missing"` 或 `"stale"` 的条目
3. 看 `source` 字段（永远是当前主语言原文）
4. 写 `text`，把 `confirmed` 改为 `true`
5. 下次 sync 自动转为 `translated`

**状态机（sync 时计算）：**

| 当前 source | lang 中 | text | confirmed | → status |
|---|---|---|---|---|
| ✗ | ✓ | — | — | `orphan` |
| ✓ | ✗ | — | — | `missing`（新建） |
| ✓ | ✓ | 空 | 任意 | `missing` |
| ✓ | ✓ | 非空 | true | `translated` |
| ✓ | ✓ | 非空 | false | `stale` |

主语言原文变化时，sync 强制把 `confirmed` 重置为 `false`（条目变 stale），翻译者重新审视后再设回 `true`。被删除的行/字段进入 `orphan` 状态，需要 `ct i18n compact` 显式清理。状态机实现在 `ct/export/i18n/state.py`（纯函数）；`ct/export/i18n/merger.py` 的 `load_translation` 供导出读取 lang 文件。

### 模块说明

| 模块 | 职责 |
|------|------|
| `ct/cli.py` | Typer CLI 薄壳：参数解析 + 结果渲染；全部命令走 canonical 用例 |
| `ct/config.py` | 加载 `config/global.yaml` 为 `GlobalConfig`；所有路径相对项目根目录解析 |
| `ct/app/canonical_workspace.py` | 组合根 `CanonicalWorkspace`：config + 资源图 + `table_order` + `reverse_refs`，CLI/Web/Excel/校验/生成器统一消费 |
| `ct/app/canonical_export.py` | 五阶段导出（解析校验 → JSON/各语言 bytes → Accessor/模板/manifest → FBS → Bundle）；前置校验闸门，有读取/主键/外键问题即中止 |
| `ct/app/canonical_commands.py` | canonical `validate/status/gen-template/i18n` 用例 + `canonical_validate`（类型/主键/跨表 ref 外键校验）+ `CanonicalValidationError` |
| `ct/app/schema_workspace/` | Draft → Change Plan → 原子 apply（`snapshot`/`candidate`/`plan`/`apply`/`commands_reducer`） |
| `ct/app/events.py` | 导出原语：`ProgressReporter` / `CancelToken` / `CancelledError` |
| `ct/schema/resources.py` | `Table`/`Record`/`Enum` + `FieldDef`；`TableResource` 提供派生属性（`i18n_fields`/`has_i18n`/`primary_field`/`resolved_json_key`/`resolved_excel_file`） |
| `ct/schema/type_expression.py` | 类型表达式（`scalar`/`named`/`vector<T>`）+ YAML 文本解析/序列化 |
| `ct/schema/resource_repository.py` | YAML 持久化（`config/schemas/` + `config/types/`）+ 类型解析 + 旧格式拒绝 |
| `ct/schema/resource_graph.py` | 依赖图（named/ref 边）+ 拓扑序 + 反向引用 + 删除保护 |
| `ct/schema/commands.py` | 可逆 rename 命令（资源/字段） |
| `ct/schema/hashing.py` | canonical schema 稳定 hash（检测模板漂移） |
| `ct/schema/naming.py` / `name_validation.py` | 命名校验（首字符大写、不以 `_` 开头/结尾；WYSIWYG 恒等域） |
| `ct/schema/indexes.py` / `identity.py` | 查询索引（Code/Group）/ 字段稳定身份 |
| `ct/excel/layout.py` | `Layout`：字段→Excel 列的唯一映射真源（stable_path/group/depth/annotation） |
| `ct/excel/layout_manifest.py` | Layout manifest 落 cache（schema_hash + 列布局） |
| `ct/excel/canonical_reader.py` | 按 Layout 读 Excel，重建 canonical 行（record→dict、展开 vector<Record>→按组读） |
| `ct/excel/canonical_template.py` | 生成模板工作簿 |
| `ct/excel/planning.py` | 数据搬移预检：稳定字段路径 + rename 命令 |
| `ct/export/canonical_fbs.py` | 共享 `types.fbs` + 各表 FBS + 校验 |
| `ct/export/canonical_binary.py` | 手写 FlatBuffers bytes + `DataBundle` |
| `ct/export/canonical_json.py` | `{json_key: rows}` JSON 序列化 |
| `ct/export/canonical_accessor.py` / `_model.py` | C#/Lua 共享 `AccessorModel` + 生成 |
| `ct/export/index_query.py` | Code/Group 查询 API 生成 |
| `ct/export/deploy.py` | 同步产物到 Unity Assets（`deploy(config, for_build, reporter)`） |
| `ct/export/i18n/state.py` | 翻译状态机（纯函数） |
| `ct/export/i18n/merger.py` | `load_translation`（读 lang 文件） |
| `ct/cache/fingerprints.py` | 分层指纹（schema/data/i18n[lang]/bundle）+ `decide_artifact_reuse` |
| `ct/cache/canonical_state.py` | canonical 状态持久化 |
| `ct/diagnostics/errors.py` | `Issue`/`ValidationIssue`/`WorkspaceIssue` + `render()`/`report_errors()` |
| `ct/web/app.py` | Flask 薄封装 + canonical JSON API |
| `ct/web/tasks.py` | `CanonicalExportTask` 后台导出任务（阶段上报 + 历史） |
| `ct/web/schema_workspace_api.py` | Draft/Plan/Apply 结构化 JSON API（不接受前端 YAML 文本） |
| `ct/web/history.py` / `logs.py` / `task_state.py` | 面板历史 / 日志缓冲 / 任务状态 |
| `ct/web/static/` | Vue3 前端（无构建，扁平 `static/`：`js/core`、`js/modules`、`styles`、`vendor`） |

### 关键设计决策

**canonical-only**：`_looks_canonical` 双路由已移除；CLI/Web 一律走 canonical workspace。旧 legacy 模块（`schema/models.py`、`excel/reader.py`、`export/*.py` legacy 生成器、`validate/*`、`cache/state.py`、`app/export.py` 等）已删除，不再提供旧格式迁移/兼容。

**导出校验闸门**：`run_canonical_export` 在写出产物前做完整校验（Excel 读取类型强转、主键空/重复、跨表 `ref` 外键值须存在于引用表主键集），任一问题即抛 `CanonicalValidationError`，避免脏数据落盘；CLI 渲染并退出 1，Web 任务置为 error 并记日志。

**增量 vs 全量**：canonical 当前恒全量重建；`cache/fingerprints.py` 的分层指纹（schema/data/i18n/bundle）已设计好但**尚未接线**到 `run_canonical_export`（增量复用未启用）。

**Schema 依赖排序**：`ref` 字段定义跨表外键（`ref: 目标表.字段`）、命名类型引用定义 named 依赖；`resource_graph` 做拓扑排序（命名类型先于依赖它的 Table，被引用表先于引用表），并提供反向引用与删除保护。

**Excel 表头布局**：表头行数 = `max_nesting_depth + 1`。前 `max_nesting_depth` 行是"字段名+类型"行——每个单元格用富文本堆：上面字段名（12pt 粗体白）、下面类型注解（9pt 斜体浅绿 `D8F3DC`）；最后一行是注释行。`vector<Record>` 按 `excel_columns` 展开为连续列组。

**FlatBuffers Binary 格式**：所有命名 Record/Enum 一次性、确定性依赖序发射进共享 `types.fbs`；每张表 `include "types.fbs"` 只定义自身 + `IndexEntry` 容器。每张表独立序列化为 bytes，随后打包为 `DataBundle`。`server_only` 字段在客户端 Binary 中排除；次语言 Bundle 只含主键 + i18n 字段变体。

**事务化 Schema 写入**：schema 修改不再直接写 YAML——先入 Workspace Draft（命令流 + undo/redo），生成 Change Plan（影响面/风险/阻塞），再原子 Apply（staging + 原子替换 + 并发保护 baseRevision/candidateHash + recover）。

**配置路径解析**：`config/global.yaml` 中所有路径均相对于项目根目录（含 `config/` 的目录）。通过 `cfg.resolve("key")` 获取绝对 `Path`。

---

## Schema 文件格式

canonical 资源分两类目录：

- `config/schemas/*.yaml` — 每文件一张 `Table`
- `config/types/*.yaml` — 每文件一个具名 `Record`（`kind: record`）或 `Enum`（`kind: enum`），可被多张表复用

字段类型使用**统一类型表达式**：`int32`/`int64`/`float`/`double`/`bool`/`string` 标量、具名类型（`ItemRarity`、`DropReward`）、`vector<DropReward>`。`ref: Table.Field` 定义跨表外键。`i18n` 与 `server_only` 不可同时标记，`i18n` 仅限 Table 顶层 `string` 字段，`server_only` 仅限 Table 顶层字段。

```yaml
# config/schemas/Item.yaml
table: Item
primary: Id
excel_file: item.xlsx        # 可选，默认 {table}.xlsx
json_key: items              # 可选，默认 {table}s
fields:
  - name: Id
    type: int32
  - name: Name
    type: string
    i18n: true               # 提取为翻译源字符串
  - name: ItemTypeId
    type: int32
    ref: ItemType.Id         # 跨表外键；值须存在于 ItemType 主键集
  - name: Rarity
    type: ItemRarity         # 具名 Enum（config/types/ItemRarity.yaml）
  - name: DropRange
    type: DropReward         # 具名 Record（config/types/DropReward.yaml）
  - name: Tags
    type: vector<int32>
    separator: ","
  - name: IsActive
    type: bool
    server_only: true        # 排除出客户端 FlatBuffers binary

# config/types/ItemRarity.yaml
kind: enum
name: ItemRarity
values: [Common, Rare, Epic]

# config/types/DropReward.yaml
kind: record
name: DropReward
fields:
  - {name: Min, type: int32}
  - {name: Max, type: int32}
```

约束：`i18n` 与 `server_only` 不可同时标记；`i18n` 只能用于 `string` 类型；不支持 `vector<vector<T>>`；Enum FlatBuffers wire type 固定为 `byte`。旧格式（`type: enum/struct/array` + `values/element/element_values`）会被 `resource_repository` 拒绝且不自动迁移。

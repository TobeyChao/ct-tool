# AGENTS.md

本文件为 Codex 与 Claude Code 提供该目录的工作指南。

---

## 项目概述

本仓库是 `ct`（配表导出工具）的工作空间。功能：将游戏策划数据从 **Excel + YAML Schema** 导出为 **JSON、FlatBuffers Binary 及 C#/Lua Accessor 代码**。

- `ct/` — 配表工具（自包含 Python 项目：src 布局包、web 面板、tests、docs、打包配置）
- `gd/` — 数据工作空间（config、excel、output 等）

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
│   ├── src/ct/           #   Python 包 (cli, schema, excel, export, validate, cache, web)
│   │   └── web/static/   #     面板前端资源（Vue 无构建，随包分发）
│   ├── tests/            #   pytest 测试
│   ├── docs/             #   工具文档与设计稿
│   ├── pyproject.toml    #   打包配置（src layout + package-data）
│   └── .venv/            #   虚拟环境
├── launcher/             # Flutter 桌面启动器（独立构建单元，运行时经设置指向 ct/.venv）
│   ├── lib/              #   Dart 源码（壳 + 概览/日志/设置三页签）
│   ├── macos|windows/    #   平台工程（macOS Swift 集成 / Windows 构建）
│   └── docs/design/      #   启动器设计稿
├── gd/                   # 游戏数据工作空间 (--root)
│   ├── config/           #   global.yaml + schemas/*.yaml
│   ├── excel/            #   策划填写的 Excel 数据表
│   ├── output/           #   导出产物
│   │   ├── json/         #     JSON (按语言分目录)
│   │   ├── fbs/          #     FlatBuffers Schema
│   │   ├── binary/       #     Binary Bundle (.bin)
│   │   └── generated/    #     C# / Lua Accessor
│   ├── cache/            #   增量缓存 (自动维护)
│   ├── i18n/             #   翻译文件 (source/ 原文 + {lang}/ 译文)
│   ├── tools/            #   flatc 等外部工具
│   └── scripts/          #   辅助脚本
├── openspec/             # 设计文档和任务列表
└── test-proj/            # .NET 二进制读取测试工程
```

---

## 安装

**统一使用项目 venv，不要全局安装**（macOS 上 Homebrew Python 是 PEP 668 托管环境，Windows 上全局安装易出现 pydantic 版本错配）。

```bash
cd python

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

将 `flatc.exe`（Windows）或 `flatc`（Linux/macOS）放入 `gd/tools/`。缺少时跳过 FlatBuffers 编译，但 JSON 导出不受影响。

---

## 测试

```bash
cd ct

# 运行全部测试
pytest

# 只跑某个子模块的测试
pytest tests/i18n/
pytest tests/cli/

# 只跑单个测试文件
pytest tests/i18n/test_sync.py

# 只跑单个测试函数
pytest tests/i18n/test_sync.py::test_xxx -v

# 带详细输出
pytest -v

# 显示警告/日志
pytest -p no:warnings
```

测试使用 `pytest` + `typer.testing.CliRunner`。每个测试通过 `_build_project(tmp_path)` 构造临时项目目录（schemas、excel、config），以 `CliRunner` 调用 `ct` 命令并断言退出码与输出产物。

---

## CLI 命令

所有子命令均支持 `--root DIR` 指定项目根目录（默认当前目录，应为 `gd/`）。

```bash
# 增量导出（只导出有变化的表）
ct export

# 强制全量导出
ct export --all

# 只导出指定表
ct export --table item

# 只导出指定语言
ct export --lang en

# 只校验，不输出产物（适合 CI）
ct validate
ct validate --table quest

# 查看哪些表有变化（含模板漂移检测）
ct status

# 根据 schema 生成 Excel 模板
ct gen-template --all
ct gen-template --table item

# Schema 改了？保留旧数据重建表头
ct gen-template --table item --update-header

# 强制全量覆盖（数据会丢失）
ct gen-template --table item --force

# 任意命令加 --verbose 显示详细日志
ct export --verbose

# i18n 翻译骨架与状态管理
ct i18n sync                          # 刷新 source + 为每语言生成/更新 lang 骨架
ct i18n sync --lang en --table item   # 缩小处理范围
ct i18n status                        # 翻译进度（每语言一行）
ct i18n status --by-table             # 按表细分
ct i18n status --json                 # CI 友好的 JSON 输出
ct i18n compact --dry-run             # 预览将被清理的 orphan 条目
ct i18n compact                       # 物理删除所有 orphan 条目
```

`ct export` 在校验通过后内部自动调用 sync，确保 lang 骨架与最新 source 一致。

### gen-template 决策矩阵

模板会在 Excel 的 Custom Document Properties 中写入元数据（表名、表头行数、schema 哈希、生成时间）。`gen-template` 会根据元数据状态决定行为，**绝不静默丢失数据**：

| 文件状态 | 默认行为 | `--force` | `--update-header` |
|---------|---------|-----------|------------------|
| 不存在 | 生成新模板 + 元数据 | 同左 | 同左 |
| 无元数据（legacy） | 拒绝 + 提示二选一 | 全量覆盖 | 用当前 schema header_rows 推断保留数据 |
| `ct_table_name` 不匹配 | 拒绝 | 拒绝 | 拒绝 |
| hash 一致（无变化） | 跳过 | 重建 | 重建 |
| hash 不同 + 无数据 | 直接重建 | 重建 | 重建 |
| hash 不同 + 有数据 | 拒绝 + 提示二选一 | 全量覆盖 | 保留数据重建 |

`ct status` 同时输出"数据变更"（Excel 文件 hash 与缓存不一致）与"模板漂移"（schema 修改后未重建模板）两类状态。

---

## 架构

### 数据流

```
config/schemas/*.yaml  ──►  Schema 加载 + 拓扑排序（按 ref 依赖关系）
excel/*.xlsx           ──►  Excel 读取（openpyxl 只读模式）
                              │
                              ▼
                        类型校验 + 引用校验
                              │
                     ┌────────┴────────────────┐
                     ▼                         ▼
              i18n sync 流程              导出流水线
       (i18n/source/{table}.json     JSON + FBS + Binary Bundle
        + i18n/{lang}/{table}.json)
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

主语言原文变化时，sync 强制把 `confirmed` 重置为 `false`（条目变 stale），翻译者重新审视后再设回 `true`。被删除的行/字段进入 `orphan` 状态，需要 `ct i18n compact` 显式清理。

### 模块说明

| 模块 | 职责 |
|------|------|
| `ct/cli.py` | Typer CLI 薄壳：参数解析 + 结果渲染；编排逻辑见 `ct/app/` |
| `ct/config.py` | 加载 `config/global.yaml` 为 `GlobalConfig` Pydantic 模型；所有路径相对项目根目录解析 |
| `ct/app/workspace.py` | 组合根 `Workspace`：root + config + 拓扑排序后的 schemas，所有用例的第一个参数 |
| `ct/app/options.py` | 用例参数对象（如 `ExportOptions`），收拢结伴出现的参数 |
| `ct/app/events.py` | 导出管道原语：`ProgressReporter` / `CancelToken` / `CancelledError` |
| `ct/app/export.py` | 导出管道：`ExportStep` 步骤序列（解析校验 → i18n sync → JSON → FBS → flatc → Accessor → Bundle）+ `ExportResult`；取消时不写 `state.json` |
| `ct/app/validate.py` | 共享解析校验阶段 `parse_and_validate`（读 Excel + 类型/引用校验 + id 集合） |
| `ct/app/template.py` | `gen-template` 决策矩阵集中实现：根据文件状态 × 用户 flag 输出 Action 枚举与说明信息 |
| `ct/app/status.py` | `ct status` 用例：`compute_status` 分类数据变更 / 模板漂移 / 未跟踪 / 缺失，返回 `StatusReport`（CLI 只渲染） |
| `ct/app/i18n.py` | i18n 用例编排：`read_i18n_rows` 为 sync 准备行数据，返回 `ReadRowsResult`（含缺失文件列表） |
| `ct/schema/models.py` | Pydantic 模型：`TableSchema` 和 `FieldDef`。支持字段类型：`int32`、`int64`、`float`、`double`、`bool`、`string`、`enum`、`struct`、`array` |
| `ct/schema/loader.py` | 依据 `ref` 字段构建依赖图并拓扑排序（格式无关，只认 canonical 模型） |
| `ct/schema/repository.py` | Schema 源抽象 `SchemaRepository` + YAML 实现：`load_all()` 读取 schema，`fbs_sources()` 提供各表 .fbs 文本（未来 .fbs 源经 `schema_format` 切换） |
| `ct/schema/conventions.py` | fbs 结构标准 `FbsConvention` + 检查器：类型映射、容器/root_type 结构、"类型名与字段名不撞名"不变量 + flatc 编译校验 |
| `ct/schema/hashing.py` | 计算 TableSchema 的稳定 hash（sha256 前 16 位 hex），用于模板元数据比对检测 schema 漂移 |
| `ct/schema/naming.py` | 命名校验器 `validate_name`：表/字段名必须首字符大写、不以 `_` 开头/结尾（WYSIWYG 恒等域，schema 加载即校验，不再做任何大小写转换） |
| `ct/excel/reader.py` | 以只读模式读取 Excel，返回 `ParsedRows`（`rows` + 与之一一对应的 `excel_rows` 绝对行号）。struct 字段展开为多列；array 字段在单元格内按 `separator` 分隔。表头行数 = `max_nesting_depth + 1` |
| `ct/excel/diff.py` | 对比 Excel 文件 MD5 hash 与缓存，输出已变更的表名列表 |
| `ct/excel/template.py` | 根据 schema 生成带多行表头的空白 Excel 文件；模板元数据读写 `read_template_metadata`、表头保留重建 `update_template`、共享数据行遍历 `iter_data_rows` |
| `ct/validate/errors.py` | 结构化问题模型 `Issue` / `ValidationIssue`（含 `row_index` / `excel_row` / `column` / `value`）/ `WorkspaceIssue`；`render()` 输出 `Excel 第N行 · 列X (字段) · 当前值 ...`，无绝对定位信息时回退旧格式 |
| `ct/validate/types.py` | 按字段类型逐一校验；主键唯一性检查；填充 `excel_row` / `column`（struct 定位到具体叶子列），返回 `ValidationIssue` |
| `ct/validate/refs.py` | 利用已解析行数据和缓存中的 ID 集合进行跨表外键校验；填充 `excel_row` / `column`，返回 `ValidationIssue` |
| `ct/export/json_writer.py` | 写出 `output/json/{table}_{lang}.json`，根键为 `schema.resolved_json_key` |
| `ct/export/fbs_generator.py` | 生成 Bundle 容器 `container.fbs`；各表 `.fbs` 文本由 SchemaRepository 提供 |
| `ct/export/flatc_runner.py` | 调用 `flatc` 编译 `.fbs` 为各语言 Accessor 代码 |
| `ct/export/binary_writer.py` | 手动将行数据序列化为 FlatBuffers bytes（无生成的 Python Accessor）；打包为 `DataBundle` 二进制（`output/binary/data_{lang}.bin`） |
| `ct/export/accessor_model.py` | 访问器生成共享模型 `AccessorModel`（client/string/i18n 字段 + 主键），C# 与 Lua 生成器消费同一模型 |
| `ct/export/csharp_accessor_generator.py` | 生成 C# Accessor 类至 `output/generated/csharp/` |
| `ct/export/lua_accessor_generator.py` | 生成 Lua Accessor 模块至 `output/generated/lua/` |
| `ct/export/i18n/extractor.py` | 将 `i18n: true` 字段的主语言原文提取为 `i18n/source/{table}.json`（扁平 `{"id.field": "text"}` 格式） |
| `ct/export/i18n/state.py` | 翻译状态机：`LangStatus` 枚举 + `merge_lang_entry` / `sync_lang_table`（计算每条目的 `status` 与字段更新规则） |
| `ct/export/i18n/sync.py` | sync 编排：刷新 source 文件 + 为每语言每表生成/更新 lang 骨架，返回 `SyncSummary` |
| `ct/export/i18n/merger.py` | 将 `i18n/{lang}/{table}.json` 中 `confirmed=true` 的译文合并回行数据；其他状态回退主语言并 warning |
| `ct/export/i18n/counts.py` | 共享状态计数 `StatusCounts`（translated/missing/stale/orphan + total/progress + 聚合）+ `count_entries()` |
| `ct/export/i18n/status.py` | 基于 `StatusCounts` 聚合每语言每表进度，提供 default/by-table/json 三种渲染 |
| `ct/export/i18n/writer.py` | 导出后基于 lang 文件汇总各语言的 stale/missing/orphan 统计 |
| `ct/export/i18n/compact.py` | `ct i18n compact` 用例：物理移除 orphan 条目，返回 `CompactSummary`（CLI 只渲染） |
| `ct/export/i18n/io.py` | 紧凑 JSON 写出（每个 key 一行）+ key 排序（id 数值升序 + schema 字段顺序） |
| `ct/cache/state.py` | 读写 `cache/state.json`（每表存储文件 MD5 hash、ID 列表、fbs bytes hash）；同时在 `cache/fbs_bytes/*.bin` 中缓存原始 FlatBuffers bytes，未变化的表可复用 |

### 关键设计决策

**增量导出**：缓存记录每个 Excel 文件的 MD5 hash。`ct export` 时只重新解析 hash 变化的文件；未变化的表直接复用缓存中的 FlatBuffers bytes。最终 Binary Bundle 始终全量重写（新鲜 bytes + 缓存 bytes 合并）。

**Schema 依赖排序**：`ref` 字段定义跨表外键（`ref: 目标表名.字段名`）。loader 对所有 schema 做拓扑排序，确保被引用表先于引用表完成校验。

**Excel 表头布局**：表头行数 = `max_nesting_depth + 1`。前 `max_nesting_depth` 行是"字段名+类型"行——每个单元格内用富文本（`CellRichText`）堆两段：上面字段名（12pt 粗体白），下面类型注解（9pt 斜体浅绿 `D8F3DC`）。struct 单元格的类型显示 `{field.name}Struct`，与 FBS 生成的 table 名一致。最后一行是注释行。struct 字段按叶子字段展开为连续列（2 个子字段占 2 列）。

**FlatBuffers Binary 格式**：每张表各自序列化为独立 bytes，随后打包为 `DataBundle`（见 `container.fbs`）。`server_only` 字段在客户端 Binary 中排除。次语言 Bundle（`data_{lang}.bin`）只包含主键 + i18n 字段变体。

**配置路径解析**：`config/global.yaml` 中所有路径均相对于项目根目录（含 `config/` 的目录）。通过 `cfg.resolve("key")` 获取绝对 `Path`。

---

## Schema 文件格式

Schema 存于 `config/schemas/*.yaml`，每文件定义一张表：

```yaml
table: item          # 唯一表名
primary: id          # 主键字段名
excel_file: item.xlsx  # 可选，默认 {table}.xlsx
json_key: items        # 可选，默认 {table}s
fields:
  - name: id
    type: int32
  - name: name
    type: string
    i18n: true         # 提取为翻译源字符串
  - name: item_type_id
    type: int32
    ref: item_type.id  # 外键；item_type 必须存在于 schemas
  - name: rarity
    type: enum
    values: [common, rare, epic]
  - name: drop_range
    type: struct
    fields:
      - {name: min, type: int32}
      - {name: max, type: int32}
  - name: tags
    type: array
    element: int32
    separator: ","
  - name: is_active
    type: bool
    server_only: true  # 排除出客户端 FlatBuffers binary
```

约束：`i18n` 与 `server_only` 不可同时标记；`i18n` 只能用于 `string` 类型；不支持 `array<struct>`。

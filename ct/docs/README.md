# ct - 配表导出工具

将 YAML Schema + Excel 数据表导出为 JSON、FlatBuffers Binary、C# / Lua Accessor 的一站式 CLI 工具。

---

## 目录

- [安装说明](#安装说明)
- [flatc 安装指引](#flatc-安装指引)
- [Schema 格式文档](#schema-格式文档)
- [CLI 命令说明](#cli-命令说明)
- [目录结构](#目录结构)
- [i18n 翻译流程](#i18n-翻译流程)
- [输出产物](#输出产物)

---

## 安装说明

工具源码位于 `ct/`，工作空间（Excel 数据、配置、导出产物）位于 `gd/`。

### 方式一：开发模式安装（推荐）

```bash
cd tool
pip install -e .
```

以可编辑模式安装，修改源码后无需重新安装。安装完成后 `ct` 命令在任意目录均可用。

### 方式二：仅安装依赖

```bash
cd tool
pip install -r requirements.txt
```

依赖列表：

| 包名         | 最低版本 | 用途                 |
| ------------ | -------- | -------------------- |
| openpyxl     | 3.1.0    | 读写 Excel 文件      |
| flatbuffers  | 24.0     | FlatBuffers 序列化   |
| typer        | 0.9.0    | CLI 框架             |
| pydantic     | 2.0      | Schema 数据模型校验  |
| pyyaml       | 6.0      | 读取 YAML 配置文件   |

> **Python 版本要求：** >= 3.10

---

## flatc 安装指引

`flatc` 是 FlatBuffers 的编译器，用于将 `.fbs` schema 编译为对应语言的读取代码。

### 步骤

`flatc` 使用**本地编译**的自研 fork（[TobeyChao/flatbuffers](https://github.com/TobeyChao/flatbuffers)，
commit `6c035fc9`，含 `--lua-snake-input` 选项），不再使用官方预编译产物。

1. **编译 flatc**
   克隆 fork 后在仓库根目录执行：
   ```bash
   cmake -S . -B build -G "Visual Studio 18 2026" -A x64
   cmake --build build --target flatc --config Release
   ```
   （macOS/Linux 去掉 `-G`/`-A` 参数即可；产物位于 `build/Release/flatc.exe` 或 `build/flatc`）

2. **放入 `tools/` 目录**
   将编译出的 `flatc`（Windows 下为 `flatc.exe`）放入项目根目录的 `tools/` 文件夹中：
   ```
   项目根目录/
   └── tools/
       └── flatc        # Linux / macOS
       └── flatc.exe    # Windows
   ```
   > 注：ct 的 Lua 目标依赖 fork 的 `--lua-snake-input` 选项，官方原版 flatc 缺少该选项，
   > 请勿用官方二进制覆盖。

3. **配置路径**
   在 `config/global.yaml` 中确认 `flatc_path` 指向正确路径：
   ```yaml
   flatc_path: tools/flatc
   ```
   路径相对于项目根目录。如果 flatc 安装在系统 PATH 中，也可以直接写可执行文件名。

4. **验证**
   运行导出命令时，工具会自动检测 flatc 是否存在。如果未找到，会输出警告并跳过 FlatBuffers 编译步骤（JSON 导出不受影响）。

---

## Schema 格式文档

每张数据表对应一个 YAML schema 文件，存放在 `config/schemas/` 目录下。

### 命名规范（所写即所得）

工具**不做任何大小写转换**：schema 里写的名字（表名、字段名）原样出现在
C#/Lua/JSON/Excel 全部产物中。命名必须满足（schema 加载时校验，违规直接报错）：

- 表名、字段名使用 **PascalCase**（首字符大写，如 `Item`、`ItemTypeId`）
- 不得以 `_` 开头或结尾
- enum 值保持原样（如 `common`、`Page`），不做转换

> 命名校验由 `ct/schema/naming.py` 的 `validate_name` 在加载时执行。
> 类型名（enum/struct 的 FBS 类型）自动加后缀：enum → `{字段名}Enum`、
> struct → `{字段名}Struct`（如 `Rarity` 字段 → `RarityEnum`），避免字段名与
> 类型名同名（flatc 拒绝字段名 == 类型名）。

### 基本结构

```yaml
table: item              # 表名（唯一标识）
primary: id              # 主键字段名
excel_file: item.xlsx    # 可选，默认为 {table}.xlsx
json_key: items          # 可选，JSON 输出的根键名，默认为 {table}s
fields:                  # 字段定义列表
  - name: id
    type: int32
  - name: name
    type: string
    i18n: true
  # ... 更多字段
```

| 顶层字段      | 必填 | 说明                                             |
| ------------- | ---- | ------------------------------------------------ |
| `table`       | 是   | 表名，作为唯一标识符                             |
| `primary`     | 是   | 主键字段名，必须出现在 fields 列表中             |
| `fields`      | 是   | 字段定义列表                                     |
| `excel_file`  | 否   | 对应的 Excel 文件名，默认 `{table}.xlsx`         |
| `json_key`    | 否   | JSON 输出时的根键名，默认 `{table}s`             |

### 字段类型

#### 基础类型

| 类型     | 说明           | Excel 中的填写方式      |
| -------- | -------------- | ----------------------- |
| `int32`  | 32 位有符号整数 | `100`                   |
| `int64`  | 64 位有符号整数 | `9999999999`            |
| `float`  | 32 位浮点数     | `3.14`                  |
| `double` | 64 位浮点数     | `3.141592653589793`     |
| `bool`   | 布尔值         | `true` / `false`        |
| `string` | 字符串         | 任意文本                |

#### 枚举类型（enum）

定义一组有限的枚举值：

```yaml
- name: rarity
  type: enum
  values: [common, rare, epic]
```

- `values` 必须为非空列表
- 每个值必须是合法的标识符（字母、数字、下划线，不以数字开头）
- 在 FlatBuffers 中序列化为从 0 开始的整数索引

#### 结构体类型（struct）

用于嵌套对象，包含子字段列表：

```yaml
- name: drop_range
  type: struct
  fields:
    - name: min
      type: int32
    - name: max
      type: int32
```

- `fields` 必须为非空列表
- struct 内**不允许嵌套 array**
- struct 的子字段支持所有基础类型、enum 和 string

#### 数组类型（array）

定义一组同类型的值列表：

```yaml
- name: tags
  type: array
  element: int32
  separator: ","
```

- `element` 指定数组元素类型，支持所有基础类型和 `enum`
- `separator` 为 Excel 单元格内的分隔符，默认 `,`
- **不支持** `array<struct>`，如需一对多关系请使用独立子表 + `ref`
- 若 element 为 `enum`，需额外提供 `element_values` 列表

### 字段标记

| 标记          | 适用类型 | 说明                                                         |
| ------------- | -------- | ------------------------------------------------------------ |
| `i18n: true`  | string   | 标记该字段需要国际化。i18n 字段会被提取到翻译文件中，并在导出时生成多语言变体 |
| `ref`         | int32 等 | 外键引用，格式为 `目标表名.目标字段名`，例如 `ref: item.id`   |
| `server_only` | 任意     | 标记该字段仅用于服务端。导出 FlatBuffers Binary 时会被排除    |

> **注意：** `i18n` 和 `server_only` 不能同时标记在同一字段上。i18n 字段用于客户端 UI 展示，server_only 字段不进入客户端 Binary。

### 完整示例

```yaml
table: item
primary: id
fields:
  - name: id
    type: int32

  - name: name
    type: string
    i18n: true
    comment: 道具名称

  - name: price
    type: float

  - name: rarity
    type: enum
    values: [common, rare, epic]

  - name: item_type_id
    type: int32
    ref: item_type.id

  - name: drop_range
    type: struct
    fields:
      - name: min
        type: int32
      - name: max
        type: int32

  - name: tags
    type: array
    element: int32
    separator: ","

  - name: is_active
    type: bool
    server_only: true
```

---

## CLI 命令说明

安装后使用 `ct` 命令。所有子命令均支持 `--root DIR` 指定项目根目录（默认当前目录）。

### `ct export` - 增量导出

```bash
ct export [OPTIONS]
```

主流程命令。解析 Excel、校验数据、导出 JSON / FlatBuffers Binary / Accessor。

| 选项             | 说明                                   |
| ---------------- | -------------------------------------- |
| `--all`          | 强制全量导出所有表（忽略增量缓存）     |
| `--table NAME`   | 只导出指定的单张表                     |
| `--lang LANG`    | 只导出指定语言（如 `zh`、`en`）        |
| `--verbose`      | 显示详细日志                           |
| `--root DIR`     | 项目根目录                             |

示例：

```bash
# 增量导出（只导出有变化的表）
ct export

# 全量导出所有表
ct export --all

# 只导出 item 表
ct export --table item

# 只导出英文版本
ct export --lang en

# 指定项目目录
ct export --all --root /path/to/project
```

### `ct validate` - 只校验不导出

```bash
ct validate [OPTIONS]
```

只执行解析和校验流程，不生成任何输出产物。适合 CI/CD 中快速检查数据正确性。

| 选项             | 说明               |
| ---------------- | ------------------ |
| `--table NAME`   | 只校验指定的单张表 |
| `--verbose`      | 显示详细日志       |
| `--root DIR`     | 项目根目录         |

示例：

```bash
# 校验所有表
ct validate

# 只校验 quest 表
ct validate --table quest
```

### `ct gen-template` - 生成 Excel 模板

```bash
ct gen-template [OPTIONS]
```

根据 Schema 定义生成带表头与元数据（表名、表头行数、schema 哈希、生成时间）的 Excel 模板。**绝不静默丢失已填数据**：根据元数据状态自动决定行为。

| 选项                 | 说明                                                                  |
| -------------------- | --------------------------------------------------------------------- |
| `--all`              | 生成所有表的模板                                                      |
| `--table NAME`       | 只生成指定表的模板                                                    |
| `--force`            | 文件已存在时强制全量覆盖（数据丢失，需用户显式确认）                  |
| `--update-header`    | 文件已存在时保留旧数据行原样追加到新表头之下（推荐用于 schema 变更）  |
| `--root DIR`         | 项目根目录                                                            |

> 必须指定 `--all` 或 `--table` 之一。

**决策矩阵：**

| 文件状态                  | 默认行为              | `--force`        | `--update-header`         |
| ------------------------- | --------------------- | ---------------- | ------------------------- |
| 不存在                    | 生成新模板 + 元数据   | 同左             | 同左                      |
| 无元数据（legacy 文件）   | 拒绝 + 提示二选一     | 全量覆盖         | 用当前 schema 推断保留数据 |
| `ct_table_name` 不匹配    | 拒绝（任何 flag 拒绝） | 拒绝             | 拒绝                      |
| hash 一致（无变化）       | 跳过                  | 重建             | 重建                      |
| hash 不同 + 无数据        | 直接重建              | 重建             | 重建                      |
| hash 不同 + 有数据        | 拒绝 + 提示二选一     | 全量覆盖         | 保留数据重建表头          |

示例：

```bash
# 生成所有表的 Excel 模板
ct gen-template --all

# Schema 改了？保留旧数据重建表头
ct gen-template --table item --update-header

# 强制全量覆盖（数据会丢失）
ct gen-template --table item --force
```

### `ct status` - 查看变更状态

```bash
ct status [OPTIONS]
```

同时检查两类状态：
- **数据变更**：Excel 文件 hash 与缓存不一致（待导出）
- **模板漂移**：当前 schema_hash 与 Excel 元数据中的 `ct_schema_hash` 不一致（schema 改了但模板未重建）

| 选项         | 说明       |
| ------------ | ---------- |
| `--root DIR` | 项目根目录 |

输出示例：

```
缺失文件:
  [missing] new_table

数据变更（待导出）:
  [changed] item

模板已过时（schema 修改后未重建）:
  [template-stale] quest  (建议: ct gen-template --table quest --update-header)

未跟踪元数据（legacy 文件）:
  [template-untracked] shop
```

无任何状态时输出 `[OK] 所有表已是最新（数据 + 模板）`。

### `ct i18n` - 翻译骨架与状态管理

`ct i18n` 子命令组用于维护 i18n 翻译文件。`ct export` 内部会自动调用 sync，确保 lang 骨架与最新 source 一致；以下命令用于翻译者独立操作。

#### `ct i18n sync` - 刷新 source 与 lang 骨架

```bash
ct i18n sync [OPTIONS]
```

扫描所有 i18n 字段：写出 `i18n/source/{table}.json`（主语言原文），并为每个 secondary 语言生成或更新 `i18n/{lang}/{table}.json` 骨架。

| 选项               | 说明                                          |
| ------------------ | --------------------------------------------- |
| `--lang LANG`      | 只处理指定语言的 lang 文件（source 仍全量刷新） |
| `--table NAME`     | 只处理指定表                                  |
| `--verbose`        | 打印每个写入文件的路径                        |
| `--root DIR`       | 项目根目录                                    |

#### `ct i18n status` - 翻译进度报告

```bash
ct i18n status [OPTIONS]
```

| 选项               | 说明                                       |
| ------------------ | ------------------------------------------ |
| `--lang LANG`      | 只显示指定语言                             |
| `--by-table`       | 按表细分（每语言每表一行）                 |
| `--json`           | 输出机器可读 JSON，供 CI 解析              |
| `--root DIR`       | 项目根目录                                 |

默认输出示例：

```
[en]   85% [########..] 170/200 translated, 12 missing, 8 stale, 10 orphan
```

#### `ct i18n compact` - 清理 orphan 条目

```bash
ct i18n compact [OPTIONS]
```

物理移除 lang 文件中所有 `status: orphan` 条目（其他状态不动）。

| 选项               | 说明                                  |
| ------------------ | ------------------------------------- |
| `--lang LANG`      | 只处理指定语言                        |
| `--table NAME`     | 只处理指定表                          |
| `--dry-run`        | 仅打印将被删除的条目，不修改文件      |
| `--root DIR`       | 项目根目录                            |

---

## 目录结构

```
项目根目录/
├── config/
│   ├── global.yaml          # 全局配置（语言、路径等）
│   └── schemas/             # 表 Schema 定义（每张表一个 .yaml）
│       ├── item.yaml
│       ├── item_type.yaml
│       └── quest.yaml
├── excel/                   # Excel 数据表（策划填写）
│   ├── item.xlsx
│   ├── item_type.xlsx
│   └── quest.xlsx
├── output/                  # 导出产物输出目录
│   ├── json/                #   JSON 文件（按语言分目录）
│   │   ├── zh/
│   │   └── en/
│   ├── fbs/                 #   FlatBuffers Schema 文件（.fbs）
│   ├── binary/              #   FlatBuffers Binary Bundle（.bin）
│   └── generated/           #   生成的 Accessor 代码
│       ├── csharp/          #     C# Accessor
│       └── lua/             #     Lua Accessor
├── cache/                   # 增量导出缓存（自动生成，勿手动编辑）
│   ├── state.json           #   每表的 Excel hash、ID 集合、schema_hash、fbs bytes hash
│   └── fbs_bytes/           #   未变化表的 FlatBuffers bytes 缓存
├── i18n/                    # 国际化翻译文件（按语言/表二维拆分）
│   ├── source/              #   主语言原文快照（工具自动维护）
│   │   ├── item.json        #     扁平 {"id.field": "text"} 格式
│   │   └── quest.json
│   └── en/                  #   英文译文骨架（翻译者维护 text/confirmed）
│       ├── item.json        #     {"id.field": {source, text, confirmed, status}}
│       └── quest.json
├── tools/                   # 外部工具
│   └── flatc                #   FlatBuffers 编译器
├── ct/                      # 工具源码
├── pyproject.toml           # 项目元数据和依赖配置
└── requirements.txt         # pip 依赖列表
```

| 目录       | 用途                                                                                        |
| ---------- | ------------------------------------------------------------------------------------------- |
| `config/`  | 全局配置文件和表 Schema 定义。`global.yaml` 控制语言、路径等全局设置；`schemas/` 下每表一个 YAML |
| `excel/`   | 策划维护的 Excel 数据表，文件名与 Schema 中的 `excel_file` 对应                              |
| `output/`  | 所有导出产物的输出目录，包括 JSON、.fbs、Binary Bundle 和生成的 Accessor 代码                 |
| `cache/`   | 增量导出的缓存数据，记录文件 hash 以判断哪些表有变化。由工具自动管理，不应手动修改            |
| `i18n/`    | 国际化文件，按"语言/表"二维拆分。`source/` 由工具自动维护（主语言原文），`{lang}/` 由翻译者维护译文 |

---

## i18n 翻译流程

每张含 `i18n: true` 字段的表会维护两类文件：

- `i18n/source/{table}.json` — 主语言原文快照，扁平 `{"id.field": "text"}`，由 `ct i18n sync` / `ct export` 自动写出
- `i18n/{lang}/{table}.json` — 每个 secondary 语言的译文骨架，每条目含四字段：

```json
{
  "1001.name": {"source": "铁剑", "text": "Iron Sword", "confirmed": true, "status": "translated"}
}
```

### 翻译者工作流

1. 运行 `ct i18n sync` 生成或刷新所有 lang 文件骨架
2. 打开 `i18n/{lang}/{table}.json`，找到 `status: "missing"` 或 `"stale"` 的条目
3. 看 `source` 字段（永远是当前主语言原文），写 `text`，把 `confirmed` 改为 `true`
4. 下次 sync 自动转为 `translated`，导出时即被 `ct export` 合并入译文

### 状态机

| 当前 source 中 | lang 中 | text | confirmed | → status      |
| -------------- | ------- | ---- | --------- | ------------- |
| ✗              | ✓       | —    | —         | `orphan`      |
| ✓              | ✗       | —    | —         | `missing`（新建） |
| ✓              | ✓       | 空   | 任意      | `missing`     |
| ✓              | ✓       | 非空 | true      | `translated`  |
| ✓              | ✓       | 非空 | false     | `stale`       |

**关键规则：**
- 主语言原文变化时，sync 会强制把 `confirmed` 重置为 `false`（条目变 `stale`），`text` 保留以便对照旧译文
- 被删除的行/字段进入 `orphan` 状态，需要 `ct i18n compact` 显式清理
- 仅 `confirmed=true` 且 `text` 非空的条目会被 `ct export` 用于次语言产物，其余回退主语言并输出 warning

---

## 输出产物

`ct export` 命令执行后会在 `output/` 目录下生成以下产物：

### 1. JSON 文件

- 路径：`output/json/{lang}/{table}.json`
- 每张表、每种语言各生成一个 JSON 文件
- 适用于编辑器预览、调试、Web 端加载等场景

### 2. FlatBuffers Schema（.fbs）

- 路径：`output/fbs/{Table}.fbs`、`output/fbs/container.fbs`
- 根据 Schema 自动生成的 `.fbs` 定义文件
- 可用 flatc 编译为各语言的序列化/反序列化代码

### 3. Binary Bundle（.bin）

- 路径：`output/binary/data_{lang}.bin`
- 将所有表的 FlatBuffers 数据打包为单个二进制文件
- 主语言 Bundle（如 `data_zh.bin`）包含完整数据（排除 `server_only` 字段）
- 次语言 Bundle（如 `data_en.bin`）只包含 i18n 字段的翻译变体
- 客户端运行时加载主 Bundle + 当前语言 i18n Bundle 即可

### 4. C# Accessor

- 路径：`output/generated/csharp/{Table}Accessor.cs`
- 自动生成的 C# 读取类，提供类型安全的字段访问接口
- 可直接集成到 Unity 项目中使用

### 5. Lua Accessor

- 路径：`output/generated/lua/{table}_accessor.lua`
- 自动生成的 Lua 读取模块
- 适用于 xLua 等 Lua 运行时环境

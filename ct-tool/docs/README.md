# ct - 配表导出工具

将 YAML Schema + Excel 数据表导出为 JSON、FlatBuffers Binary、C# / Lua Accessor 的一站式 CLI 工具。

---

## 目录

- [安装说明](#安装说明)
- [flatc 安装指引](#flatc-安装指引)
- [Schema 格式文档](#schema-格式文档)
- [CLI 命令说明](#cli-命令说明)
- [目录结构](#目录结构)
- [输出产物](#输出产物)

---

## 安装说明

工具源码位于 `ct-tool/`，工作空间（Excel 数据、配置、导出产物）位于 `gd/`。

### 方式一：开发模式安装（推荐）

```bash
cd ct-tool
pip install -e .
```

以可编辑模式安装，修改源码后无需重新安装。安装完成后 `ct` 命令在任意目录均可用。

### 方式二：仅安装依赖

```bash
cd ct-tool
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

1. **下载 flatc**
   前往 [FlatBuffers GitHub Releases](https://github.com/google/flatbuffers/releases) 页面，下载与操作系统对应的预编译 `flatc` 可执行文件。

2. **放入 `tools/` 目录**
   将下载的 `flatc`（Windows 下为 `flatc.exe`）放入项目根目录的 `tools/` 文件夹中：
   ```
   项目根目录/
   └── tools/
       └── flatc        # Linux / macOS
       └── flatc.exe    # Windows
   ```

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

根据 Schema 定义生成带有表头的空白 Excel 模板文件，方便策划开始填表。

| 选项             | 说明                     |
| ---------------- | ------------------------ |
| `--all`          | 生成所有表的模板         |
| `--table NAME`   | 只生成指定表的模板       |
| `--root DIR`     | 项目根目录               |

> 必须指定 `--all` 或 `--table` 之一。

示例：

```bash
# 生成所有表的 Excel 模板
ct gen-template --all

# 只生成 item 表的模板
ct gen-template --table item
```

### `ct status` - 查看变更状态

```bash
ct status [OPTIONS]
```

对比当前 Excel 文件的 hash 与缓存，列出哪些表发生了变更。

| 选项         | 说明       |
| ------------ | ---------- |
| `--root DIR` | 项目根目录 |

输出格式：

```
  [changed] item         # 有变化，需要重新导出
  [  ok   ] quest        # 无变化
  [missing] new_table    # Excel 文件不存在
```

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
│   └── export_cache.json    #   记录每张表的文件 hash 和 ID 集合
├── i18n/                    # 国际化翻译文件
│   ├── source.json          #   从 Excel 提取的源语言字符串
│   └── en.json              #   英文翻译（人工或机翻填写）
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
| `i18n/`    | 国际化相关文件。源语言字符串自动提取，翻译文件由翻译人员维护                                  |

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

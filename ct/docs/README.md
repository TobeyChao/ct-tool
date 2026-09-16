# ct — 配表导出工具

把 **Excel 数据表 + YAML Schema** 导出为 **JSON / FlatBuffers Binary / C#·Lua Accessor** 的一站式 CLI。

> 本文 2026-09-12 按**当前实现**重写。此前版本多处与实现不符（小写 schema、`type: array` + `separator`、
> 内联 `struct`、JSON/生成物路径、`binary_writer`），已全部更正。
> 格式契约的权威来源是 `openspec/specs/flatbuffers-export/spec.md`。

## 目录

- [快速开始](#快速开始)
- [工作区结构](#工作区结构)
- [Schema 格式](#schema-格式)
- [具名类型资源](#具名类型资源)
- [Schema 工作台：新增资源与保存](#schema-工作台新增资源与保存)
- [i18n 翻译流程](#i18n-翻译流程)
- [导出产物](#导出产物)
- [二进制格式](#二进制格式)
- [部署到 Unity](#部署到-unity)
- [CLI 命令](#cli-命令)
- [会报错的写法速查](#会报错的写法速查)

---

## 快速开始

```bash
cd ct/
python -m venv .venv && .venv/bin/pip install -e .     # 依赖：openpyxl / flatbuffers / typer / pydantic / pyyaml / flask

cd <工作区>              # 含 config/ excel/ 等，如 fabulous-game 的 Config/gd
ct export                # 增量导出（默认复用未变更产物；--all 强制全量重建）
ct status                # 看哪些表待导出
```

Python ≥ 3.10。所有子命令都支持 `--root DIR` 指定工作区根目录（默认当前目录）。

---

## 工作区结构

工作区根目录（`--root`）的布局；路径在 `config/global.yaml` 里配置：

```
<工作区>/
├── config/
│   ├── global.yaml        # 语言、路径、deploy 配置
│   ├── schemas/           # 每张表一个 YAML（table: <Name>）
│   └── types/             # 具名类型资源：kind: record / kind: enum
├── excel/                 # 策划填写的数据表（{Table}.xlsx）
│   └── layout_manifests/  # 每表一份列路径映射 + 定宽偏移（**需入库**）
├── i18n/
│   ├── source/            # 主语言原文快照（工具自动维护）
│   └── {lang}/            # 各次语言译文骨架（翻译者维护）
├── output/                # 导出产物（见下）
├── cache/                 # 增量缓存 + 成功账本（工具自动维护，勿手改）
└── .ct/                   # 私有状态（**建议加入 .gitignore**）
    ├── export.lock        # export/deploy 的工作区排他锁
    └── export-publication.json   # 仅发布进行中存在；中断恢复用
```

`.ct/` 是工具的私有目录，**固定在工作区根下**，不随 `cache_dir` 变化——否则换个
缓存目录就会各锁各的、恢复记录也会失联。它只包含锁与一次发布的恢复记录：
`export.lock` 是空的（**文件存在不代表锁被占用**，占用与否由系统 advisory lock
决定，进程退出会自动释放）；`export-publication.json` 只在一次发布进行期间存在，
成功后即被清理，内容损坏时工具会报错并**保留材料**而不是静默删除。

`config/global.yaml`：

```yaml
primary_lang: zh
secondary_langs: [en, ja]
schemas_dir: config/schemas
types_dir: config/types          # 默认值
excel_dir: excel
output_dir: output
cache_dir: cache
i18n_dir: i18n
deploy:                          # 可选；见「部署到 Unity」
  enabled: true
  unity_project: ../../Client
  targets: [...]
  build_targets: [...]
```

---

## Schema 格式

### 命名规范（WYSIWYG，写什么就是什么）

工具**不做任何大小写转换**。schema 里写的表名/字段名原样出现在 C#、Lua、JSON、Excel 全部产物中。

- 表名、字段名用 **PascalCase**（首字符大写，如 `Item`、`ItemTypeId`）
- 不得以 `_` 开头或结尾
- 枚举值保持原样（如 `common`、`Panel`），但必须是合法标识符

> 违规在**加载时**直接报错（`ct/schema/naming.py`）。

### 表（Table）

```yaml
table: Item                 # 表名（唯一标识）
primary: Id                 # 主键字段名，必须在 fields 里；**必须是 int32**（索引向量/idHash/ByID(int) 都是 32 位），且不能 server_only
json_key: Items             # 可选，JSON 根键；默认 {Table}s
excel_file: Item.xlsx       # 可选，Excel 文件名；默认 {Table}.xlsx
fields:
  - name: Id
    type: int32
    comment: "道具唯一 ID，禁止修改"
  - name: Name
    type: string
    i18n: true
    comment: "道具名称（多语言）"
  - name: Price
    type: float
  - name: Rarity
    type: ItemRarity        # 具名 enum → config/types/ItemRarity.yaml
  - name: ItemTypeId
    type: int32
    ref: ItemType.Id        # 跨表引用
  - name: DropRange
    type: ItemDropRange     # 具名 record → config/types/ItemDropRange.yaml
  - name: Tags
    type: vector<int32>     # 向量
  - name: IsActive
    type: bool
    server_only: true
```

### 字段类型

**标量**（12 种，`type` 直接写名字）：

| | | | |
|---|---|---|---|
| `int8` | `uint8` | `int16` | `uint16` |
| `int32` | `uint32` | `int64` | `uint64` |
| `float` | `double` | `bool` | `string` |

**向量**：`vector<T>` 文本类型表达式，`T` 为标量、enum 或 record。

- Excel 单元格里用**英文逗号**的 `[1,2,3]` 文法
- ⚠️ `separator` 字段**已移除**（写了直接报错）
- ⚠️ 只支持**一层**：`vector<vector<T>>` 被拒；要嵌套请用具名 Record 包装
- `vector<Record>` 必须额外声明 `excel_columns: N`（定长展开 N 组列）
- `vector<enum>` 在 JSON 里是枚举名，Lua 侧是序号

**具名类型**：直接写类型名（如 `type: ItemRarity`），定义放 `config/types/`。

### 字段标记

| 标记 | 适用 | 说明 |
|---|---|---|
| `comment` | 任意 | 生成到模板表头与产物注释 |
| `i18n: true` | **仅顶层标量 `string`** | 提取到翻译源；导出时生成稀疏 i18n 表。⚠️ record 字段与 `vector<string>` 都**不允许**标 |
| `ref` | 标量 | 跨表主键外键，`目标表.主键`（如 `ItemType.Id`）；目标不是该表主键（含字段名打错）在加载/候选校验阶段报错 |
| `server_only: true` | 任意 | 排除出客户端二进制；⚠️ 主键不能标，且不能与 `i18n` 同标 |
| `excel_columns: N` | `vector<T>` | 定长展开 N 组列（`vector<Record>` 必填） |

### 表级查询索引

目前只有 `codename` 一种（每张表最多一个）：

```yaml
indexes:
  - kind: codename      # 精确字符串查找；**不写 field**，固定指向名为 CodeName 的 string 字段
```

`codename` 是一个**约定的固定字段名**，不是「随便指一个 string 字段」——与 参考实现 的
flags `1<<1 CodeName` 同构。所以「表里没有 CodeName 字段 / 它不是 string / 它带 i18n /
它是 server_only」都会在**加载期**报错，而不是等导出。
非标量字段（`vector`、`i18n`、`server_only`）不能做索引字段。

**声明了索引的表，每一行的 `CodeName` 必须非空且唯一** —— 导出期（`解析校验` 阶段）硬报错，
`ct validate` 同样拦（`IssueCode.DUPLICATE_CODENAME`）。为什么必须有这道闸门：建桶表时对空串
跳过、也**不判重**，所以两行写同一个 `CodeName` 时导出**不报错**，而运行期 `ByCodeName()` 只
命中探测序更靠前的那个 —— 另一行**永远查不到**且毫无提示；空值那一行同理。

> 曾经还有一种 `kind: group`（按 int32/bool/Enum 字段做一对多分组查找），**已砍掉**：
> 没有任何表声明过它，Lua 侧始终是占位 stub，而且导出器会静默丢掉「group 列留空」的行
> ——那些行读出来是默认值 `0`，却不在 key `0` 的组里。要重新做，见游戏仓
> `Docs/TODO/开工方案.md` 里留的计划（含这条默认值语义必须一并解决）。

---

## 具名类型资源

`config/types/*.yaml`，每个文件一个资源：

**enum** — 顺序**即 wire 序号**：

```yaml
kind: enum
name: ItemRarity
comment: "稀有度"
values:
  - name: common      # 第 0 项 = 默认值（值为它时槽位不写、读回 0）
    comment: 普通
  - name: rare
  - name: epic
```

> ⚠️ **不要重排** `values`：顺序变了默认值语义与填充率都会变。

**record**（等价于 FlatBuffers 的嵌套 table）：

```yaml
kind: record
name: ItemDropRange
comment: "掉落范围"
fields:
  - name: Min
    type: int32
  - name: Max
    type: int32
```

> ⚠️ record 字段**不允许** `i18n` / `server_only`（schema 层硬报错）。
> 这条约束由 schema 层独占负责 —— 下游导出/生成两层**不会报错，只会静默忽略**。

---

## Schema 工作台：新增资源与保存

Web 面板的 Schema 页可以在不手写 YAML 的前提下新建 Table / Record / Enum：

- **入口**：模块头部「新增 Schema」（自选类别）、每个资源分组右侧「＋」（预选该类别）、
  空工作区里的空状态入口（同一个表单）。
- **最小合法内容**：Table 只填名称/注释，自动带固定 `primary: Id` + `Id: int32`（不自动加
  CodeName 或索引）；Record 必填首个字段（名称 + 类型，可直接选引用）；Enum 必填首个具名项
  （ordinal 从 0 按输入顺序派生）。空名称、不合法名称、跨类别重名、空 Record/Enum 都会被拦下。

### 草稿 → 保存 → 模板 → 导出 的边界

| 阶段 | 做了什么 | 不做什么 |
|---|---|---|
| 草稿 | 命令流 + undo/redo cursor 存在 IndexedDB（按工作区隔离）；状态条显示**净变化资源数** | 不写任何文件；重命名/往返改名按**最终结构**归零 |
| 预检 | 新增/添加字段前调 `POST /api/schema-workspace/candidate`（带当前草稿前缀）确认拟新增命令 | 预检通过**不是**持久化授权；服务端保存时再次校验 |
| 保存 | `POST /api/schema-workspace/save`：按 `schemaRevision` + `candidateHash` 复核，只发布**实际变化**的资源 YAML（新增/删除/重命名/引用更新同一事务） | 不读 Excel、不改 layout manifest、不动 i18n/output/成功账本；零差异请求不写文件 |
| 模板 | 保存只刷新**只读**状态；需要时点「更新模板」显式调用 `gen-template`（新表必须先保存） | 保存绝不自动重建工作簿；模板失败独立展示，不回滚已保存的 YAML |
| 导出 | `ct export` 读取前核对可信 manifest + 真实受管表头结构；Enum token 域与 CodeName 数据闸门在读取阶段拦截 | 布局证明不了就拒绝读取，且不借导出刷新 manifest 掩盖漂移 |

并用草稿的同一份候选派生所有视图（资源树、计数、Quick Open、类型选择器、引用选择器、
反向引用）：新建的 Record/Enum 立即可作字段类型，新建的 Table 只作为 `Table.Field` 引用
目标出现（**不会**进具名类型列表），无需中间保存。

### API 命令示例（面板内部使用，不接受前端 YAML 文本）

```jsonc
// 新增 Enum / Record / Table（payload.kind 与 resource.kind 必须一致）
{"type":"add_resource","payload":{"kind":"enum","resource":{"kind":"enum","name":"ItemRarity",
  "values":[{"name":"Common","comment":"普通"}]}}}
{"type":"add_resource","payload":{"kind":"record","resource":{"kind":"record","name":"DropReward",
  "fields":[{"name":"Min","type":"int32"}]}}}
{"type":"add_resource","payload":{"kind":"table","resource":{"table":"Quest","primary":"Id",
  "fields":[{"name":"Id","type":"int32"},{"name":"Rarity","type":"ItemRarity"}]}}}

// 预检：commands 是当前草稿前缀 + 拟新增命令
POST /api/schema-workspace/candidate  {"commands":[ ... ]}
// → {"ok":true,"data":{"resources":[...],"issues":[...],"netDiff":{...},"candidateHash":"...","schemaRevision":"..."}}

// 保存：只写实际变化的 YAML
POST /api/schema-workspace/save
  {"schemaRevision":"<快照基线>","commands":[ ... ],"candidateHash":"<预检得到的 hash>"}
// → 200 {"ok":true,"data":{"isNoOp":false,"written":["/…/config/types/ItemRarity.yaml"],"deleted":[],
//          "notes":[...],"schemaRevision":"<新基线>","resources":[...]}}（data 内还有 unchanged / changedResources / netDiff / recovery 等键）
// → 400 结构问题（issues 带 commands[i].payload.resource.… 定位）
// → 409 conflict.kind ∈ schema-revision | candidate-hash | target | legacy-apply | legacy-apply-recovered；
//    工作区忙时同样返回 409，但响应只带 "busy": true（无 conflict 对象）

// 模板（显式、按表）：新 Table 保存后才能生成
POST /api/schema-workspace/gen-template  {"table":"Quest"}
```

---

## i18n 翻译流程

含 `i18n: true` 字段的表维护两类文件：

- `i18n/source/{Table}.json` —— 主语言原文快照，扁平 `{"Id.字段": "文本"}`，**只由 `ct i18n sync` 写出**（`ct export` 从不写 source）
- `i18n/{lang}/{Table}.json` —— 次语言骨架，每条四字段：

```json
{ "1.Name": {"source": "药水", "text": "Potion", "confirmed": true, "status": "translated"} }
```

**翻译者工作流**：`ct i18n sync` → 改 `text` 并把 `confirmed` 置 `true` → 下次导出即被合并。

**状态**（`translated` / `missing` / `stale` / `orphan`）：

| source 中有 | lang 中有 | text | confirmed | → status |
|---|---|---|---|---|
| ✗ | ✓ | — | — | `orphan` |
| ✓ | ✗ | — | — | `missing` |
| ✓ | ✓ | 空 | 任意 | `missing` |
| ✓ | ✓ | 非空 | true | `translated` |
| ✓ | ✓ | 非空 | false | `stale` |

- 主语言原文一变，sync 就把 `confirmed` 重置为 `false`（条目变 `stale`），`text` 保留以便对照
- 被删的行/字段变 `orphan`，用 `ct i18n compact` 显式清理
- **只有 `confirmed=true` 且 `text` 非空的条目**才进入次语言产物；其余回退主语言原文并告警
- 进度 = `translated / (total − orphan)`

---

## 导出产物

```
output/
├── json/{Table}_{lang}.json      # 每表每语言一份（根键 = json_key，默认 {Table}s）
├── fbs/{Table}.fbs               # 每表一份
├── fbs/types.fbs                 # record / enum 具名类型
├── fbs/container.fbs             # 容器表（槽位约定见下）
├── binary/data_{lang}.bin        # 每语言一个 Bundle
└── generated/
    ├── csharp/{Table}Accessor.cs、Enums.cs
    └── lua/{Table}Accessor.lua、Enums.lua
```

- **主语言 Bundle**（`data_zh.bin`）= 各表全量（排除 `server_only`）
- **次语言 Bundle**（`data_en.bin`）= 各表的**稀疏 i18n 表**（`{Table}_i18n`：主键 + i18n 字段，行序与主表 1:1）
- 客户端加载「主 Bundle + 当前语言 i18n Bundle」即可；切语言只换后者

> `.fbs` 是**结构参考文本**：`flatc` 已退役，二进制由 `export/canonical_binary.py` 直接构建。

**生成物形态**（生成器契约，详见 spec）：

- C# 在命名空间 `GameFramework.ConfigGen`；行类型以表名命名（`Item`，**无 `Row` 后缀**），嵌套 record 同规则
- Lua 模块名 `{Table}Accessor`，经工作区的 `Config.<Table>` 懒加载注册表访问
- 定宽（uniform）表的字段读发射**字面量偏移**；非定宽发射 vtable 槽位
- **行 / record 的每个 getter 都带开发期世代守卫**，且必须用 `#if` **源码级**包住：

  ```csharp
  public int Min
  {
      get
      {
          #if CONFIG_DEBUG || UNITY_EDITOR || DEVELOPMENT_BUILD
          TableVersion.Check(_version);
          #endif
          return WireReader.I32At(_row, 4);
      }
  }
  ```

  为什么逐字段检查：行 / record 是**值类型**，只存裸指针 + 世代号，可以被存进字段 / 容器 /
  闭包跨重载存活；句柄过期后 `_row` 指向已释放（或被复用）的内存，读出来是**静默错值**
  —— 不是异常也不是 null。所以过期检查没有别的地方可放。

  为什么必须是 `#if` 而不是「常驻调用 + 发布期空实现」：后者实测有热路径回归
  （`deployed-perf-bench` 同会话交替 A/B 五轮稳定复现：float32 字段读 **+12.7%**、定宽 `.Id` +9.8%；
  常驻空调用让部分 getter 失去内联资格）。发布包里这些 getter 必须与「没有守卫」逐字节一致，
  所以调用点只能根本不存在。ct 侧有 `assert_guarded_getters()` 把这个形状钉成断言。

---

## 二进制格式

每张表在 Bundle 里是一个**容器表**（`container.fbs`），槽位约定：

| slot | 内容 | 说明 |
|---:|---|---|
| 0 | `items` | 行向量 |
| 1 | `index` | 主键**有序**的 `(key, row)` 对，stride 8。**仍是行的来源** |
| 2 | `idHash` | 主键哈希桶，存「index 位置 + 1」，`0` = 空 |
| 3 | `codeNameIndex` | CodeName 索引桶，存 `rowIndex + 1`，key = FNV-1a 64 |

> slot 4 / 5 曾归 Group 索引（`groupIndex` + `groupHash`），**已砍**，槽位空出。

**两条查询路径都是 O(1) 哈希，读端不做二分**：

- **主键**：`b = (key × 2654435761) & (slots−1)`，线性探测，命中后按 `index[pos]` 确认
- **CodeName**：FNV-1a 64 取低位，命中后按字段做精确字符串确认

> `idHash` 对每张表**必然产出**（`primary` 是必填项）。读端**没有**二分兜底：缺 `idHash` 会在建表期（C#）
> 或首次查询时（Lua/原生）**硬报错**，不会静默返回空。

**定宽（uniform）布局**：由表 schema 的 `uniform` 键**声明**（缺省 `true`；`uniform: false` 退回变长读）。
声明为定宽的表所有行共享同一 vtable，于是 slot→行内偏移是**表级常量**，生成器直接发射字面量偏移
（省掉每次读的 vtable 走查；部署版实测 `OffsetsFor` 为 1 种 vtable 2.24ns / 2 种 7.71ns）。
布局由 Schema 确定：字段按实际宽度对齐，对象大小补齐到最大对齐值；字符串、向量与 Record 在行内占 4 字节引用。
写入端与 Accessor 共用布局计划，不再通过空白行探测偏移。每个定宽对象（含嵌套 Record）写出后校验实际偏移和大小；变长负载不影响行内布局。
填充率 **SHALL NOT** 参与该决策：它只是导出输出里的诊断数字 —— 导出日志每行以**布局形态**（取自声明）开头，
填充率与体积比随后，不写成「填充率 → 布局」，否则会被读成已删除的数据派生规则；定宽体积超过常规 1.25x 时会在同一行给提示。
修改布局后必须重新导出 Binary 和 Accessor，不能混用旧产物。
slot→偏移落在 `excel/layout_manifests/{Table}.json`（**需入库**，供跨端迁移用）；**填充率与定宽声明都不落盘** ——
manifest 的字段集合是 schema 的纯函数，改 Excel 数据不会让它变。

---

## 部署到 Unity

`config/global.yaml` 里配 `deploy:` 后，CLI 的 `ct export` 在导出完成后自动同步
（由 `ct/src/ct/cli.py` 的 `_deploy_for_service` 回调在导出之后触发，`_run_deploy()` 是独立
`ct deploy` 命令的入口；**web 面板的导出不会部署**，它只导出产物到 `output/`）：

```yaml
deploy:                            # 可选；整段不配 或 enabled: false ⇒ 导表行为与没有 deploy 时完全一致
  enabled: true
  unity_project: ../../Client      # Unity 工程根目录：相对**工作区根**（project_root，即 --root）解析，或写绝对路径
  targets:                         # 常规目标：source 相对工作区根解析；dest 相对 unity_project 解析
    - {source: output/binary,           dest: Assets/Content/Config}          # → <unity_project>/Assets/Content/Config
    - {source: output/generated/csharp, dest: Assets/Scripts/Config/Gen}
    - {source: output/generated/lua,    dest: Assets/Scripts/Lua/Config/Gen}
  build_targets:                   # 仅在 --for-build 时追加；裸跑 ct export / ct deploy 不部署这些目标
    - {source: output/binary,           dest: Assets/StreamingAssets/Config}
```

**路径语义（写错必踩坑）**：

| 配置项 | 解析基准 | 说明 |
|---|---|---|
| `unity_project` | **工作区根**（`project_root`） | 相对路径 ⇒ `<工作区>/<unity_project>`；绝对路径按原样使用。留空 ⇒ 不部署 |
| `source` | **工作区根** | 与 `schemas_dir` / `output_dir` 等同一基准，例如 `output/binary` ⇒ `<工作区>/output/binary` |
| `dest` | **`unity_project`**（Unity 工程根） | 例如 `Assets/Content/Config` ⇒ `<unity_project>/Assets/Content/Config` |

- `enabled: false` 或整段 `deploy:` 缺失 ⇒ `ct export` / `ct deploy` 都不做任何部署动作，行为与引入 deploy 前一致。
- `build_targets` **只在** `ct export --for-build` / `ct deploy --for-build` 时追加到 `targets` 之后；不带该 flag 时被忽略。

同步语义：目标目录被同步为与源**完全一致** —— 新增写入、变化覆盖、**多余删除**
（代码产物同步时保留已存在文件的 `.meta`；产物被删则连带删同名 `.meta`）。
内容不变则不写，避免无谓的 mtime 变化触发 Unity 重导入。

> 方向是**单向**的：tool 产出 → 工程消费。别把工程里的产物反向写回 `output/`。

---

## CLI 命令

| 命令 | 作用 |
|---|---|
| `ct export` | 导出主流程（默认增量复用，`--all` 强制重建） |
| `ct deploy` | 只把**当前产物**同步到 Unity，不触发导出 |
| `ct validate` | 只解析校验，不产出 |
| `ct gen-template` | 按 schema 生成 Excel 模板表头 |
| `ct status` | 列出缺失 / 数据变更 / 模板漂移；另有「未完成的发布」提示（非空才打印） |
| `ct panel` | 启本地面板（浏览器打开即用） |
| `ct i18n sync` | 刷新 source + 生成/更新各语言骨架 |
| `ct i18n status` | 报告翻译进度 |
| `ct i18n compact` | 物理移除 `orphan` 条目 |

**常用选项**

```bash
ct export [--all] [--table T] [--lang L] [--verbose] [--for-build] [--root DIR]
ct deploy [--for-build] [--root DIR]
ct validate [--table T] [--verbose] [--root DIR]
ct gen-template (--all | --table T) [--root DIR]
ct status [--root DIR]
ct panel [--host 127.0.0.1] [--port 8000] [--no-browser] [--root DIR]
ct i18n sync    [--lang L] [--table T] [--verbose] [--root DIR]
ct i18n status  [--lang L] [--by-table] [--json] [--root DIR]
ct i18n compact [--lang L] [--table T] [--dry-run] [--root DIR]
```

### `ct export` 的增量语义

- 默认完整读取、校验 Excel（含主键与跨表 ref），校验通过后按生成器版本和实际输入复用 JSON、表级 bytes、Accessor、FBS 与 Bundle。缓存位于 `cache/artifacts/`，缺失或损坏会自动重建；完整导出成功后回收本次未使用的旧缓存。
- 输出内容一致时不重写，保留文件时间戳；缺失或被修改的产物会恢复。layout manifest 按**规范序列化逐字节比较**：内容一致即不重写（也会顺带清掉磁盘上遗留的已废弃键）。
- 翻译按实际合并结果参与缓存；仅改 JSON 排版、派生状态或 orphan 条目不会重建产物。Accessor 的输入包含**schema 声明的**定宽布局，因此只有改 schema（含 `uniform`）才重新生成 —— 改 Excel 数据不会。
- `--all` 强制重新生成并写出选中范围内的所有产物。
- 无 `--table` / `--lang` 过滤时，在生成成功后删除已不需要的旧产物，不再清空整个输出目录。
- `--table T` / `--lang L` 保留既有范围语义（Bundle 也仅包含所选表）；过滤导出不清理范围外产物。
- `cache/state.json` 继续记录成功导出及部署后的 Excel 状态；纯生成缓存独立维护，不代表导出或部署已经成功。修改生成器行为时需更新 `CODEGEN_VERSION`。

#### 缓存、账本与发布的关系

| 东西 | 是什么 | 失败时会怎样 |
|---|---|---|
| `cache/artifacts/` | 生成缓存（内容寻址） | **可丢弃**：损坏/缺失自动重建，失败运行也可以留下有效条目 |
| `cache/state.json` | 成功账本（`ct status` 的判据） | **只有本地发布与（CLI 下）部署都成功才推进**；失败保持上一次成功记录 |
| `.ct/export-publication.json` | 一次发布的恢复记录 | 只覆盖本次要改写的文件；成功后清理 |

「账本不变」不等于「所有 cache 文件不变」：生成缓存是中间物，账本才是「这批数据
确实导出并部署过」的凭证。

#### 一次导出的写入边界

- 全部生成与 FBS/定宽检查通过后，才在一个**可恢复事务**里改写正式输出与
  `excel/layout_manifests/`；任一步失败会回滚到发布前状态（内容与 mtime），
  生成阶段失败则**完全不碰**正式产物。
- 全量导出时，陈旧产物的删除也在同一事务内 —— 中断后下次会自动找回来。
- 同一工作区的 export/deploy **互斥**：重复发起会立即以「工作区正在导出/部署」
  失败，不会静默排队。进程被强杀不会留下永久阻塞（锁由系统释放），下次
  export/deploy 会先恢复未完成的发布再继续。

#### 明确不提供的保证

- **外部编辑不受锁保护**：Excel、译文、schema 在捕获之后被改动会被检测到并中止
  （不会把新版本冒充成本次已导出），但工具不阻止外部写入。
- **跨工作区共享同一个物理输出目录**不在互斥保证内；不同 `--root` 各自独立加锁。
- `ct validate` / `ct status` 是**只读**的：它们会报告未完成或损坏的发布，但不会
  执行恢复、也不写任何文件。
- Schema 保存与导出/部署**共用同一把工作区锁与同一个可恢复发布器**：保存期间
  导出会立即以「工作区正在保存、导出或部署」失败，反之亦然；两者不会各自发布半套文件。

`ct status` 的真实输出（缺文件 / 数据变更 / 模板漂移 / 未完成发布，只在非空时打印；全新鲜时只有一行）：

```
缺失文件:
  [missing] NewTable
数据变更（待导出）:
  [changed] Item
模板已过时（schema 修改后未重建）:
  [template-stale] Quest  (建议: ct gen-template --table Quest)
未完成的发布:                                    ← 存在未完成/损坏的恢复记录时
  [publication] 存在未完成的发布（operation …, 阶段 publishing）

[OK] 所有表已是最新（数据 + 模板）      ← 以上都空时
```

---

## 会报错的写法速查

| 写法 | 结果 |
|---|---|
| `table: item`（小写） | ❌ 命名校验失败 |
| `type: array` + `element:` | ❌ 已改为文本类型表达式 `vector<int32>` |
| `separator: ","` | ❌ 字段已移除；vector 用内置 `[...]` 文法 |
| 内联 `type: struct` + `fields:` | ❌ 只支持具名类型（`config/types/`） |
| `vector<vector<T>>` | ❌ 要嵌套请用具名 Record 包装 |
| `vector<Record>` 缺 `excel_columns` | ❌ 必填 |
| `excel_columns` 用在非 vector 上 | ❌ 仅适用于 `vector<T>` |
| 主键标记 `server_only` | ❌ 主键必须进客户端二进制 |
| 主键类型不是 `int32`（含 `int64`/`int8`/`uint*`） | ❌ |
| 整数列的值超出其声明类型的值域（如 `int32` 列填 `5000000000`） | ❌ 解析校验阶段报类型错误 |
| `i18n: true` 标在非**标量 string** 上（含 `vector<string>`） | ❌ |
| 同一字段同时 `i18n` + `server_only` | ❌ |
| record 字段标 `i18n` / `server_only` | ❌ schema 层报错（下游不会报，只会静默忽略） |
| `indexes` 的 CodeName 字段不是 string（或带 i18n / server_only / 是 vector） | ❌ |

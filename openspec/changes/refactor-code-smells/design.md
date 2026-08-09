## Context

现状已逐项核实（见 proposal.md Why 的动机；本节只列影响方案的约束）：

- `cli.py` 仍内联三块用例逻辑：`status()` 的模板漂移分类（读模板元数据 +
  算 schema hash）、`i18n_compact` 的文件操作（open + 筛 orphan + del +
  dump_lang_file）、`_read_all_rows_for_sync` 编排；`i18n_sync` 还在 CLI
  预过滤 schema 后又把 `table_filter` 传给 `sync_all` 二次过滤。
- `JsonStep.run`（app/export.py）一个函数做 JSON 写出、主表 fbs bytes
  构建+缓存、i18n bytes 构建+缓存、cache hash 更新四件事。
- `binary_writer.py` 内有三份类型分派链：`_build_struct` 与
  `build_table_bytes` 的槽位写入、`_build_array` 的元素写入。
- **C#/Lua 访问器生成器零测试覆盖**（无 golden）；重构前必须先落特征测试。
- i18n 计数三处重复：`TableSyncStats`（sync.py）、`TableCounts` /
  `LangCounts`（status.py）、`report_stale_summary`（writer.py）；
  状态比较 sync 用 `LangStatus` 枚举，status/writer 用字符串字面量。
- 重复小工具：`_column_span`（reader/template 各一份）、`_resolve_flatc`
  （conventions/flatc_runner 各一份）、`_load_lang_file` 与
  `load_translation` 实现相同、`_has_data_rows` 与 `update_template`
  的"跳过表头找非空行"遍历重复。
- 死代码已 grep 验证零调用：`csharp_accessor_generator.py` 的 `_BB_READ` /
  `_field_slot_index` / `_i18n_field_slot_index` / `_voffset`（四个全无调用，
  生成路径直接使用 flatc 产出的访问器方法名，不存在槽位索引逻辑）、
  `get_cached_ids`、`serialize_row`/`write_json` 的
  `exclude_server_only` 参数、`TableSyncStats.created/updated`、
  `WorkspaceIssue.detail`、sync.py 未使用的 `load_source_file` import。
- `AccessorStep` 用 `except ImportError: pass` 静默吞掉生成器导入失败；
  `ExportPipeline` 取消时 `tables_exported` 返回计划表数而非实际完成数。

## Goals / Non-Goals

**Goals:**

- CLI 可观察行为逐字不变，pytest 全绿为验收线；仅修两处失败路径缺陷；
- 用例逻辑下沉到应用层，Change 3 网页面板直接复用
  status / compact / export 用例接口；
- 收敛重复分派链与重复小工具，删除零调用死代码，消除静默失败；
- 按《重构》原则小步推进：每个阶段独立绿、可提交、可单独 revert。

**Non-Goals:**

- 不改 flatc 失败时 CLI 退出码（既有行为决策，归面板 / 独立行为变更）；
- 不修"缓存键缺 schema hash"（行为变更，独立 change，archives 已有记录）；
- 不做任何界面实现；
- 不改导出产物格式：JSON / binary bytes / fbs / accessor 文本逐字不变；
- 不把全部 7 处类型分派统一成全局策略注册表（YAGNI，见 D3 备选）。

## Decisions

### D1. 用例下沉：status / compact / sync 读表

分层依据：`compact` 与 `sync` 同属 i18n 领域操作（读写 lang 文件），归
`ct/export/i18n/`（与 sync.py 并列）；`status` 跨 Excel / 模板元数据 /
cache 三类来源做组合，归 `ct/app/`；`read_i18n_rows` 是为 sync 准备数据的
用例编排（调 domain 的 read_excel），归 `ct/app/`。

**`ct/app/status.py`** —— 把 `cli.status()` 的分类逻辑整体搬移（搬移函数
8.1），返回结构化报告，CLI 只渲染：

```python
@dataclass(frozen=True)
class StatusReport:
    changed: list[str]      # 数据变更（待导出）
    drifted: list[str]      # 模板已过时
    untracked: list[str]    # legacy 文件无元数据
    missing: list[str]      # Excel 文件缺失

def compute_status(ws: Workspace, cache: CacheState) -> StatusReport: ...
```

内部复用 `get_changed_tables` / `read_template_metadata` /
`compute_schema_hash`，逻辑与现 CLI 完全一致；渲染文本
（`[changed]` / `[template-stale]` / `[template-untracked]` /
`[missing]` / `[OK]`）留在 CLI presenter，逐字不变。**顺序约定**：
各组内按 `ws.order`（拓扑顺序）排列；分组输出顺序沿用现 CLI
（missing → changed → drifted → untracked），保证渲染逐字一致。

**`ct/export/i18n/compact.py`** —— 把 `cli.i18n_compact` 的文件操作搬移为
用例（拆分阶段 6.11），返回 summary：

```python
@dataclass(frozen=True)
class CompactFileResult:
    lang: str
    table: str
    removed_keys: list[str]

@dataclass
class CompactSummary:
    dry_run: bool
    touched: bool
    total_removed: int
    files: list[CompactFileResult]

class CompactError(ValueError): ...

def compact_i18n(cfg, schemas, *, lang=None, table=None, dry_run=False) -> CompactSummary: ...
```

内部复用 `load_translation` / `dump_lang_file`；lang 不在
`secondary_langs` 时抛 `CompactError`，CLI catch 后输出现有文案并
`Exit(1)`（`CompactError` 消息即现 CLI 文案
`语言 '{lang}' 不在 secondary_langs 中`）。`files` **只含检查过且有
orphan 条目的文件**（无 orphan 的文件不产生条目，与现 CLI 只输出
touched 文件一致）；dry_run 时 `removed_keys` 为"将移除"的 key，
非 dry_run 为"已移除"的 key。CLI 的渲染文本（`[dry-run]` / `[compact]` /
`[compact] 无 orphan 条目，无需操作` / `[compact] 总计移除 N 条`）
逐字保留。

**`ct/app/i18n.py::read_i18n_rows(cfg, schemas)`** —— 从
`cli._read_all_rows_for_sync` 整体搬移，返回结构化结果（app 层不 print）：

```python
@dataclass(frozen=True)
class ReadRowsResult:
    rows_by_table: dict[str, list[dict]]
    missing: list[tuple[str, Path]]      # (table, xlsx_path)

def read_i18n_rows(cfg, schemas) -> ReadRowsResult: ...
```

CLI 遍历 `missing` 渲染 `[warn] {path} 不存在，跳过 {table}`（逐字不变）。
`i18n_sync` 的 `--table` **保留表存在性校验**（不存在时报错退出，行为不变），
只把过滤职责归 `sync_all`（删除 CLI 预过滤后的二次过滤）。

### D2. JsonStep 关注点分离（提炼函数 6.1）

步骤序列与日志文本不变，仅把 `JsonStep.run` 按关注点拆私有方法：

- `_export_changed_table(ctx, name, schema, rows, langs)`：写 JSON → 构建并
  缓存主表 fbs bytes → 构建并缓存 i18n bytes → 更新 cache；
- `_reuse_unchanged_table(ctx, name, schema, langs)`：复用缓存 bytes；
- 内部再拆 `_write_json` / `_build_and_cache_bytes` / `_update_cache`。

**备选**：拆成独立步骤（Json / FbsBytes / CacheCommit）——否决：改变步骤
序列与未来面板的进度展示，收益小风险大；提炼函数已消除"一函数管四件事"。

### D3. binary_writer 类型分派收敛（函数组合成类 6.9 / 查表取代条件链）

- 槽位写入提炼 `_prepend_slot(builder, slot, type_name, value)`，配一张
  `_SCALAR_SLOT_WRITERS: dict[str, Callable]`（含默认值），
  `_build_struct` 与 `build_table_bytes` 共用；offset 预构建
  （string/struct/array）保留两遍结构。
- `_build_array` 元素分派同样查表 `_ELEMENT_VECTOR_WRITERS`。
- reader 的 `_coerce` / `_coerce_element` 提炼共享标量转换 helper
  `_coerce_scalar(value, type_name)`，行为逐字不变（保留 int64 的
  `int(float(value)) if "." in value else int(value)` 等细节）。
  **注意两者 int 转换语义不同**：`_coerce` 处理 Python 值（`int(value)`），
  `_coerce_element` 处理字符串（`int(float(value)) if "." in value else
  int(value)`），共享时用参数区分或保留分层，不得盲目合并。

**备选**：为每种字段类型建策略类（以多态取代条件表达式 10.4）——否决：
字段类型是闭集，查表足够；全局注册表等 schema 类型扩展需求出现再评估。

### D4. Accessor 生成器模型化（拆分阶段 6.11）

新增 `ct/export/accessor_model.py`：

```python
@dataclass(frozen=True)
class AccessorModel:
    schema: TableSchema
    client_fields: list[FieldDef]      # 非 server_only
    string_fields: list[FieldDef]
    i18n_fields: list[FieldDef]
    primary: FieldDef

def build_accessor_model(schema: TableSchema) -> AccessorModel: ...
```

**明确不含槽位索引**：已核实 C# 生成器的 `_BB_READ` / `_field_slot_index` /
`_i18n_field_slot_index` / `_voffset` 全部零调用，Lua 生成器也没有任何
槽位逻辑——为模型发明 slots 属于 Speculative Generality。模型只承载两个
生成器真正重复计算的派生数据（字段筛选），C# 类型映射留在 C# 生成器内；
槽位相关死代码随 D7 直接删除。两个生成器消费同一模型，各自渲染语言文本。

**先补 golden 特征测试再动手**（重构第一原则：先有安全网）：固定两个样例
schema 把当前 C# / Lua 生成文本存为期望快照，断言逐字一致；改完生成器后
该断言验证零漂移。样例覆盖面明确为：样例 A = i18n string + enum +
array<int32> + server_only int32；样例 B = struct（含 int32 / string
子字段）+ 普通标量（int32 / int64 / float / double / bool）。

**备选**：合并成一个"代码生成 DSL"——否决：两语言差异大，过度抽象；
共享模型 + 各自渲染是收益/复杂度最优。

### D5. i18n 计数统一（函数组合成类 6.9）

新增 `ct/export/i18n/counts.py`：

```python
@dataclass(frozen=True)
class StatusCounts:
    translated: int = 0
    missing: int = 0
    stale: int = 0
    orphan: int = 0
    def total(self) -> int: ...
    def progress(self) -> float: ...   # 与现状一致：active = total - orphan

def count_entries(entries: dict[str, dict]) -> StatusCounts: ...
```

- sync.py：`TableSyncStats` 由 `StatusCounts` 承担，删除 `created/updated`
  及其聚合（无展示消费）；`StatusCounts` 提供 `__add__`（值对象语义，
  返回新实例），`totals_by_lang()` 用 `agg = agg + stats` 聚合，返回
  `dict[str, StatusCounts]`（现有测试只断言 `.missing`，兼容）；
- status.py：`TableCounts` / `LangCounts` 组合 `StatusCounts`，并保留
  原有字段属性（`translated` / `missing` / `total` / `progress` 等转发到
  `StatusCounts`），render 函数本身无需改动，输出不变；
- writer.py：`report_stale_summary` 用 `count_entries` + `LangStatus` 枚举；
- status.py / writer.py 的字符串状态比较统一改用 `LangStatus` 枚举
  （与 sync.py 一致）。

### D6. 重复小工具收敛（提炼函数 6.1 / 搬移函数 8.1）

- `_column_span` 上移为 `FieldDef.column_span()` 方法（schema/models.py，
  不引入跨层依赖），reader / template 删除本地副本；
- `conventions._resolve_flatc` 公开为 `resolve_flatc_path()`，
  `flatc_runner` import 复用，删除本地副本（export 依赖 schema，方向正确）；
- sync.py 删 `_load_lang_file`，改用 `load_translation`（实现完全相同）；
- `ct/excel/template.py::iter_data_rows(path, header_rows) -> Iterator[tuple]`
  产出表头下的非空行——**"非空"定义为任一单元格 `not None`**（与现
  `_has_data_rows` / `update_template` 的判断一致，不是字符串 strip 语义；
  **生成器，不预收集**）；`app/template.py::_has_data_rows`
  改为 `any(iter_data_rows(...))` 短路返回（现状即为找到首行非空即返回，
  list 化会丢失短路；顺带消除 app 层对 openpyxl 的直接依赖——内幕交易
  3.19），`update_template` 需要全量数据时再 `list(...)`。

### D7. 死代码清理（移除死代码 8.9）

已 grep 验证零调用（`load_source_file` 在 tests 有使用 → 函数保留，
只删 sync.py 的未用 import）：

- `csharp_accessor_generator.py` 的 `_BB_READ` / `_field_slot_index` /
  `_i18n_field_slot_index` / `_voffset`（生成路径不使用，见 D4）；
- `get_cached_ids`（cache/state.py）；
- `serialize_row` / `write_json` 的 `exclude_server_only` 参数（调用方均
  未传；JSON 产物行为不变——server_only 字段照常输出）；
- `TableSyncStats.created/updated` 与聚合（随 D5 删除）；
- `WorkspaceIssue.detail`（零调用；`Issue.to_dict` 保留，供未来面板）；
- sync.py 未使用的 `load_source_file` import。

### D8. 失败路径修复

- **AccessorStep 不再静默吞 ImportError**：两个生成器 import 移到
  `ct/app/export.py` 模块顶部（AccessorStep 定义于该文件），删除
  `try/except ImportError`。生成器只依赖 pathlib + schema.models，
  无循环 import，失败即真实 bug，应直接暴露。
- **取消计数语义**：`ExportContext` 增加 `exported_tables: list[str]`；
  `JsonStep` 在 `_export_changed_table` 与 `_reuse_unchanged_table`
  完成时都记录表名（两种路径都算"已处理"）；取消时
  `tables_exported=len(ctx.exported_tables)`。CLI 无取消入口
  （`CancelToken` 从不被 cancel），行为不可观察；面板受益。

### D9. 实施节奏：七阶段，每阶段独立绿

```
A 死代码清理（纯删，零风险）
B 重复小工具收敛（纯搬移/上移）
C i18n 计数统一（共享模型替换，render 不变）
D CLI 用例下沉（status / compact / sync 读表 → app 层）
E JsonStep 关注点分离 + 失败路径修复
F binary_writer 类型分派收敛（补 binary golden）
G Accessor 模型化（先补 C#/Lua golden 再改生成器）
```

每阶段结束 pytest 全绿 + `git diff` 复核无无关改动；G 阶段第一步必须
落下 golden 快照（当前输出即期望），再改生成器。

## Risks / Trade-offs

- [行为漂移（重构最大风险）] → 每阶段以 pytest 为安全网；G 先落 golden；
  完成时对 `gd/` 真实数据做 CLI 输出快照对比。
- [accessor 生成文本变化（当前零测试覆盖）] → 先补 golden 特征测试再改；
  golden 断言逐字一致；快照存 `tests/fixtures/`（生成文本较长，内联会
  淹没测试文件）。
- [binary 字节漂移] → 槽位写入只收敛分派不改值/默认值；F 阶段补
  `build_table_bytes` 固定 schema 的逐字节 golden，改完验证。
- [计数模型替换影响 CLI 渲染] → status/compact 文本断言保持；C 阶段后
  跑全部 i18n 测试。
- [用例下沉后 CLI 仍是文本 presenter] → 面板 change 只需调 app 层函数，
  不碰 CLI；现有 CLI 输出由 presenter 测试兜底。
- [binary golden 依赖 flatbuffers 库字节布局] → 快照在库升级时重录即可，
  测试注释中注明。

## Migration Plan

1. 按 D9 七阶段顺序实施，每阶段独立提交；
2. 每阶段运行 `cd tool && pytest`，失败回退最近绿点换更小步；
3. 全部完成后：`ct status / export / validate / i18n *` 在 `gd/` 上做
   输出快照对比 + `git diff` 复核；
4. 回滚策略：按阶段提交逐个 revert（每阶段行为独立，无跨阶段耦合）。

## Open Questions

- flatc 编译失败时 CLI 是否应失败退出 → 归面板 / 独立行为变更 change，
  不阻塞本 change。注：flatc 自身退出码不归我们控制；我们能控制的是
  "编译失败是否透传为 ct 的非零退出码"，该决定留给面板 / 独立 change。
- 取消发生在 BundleStep 中途时，`data_{lang}.bin` 可能已部分写入磁盘
  （表循环逐表写）。临时文件 + rename 原子写归面板 change（本 change
  只修计数语义，不解决半写产物）。
- 缓存键是否加入 schema hash（既有缺陷）→ 独立行为变更 change。

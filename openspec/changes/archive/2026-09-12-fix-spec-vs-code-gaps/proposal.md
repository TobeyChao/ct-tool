## Why

2026-09-12 的全仓规格复核留下 5 处「规格 vs 代码」不一致，逐条实测后确认它们**全都是真 bug，而不是规格写错**（唯一方向相反的是主键类型，见 What Changes 第 5 条）：

- `ct i18n sync --lang`、`ct i18n compact --lang/--dry-run`、`ct i18n status --by-table/--lang`、`ct gen-template --table`、`ct export --lang` 这五个过滤/开关**被接受但静默忽略或静默无操作**，命令退出码 0，用户以为生效了。其中 `ct i18n compact --dry-run` 因为没转发 `dry_run` 而**真的删除了文件**（实测输出里 `dry_run: False`），属数据丢失级缺陷。
- `ct i18n compact` 把 `canonical_i18n_compact` 返回的 **dict 直接插值进输出行**（`[compact] 总计移除 {'dry_run': False, ...} 条`），规格要求的 `[compact] en/Item: 移除 3 条 orphan` 与 `[compact] 无 orphan 条目，无需操作` 都不可能出现（后者是死分支：非空 dict 恒为真）。
- `ct i18n status` 没有进度条、`--json` 少了规格要求的 `langs` 外层、`--by-table` 无任何效果。
- 主键值越界（例如 Excel 里给 `int32` 主键填 `5000000000`）能通过 `ct validate`，然后在 `ct export` 阶段炸出 **Python traceback**（`TypeError: bad number 5000000000 for type int32`）。
- 主键类型：规格写 `int32` 或 `int64`，代码接受任意整数标量，而**导出与读取链路恒为 32 位**（索引向量 `PrependInt32`、`idHash` 取低 32 位、生成的 `ByID(int)`）——两边都不是真相，见 design.md D1。

## What Changes

1. **过滤/开关一律真生效，未知取值一律报错**（`ct export --lang`、`ct i18n sync --lang`、`ct i18n compact --lang`、`ct i18n status --lang`、`ct gen-template --table`，以及 `ct i18n sync|compact --table`）：口径统一为 `表 'X' 不存在` / `语言 'X' 不在 secondary_langs 中（可用: ...）`，退出码非 0，与既有 `canonical_validate` / `run_canonical_export` 的写法一致。
2. **`ct i18n compact`**：转发 `--dry-run` / `--lang`（dry-run 绝不落盘），逐文件输出 `[compact] en/Item: 移除 N 条 orphan`，dry-run 额外打印待删 key 列表，无 orphan 时输出 `[compact] 无 orphan 条目，无需操作`。
3. **`ct i18n status`**：默认每语言一行 `[en]  89% [█████████░] 170/190 translated, 12 missing, 8 stale, 10 orphan`（10 格进度条）；`--by-table` 追加逐表行；`--json` 只在 stdout 输出 `{"langs": {...}}`（每语言四态计数 + `total` + `progress` + 逐表 `tables`）。
4. **`ct i18n sync`**：`--verbose` 逐文件输出写入路径与变更条目数；完成时输出规格要求的汇总行 `[i18n sync] 处理 N 张表 × M 语言：新增 a、更新 b、stale c、orphan d`。
5. **主键类型收紧为 `int32`，主键值域显式校验**：主键在索引向量、`idHash`、生成的 `ByID(int)` 与行属性上都是 32 位，只有 `int32` 能让这条链自洽（19 份现存 schema 全部是 `int32`，无一依赖其它整数标量）。schema 加载阶段拒绝非 `int32` 主键；同时整数列的值必须落在其**声明类型**的值域内，越界在解析校验阶段以类型错误报出（`ct validate` 与 `ct export` 一致），不再落到产物生成阶段抛 traceback。

## Capabilities

### New Capabilities

无（不新增能力域）。

### Modified Capabilities

- `cli-interface`：`ct export command`（未知 `--table/--lang` 报错）、`ct i18n sync command`（`--lang` 生效、`--verbose` 逐文件、汇总行）、`ct i18n status command`（进度条 / 进度定义 / `--by-table` / `--json` 结构）、`ct i18n compact command`（`--dry-run`/`--lang` 生效、逐文件输出）、`ct gen-template command`（未知 `--table` 报错）
- `i18n-pipeline`：`Status reporting`（进度百分比的定义：orphan 不计入分母）
- `schema-management`：`Validate primary key type`（主键类型收紧为 `int32`）
- `excel-processing`：`Read Excel data according to schema`（整数列值域校验，越界即类型错误）
- `schema-editor/workbench`：`Add-field role and constraint mutual exclusion`（主键类型描述 `int32`/`int64` → `int32`，并写明 Apply 时由模型拒绝其他整数标量）

## Impact

- 代码：`ct/src/ct/cli.py`（三个 i18n 子命令 + gen-template 的过滤与渲染）、`ct/src/ct/app/canonical_commands.py`（`canonical_i18n_sync/compact` 新增 `lang_filter`、表名/语言名校验、汇总统计）、`ct/src/ct/app/canonical_export.py`（`--lang` 校验）、`ct/src/ct/excel/canonical_reader.py`（整数值域）、`ct/src/ct/schema/resources.py` + `ct/src/ct/schema/type_expression.py`（主键类型）。
- 行为变化（需知会）：`ct i18n status --json` 多一层 `langs` 键；非 `int32` 主键的 schema 现在**加载即失败**；整数列越界值现在**校验即失败**（此前是导出期 traceback 或静默截断风险）。
- 兼容性：web 面板不受影响——`canonical_i18n_status` 的返回结构未变（`langs` 外层只在 CLI 侧组装），`/api/i18n/sync`、`/api/i18n/compact` 的请求体未变，新增的 `lang_filter` 均为可选关键字参数。

# Design: fix-cli-filters-and-integer-domain

## D1 主键类型恒为 `int32`（不是 `int32`/`int64`，也不是任意整数标量）

规格原来写「`int32` 或 `int64`」，代码实际接受 8 种整数标量，两边都不成立。实测证据（2026-09-12，`/tmp/ctbig`、`/tmp/ctoob`、`/tmp/ctpk`）：

| 环节 | 事实 |
|---|---|
| 导出索引向量 | `canonical_binary.py:343` `builder.PrependInt32(int(row.get(primary, 0) or 0))`，槽位宽 4 字节 |
| 导出 `idHash` | `canonical_binary.py:351` `(keys[i] * 2654435761) & 0xFFFFFFFF`，恒取低 32 位 |
| 生成 C# 访问器 | 主键查询签名恒为 `public static Item? ByID(int id)`（`canonical_accessor.py`），与主键声明的宽度**无关** |
| 生成 C# 行属性 | 按声明宽度（`uint64` → `public ulong Id`），于是 API 自身不对称：能读到 `ulong`，只能用 `int` 查 |
| 现有 schema | 19 份（game 5 + ct-tool fixtures 4 + 沙盒 10）主键**全部是 `int32`**，无一份依赖其它整数标量 |
| 越界后果 | 主键值 `5000000000`：`ct validate` **通过**，`ct export` 抛 `TypeError: bad number 5000000000 for type int32` 并打印 Python traceback |

结论：让主键类型与承载宽度一致，取 **`int32`**。理由：它是唯一自洽的宽度（索引/哈希/`ByID`/行属性同宽）；`int64`/`uint64` 主键只会产生「声明 64 位、实际只能查 32 位」的陷阱；`int8`/`int16` 等宽度虽能隐式加宽到 `int`，但同样没有实际价值。代价是**非 `int32` 主键的 schema 现在加载即失败**——实测无现存 schema 受影响。

拒绝的替代方案：

- **放宽到 8 种整数标量**（即我最初基于「现存可能有其它整数主键的表」给出的建议）：该前提经实测为**假**，且会保留 `ulong Id` + `ByID(int)` 的不对称 API。
- **把索引向量 / `idHash` / `ByID` 拓宽到 64 位**：要同时改生成器、C# 读取端、Lua 绑定与 `ExportAccessorVerify` 产物，且原生插件（Windows dll 尚未重建）与数据格式存在版本偏斜风险，收益（支持 >2^31 的主键）与成本不成比例。

## D2 进度百分比的分母：`total - orphan`（保留代码语义，改规格示例）

代码 `_i18n_progress` 定义为 `translated / (total - orphan)`，并在 docstring 写明「无活跃条目视为 100%」。规格没有normative定义，只在示例里出现 `85% ... 170/200`（170+12+8+10=200，即把 orphan 计入分母）。

选择保留代码语义：orphan 是 source 中已不存在的残留条目（`compact` 专门用来清它们），把它们算作「未完成的翻译工作」会让进度永远无法自然到达 100%。因此**修正规格示例的算术**（170/190 → 89%）并补一句定义，而不是改代码。同理，`--json` 的 `total` 仍是四态之和（含 orphan），`progress` 是不含 orphan 的分母。

## D3 `--json` 的 `langs` 外层只在 CLI 侧组装

规格要求 `ct i18n status --json` 输出 `{"langs": {...}}`。`canonical_i18n_status()` 的返回值**同时**是 web 端点 `GET /api/i18n/status` 的响应体，前端 `i18n.js` 直接按 `progress[lang]` 取用。故：`canonical_i18n_status()` 返回结构**不变**，`langs` 外层与 `--lang` 过滤在 `cli.py` 的渲染层组装——CLI 契约按规格走，web 契约零改动。

## D4 未知过滤取值一律报错，沿用既有措辞

`canonical_validate`（`表 'X' 不存在`）与 `run_canonical_export`（同）已经这么做了，`_i18n_table`（`表 'X' 不存在` / `表 'X' 没有 i18n 字段`）与 `canonical_i18n_entries`（`语言 'X' 不在 secondary_langs 中`）也有了。本次把这套口径补齐到 `canonical_gen_template` / `canonical_i18n_sync` / `canonical_i18n_compact` / `canonical_i18n_status`(CLI) / `canonical_export`，不发明新措辞。`ct gen-template --table` 额外对「仅大小写不符」给出提示（规格明确要求 PascalCase 精确匹配，这是最常见的输入错误）。

## D5 整数值域校验放在读取层（`_coerce_scalar`）

越界值必须在**解析校验阶段**变成结构化 `IssueCode.TYPE`，才能同时满足：`ct validate` 报错、`ct export` 阶段 1 中止（不落脏产物）、web 导出同样受益。故在 `canonical_reader._coerce_scalar` 内按**声明类型**查值域表，越界即 `(raw, False)`——与既有的「期望 X 类型」错误路径完全一致。放在 flatbuffers builder 处（现状）是错的：那是产物写入阶段，只能抛 Python 异常。

主键值域校验因此自动被覆盖（主键是普通整数列之一），不需要在 `_primary_issues` 里再写一份。

## D6 `ct i18n sync` 的汇总行与 `--verbose`

汇总行由 `canonical_i18n_sync` 作为**最后一条 message** 返回（`处理 N 张表 × M 语言：新增 a、更新 b、stale c、orphan d`），CLI 已给每条 message 加 `[i18n sync] ` 前缀，故输出与规格示例逐字一致；`--verbose` 的逐文件行同样走 message（`写入 i18n/en/Item.json（新增 2、更新 0、stale 0、orphan 0）`）——避免把渲染逻辑塞进 app 层，也让 web 端 `{"synced": [...]}` 顺带获得同样的信息。返回类型保持 `list[str]`，`canonical_i18n_sync` 的既有调用方（web、测试）零改动。

## 1. 冻结形状清单

- [x] 1.1 从 `test-proj/RefConfigBench/ref_table_shapes.json` 与 `D:\dev_trunk_harmony\design-data\ExcelRecord.json` 按类名 join，产出 `native/fixtures/bench/shape-r.json`（2.2 MB），头部记录来源、口径、冻结时刻与两份留档的计数；验证：清单内 2,027 张表（1,373 Config + 654 Enum）、行数合计 691,518、i18n 字段 816、向量字段 982、引用边 2,583，`xtask bench-shape-check` 只读自检跑通（命令见 evidence/acceptance.md）。
- [x] 1.2 实现抽样规则：全 Enum + 按（行数桶 × 字段桶）分层抽样 + 按槽位强制 top-12（哈希排序、无 RNG 状态）；验证：自检输出薄表占比 408‰ vs 全量 432‰（阈值 80%）、分层覆盖全量 28 个非空分层，合计 818 张表 / 249,569 行 / 3,709,512 槽位 / 10 种语言，`Res`、`Skill`、`Buff`、`Item` 等 12 张巨型表在列。
- [x] 1.3 为每张表补齐类型语法（标量 / 引用 / 向量 / 内联 struct / 记录数组 `TYPE[N]`）与嵌套深度，使 `header_rows = 嵌套深度 × 2` 形成多值分布；验证：自检输出嵌套深度分布 1/2/3/4/5/6/7 → 1,302/360/278/61/23/2/1 张表，单一深度占比 64% < 90% 阈值，夹具实测表头行数 2–14。

## 2. 让形状与偏差可追溯

- [x] 2.1 新增 `native/fixtures/bench/README.md`：记录形状来源（两份留档的出处与口径差异）、抽样规则、两档构成表、命名规范化、以及偏差登记；验证：9 项偏差逐条可在第 5 节定位（`multi-area-columns`、`multi-table-workbooks`、`animevent-curves`、`track-binaries`、`translation-fill-rate`、`i18n-per-language-aggregation`、`vector-expansion-widths`、`long-table-names`、`regression-tier-tail-bias`），文档声明夹具不用于产物正确性对照。
- [x] 2.2 在夹具自检中加入"不对未建模维度做覆盖断言"的检查；验证：`bench-shape-check` 断言已建模/未建模列表与常量一致、两者不相交，并原样打印 9 项未建模维度。

## 3. 夹具生成（原生路径）

- [x] 3.1 在 `ct-xtask` 内实现 `--sizes r` 的原生生成（`shape-r.json` → schema YAML + 工作簿 + 布局 manifest + i18n 骨架，`real_fixture.rs`）；验证：把 `PATH` 限制为 `%SystemRoot%\System32`（无 python）后生成成功且摘要与常规运行一致；`real_fixture.rs` 无进程派生，`Command::new(python)` 只存在于 S/M/L 分支。
- [x] 3.2 按冻结清单写入每个表的 schema 与工作簿（一表一工作簿）、表头行数随嵌套深度变化、向量/记录数组横向展开、Enum 表建成独立表（同样有工作簿）；验证：654 张 Enum 表工作簿齐全、表头行数分布 `{2:728,4:41,6:38,8:4,10:5,12:1,14:1}`、`Skill` 131 列含 46 个展开列、`ActivityActive` 的 `RewardItem[3]` 展开为 3 组 × 2 子字段。
- [x] 3.3 按口径 A 生成译文（每个 i18n 单元格一条）；验证：`FIXTURE.json` 的 `translatedEntriesPerLang=117146`、`translatedEntries=1054314`（9 语言），i18n 文件恰好覆盖清单里 69 张有 i18n 字段的表（每语言 69 个 + source 69 个，无多余、无缺失）。
- [x] 3.4 保证确定性：固定种子、生成前清空目录、只消费冻结清单；验证：三次独立生成同一 `inputDigest=sha256:def7ea106…`，`realWorkspaceUntouched` 为真且 `git status --porcelain gd` 为空。
- [x] 3.5 补 `--sizes r-full`（2,027 张表）且默认不生成；验证：`FIXTURE.json` 表数 2,027（1,373 Config + 654 Enum）/ 691,518 行 / 6,953,587 槽位 / 每语言 301,656 条（9 语言 2,714,904），`ct validate` 通过；默认路径（不传 `--sizes` 或 `all`）只展开 s/m/l。

## 4. xtask 接线

- [x] 4.1 `native/crates/ct-xtask/src/fixtures.rs` 的尺寸白名单加入 `r` / `r-full`（错误信息列出全部可选尺寸，`all` 仍只表示 s/m/l）；验证：`xtask bench-fixtures --sizes r` 成功、`--sizes bogus` 报错并提示完整选项。
- [x] 4.2 `native/crates/ct-xtask/src/bench.rs` 为回归档接线判定：参照不在位时产出 `verdict=regression-pass|regression-fail`、`baselineMode=archived-run`，且报告字段不出现配对测量口径；验证：`bench-r-regression-check.json` 五个场景全部 `regression-pass` + `archived-run`、`engines.python=null`，补齐了缺失夹具时的尺寸相关提示。
- [x] 4.3 门槛判定与测量解耦对新档位仍可用；验证：`xtask bench-recheck --report native/docs/baseline/bench-r-windows.json` 用当前常量重算成功，未改动样本、未重跑测量。

## 5. 实测与留档

- [x] 5.1 在 Windows 真机跑回归档 5 轮（1 轮预热），产出 `native/docs/baseline/bench-r-windows.json`，记录表数/行数/槽位/语言数、耗时分布、进程树峰值 RSS、产物摘要与判定；验证：留档内的夹具摘要与冻结清单逐项一致（818 / 249,569 / 3,709,512 / 117,146 / 10 语言 / `inputDigest`），`realWorkspaceUntouched` 为真，产物 10,646 个。
- [x] 5.2 用「同档位热场景 / 冷全量」口径复核固定开销，而不是按单元格跨档位插值；验证：回归档冷全量 422.8s、热 153.2s（固定开销 36%），L 档 101.3s / 54.5s（54%）；并更正了原设计里「L 档 per-table 占 0.7%」的三点插值口径（同模型外推回归档低估 15.7×）。
- [x] 5.3 更新 `native/README.md`：新增两档尺寸、原生生成入口、判定路径与偏差登记入口；验证：文档里的命令逐条可执行，S/M/L 与 `r`/`r-full` 的生成后端差异已写明，不再声称夹具生成一律依赖 `ct/.venv`。

## 6. 验收

- [x] 6.1 逐条对照 `specs/benchmark-fixtures/spec.md` 的 12 个 scenario 给出证据（命令 + 产物路径 + 计数）：`openspec/changes/bench-real-shape/evidence/acceptance.md`；验证：无遗留无证据的 scenario。
- [x] 6.2 记录本次未做项：`evidence/acceptance.md` 与 `design.md` Non-Goals/Open Questions 对齐——① 新档位的时间/RSS 门槛数值未提案（需另开变更，本次只给实测数据）；② S/M/L 仍走 Python 生成脚本，未一并切到原生入口；③ `r-full` 只做了生成与校验，未做性能实测；④ 未做 Python 配对测量（`ct/` 可选，回归判定已覆盖）。

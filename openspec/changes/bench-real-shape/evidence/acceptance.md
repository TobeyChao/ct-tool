# bench-real-shape 验收证据

逐条对照 `specs/benchmark-fixtures/spec.md` 的 scenario，给出命令、产物路径与计数。
测量环境：Windows x86_64 / 28 逻辑核；`ct` release 二进制 `native/target/release/ct.exe`。

产物路径（都在 `native/target/bench/`，不进版本库）：

| 档位 | 目录 | 文件 | 体积 | 输入摘要 |
|---|---|---|---|---|
| `r` | `native/target/bench/bench-r` | 3,354 | 204.3 MB（Excel 34.7 + i18n 165.3） | `sha256:def7ea106…` |
| `r-full` | `native/target/bench/bench-r-full` | 11,992 | 549 MB | `sha256:036a8590f…` |

留档（进版本库）：`native/docs/baseline/bench-r-windows.json`（5 轮测量）、
`native/docs/baseline/bench-r-regression-check.json`（对留档做回归判定的 1 轮复核）。

---

## 1. Two-tier real-shape fixture family

| Scenario | 证据 |
|---|---|
| Regression tier composition | `bench-r/FIXTURE.json`：`tables=818`（`configTables=164` / `enumTables=654`）、`rows=249569`、`dataCells=3709512`、`i18nFields=127`、`translatedEntriesPerLang=117146`、`languages` 10 项。命令：`cargo run --release -p ct-xtask -- bench-fixtures --sizes r` |
| Full tier is opt-in | `fixtures.rs` 的默认与 `all` 都只展开 `SIZES = s,m,l`；`r`/`r-full` 只在显式 `--sizes` 时生成（本次 `r-full` 是手动执行一次，未进任何默认路径） |
| Verdict without a reference implementation | `bench-r-regression-check.json`：五个场景全部 `verdict=regression-pass`、`baselineMode=archived-run`；报告 `engines.python = null`，控制台明确打印「无 Python 参照：改用本机留档回归判定」 |

## 2. Shape fidelity from measured distributions

| Scenario | 证据 |
|---|---|
| Stratified sampling preserves the distribution | `bench-shape-check` 输出：薄表占比 `回归档 408‰ vs 全量 432‰`（阈值 = 全量的 80%，自检失败即报错）；`分层覆盖：回归档覆盖全量 28 个非空分层`。抽样实现里每层 `want.clamp(1, len)`，分层覆盖是自检断言而非口头保证 |
| Variable header depth | `bench-shape-check` 输出嵌套深度分布 `{1:1302, 2:360, 3:278, 4:61, 5:23, 6:2, 7:1}`（自检拒绝单一深度 >90%）；`bench-r` 布局 manifest 实测 `header_rows` 分布 `{2:728, 4:41, 6:38, 8:4, 10:5, 12:1, 14:1}` |
| Fixed-cost share is observable | 见下方「实测对照」：同档位内 `热 / 冷全量` 可量化（回归档 153.2s / 422.8s = 36%），且按单元格跨档位插值被实测否证（同一模型外推回归档 26.9s，实测 422.8s，低估 15.7×） |

## 3. Frozen shape manifest and provenance

| Scenario | 证据 |
|---|---|
| Regeneration without the real workspace | 形状行数来源 checkout `D:\dev_trunk_ref` **本机不存在**，生成仍成功（两次独立生成摘要一致）。生成期只读 `native/fixtures/bench/shape-r.json`；`real_fixture.rs` 无任何外部路径读取 |
| Real workspace untouched | `bench-r-windows.json` 的 `realWorkspaceUntouched = {gdDirtyBefore: 0, gdDirtyAfter: 0, unchanged: true}`；测量后 `git status --porcelain gd` = 0 行 |

## 4. Deterministic regeneration

| Scenario | 证据 |
|---|---|
| Identical inputs across runs | 三次独立生成（两次常规、一次 `PATH` 只剩 System32）都写出同一 `inputDigest = sha256:def7ea106…`，`writtenCells` 同为 5,210,139；摘要是语义摘要（忽略 xlsx 里随时间变化的文档属性） |

## 5. Documented deviations

| Scenario | 证据 |
|---|---|
| Every unmodelled dimension is registered | `bench-shape-check` 断言清单里的 `modelled` / `unmodelled` 与常量完全一致、两者不相交，并原样打印 9 项未建模维度；`native/fixtures/bench/README.md` 第 5 节逐条给出「真实 vs 夹具」与方向 |

## 6. Fixture generation independent of the Python reference implementation

| Scenario | 证据 |
|---|---|
| Generation without the optional Python reference | 把 `PATH` 限制为 `%SystemRoot%\System32`（无 python/py）后执行 `bench-fixtures --sizes r` 成功，产出摘要与常规运行一致；`fixtures.rs` 里 `Command::new(python)` 只存在于 S/M/L 分支（`generate_python_sizes`），`real_fixture.rs` 无进程派生 |
| Measurement does not require an interpreter | 两次测量都以 `--python <不存在的路径>` 运行：报告 `engines.python = null`，`judge` 走回归判定分支，10,646 个产物全部由原生二进制写出 |

---

## 实测对照（同一台机器）

| 口径 | L 档（现状夹具） | 回归档 `r`（真实形状） | 倍率 |
|---|---|---|---|
| 冷全量（中位） | 101.3s | **422.8s** | 4.2× |
| 热（输入无变化） | 54.5s | **153.2s** | 2.8× |
| 改单表 / 改译文（中位） | 54.2s / 54.5s | 149.0s / 146.4s | 2.7× |
| 产物文件数 | 607 | **10,646** | 17.5× |
| 数据单元格 | 18.48M | 3.71M | 0.20× |
| 冷全量峰值 RSS（进程树） | 7,014 MiB | 5,549 MiB | 0.79× |
| 冷全量峰值 RSS（单进程） | 7,035 MiB | 5,573 MiB | 0.79× |

`r` 的冷全量样本：`[407610, 408737, 422757, 440727, 636133]` ms（最后一轮受并行负载影响，中位不受影响）。

**结论**：真实形状用 20% 的单元格换来 4.2 倍的冷全量耗时；其中 36%（153.2s）在输入完全未变时也要付出，
由 818 张表 × 10 语言 = 8,180 个「表×语言」单元驱动。按单元格线性外推（S/M/L 三点插值模型）会低估 15.7×，
因此 L 档的绝对耗时不能作为真实工作区成本的代理。

**原设计口径的更正**：proposal/design 初稿用「S/M/L 三点插值 ⇒ L 档 per-table 项占 0.7%、真实 28.4%」论证动机；
该 0.7% 是插值模型把三档差异全部归入单元格项后的产物，实测否证。现在的口径改为同档位内的
`热 / 冷全量` 比值（L 54%、r 36%），仍能说明固定开销不可忽略，但不再声称「L 档几乎不含固定开销」。

## 回归验证

| 检查 | 结果 |
|---|---|
| `cargo test --workspace` | 全部通过，0 failed |
| `cargo clippy --workspace --all-targets -- -D warnings` | 干净（修掉了新增代码的 5 个 clippy 警告） |
| `cargo fmt --check` | 干净 |
| `ct validate --root native/target/bench/bench-r` | `校验通过` |
| `ct validate --root native/target/bench/bench-r-full` | `校验通过` |
| `xtask bench-recheck --report native/docs/baseline/bench-r-windows.json` | 用当前常量重算成功；不改样本、不重跑测量 |
| `xtask fingerprint --check` | 新增源码文件后基线失配 → 已重新生成 `native/docs/baseline/source-tree.json`（1,202 个文件，树摘要 `f2feac9e…`）并复验通过 |

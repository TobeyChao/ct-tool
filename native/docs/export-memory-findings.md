# 导出内存占用归因：每格约 2.3 KB（2026-10-01）

测量日期：2026-10-01。主机：Apple M1 Pro（10 核 / 32GB），macOS 27.0.1。
被测内核：`ct 0.0.0`，源码 `2c9ffdb`（干净树），`cargo build --release`。
口径：`/usr/bin/time -l` 的单进程 `maximum resident set size`，配合 `CT_MEMDIAG=1` 的驻留自述。

## 结论

1. 峰值由**格子数 × 每格表示成本**决定，与 xlsx 文件大小基本无关。m 档夹具的 50 张表在磁盘上
   合计 11.2 MB，在内存里要 **950 MB**。
2. 每格成本实测 **≈ 2.3 KB**（与行数线性，见 §1），而同一格在 xlsx 里约占 **6 字节** —— 放大约 400×。
3. 不是泄漏，是表示选型：`CanonicalParsedRows.rows` 是 `Vec<serde_json::Map<String, Value>>`，
   每格 = 一个堆分配的字段名 `String` + 一个 `serde_json::Value`（文本值再带一个 `String`）；
   同一格在流水线里还要经过 calamine `Data`、`ProbeValue`、`RawValue` 三份中间表示。
4. 解析结果**整批常驻**（引用校验要跨表），所以增量导出也不省这部分：m 档冷 986 MB / 增量 865 MB。
5. `CT_MEMDIAG` 的数字是**净字节估算**，与真实 RSS 差 4–19×（§4），不能当内存门槛用。

## 1. 每格成本的直接测量

最小工作区：单表 `Micro`，6 列（int32 / string / string+i18n / int32 / double / string），
`gen-template` 生成后用脚本填 N 行，`ct export --all --table Micro` 测峰值。
每格 = （峰值 − 10 MB 进程基线）/ 格数。

| 行数 | 格数 | xlsx | memdiag 估算 | 峰值 RSS | 每格 RSS |
|---:|---:|---:|---:|---:|---:|
| 200 | 1,200 | ~7 KB | 0.1 MiB | 12.8 MB | 2,471 B |
| 2,000 | 12,000 | ~40 KB | 1.4 MiB | 36.8 MB | 2,337 B |
| 20,000 | 120,000 | ~400 KB | 13.8 MiB | 267.5 MB | 2,250 B |
| 2,000（某列 400 字长文本） | 12,000 | ~1.1 MB | 14.6 MiB | 288.1 MB | 24,303 B |

斜率稳定 ⇒ 每格固定成本；文本越长越是线性放大（长文本在多份表示与序列化缓冲里各存一遍）。

## 2. m 档与真实工作区

m 档：50 表 × 2000 行，1,848,502 个非空数据格，400,000 条翻译，xlsx 合计 11.2 MB。

| 场景 | 耗时 | 峰值 RSS |
|---|---:|---:|
| 冷全量 `export --all` | 8.67s | 986 MB |
| 增量（无改动） | 5.33s | 865 MB |
| 增量（改一张表） | 5.6s | 928 MB |
| 增量（改一条翻译） | 5.45s | 836 MB |
| `validate`（只解析校验，不产生产物） | 2.48s | 417 MB |
| 单表 Base（2000 行 × 20 列 = 4 万格） | 0.06s | 119 MB |
| `--lang zh`（单语言） | 5.65s | 779 MB |
| 默认 3 worker + 96 MB 波预算 | 8.74s | 932 MB |
| `CT_MAX_WORKERS=1` | 10.17s | **728 MB** |
| `CT_EXPORT_MEMORY_BUDGET_MB=8` + `CT_MAX_WORKERS=1` | 9.82s | 723 MB |

l 档：100 表 × 10000 行，18,480,119 格，夹具 642 MB —— 冷全量 **86.4s / 7,225 MB**（单样本；
官方基线 `bench-l-macos-native.json` 记 98.95s / 7,085 MB，同量级）。
真实游戏工作区（14 表）：冷 0.09s / 13 MB，增量 0.03s / 12 MB。

可操作结论：**并行度是唯一有效旋钮**（3 worker → 1 worker：−22% 内存，+16% 时间）；
波预算从 96 MB 压到 8 MB 几乎不再降，说明 ~720 MB 是 m 档地板，主项是"全量解析常驻"。

对照：Python 时代同一 m 档夹具冷 552 MB / 增量 375 MB，比原生省 1.6–1.8×，
但耗时 32.6s / 18.2s（原生 3.3–3.8× 快）。当时的读取路径是逐表流式，属"拿内存换速度"的取舍。

## 3. 结构归因：一格要花几份

| 阶段 | 类型 | 每格代价 |
|---|---|---|
| calamine 读工作簿 | `Data::String` | 1 个堆字符串 |
| 探针报告 | `reader.rs` `ProbeReport.cells: Vec<ProbeCell>` → `ProbeValue::Text(String)` | 1 个堆字符串 |
| 行归组 | `canonical.rs` `BTreeMap<u32, Vec<RawValue>>` → `RawValue::Text(String)` | 1 个堆字符串 |
| 按路径索引 | `value_by_path.insert(column.stable_path.clone(), raw)` | 1 个堆键字符串 |
| 最终行 | `CanonicalParsedRows.rows: Vec<serde_json::Map<String, Value>>` | 键 `String` + `Value`（文本再 1 个 `String`） |
| 消费者 | `ct-app/src/validate.rs` `PreparedTable.parsed` 全量持有 | 整批常驻 |

一个文本格因此最多产生 4–6 次独立分配；每次小字符串 `malloc` 带 16 B 头 + 16 B 对齐，
`"Price"`（5 B）实际占 ~32–48 B。相关位置：
`native/crates/ct-excel/src/canonical.rs`（`CanonicalParsedRows:291`、`RowReader::read` 的
`result.insert(field.name.clone(), value)` 与 `value_by_path`）、`native/crates/ct-excel/src/reader.rs:13`、
`native/crates/ct-app/src/validate.rs:23`。

为什么整批留着：引用校验跨表（某表字段引用另一表主键），必须两张表同时在手；
`--table` 单独导出会因此失败（当前报错文案是 `Excel 文件不存在: <被引用表>.xlsx`，具有误导性，
见 TODO R5）。

## 4. 内存口径警告：`CT_MEMDIAG` 不等于 RSS

m 档冷全量的自述：

```
[memdiag] capture  excel=11.2MiB i18n=47.1MiB manifests=0.7MiB   (#50/#100/#50)
[memdiag] prepare  parsed_rows=199.3MiB                          (#100000)
[memdiag] waves    payload 累计 86.1MiB（波预算 96MiB）
[memdiag] after    build_bytes=31.9MiB payload=86.1MiB
```

计数合计约 376 MB，而 RSS 是 986 MB（≈2.6×）。单看解析：199.3 MiB / 185 万格 ≈ 113 B/格，
真实每格是数百字节到 2.3 KB —— `memdiag::sample_rows` 只按「每行 96 B + 每格 64 B + 字符串长度」
估净字节，不含分配器头/对齐/B 树节点。**用 memdiag 定位来源可以，当门槛不行。**

## 5. 候选优化（均未实现，收益为估算）

| 编号 | 做法 | 预期 | 风险 |
|---|---|---|---|
| R1 | 解析结果改 typed/columnar：数值列 `Vec<f64>`/`Vec<i64>`，字符串列 arena + `(offset,len)` | parsed 199 MiB → 20–30 MiB 量级 | 动 `canonical` 层与全部消费方（校验、生成器、FBS 构建） |
| R2 | 键名去重：用字段索引代替 `field.name.clone()`，`value_by_path` 复用同一份路径 | 每格省 1–2 次分配；低风险第一步 | 消费方按名字取值的接口要改 |
| R3 | 引用闭包 + 流式保留：只保留被引用的表/列，或解析完即转产物字节 | 可让"整批常驻"消失 | 动校验语义（跨表引用完整性），风险最高 |
| R4 | 产物直接构造：解析 → FlatBuffers/JSON 字节，不留 JSON 树 | 去掉第 5 份表示 | 与 R1 重叠，需重排 pipeline |
| R5 | 修 `--table` 的报错文案（"引用表未纳入本次选择"），并在 memdiag 输出里标注"净字节估算" | 无性能收益，避免误读 | 无 |

## 6. 复现

```sh
# 大档夹具（固定 seed）
cargo run --manifest-path native/Cargo.toml -p ct-xtask --release --locked -- bench-fixtures --sizes m --out /tmp/bench

# 单次测量（峰值 RSS + 分阶段驻留）
CT_MEMDIAG=1 /usr/bin/time -l native/target/release/ct export --all --root /tmp/bench/bench-m

# 旋钮对照
CT_MAX_WORKERS=1 CT_EXPORT_MEMORY_BUDGET_MB=16 /usr/bin/time -l native/target/release/ct export --all --root /tmp/bench/bench-m
```

微工作区：写一份 6 列 schema → `ct gen-template --table Micro --root <ws>` → 脚本填 N 行 → 同上测量。

## 7. 局限

- 单机单版本（M1 Pro / macOS 27.0.1 / `2c9ffdb`），未在 Windows/Linux 复测。
- l 档是单样本；官方 l 基线是 5 次中位数，两者同量级但不可混用。
- 只用 RSS 观测，未做堆剖析（未跑 heaptrack/dhat），所以"每格 2.3 KB"是**端到端**成本，
  未进一步拆成"表示本身 / 分配器保留页"两部分。
- `memdiag` 是估算口径；本文件给出的每格数字均来自 RSS 差值，不是 memdiag 计数。

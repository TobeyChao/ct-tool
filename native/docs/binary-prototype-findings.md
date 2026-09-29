# FlatBuffers 二进制原型结论（rust-native-core 任务 1.7）

日期：2026-09-17。基线：Python `ct/export/canonical_binary.py`（flatbuffers 包）。
实现：`ct-export/src/flat_builder.rs`（自研最小构建器）+ `ct-export/src/binary.rs`。

**结论：字节级一致达成，继续全面迁移的技术风险解除。**

## 对照方法

`fixtures/binary/generate.py`（ct/.venv 运行）直接调用 canonical 生成器，
把 Schema/行数据（`input/*.json`）与 golden 字节（`golden/*.bin`）落盘；
`tests/compat/tests/binary_golden.rs` 用 Rust 原型重建并逐字节对照。

| 场景 | 覆盖点 | 结果 |
|---|---|---|
| item_nonuniform | 嵌套 Record（Effect→Position）、vector<record>、vector<string>、vector<int32>（含 ±int32 极值）、enum、string、uint64 最大值、double、Unicode/Emoji、空串、server_only 排除、codename 索引、主键乱序行 | ✅ 逐字节一致（944 B） |
| item_uniform | 同 schema 定宽布局、共享 vtable、含默认值行 | ✅ 一致（936 B），vtable 数 = 1 |
| empty | 零行 + 主键 + codename 索引 | ✅ 一致（116 B） |
| sparse_nonuniform | 大量缺省字段 → 槽位省略、行间不同 vtable | ✅ 一致（220 B，2 种 vtable） |
| sparse_uniform | 同输入定宽 | ✅ 一致（236 B），vtable 数 = 1 |
| bundle | 两表打包（名称乱序输入 → 排序）、内嵌表字节向量 | ✅ 一致（392 B） |

uniform 回读校验（每个对象验证 vtable 布局 == schema 推导布局）同步移植，
原型构建过程中未触发。

## 技术决策

1. **自研最小 FlatBuffers 构建器，不用 flatbuffers crate**：uniform 定宽
   布局需要手工 Pad/Prep（控制每个槽位的精确偏移），公开 crate API 不暴露
   足够控制力；且 vtable 内容去重、共享字符串去重的行为必须与既有格式
   逐点一致，自研反而更可控。构建器约 260 行，测试覆盖见上表。
2. **soffset 可正可负**：vtable 去重后对象可能引用地址更高的既有 vtable。
   回读/统计代码必须用有符号运算（原型踩坑已修）。
3. 容器槽位约定保持：0=items、1=主键有序索引（key+rowIndex 对）、
   2=idHash（Knuth 乘法哈希）、3=CodeName（FNV-1a 64）；4/5 槽位废弃不复用。

## 初步耗时（item_uniform，同输入重复构建，本机）

| 实现 | 耗时 |
|---|---|
| Python（50 次均值） | 0.381 ms/次 |
| Rust 原型 debug | 0.069 ms/次 |
| Rust 原型 release | 0.010 ms/次 |

单表微基准仅说明生成器路径的数量级收益（release ≈ 38x），不代表端到端
导出（Excel 解析/校验占大头），正式结论以任务 6.5 的配对基准为准。

## 遗留

- 行数据目前直接消费 canonical JSON（Value 树）；类型化中间表示
  （避免 Value 开销）随任务 2.4/3.3 落地。
- `Data::DateTimeIso` 等边缘形态未进二进制路径（标量由解析层转换）。
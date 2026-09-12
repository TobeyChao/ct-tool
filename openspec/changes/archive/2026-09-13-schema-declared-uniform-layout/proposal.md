## Why

定宽（uniform）布局的开关当前是**数据派生的**：导出时先用非定宽方式产出一份字节，数出「写了多少槽位 / 总槽位」得到 `fill_rate`，`fill_rate >= 0.75` 才开定宽。这条判定把三样东西串在了一起：

1. **布局随数据变**：改 Excel 数据（把某字段填成默认值、清空、增删行）就能让填充率跨过阈值，于是 `uniform` 翻转 → `slot_offsets` 重规划 → **二进制行布局与 10 个 accessor 一起变形态**。
2. **manifest 里存了数据派生的字段**：`uniform` / `fill_rate` 写进 `layout_manifests/*.json`（入库文件），使一个本该只由 schema 决定的产物跟着数据漂。
3. **漂移判定看不见它**：`ct status` 只看 `schema_hash` + 工作簿列数，所以这类翻转**不会被报成「模板已过时」** —— 用户只会看到产物变了而不知道为什么。

实测确认这种翻转是真实且廉价的（UIConfig 79.2% → 只把两行的 `Stack` 从 `true` 改成 `false` 就掉到 70.8%，`uniform` 由真翻假、`slot_offsets` 清空、accessor 从 `I32At(_row, 4)` 变成 `I32At(_row, _off[4])`）。

同时，实测也纠正了定宽收益的归因：**收益不来自「字面量偏移比槽位读快」**（端到端无可测差异，3.66 vs 3.75 ns），而来自**消掉每次行访问的 `OffsetsFor`**（部署版 2 种 vtable 7.7 ns，1 种 2.24 ns）。因此这个机制本身值得留，值得改的是**谁来决定它**。

## What Changes

- Schema 新增表级布尔键 `uniform`（默认 `true`）：定宽与否**由 schema 声明**，SHALL NOT 再由填充率判定。
- `uniform: false` 是**逃生门**：给极稀疏的表退回变长布局换体积；默认值不写进 canonical 持久化表示，因此默认表不产生 schema_hash 漂移。
- 删除 `UNIFORM_FILL_THRESHOLD`（0.75）与「先探测填充率再决定布局」的判定链；`fill_rate` 仍计算，但**降级为诊断数字**。
- Layout manifest 去掉 `uniform` / `fill_rate` 两个键，剩余字段全部是 schema 的纯函数：`format / schema_hash / header_rows / columns / nodes / slot_offsets`。
- 导出日志在定宽体积比 > 1 时给出**提示**（非阻断），把「空间换速度」的账显式交回给人。
- **运行时的非定宽读路径保留**：它是 `uniform: false` 逃生门的支撑，今日无人走不等于可以删。

## Capabilities

### Modified Capabilities

- `schema-management`: 新增表级 `uniform` 键的加载与默认值语义、持久化排除规则。
- `flatbuffers-export`: 定宽判据由「被判定」改为「被声明」；字面量偏移与槽位读两条路径的触发条件重写。
- `incremental-export`: 生成缓存的复用输入去掉「数据决定的定宽布局」；删除「数据变化使表从定宽切到非定宽」这一场景（该情形不再存在）。
- `excel-processing`: 明确 layout manifest 的字段集合，钉住 `uniform` / `fill_rate` 不再是 manifest 字段。
- `csharp-binary-reader-test`: fixture 的定宽/变长分工重写（默认表全为定宽；变长基线需显式声明 `uniform: false`）。
- `cli-interface`: 导出输出新增填充率与体积比报告，以及定宽体积膨胀时的诊断提示。

## Impact

- ct 侧：`ct/schema/resources.py`（表模型）、`ct/app/exporting/build.py`（判定链与日志）、`ct/app/exporting/models.py`（`to_layout_info`）、`ct/excel/layout_manifest.py`（字段集合）、`ct/app/canonical_export.py`（转发常量）、受影响测试与 fixture。
- 游戏仓：**二进制与生成的 accessor 预期逐字节不变**（当前 5 张表填充率均在阈值之上，声明默认 true 与原判定结果一致）；只有 5 个 layout manifest 各少 2 个键。这使本次改动的验收非常干净：产物不变、manifest 变小。
- 运行时代码（C# `ConfigRuntime.cs` / Lua `GD`）**不改**：非定宽路径仍是逃生门的实现。
- 不改 Excel 布局、JSON/FBS、C#/Lua API、Web API、launcher 协议。

## Non-goals

- 不删除非定宽读路径（它服务 `uniform: false`），不做原生插件重编。
- 不为「声明 uniform 但很稀疏」引入新的诊断等级：`ct/diagnostics/errors.py` 当前只有错误级 `IssueCode`，加 warning 级是独立改动；本次把提示放在导出输出里（数字本来就在那里算出来了）。
- 不把 `uniform` 暴露到 schema 编辑器 UI：默认值覆盖全部日常场景，逃生门由 schema 作者直接声明。
- 不改 `--all` / 增量语义与 `template-layout/2` 格式号（删字段对读兼容，不需要迁移）。

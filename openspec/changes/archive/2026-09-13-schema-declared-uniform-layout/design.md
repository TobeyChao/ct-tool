## Context

定宽布局是 2026-09-11 落地的行内布局优化：填充率 ≥ 75% 的表，导出期把所有槽位**无条件写出**，于是全表共享**一种 vtable**，`slot→offset` 成为表级常量，生成器据此发射字面量偏移读。

实测（`Docs`/`ct-tool` 两侧报告，2026-09-11）：

| 口径 | 非定宽 | 定宽 | 倍数 |
|---|---:|---:|---|
| 部署代码 E2E 行访问（2 种 vtable） | 16.99 ns | 4.88 ns | **3.48×** |
| 基准工程 E2E 行访问（同形状） | 6.86 ns | 3.77 ns | 1.82× |
| `OffsetsFor`（1 种 / 2 种 vtable） | — | 2.24 / 7.71 ns | 3.4× |
| **字段读本身**（`_off[slot]` vs 字面量） | 3.66 ns | 3.75 ns | 无可测差异 |

结论：**收益来自消掉 `OffsetsFor`，不是来自字段读**。因此机制值得保留，要改的是决策来源。

## Decisions

### D1 判据从「数据派生」改为「schema 声明」，默认 `true`

表级 `uniform: bool = True`。`uniform: false` 是逃生门（极稀疏表用体积换速度）。

理由：默认 true 让**默认行为完全可预测**——布局不再随数据变，`fill_rate` 不再是决策者。逃生门保留「将来出现很稀疏的大表」时的退路，代价是运行时两条读路径都留着（D4）。

### D2 默认值不进 canonical 持久化表示

`resource_to_data` 用 `model_dump(exclude_defaults=True)`。默认 `true` 因此**不出现在** `resource_to_data` 输出里 ⇒ 默认表 `schema_hash` 不变、不产生全表漂移；只有显式 `uniform: false` 才改变 hash（那确实是真实的配置差异）。`extra="forbid"` 保证 `uniform` 加进模型后 YAML 才接受这个键。

### D3 `fill_rate` 降级为诊断，manifest 去掉 `uniform` / `fill_rate`

`fill_rate` 仍要算——导出日志要报它、要拿它判体积提示——但**不再参与任何决策**。manifest 的字段集合收敛为 schema 的纯函数：

```
format / schema_hash / header_rows / columns / nodes / slot_offsets
```

`slot_offsets` 保留：它是 `plan_object_layout(fields, records)` 的输出，纯 schema 派生，且是 wire 行布局唯一可评审的记录（测试也钉它）。非定宽表（`uniform: false`）不写 `slot_offsets`。

### D4 运行时的非定宽读路径保留

`ConfigRuntime.ConfigTable.OffsetsFor` 与生成器的 `_off[slot]` 形态**不删**。它是 `uniform: false` 的支撑；今日 5 张表都走定宽 ⇒ 它是**未被执行**的代码，不是死代码。删掉它等于取消逃生门。

> ⚠️ 这条修正了本变更提案初期的一处自相矛盾（既想保留逃生门、又想删掉逃生门的实现）。若将来决定「永远定宽、不要逃生门」，删运行时代码应作为**独立变更**，因为它还牵涉 Lua 侧 `I18nStr` 的槽位读（那需要新增原生绑定 ⇒ 5 平台插件重编）。

### D5 体积提示放在导出输出，不新增诊断等级

`ct/diagnostics/errors.py` 的 `IssueCode` 只有错误级（`TYPE`/`REF`/`DUPLICATE_PK`/`DUPLICATE_CODENAME`/`SCHEMA`/`TEMPLATE`/`WORKSPACE`），没有 warning 级；加一级是独立改动。而导出时 `bytes_normal` 与 `bytes_uniform` 本来就已经算出来了（导出日志形如 `定宽（schema 声明）｜填充率 92.9%（436 B → 424 B，0.972x）`），所以提示就落在这行：体积比明显 > 1 时追加提示。`ct validate` 不做这件事——它不构建字节，为此把二进制写入拉进 validate 是不划算的耦合。

### D6 不升 `template-layout` 格式号

删两个键对**读**是兼容的（`parse` 用 `.get(key, default)`），且本仓处于开发期、无存量需要迁移。升 `/3` 会让所有存量 manifest 被判不可信并卡住 `gen-template`，是纯粹的成本。

## Risks

| 风险 | 处置 |
|---|---|
| 声明 uniform 的表变稀疏 ⇒ 体积膨胀（旧模型估最坏 3.26×，实测真实形状 ≤1.032×） | D5 的导出期提示；必要时该表加 `uniform: false` |
| 全表默认 uniform 会写空 string/vector 对象 | 当前 5 张表实测**反而更小或持平**（0.972×–1.000×，行数少时省下的 vtable 复制占优）；行数变大后才显现（6685 行基准 +3.2%） |
| 逃生门无人日常走 ⇒ 路径腐烂 | 保留一条 fixture 显式声明 `uniform: false`，让该路径持续被测试覆盖 |

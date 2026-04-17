## Context

i18n 流水线现状：
- `extract_i18n_strings` 把所有 i18n 字段写入单文件 `i18n/strings_source.json`，key 用 `table.id.field` 字符串
- `merge_translations` 读 `i18n/strings_{lang}.json`，缺译退回主语言并 warning
- `report_stale_summary` 仅汇总 source 内 `status: stale` 条目
- 翻译者必须人工创建 `strings_{lang}.json`，没有任何骨架辅助
- 字段命名混乱（key 大小写、表名是否大写不统一）

提案要求重构文件布局、引入完整的状态机，以及增加 `ct i18n` 子命令组。本设计聚焦架构与跨模块决策。

## Goals / Non-Goals

**Goals:**
- 翻译者打开任意 lang 文件即可看到当前需要做什么（status 一目了然）
- sync 流程幂等：相同输入运行多次结果完全一致
- 主语言改动 → 自动 invalidate 译文（confirmed=false）
- 增删行/字段 → 自动新增/标记 orphan，不静默丢失译文
- 可分语言、分表运行，便于大型项目分工
- CI 可读取 `ct i18n status --json` 判断翻译完整度

**Non-Goals:**
- 不做向后兼容：旧 `strings_source.json` / `strings_{lang}.json` 不自动迁移
- 不做翻译质量校验（占位符一致性、长度限制等留待后续）
- 不做翻译 memory / 模糊匹配（不在本变更范围）
- 不做 PO/gettext 互操作
- 不做翻译者 GUI / Web 编辑界面

## Decisions

### D1: 目录结构按"语言/表"二维拆分

**决策：** `i18n/source/{table}.json` + `i18n/{lang}/{table}.json`，每文件只承载一张表的翻译。

**理由：**
- 翻译者按表领任务，互不冲突
- diff 干净：策划改一张表只动一个文件
- 增删 i18n 字段时只重写相关表
- 文件名隐含 table，文件内 key 可省略 table 前缀

**备选：**
- 单文件每语言（旧方案）：增量改动 diff 噪音大，并发协作困难 → 否决
- 三维拆分（按字段再分）：文件数量爆炸，无明显收益 → 否决

### D2: lang 文件单条目结构与状态机

**决策：** 每个 key 携带四个字段
```json
"1001.name": {"source": "铁剑", "text": "Iron Sword", "confirmed": true, "status": "translated"}
```

状态计算规则（sync 时由工具计算并写入 status）：

| 当前 source 中 | lang 中 | text | confirmed | → status |
|---|---|---|---|---|
| ✗ | ✓ | — | — | orphan |
| ✓ | ✗ | — | — | missing（新建条目） |
| ✓ | ✓ | 空 | 任意 | missing |
| ✓ | ✓ | 非空 | true | translated |
| ✓ | ✓ | 非空 | false | stale |

sync 时的字段更新规则：
- 若 `lang.source != current_source`：覆盖 lang.source 为 current，同时强制 `confirmed=false`，text 保留
- 若一致：source/text/confirmed 都不动
- 新建条目：`source=current, text="", confirmed=false`
- 不在 source 中的 key：保持 source/text/confirmed 不动，仅状态变 orphan

**理由：**
- `confirmed` 是显式人工开关，比"对比 source 字符串"更直观
- source 字段冗余存在，让翻译者无需切窗口看主语言原文
- 主语言改动 → 自动 invalidate（强制 confirmed=false），杜绝"漏翻"
- 状态机覆盖所有边界（新增/改动/删除/孤儿）

**备选：**
- 翻译者手动改 source 字段（无 confirmed 字段）：耦合两件事，易遗漏 → 否决
- 不持久化 status，每次按需计算：人读 lang 文件时无快速线索 → 否决
- 引入 fuzzy/conflicted 等更多状态：边界变模糊，YAGNI → 否决

### D3: source 文件极简扁平结构

**决策：** `{ "id.field": "text" }`，无包裹对象。

```json
{"1001.name": "铁剑", "1001.desc": "锋利的铁制长剑", "1002.name": "魔法卷轴"}
```

**理由：**
- source 只承载一个语义（主语言原文），不需要嵌套
- 行数 = 翻译条目数，规模感直观
- 后续若需要加元数据（如 comment），改回对象格式即可，是宽进窄出的演进路径

### D4: JSON 写出格式 — 每条占一行

**决策：** 自定义 writer，外层手动写 `{`/`}`/`,`，每条 entry 用 `json.dumps(value, separators=(", ", ": "))` 序列化值。

```json
{
  "1001.name": {"source": "铁剑", "text": "Iron Sword", "confirmed": true, "status": "translated"},
  "1001.desc": {"source": "锋利的铁制长剑", "text": "A sharp iron sword", "confirmed": true, "status": "translated"}
}
```

key 排序：先按 id 升序，再按 schema 中 field 出现顺序。

**理由：**
- 标准 `json.dump(indent=2)` 把每个字段独立成行，diff 噪音大
- 紧凑写法让翻译者一眼看到 source/text/confirmed 同行对照
- 排序保证可重现，避免 sync 之间的虚假 diff

**备选：**
- 直接 `json.dumps(indent=2)`：diff 噪音、扫读慢 → 否决
- 引入第三方库（如 `jsbeautifier`）：依赖膨胀 → 否决

### D5: CLI 命令布局 — Typer 子命令组

**决策：** 创建 `i18n` Typer app 挂载到主 app，提供三个子命令：

```
ct i18n sync     [--lang LANG] [--table TABLE] [--root DIR] [--verbose]
ct i18n status   [--lang LANG] [--by-table] [--json] [--root DIR]
ct i18n compact  [--lang LANG] [--table TABLE] [--root DIR] [--dry-run]
```

`ct export` 在解析 schema 之后、生成各语言产物之前自动调用 sync 内部入口（不打印进度，仅在 verbose 模式下汇总）。

**理由：**
- `i18n` 是独立运维操作（翻译者不需要执行 export），命名空间分离更清晰
- `compact` 是破坏性操作（删除 orphan），分离命令避免误触
- export 内部 sync 保证导出前骨架最新，避免"忘了 sync 就 export"的踩坑

**备选：**
- 把 sync 做成 `ct export` 的副作用，无独立命令：翻译者无法独立刷新 → 否决
- 把 compact 合到 sync 的 `--prune-orphans` 标志：风险藏在常用命令里 → 否决

### D6: status 视图设计

**决策：** 三种渲染模式：
- 默认：每语言一行，进度条 + 各状态计数
- `--by-table`：每语言每表一行，便于定位翻译瓶颈
- `--json`：机器可读，CI 可解析判断完整度

示例默认输出：
```
[en]  85% [████████░░] 170/200 translated, 12 missing, 8 stale, 10 orphan
[ja]  60% [██████░░░░] 120/200 translated, 50 missing, 20 stale, 10 orphan
```

**理由：**
- 默认模式人读最快
- `--by-table` 便于分配翻译任务
- `--json` 是 CI 集成必需

### D7: 删除策略 — orphan 默认保留，compact 显式清理

**决策：** sync 不主动删除 orphan 条目，仅标记。`ct i18n compact` 才物理移除。

**理由：**
- 译文是人工劳动成果，不能因策划误删一行就静默丢失译文
- orphan 状态可见即可，翻译者/策划自行决定是否清理
- compact 单独一步，类似 `git gc`，运维操作显式化

### D8: sync 调用语义

**决策：** sync 流程：
1. 加载所有 schema（拓扑序）
2. 读取所有 Excel（如果文件未变，可走缓存）
3. 对每张有 i18n 字段的表，提取当前主语言 entries → 写 `i18n/source/{table}.json`
4. 对每个 secondary_lang × 每个 i18n 表：
   - 读取（或新建空）`i18n/{lang}/{table}.json`
   - 按 D2 规则更新每个 key
   - 计算 status
   - 紧凑格式写回
5. `--lang LANG` 限定只处理一个语言；`--table TABLE` 限定只处理一张表

`ct export` 内部入口：相同流程但安静运行，仅在 verbose 时输出汇总。

**理由：**
- 表 × 语言双向遍历是 O(N×M)，但每张表已在内存，开销小
- `--lang/--table` 范围控制让大型项目按需操作

### D9: 配置层不引入新键

**决策：** 复用 `global.yaml` 中已有的 `i18n_dir`、`secondary_langs` 配置，不增加新键。

`i18n_dir` 现指 `gd/i18n/`，sync 在其下创建 `source/` 与 `{lang}/` 子目录。

**理由：** 现有配置足够覆盖；保持配置项最小集。

## Risks / Trade-offs

- **[风险] 翻译者忘记把 confirmed 改回 true** → status 仍为 stale，下次 sync 可见；status 视图能显示 stale 数量，CI 可阻断；不会静默错误
- **[风险] 主键变更被当作"删旧 + 新增"** → 旧 key 变 orphan，新 key 是 missing，译文不会自动迁移 → Mitigation：在 compact 命令前提示 orphan 详情，让翻译者人工迁移；后续可考虑相似度匹配但本次不做
- **[风险] sync 重写文件可能丢失翻译者的注释/格式** → 自定义 writer 完全控制输出，但任何手写注释会被覆盖 → Mitigation：在 lang 文件顶部不留注释槽，约定靠 status 字段自描述
- **[风险] 紧凑 JSON writer 实现 bug 导致非法 JSON** → 通过单元测试覆盖（空 dict、含特殊字符的 source、unicode、嵌套对象等）+ 写出后 `json.loads` 自检
- **[风险] BREAKING：旧文件不兼容会让仓库历史出现死文件** → 开发期可接受；本变更明确删除 `gd/i18n/strings_en.json`，重新 sync 生成新结构
- **[风险] 单文件锁竞争（多人同时 sync）** → 当前是单机 CLI，本变更不解决；后续若上 CI 多 worker 再考虑
- **[权衡] orphan 默认不清理 → 久而久之文件会膨胀** → compact 命令解决；`ct i18n status` 显示 orphan 计数提醒

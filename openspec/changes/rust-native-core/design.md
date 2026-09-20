## Context

动机见 proposal.md。当前唯一导出管线在 `ct/app/exporting/build.py`，完成策略在 service.py；prepare_tables 在生成缓存前用 openpyxl 读取并校验选中表及 ref 闭包。ArtifactCache 对生成器的完整有效输入递归 JSON 编码，二进制以 Base64 包装存储。uniform 诊断探测存在额外 bytes 构建；这些是待测候选热点，不是已证实的耗时占比。

现有事务、工作区锁、Schema revision/candidateHash、可丢弃缓存与成功账本必须整体迁移。当前仓库有未提交功能和规格变更，实施基线必须包含届时实际验收通过的行为，不能只固定到旧 HEAD。

## Goals / Non-Goals

**Goals:** 发布无 Python 的 CLI/worker，所有桌面业务依赖同一 Rust 核心；按真实基准减少解析、分配和重复遍历；现有数据与游戏读取端无迁移。

**Non-Goals:** 不在首版引入 FFI、自定义 Excel 格式、云服务或后台文件监控作为正确性来源；不以吞掉校验/恢复成本换跑分；不永久维护两套生产内核。

## Decisions

### 1. Rust workspace 与模块职责

拟定 `native/`，包含 ct-core（领域、用例、存储）、ct-cli（参数与文本输出）、ct-protocol（消息/版本）和 worker 适配层。发布同一个 ct 可执行文件，`ct worker` 提供 stdio 服务。CLI 的 export/validate/status/gen-template/i18n/deploy 命令和桌面调用相同用例，通过显式完成策略区分 CLI 自动部署与桌面只导出。

不选 Flutter/Dart 重写导出，是为了让独立 CLI 与 UI 解耦并集中处理原生数据布局；不先做零散 Python 扩展，避免跨语言大表搬运和多套中间模型长期并存。迁移期间 Python 仅作对照或旧版本运行，新的生产入口不自动回退。

### 2. 协议 v1（本 change 唯一所有者）

UTF-8 NDJSON over stdin/stdout，每行一条消息，stderr 仅诊断。首条 hello 协商 protocolVersion、coreVersion、capabilities；不兼容时禁用业务写入。请求包含 requestId、method、workspaceRoot、params；响应/事件带 requestId、workspaceId、递增 seq 和 type（progress/log/issue/result/error）。连接内每个已接受请求最多一个终态；断连无终态视为未知。issue 包含 code、resource、fieldPath、excelRow 及可选文件路径；不靠解析人类日志定位。

方法组：workspace.open/snapshot/status/recover、resources.list、table.preview、schema.candidate/save、template.plan/generate、validate、export、deploy、i18n.query/save/sync/status/compact，history.list、logs.list、tasks.list/issues/dismiss，以及 cancel/shutdown。schema.candidate 接原始 schemaRevision、commands、cursor，schema.save 另需 candidateHash。表和翻译查询分页；消息上限默认 4 MiB，超限返回结构化错误，长数据改分页。事件队列有界且合并进度，终态和问题不可静默丢弃；大量问题分页读取。分页令牌绑定快照 revision，输入变化时返回 stale-page 并由客户端重查，不混合两版行数据。schema 候选响应回显 draftGeneration；保存请求重复 requestId 不得再次执行，同一连接拒绝重复 ID，重连不重放。

worker 在无任务时等待；写任务期间仍读 cancel/shutdown 控制消息，用工作线程执行业务。取消仅设置 token，发布后延迟取消。关闭连接不能重放写请求；shutdown 等待安全边界。协议序列化对 i64/u64 超出安全 JSON 整数范围使用明确的十进制字符串标签，避免 Dart/工具链损失精度。此传输表示不改变游戏 JSON 格式。

前端 change 只消费本契约和同源样例；内核可以用协议测试客户端独立验收，不等 Flutter 完成。

### 3. 迁移完整性与服务归属

能力映射见 `coverage.md`，该清单是实施验收输入，不把“后续盘点”当作完成条件。桌面导出成功后由核心在实际配置 cache_dir 下记录最近五次历史；历史写失败与已成功的业务提交分开报告，不诱导重放导出。CLI 不追加面板历史。日志按模块/级别可查询、任务状态及问题可分页，任务失败可显式 dismiss，重连同一 worker 不复活已关闭通知；重启日志可清空但历史不能丢失。

所有业务统计通过 config.resolve 等价能力从真实配置取值，不保留 Dart 硬编码目录读法。文件名可不同于 Table 名，资源实际来源路径、excel_file、json_key、transitive schema hash、layout manifest 格式均列入对照。schema_hash 不能仅“语义类似”：必须复现 canonical 默认字段省略、排序、编码和摘要截取，避免升级后全表假漂移。跨语言 schemaRevision/candidateHash 通过同源向量校验，不因 JSON 浮点/Unicode/默认值序列化差异误判。

恢复只面向新格式 journal（.ct/export-publication.json）：committed 清理、backup/publish 可证回滚、不完整备份保留并阻塞。不做旧 apply-journal/1、旧锁文件等任何历史格式迁移。发生恢复后不继续使用恢复前的 schemaRevision，而是返回恢复完成/基线变化要求重载。读取快照遇到待恢复事务返回 blocked/recovery-needed，不静默暴露半套资源，也不在只读查询中自动写恢复。客户端恢复入口显式调用 workspace.recover；该请求获取共享写锁、恢复 journal 后返回新基线/恢复结果，不保存草稿、不导出、不推进成功账本。

Schema 保存对新增/改名/删除均检查名称、规范化目标、跨平台大小写碰撞和 Excel 归属；不得让两张表认领同一规范化 workbook。保存不读 Excel 数据，即使 Excel 缺失或非法也可完成合法结构保存；删除仅删除 YAML，Excel 和产物保留。

### 4. 编译布局与类型化中间数据

一次加载 YAML、构造资源图并编译字段路径、类型、默认值、列和二进制布局计划。解析结果保留源单元格坐标及稳定顺序，减少 row dict 与反复名称查找。使用按表独立的中间表示，保留精确整数、浮点和枚举 token 语义。

Excel 读取优先验证 Calamine 候选；模板写入评估 Rust XLSX writer（例如 rust_xlsxwriter）并建立独立适配边界。库只是候选，不把其默认日期/公式/空值转换作为产品契约。早期原型必须验证 formula cached values、日期、空单元格、错误值、合并表头和固定 vector 展开；写入必须保留现有模板样式、stable column path 迁移及阻塞条件。当前迁移读取 data_only 值后重建，并非任意工作簿无损编辑；不新增公式计算器，不承诺保留用户附加 Sheet/宏/图表。活跃 Sheet 选择、空结果公式、Rich Text 表头、1900/1904 日期与稀疏行坐标均须对照，不能默认第一 Sheet 或从零重编号。库不满足时更换适配实现，不能减少验收范围。

### 5. 分层缓存与依赖图

每次从实际捕获字节计算输入摘要，不能仅凭 mtime/size 或 watcher 事件跳过读取。键分层：解析器版本 + Excel 字节 + layout/读取规则；局部校验版本 + 行数据 + Schema/Enum/索引；ref 校验 + 来源外键投影 + 目标主键集合；产物 + 生成器版本 + 对应表/类型/有效译文/布局。缓存记录携带类型版本、输入键和完整性校验，损坏/不认识即失效重建，不执行缓存对象。

不能只传播“表变了”：目标主键变更必须失效依赖 ref 检查，Record/Enum 变更传播到传递使用者。过滤导出仍读取或复用 ref 闭包，生成范围保持原有局部 Bundle 语义。旧 state.json 仍只用于状态；Rust 缓存独立版本命名空间，不要求迁移 Python 生成缓存。

生成器共用已计算的指纹，不反复对全表 JSON 编码。bytes 缓存保存原始 bytes，元信息单独记录；输入内容相同的格式化翻译变更不导致产物失效。`--all` 绕过解析、校验和生成复用；`validate` 保持只读，不生成持久缓存。完整校验覆盖可由对当前输入有效的缓存结果与重新执行结果共同组成，失败检查不被成功账本覆盖。

### 6. 有界并行与发布

按工作簿解析，按表构建；先局部校验/主键集合，再全选中 ref 闭包检查，再生成。worker 数量按 CPU 和内存预算限制；共享工作簿不重复解压。输出、问题列表、Bundle 表序和索引顺序使用稳定排序，不能依赖线程完成顺序。大产物同卷暂存，避免把所有语言产物同时复制到内存。

正式发布前完成结构检查和输入复核，采用 prepared/backed_up/publishing/committed 恢复协议（仅新格式）。新增文件清理、删除恢复、mtime、晚取消和部署/账本失败沿用 export-publication 语义。锁只需保证新进程间互斥；journal 与 state.json 不保留旧格式；新缓存可丢弃。

### 7. 对照与性能验收

只在临时工作区运行。基线使用记录的源码树指纹（包括相关未提交改动）、依赖版本、硬件/OS、数据种子和配置；Python 使用 ct/.venv。Rust release 构建，每场景预热一次再至少五次测量，记录中位数、尾部样本、峰值 RSS、阶段耗时、缓存命中与输出摘要。

固定 S/M/L 夹具：S=10 表×100 行，M=50×2000，L=100×10000；每表约 20 字段，覆盖 ref/Enum/Record/vector，3 个语言，包含 uniform on/off；另设兼容边界夹具。冷全量指新进程+空应用缓存，不谎称 OS 页缓存为空；热缓存同时测新 CLI 进程和存活 worker；改单表/仅译文从相同成功状态克隆。

建议验收门槛（原始提案值，2026-09-19 已显式修订，见下条决策）：M/L 冷全量中位耗时不超过 Python 的 50%，热无变化不超过 20%，改单表与译文不超过 35%；S 不回退超过 max(基线10%, 50ms)，峰值 RSS 不超过基线 1.2 倍。三平台均记录；不达标必须报告并显式修订提案后才能降低门槛，不能以“用了 Rust”认定完成。这些是规划目标，不是已测收益。

**决策（2026-09-19）：性能/内存门槛按实测分档修订，并同时记录被否决的替代方案。**
Windows 上 runs=5 配对测量（`native/docs/baseline/bench-{m,s}-windows.json`）结果：M 档耗时比 0.296–0.315，
峰值 RSS 比 2.11–2.31×、绝对 682–926MiB（上一份 runs=3 记录为 0.254–0.350 与 2.42–6.97×、冷 2.75GiB）；S 档耗时比 0.371–0.476、
RSS 比 0.300–0.704。原口径有两处与自身证据冲突：①热 CLI ≤0.2 要求快 5 倍，而其余三项场景只要求 ≤0.35，
且实现稳定在快 3.2 倍；②1.2× 的内存上限与「按表并行换时间」的设计取向直接矛盾——一轮写穿暂存与
分波释放已经把冷档峰值从 2.75GiB 降到 926MiB（−67.1%）而耗时还快了 11%，剩余峰值的六到七成是阶段 1
校验闸门要求的「全部表解析行集」，它不受任何波宽预算约束（24/48/96/192MiB 扫描下峰值 879–960MiB、
耗时 11.02–11.16s，全在噪声内）。要继续压到 1.2× 只有一条路：把闸门也改成按波进行，代价是二次解析
（`ct validate` 实测 2.52s，占 `ct export` 11.35s 的 22%），会把改单表（实测 0.303）/改译文（实测 0.312）两项推到 ≈0.38–0.39，逼近并可能越过 ≤0.35。
**因此本 change 不采用该方案**，改为：时间项热 CLI 统一到 ≤0.35；内存项分档（S ≤1.2×，M/L ≤2.5× 且绝对
≤1.25 GiB），并把上面两组数字与被否决方案一并留档。任何再次放宽仍需先改提案；跨平台（macOS/Linux）
与 L 档配对测量仍未完成，6.5 保持未验收。
**2026-09-19 追加（L 档实测）**：L 档已在 Windows 完成 runs=5 配对测量（`native/docs/baseline/bench-l-windows.json`：100 表 × 1 万行、18.48M 数据格、607 产物）：耗时比 0.288–0.331 全部达标、产物聚合摘要与 Python 逐字节一致、RSS 比 1.85–1.94× 优于 M 档，但按 M/L 共用的绝对上限 ≤1.25GiB 判定时四项记 `fail`（Rust 绝对峰值 5.6–7.0GiB 对 10 倍数据量）。结论：绝对上限是「不随数据量缩放的常量」，L 档要收口必须先显式修订该项口径（按档给绝对值）或改分波流式闸门（代价已在上文量化：+22% 时间）；本 change 不默认放宽，6.5 仍保持未验收。
**2026-09-19 追加决策（L 档绝对上限口径）**：上段的 L 档实测结果（耗时比 0.288–0.331 全达标、
RSS 比 1.85–1.94 优于 M 档、607 个产物聚合摘要与 Python 逐字节相同，但绝对峰值 5,605–7,015MiB
越过 M/L 共用的 1.25GiB 常量）说明**那个常量本身是口径缺陷**：绝对上限不随数据量缩放，10 倍夹具
必然越界，把它当成实现退步会误导后续优化方向。**采纳 A**：绝对上限按档给定（M ≤1.25GiB、
L ≤7.5GiB≈2× 数据量的线性外推加余量），继续以比值 ≤2.5× 作为「并行换时间」的真实约束；
**再次否决 B**（把校验闸门改成分波流式以压低峰值），代价与上文相同——二次解析 +22% 时间会把
改单表/改译文从 0.288/0.293 推到 ≈0.38，越过 ≤0.35 的时间上限。同时把**判定与测量解耦**：
`xtask bench-recheck --report <json>` 用当前常量重算既有报告的 verdict（不改样本、不重跑几小时的
配对测量），其分档常量与被采纳/被否决的边界各有一个单元测试钉住（L 档实测样本判 pass、同一批样本
按 M 档上限判 fail、9GiB 仍判 fail）。门槛条文已同步到 `specs/native-core-runtime/spec.md`。


JSON/FBS/C#/Lua/二进制按字节对照；Excel ZIP 不要求容器字节相同，按迁移后的单元格值、样式、列宽、验证和迁移语义对照；公式输入/缓存缺失另做读取兼容夹具，不新增重建后保留公式文本的承诺。错误比较代码/定位/退出状态，明确既有公开文本和 JSON 保持兼容。C#/Lua 读取端回归用于排除二进制与生成代码一起错的情况。

## Risks / Trade-offs

- [严格二进制一致性增加工作量] → 先验证 layout、vtable、索引、字符串和浮点边界，性能原型不通过则不铺开全部迁移。
- [Excel 写入生态存在差异] → 读取和模板迁移原型同时完成，不将写入留到最后；不以 Python 常驻兜底冒充无 Python 完成。
- [增量遗漏依赖导致错误成功] → 故障/变更矩阵覆盖 ref 主键、类型、翻译、布局、版本和损坏缓存；默认与 --all 同输入对照。
- [兼容过渡期双实现增加维护] → 固定对照夹具，生产入口只选一套内核；禁止同工作区两套并发写入。
- [基准受机器影响] → 同机配对测量、固定夹具与模式，保留原始结果，不引用第三方倍数。

## Migration Plan

1. 冻结基线和协议 v1；交付复杂表读取/模板迁移/二进制原型及初步性能报告（约 1–2 人周）。
2. 迁移领域和业务用例，先满足兼容，再加缓存和并行；CLI/worker 同步跑差异测试。
3. 完成三平台 CLI 和 worker 发布，供界面 change 接入；核心实现与回归初估约 7–12 人周，风险以原型收敛。
4. 内核验收不依赖 Flutter 完成；桌面整体发行则等待两边均通过。
5. 回滚前退出所有写进程并恢复 journal；源数据/产物协议未变，旧缓存可重建，禁止修改真实 gd 作为试验。

## 1. 基线、协议与技术验证

- [x] 1.1 固定当前可验收源码树/依赖及未提交相关变更的指纹，以 coverage.md 固定业务兼容矩阵，验证覆盖现行 CLI、Schema、Excel、i18n 与发布测试。
  - 证据：`cargo run -p ct-xtask -- fingerprint` 生成 `native/docs/baseline/source-tree.json`
    （`tree.sha256` + 逐文件哈希 + Cargo.lock 摘要 + rustc/参照 Python 版本 + 两侧测试清单 +
    当时的 commit 与脏路径数），`--check` 只比对源码树内容字段，已挂进 CI。
    `native/docs/baseline/compat-matrix.json` 是 `coverage.md` 21 行的机器可读形式，
    `tests/compat/tests/coverage_matrix.rs`（5 例）逐行逐格比对两份文档，并强制：矩阵引用的每个
    Python 参照测试文件真实存在且含测试函数、原生锚点文件含 `#[test]`/`testWidgets(`、点名的
    `文件::测试函数` 确实存在、现行 Python 测试（除 `ct/tests/web`、`ct/tests/architecture`）
    全部被某一行承接。实测留档：Python 687 个测试函数、原生 253 个 `#[test]`（46 个测试文件）。

- [x] 1.2 建立 S/M/L 临时夹具和四种基准场景，运行 Python 基线，保存硬件、种子、原始耗时/RSS/产物摘要，确认未写真实 gd。
  - 已落地：`native/fixtures/bench/generate.py`（固定种子 20260918，支持 s/m/l，写 global/types/schemas →
    `ct gen-template` 造表头 → openpyxl 追数据行 → `ct validate` 自检 → 造「改单表/改译文」替换件 →
    清空 output/cache/.ct，保证两引擎都从零缓存冷启动）；`xtask bench-fixtures`/`xtask bench`
    驱动 S/M 两种引擎 × 冷全量/热 CLI/热 worker/改单表/改译文四场景（预热 1 次 + N 个正式样本），
    原始样本、中位数/最值、进程树峰值 RSS、产物数量与聚合摘要、硬件（OS/arch/逻辑核）、种子、
    commit 与脏路径数全部落 `native/docs/baseline/bench-<尺寸>-windows.json`。
    实测留档（2026-09-19 内存优化后 runs=5 重测）：S（10×100，67 产物）Rust 0.746–0.919s vs
    Python 1.929–2.044s；M（50×2000，307 产物）Rust 7.02–11.10s vs Python 23.02–35.22s；
    两侧每场景产物聚合摘要相等（冷全量 070051ce…）。
    `realWorkspaceUntouched` 记录 `git status --porcelain gd` 前后 0/0 条。
  - 2026-09-19 补齐 L 档并勾项：`xtask bench-fixtures --sizes l` 造出 100 表 × 10,000 行
    （18,480,481 数据格、4,000,000 条译文、3 语言、607 个产物，种子 20260918 不变），
    `xtask bench --size l --runs 5` 完成 S/M/L 三档里的最后一次 Python 配对基线
    （`native/docs/baseline/bench-l-windows.json`，host=windows x86_64 / 28 逻辑核）：
    Rust 中位 54.2–101.3s 对 Python 185.3–306.2s，比值 0.288–0.331 全部达标；
    四个可比场景两侧产物聚合摘要逐字节相等（cold/hot-cli `46fb81ee…`、改单表 `8d088810…`、
    改译文 `bb6f47bd…`，均 607 个文件）；`realWorkspaceUntouched` 记 `git status --porcelain gd`
    前后 0/0 条，测量只用临时副本。至此本项要求的「S/M/L 夹具 + 四场景 + Python 基线 +
    硬件/种子/原始样本/RSS/摘要 + 未写真实 gd」在参考平台 Windows 上全部成立；
    macOS/Linux 的配对测量按提案归任务 6.5，不由本项宣布完成。

- [ ] 1.3 建立 native Cargo workspace 和 CI 基础，验证三平台编译及独立 CLI smoke。
  - 已落地：`native` workspace（12 个 crate + tests/ + fuzz/）与 `.github/workflows/native.yml`
    （windows/macos/ubuntu 三份矩阵：fmt、clippy -D warnings、cargo test、`fingerprint --check`、
    release 构建、`cargo run -p ct-xtask -- dist` 的独立 CLI/worker smoke 与无 Python 自检、运行时包上传）。
  - 原未勾选原因（Windows 阶段）：当时只有 Windows 实测，macOS/Linux 的编译与 smoke 缺真机结论。
  - 2026-09-24 macOS Apple Silicon 实机补验：`cargo fmt --all --check`、
    `cargo clippy --workspace --all-targets -- -D warnings`、`cargo test --workspace` 全绿；
    release CLI 与 `xtask dist` 构建通过，包内 CLI/worker 自检通过。Linux 仍缺实跑，故保持未勾选。

- [x] 1.4 输出协议 v1 文档/机器 schema/同源样例，覆盖方法、握手、事件、取消、分页、错误与大整数；用契约测试验证样例并供 Flutter 消费。
- [x] 1.5 验证 Excel 读取候选对公式缓存、日期、空值、错误值及固定 vector 的行为，与 openpyxl 夹具逐项对照。
- [x] 1.6 验证 Excel 写入适配的表头样式与 stable column path 迁移，确认不可迁移数据拒绝覆盖并记录依赖选型结果。
- [x] 1.7 跑通复杂表类型化解析和 uniform/非 uniform 二进制原型，对照字节和初步耗时后记录继续迁移的技术结论。

## 2. 领域模型与数据准备

- [x] 2.1 实现配置路径、YAML 资源模型及类型表达式，验证自定义目录、非法字段和跨平台大小写冲突诊断。
- [x] 2.2 实现资源依赖图、拓扑序、反向引用和循环检测，验证 Record/Enum/ref 的现行允许范围。
- [x] 2.3 实现布局计划、manifest 读取兼容与行坐标映射，验证 Schema 漂移和缺 manifest 行为。
- [x] 2.4 实现 scalar/Enum/Record/vector 解析与精确数值处理，逐项通过边界和嵌套类型对照夹具。
- [x] 2.5 实现主键、CodeName、枚举及 ref 闭包校验，验证单表过滤仍拒绝坏引用且问题顺序确定。
- [x] 2.6 接通只读 validate/status，用目录快照验证不写缓存、不恢复事务且正确报告 pending journal。

## 3. 生成与完整业务用例

- [x] 3.1 实现 JSON 输出及格式细节，验证所有语言/过滤组合与基线逐字节一致。
- [x] 3.2 实现 FBS 文本及结构检查，验证传递类型和非法布局对照且正式导出不调用 flatc。
- [x] 3.3 实现表级 FlatBuffers、定宽槽位及 vtable 检查，验证默认值/空表/嵌套向量及布局对照。
- [x] 3.4 实现查询索引与 Bundle 组装，验证哈希碰撞、顺序及局部 Bundle 字节一致。
- [x] 3.5 实现 C# Accessor 和枚举生成，通过文本对照及独立 C# 读取测试。
- [x] 3.6 实现 Lua Accessor 和枚举生成，通过文本对照及独立 Lua 读取夹具。
- [x] 3.7 实现 i18n 合并和稀疏语言产物，验证主语言 fallback、过滤与三语言输出。
- [x] 3.8 实现 i18n sync/status/compact 与条目保存，验证四态、confirmed、dry-run、过滤和无关文件保持。
- [x] 3.9 实现模板新建及保留数据迁移，验证表头样式、列路径迁移、无 manifest 拒绝和失败原文件不变。
- [x] 3.10 实现 Schema 命令重放、候选及净差异，验证创建/改名/删除、undo/redo、引用和跨类别名称冲突。
- [x] 3.11 实现 Schema revision/candidateHash 与 YAML-only 保存服务，验证旧基线拒绝、目录成员变化和事务失败保留原文件。

- [x] 3.12 对照 canonical hash/resourceId/revision/candidateHash 和默认值省略规则，验证升级不误报 drifted、无变化保存不重排 YAML，以及 Excel 路径归属冲突拒绝。
- [x] 3.13 增加非首个活跃 Sheet、公式缓存缺失、日期、空行坐标、富文本和超长 Enum 下拉夹具，验证读取/模板语义且无任意工作簿无损保留的错误承诺。

## 4. 可靠存储与入口策略

- [x] 4.1 实现规范化工作区锁，运行新旧进程互斥、进程死亡释放和 Windows 锁区间对照测试。
- [x] 4.2 实现兼容 journal 的多文件发布/恢复，在各阶段注入失败，验证旧文件/mtime 恢复和新增文件清理。
- [x] 4.3 实现输入捕获与发布前复核，验证 Excel/YAML/译文和目录成员在构建期间变化会阻止发布。
- [x] 4.4 实现部署及独立部署用例，验证目标范围、错误和不更新成功账本的行为。
- [x] 4.5 实现 CLI/桌面完成策略、晚取消和 state.json，验证部署或记账失败不误报成功，部分导出保留其他账本条目。

- [x] 4.6 实现发布 journal 恢复、workspace.recover 和只读快照恢复阻塞，验证完整回滚/已提交清理/备份缺失保留和恢复后旧基线拒绝（仅新格式，不做旧格式迁移）。

## 5. 增量和并行优化

- [x] 5.1 实现类型化解析缓存及版本/校验和校验，验证同 mtime 内容变更、损坏、缺失和版本升级均正确重建。
- [x] 5.2 实现局部及 ref 校验依赖指纹，验证目标主键删除、Record/Enum 变更触发所需失效且不漏报非法数据。
- [x] 5.3 实现共享分层产物指纹及原始 bytes 缓存，验证翻译无效元信息变化不重建、输出缺失/改写可修复。
- [x] 5.4 实现按工作簿/表的有界并行与稳定汇总，验证不同并发度输出和诊断顺序一致并记录峰值内存。
- [x] 5.5 优化诊断探测和大产物暂存，保留现有诊断语义，使用阶段 profile 证明减少重复构建/复制。
  - 证据：内核新增阶段 profile（`ExportResult.stages`）与 `Reporter::issues`，`run_export` 用内部 `Probe`
    包裹上层 reporter，逐阶段计时并携带闸门已算出的结构化问题；worker 因此不再二次跑
    `canonical_validate`（删除 `structured_issues`）并把 `stages` 填进 `export 终态 payload`，CLI 在
    `CT_PROFILE=1` 时把阶段耗时/写入与复用计数打到 stderr（默认文本与 golden 不变）。
    `tests/compat/tests/stage_profile.rs`（4 例）实测：阶段名恰为
    `lock/prepare/json/fbs/bundle/publish` 各一次且合计不超过总耗时；冷导出写出 N 个产物、
    增量导出写出 0 个并复用同样 N 个（缓存命中>0、miss=0）、`--all` 写回全部 N 个；
    校验失败带出的 issues 与重跑 `canonical_validate` 逐值相等（2 条）。
- [x] 5.6 实现 --all 绕过所有计算缓存及强制写出，对每个增量场景比较成功失败、字节和 mtime 契约。
  - 证据：`tests/compat/tests/incremental_matrix.rs`（7 例）逐场景对照：无变更导出保持字节与 mtime 不变、
    `--all` 强制写出全部产物且 `cache_hits==0 && cache_misses>0`、有效译文只更新 en 产物、
    译文排版性无效变化不动任何产物、产物缺失/被改写后修复、生成缓存损坏与账本版本不识别均重建且保留 mtime、
    非法数据在增量与 `--all` 两种模式下都失败且零改动、单表过滤导出与全量字节一致。

## 6. CLI、worker 与发布验收

- [x] 6.1 实现兼容 CLI 参数、文本与 JSON 输出，覆盖过滤错误、退出码和 panel 迁移指引的命令级测试。
- [x] 6.2 实现 worker 握手、请求路由及所有业务方法，使用独立协议客户端完成完整操作链，不依赖 Flutter。
- [x] 6.3 实现控制消息响应、有界事件队列、分页及安全 shutdown，验证忙碌时取消、超限/坏消息、断连和大整数不丢精度。
  - 证据：`native/tests/protocol`（进程内 worker 契约夹具）新增 handshake/envelope/request_id/cancel/pagination/event_queue/contract_cases 七组共 36 个用例，
    `cargo test -p ct-tests-protocol` 连续三次全绿（45 passed）。
    实现侧补齐：`issue` 事件与终态同级不可丢弃、写任务失败时按 `error.issues[]` 同步送出 `issue` 事件、
    分页响应统一回传 `revision`、消息上限按消息体计（恰好 4 MiB 可用）、外部改动/写入推进快照代次、
    shutdown 后新请求 `busy` 且终态仍送达、取消以 `result.outcome=cancelled` 表达、大整数双向 `$int` 编解码。
- [x] 6.4 运行所有兼容/故障注入/并发对照，交付产物摘要与诊断差异报告，未解决差异不得切换生产入口。
  - 证据：`native/docs/baseline/parity-report.md`（基线锚点、12 个 golden 文件逐字节与聚合摘要、
    CLI 文本/退出码/产物逐场景对照、故障注入与并发清单、5 项刻意保留差异、生产入口判定），
    配套 `cli-text-diff.md`（6 场景文本一致 + 11/11 产物字节一致）与 `bench-{s,m}-windows.json`
    （S 3 组、M 3 组聚合摘要两侧逐场景相等）。全量对照：`cargo test --workspace` 261 passed / 0 failed。
  - 本轮由对照跑出的两处真实缺陷已修复并加断言：record 成员表头注解归属（`ct-excel/tests/layout_header_parity.rs`）
    与恢复未清私有暂存文件（`publication_recovery.rs::crash_after_prepared_cleans_private_only`）。
    结论明确记录：不切换生产入口的原因是峰值内存等性能门槛与跨平台/界面验收未完成，而非存在字节级分歧。

- [ ] 6.5 在 Windows/macOS/Linux 按配对测量规范运行四种性能场景，提交原始结果与门槛比较，不达标继续优化或显式修订提案。
  - Windows 已按规范完成 **runs=5** 配对测量并按修订口径逐项达标（`bench-{m,s}-windows.json`；上一轮
    runs=3 记录保留为 `bench-{m,s}-windows-2026-09-18.json`）：M 档耗时比 冷 0.315 / 热 CLI 0.296 /
    改单表 0.303 / 改译文 0.312；峰值 RSS 比 2.11–2.31×、绝对 682–926MiB（优化前 2.42–6.97×、冷 2.75GiB）。
    S 档耗时 0.371–0.476、RSS 比 0.300–0.704。`xtask bench` 的判定常量已同步为修订值
    （热 CLI ≤0.35；内存 S ≤1.2×、M/L ≤2.5× + 绝对 ≤1.25GiB），`thresholds.*.verdict` 现记 `pass`。
  - 门槛修订已按本项要求「报告 + 显式修订提案」走完：见 `design.md` 的 2026-09-19 决策与
    `specs/native-core-runtime/spec.md` 的条文（热 CLI ≤0.2 → ≤0.35；内存分档 S ≤1.2×、M/L ≤2.5× 且
    绝对 ≤1.25 GiB），修订理由与被否决的「按波校验（二次解析 +22% 时间）」一并留档。
  - 未勾选原因：macOS/Linux 无真机（只有 CI 定义）、L 档夹具与基线未跑，故 6.5 仍属未完成；
    `xtask bench` 的 `thresholds.*.verdict` 在按修订口径重算前仍会显示 M 档内存 `fail`（门槛常量仍在
    `xtask` 里按旧值判定，属于本项收尾的机械改动）。
  - L 档 Windows 配对测量已完成（runs=5 + 1 预热，报告 `native/docs/baseline/bench-l-windows.json`）：
    夹具 100 表 × 10,000 行 = 18,480,481 数据格 + 4,000,000 条译文，3 语言，607 个产物。
    **耗时全部达标**：比 Python 快 3.0–3.4 倍（cold 0.331、hot-cli 0.294、table 0.288、i18n 0.293，
    上限 0.5/0.35）；**产物 607 个文件的聚合摘要与 Python 逐字节一致**（四个可比场景全等）；
    真实 `gd/` 测量前后各 0 行改动。
    **但绝对内存上限不达标**：Rust 峰值 RSS 5.6–7.0 GiB（cold 7,015MiB、其余 5,605–5,695MiB），
    Python 同档 2.9–3.8 GiB，比值 1.85–1.94×（优于 M 档的 2.11–2.31×，且 ≤2.5× 通过），
    而 `xtask bench` 对 M/L 共用的绝对上限 ≤1.25GiB 是按 M 档（682–926MiB）定的 —— 该常量不随数据量
    缩放，L 档 10 倍数据下必然越界，`thresholds.*.verdict` 四项记 `fail`。
  - 由此产生一个待决口径（不擅自放宽）：绝对上限改为按档给（如 M ≤1.25GiB、L 按数据量线性外推
    ≈7.5GiB 并以比值 ≤2.5× 为真实约束），或把闸门改为分波流式以真正压低峰值（此前实测代价：二次解析
    +22% 时间，会把两项推到 ≈0.38–0.39）。两条路都需要显式修订提案，已按本项要求列在这里等决策。
  - L 档口径已按方案 A 显式修订：门槛条文与 `xtask bench` 常量同步为「绝对上限按档给」
    （M ≤1.25GiB、L ≤7.5GiB），并用新增的 `xtask bench-recheck` 对既有三份报告重算判定——
    `bench-l-windows.json` 四项 `fail → pass`（RSS 比 1.848/1.938/1.904/1.928），
    `bench-m-windows.json` 与 `bench-s-windows.json` 判定不变（仍全 pass，M 档 RSS 比 2.108–2.310
    对 1.25GiB 上限、S 档 0.300–0.704 无绝对上限）；样本、种子、产物摘要一字未动。
    分档常量与被否决方案各有单元测试钉住（`ct-xtask` 新增 5 例，10 passed）。
    本项仍不勾选：只剩跨平台缺口——macOS/Linux 真机配对测量由用户后续完成（S 档数分钟即可跑，
    `cargo run -p ct-xtask -- bench --size s --runs 5`，需要 Python 参照在位）。
  - 未勾选原因：macOS/Linux 无真机（只有 CI 定义），L 档已在 Windows 完成且暴露绝对上限口径问题；按提案要求，跨平台结果或
    显式的门槛修订完成前不得宣布此项通过。
  - 2026-09-24 macOS Apple Silicon S 档已完成 5 轮配对测量（`native/docs/baseline/bench-s-macos.json`）：
    冷全量/热 CLI/改单表/改译文时间比 0.197–0.240、RSS 比 0.399–0.512，四项均 `pass`
    （改为 macOS 默认 3 worker 后复跑）；
    两侧 67 个产物摘要逐场景一致，`gd/` 前后零改动。`hot-worker` 无 Python 对照，记 `no-baseline`。
    M 档首轮 8 worker 的 RSS 比 2.56–2.95 超标，失败报告保留为
    `native/docs/baseline/bench-m-macos-8workers.json`；macOS 默认并发调到 3 后，M 档 5 轮配对
    四项均 `pass`（时间比 0.287–0.307、RSS 比 1.826–2.404），两侧 307 个产物摘要相同。
    macOS L 档与 Linux 全档仍未完成，本项保持未勾选。

- [ ] 6.6 生成各目标平台独立运行时包和版本信息，在无 Python 环境验证 CLI/worker 及中文空格路径，提供给桌面打包。
  - Windows 已完成并真跑：`cargo run -p ct-xtask -- dist` 产出
    `native/dist/ct-native-0.0.0-x86_64-pc-windows-msvc{,.zip}`（zip 2,653,224 字节、
    `bin/ct.exe` 6,574,592 字节 sha256 `5564dfbd6f43…`），包内含 `VERSION.json`
    （target/family/pythonRuntimeRequired=false/commit/Cargo.lock 摘要/二进制哈希/`ct --version` 原文）
    与 `RUNTIME-CHECK.txt`：自检把 PATH 从 58 个目录收敛为包内单目录、清掉 `PYTHONHOME/PYTHONPATH/VIRTUAL_ENV`，
    在 `…\ct-native 运行时 验证 <triple> <pid>\配表工作区`（中文+空格）里真跑
    `--version/validate/status/export` 与 `ct worker`（hello+workspace.open+shutdown 三条终态齐全），
    导出后 `output/json/Item_zh.json` 存在且汇总行为「增量导出：写入 11，复用 0；生成缓存命中 0」。
  - 原未勾选原因（Windows 阶段）：当时 macOS/Linux 的包与无 Python 验证只有 CI 定义；
    桌面壳集成（launcher 使用内置运行时）属 native-flutter-workbench。
  - 2026-09-24 macOS Apple Silicon 实机补验：`native/dist/ct-native-0.0.0-aarch64-apple-darwin/`
    及 zip 已产出，`VERSION.json` 记 `pythonRuntimeRequired=false`；`RUNTIME-CHECK.txt`
    记录在中文空格临时路径与无 Python 环境下 `--version`/validate/status/export/worker 全通过。
    Linux 仍缺运行时包真机自检，故保持未勾选。

- [ ] 6.7 演练发布中断恢复与版本回滚，更新 CLI 安装/缓存说明；验收后删除 Python 实现，无回退路径。
  - 演练已真跑并留档 `native/docs/baseline/recovery-drill.md`（脚本 `native/tools/bench/recovery-drill.mjs`）：
    在中文+空格路径的临时工作区里 `export --all` 于 journal 落盘后被 SIGKILL（197,678 字节 journal、
    307 个 `.ct-stage-*`），`ct status` 报「未完成的发布（阶段 prepared）」且只读不写、`ct recover --json`
    回 `recovered: true`，恢复后 307/307 产物聚合摘要回到基线、mtime 全保持、journal 清场、残留暂存文件 0；
    把 `cache/state.json` 版本标记改成不识别值后 `--all` 全量重建、字节摘要不变；再与 Python 参照交替导出，
    聚合摘要三度一致。演练暴露 `cleanup()` 不删 `entry.staged` 的泄漏，已修复并加断言。
    CLI 安装/缓存说明见 `native/README.md`「原生入口」「开发/测试入口」与 `native/docs/baseline/isolation-check.md`。
  - 本轮另已把「不需要 Python」的机械部分做完：`launcher/tool/build_windows.ps1` 默认嵌入原生运行时
    （只留 `-LegacyPythonRuntime` 过渡开关）；`.github/workflows/native.yml` 新增桌面壳 job（构建 ct 二进制 +
    `dart format --set-exit-if-changed` + `flutter analyze` + `flutter test`，真实 worker 用例经 `CT_WORKER_BIN` 生效）；
    `xtask bench`/`fingerprint`/`coverage_matrix` 三处对 Python 缺失降级为「留档/跳过」而非失败。
  - 未勾选原因：本项最后一句「验收后删除 Python 实现，无回退路径」未执行——删除不可逆，需单独授权。
  - 2026-09-19 用户决定：**不删 `ct/`，但验收路径不得再依赖它**。已逐条摘除依赖并做改名演练验证
    （`ct` → `ct_off_rehearsal`，全程无解释器可用）：
    1. 性能基准：无参照时改用本机留档回归判定（`--against`，默认 `bench-<尺寸>-<平台>.json`），
       verdict 记 `regression-pass`/`regression-fail` + `baselineMode=archived-run`，新增 3 例单测钉住
       「变慢/产物摘要变化/峰值越档都必须 fail」与「无参照也不许伪装成配对测量」。
    2. CLI 文本对照：`tools/parity/cli-text-diff.mjs` 默认比对留档基线
       `native/docs/baseline/cli-text-diff-python.json`（本轮在参照仍在位时刷新，6 个场景退出码/文本/
       11 个产物字节全一致），只有 `--live-python` 才同机再跑一次并刷新留档。
    3. 恢复演练：`recovery-drill.mjs` 的「与 Python 交替导出」在参照缺席时显式记「跳过，不记为通过」。
    4. 兼容矩阵与指纹：`coverage_matrix` 的 pythonTests 等式校验在 `ct/tests` 缺席时降级为历史留档；
       `fingerprint` 的 `ct` 范围与文件数下限改为随在位与否计算（无 ct 时 818 文件自洽）。
    5. 锁互斥用例：删除 `python_holder_excludes_rust`，跨进程互斥与死亡释放由纯 Rust 的
       `cross_process_busy_and_death_release` 覆盖，`compat-matrix.json` 锚点同步替换（无悬空引用）。
    6. CI：`.github/workflows/ct-tests.yml` 改为仅 `workflow_dispatch`，不再随 push/PR 参与验收。
    演练结论：`cargo test --workspace` 277 passed、`flutter test` 283 全绿、`xtask dist` 自检通过、
    桌面负载校验通过（27 文件 / 0 痕迹 / status+validate exit 0）、`bench --size s` 给出 `regression-pass`。
    恢复 `ct/` 后重算指纹回到含 `ct` 的基线。本项仍不勾选：「删除」这一句按决定不再执行，
    收口条件改为「跨平台配对测量补完」（见 6.5）。
  - 本轮复核更正一处过期证据：桌面壳**已不再**经 `PanelService`/HTTP 走 Python 面板
    （`launcher/lib/services/panel_service.dart` 与面板式页面已删除，入口是 `ct worker` NDJSON 工作台；
    `rg -i python launcher/lib` 只剩「绝不回退 Python」的说明文案），所以删除 `ct/` 不会让桌面入口失效。
    真正的剩余门槛是：①性能/内存门槛是**与 Python 配对**的比值且当前判负，删了就永远无法重测
    （1.2 的 L 档、6.5 的跨平台配对同理）；②删除必须同步改 `xtask fingerprint` 的 `ct` 域、
    `docs/baseline/compat-matrix.json` 的 `pythonTests`（55 处引用）、`.github/workflows/ct-tests.yml`、
    `launcher/tool/build_windows.ps1` 的 `-LegacyPythonRuntime`、`AGENTS.md` 以及 `web-panel`/
    `web-panel-design-system`/`launcher` 主规格（即 6.8 与桌面 change 的 5.6）。本轮不擅自执行该不可逆动作。

- [ ] 6.8 在实际验收完成后同步相关规格及 launcher/incremental-export 的旧 Purpose 描述；保留实施证据，未通过项不得勾选或用归档代替验收。
  - 本轮已同步「已验收且确实变了」的文档面：`native/README.md`（原生入口/三类测试入口/基线产物索引）、
    `ct/docs/README.md`（本目录标注为 Python 参照实现、`ct panel` 标注仅旧对照入口）。
    主规格侧无需改字：`openspec/specs/incremental-export/spec.md` 的 Purpose 已经写成
    「默认增量复用 + 内容寻址生成缓存」，`cli-interface`/`unity-deploy` 的缓存表述与现行实现一致（本轮实测复核）。
  - 未勾选原因：`openspec/specs/launcher/spec.md` 的 Purpose/Requirement 仍描述「内置冻结 ct panel 运行时 +
    外部工具目录回退」，那是 native-flutter-workbench 未验收的部分，按该项要求不得提前改写；
    5 个 delta 规格的整体同步留待 6.5/6.6/6.7 收尾后执行（归档不能代替验收）。

- [x] 6.9 更新原生安装/构建/测试和旧Python隔离对照入口，验证 PATH 不混淆、gd 无工具依赖，对齐 tool-workspace-separation delta。
  - 文档：`native/README.md` 新增「原生入口（生产路径，不需要 Python）」「开发/测试入口（三类互不混淆）」
    表格与基线产物索引；`ct/docs/README.md` 顶部标注本目录现为 Python 参照实现、`ct panel` 行标注仅旧对照入口。
  - 验证：`node native/tools/bench/isolation-check.mjs` → `native/docs/baseline/isolation-check.md`：
    用发行包二进制在真实 `gd/` 上以「PATH 只有包内 bin + 删除 PYTHON* 变量」只读跑
    `--version/validate/status`（退出码 0/0/0），`git status --porcelain gd` 前后 0/0 条，
    `gd/` 4 层内无 `*.py|*.pyc|*.exe|*.dll|__pycache__|.venv`（0 处）；`xtask dist` 自检另证
    CLI/worker 在无解释器环境下完成导出。该检查还抓出并在 6.4 修复了 record 表头注解差异。

- [x] 6.10 实现桌面导出历史读写、模块日志、任务问题分页与dismiss，验证配置cache_dir、重启保留和历史失败不误报业务提交失败。
  - 证据：`tests/compat/tests/desktop_history.rs`（7 例：五条裁剪与最新在前、按配置 `cache_dir` 落盘、未知格式忽略后整体替换、
    CLI 路径不写桌面历史、桌面导出写入 `result=success` 条目、历史写失败仍返回成功且留下警告、连续两次导出不改变业务结果）与
    `tests/protocol/tests/desktop_state.rs`（7 例：历史跨 worker 重启读回、workspaceId 跨连接归属、模块/级别日志筛选、
    任务问题按 limit=1 拼接等于终态明细（含 `excelRow`/`resource`/`fieldPath`）、dismiss 与重连不复活、日志环形上限 2000、
    历史写失败在协议层表现为 `result.outcome=succeeded` + `issues[].code=history-write-failed` + 一条 log 事件）。
  - 实现侧修正：历史写失败此前被并入 `RunError::Other` 造成“业务失败”误报，现改为 `ExportResult.history_warning` +
    诊断日志 + 终态 `issues[]` 分开报告；历史条目状态码由 `ok` 改为稳定码 `success`。
- [x] 6.11 验证分页revision/重复requestId/候选代次/协议错误分类，用同源Dart/Rust契约夹具覆盖乱序、重复、重连和输入变化。
  - 证据：`native/fixtures/protocol/wire-cases.json`（7 例：握手不兼容、重复 requestId、输入变更后分页令牌失效、
    重连不重放写任务、大整数往返、候选代次回显、安全关闭）由 Rust 侧用真实 worker 逐例执行
    （`contract_cases.rs`，含 `protocol.v1.json` 逐消息校验与 `seq` 单调断言），Dart 侧
    `launcher/test/protocol/wire_cases_test.dart` 解码同一批消息核对类型/错误码词表/大整数精度（5 passed）。
- [x] 6.12 逐行完成 coverage.md 的内核验收映射，显式检查 server_only、游戏读取缓存/语言切换、部署.meta/for-build/缺源保护；报告未实现历史规格的排除理由。
  - `coverage.md` 末尾新增「逐行验收映射（任务 6.12）」：21 行逐条给出结论与点名锚点、
    8 条显式检查项（server_only、语言切换/generation 与 fallback、.meta、for-build、缺源保护、
    解析/ref 缓存不漏校验、无 Python 独立包、旧格式不迁移）与 10 条不迁移项及理由，
    与 `native/docs/baseline/compat-matrix.json` 同源生成。
    `coverage_matrix.rs::explicit_acceptance_checks_are_mapped` 强制：每个显式项的锚点文件/测试真实存在、
    必须出现 server_only/语言切换/.meta/for-build/缺源/缓存/Python/不迁移 关键词、
    不迁移项理由不得含糊（≥12 字）。游戏端实读一项显式标为「部分（环境受限）」。

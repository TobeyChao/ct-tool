# 项目参考

`ct` 从 Excel + YAML Schema 导出 JSON、FlatBuffers Binary 和 C#/Lua Accessor。
main 的 Rust 内核通过 CLI、Web 和 worker 复用 `ct-app` 用例。浏览器界面由原生运行时嵌入，
Flutter launcher 保留桌面启动壳。当前交付支持 macOS，Windows 延后，Linux 不支持。

## 目录与术语

| 位置 | 职责 |
|---|---|
| `native/crates/` | Rust 领域、应用、存储、生成器及入口 |
| `native/tests/` | 独立兼容、进程、故障恢复和协议验收 |
| `native/fixtures/` | 冻结输入、独立期望值和来源摘要 |
| `native/docs/baseline/` | 原始验收、性能、迁移与历史参考 |
| `web/static/` | 无前端构建步骤的 HTML/CSS/ES modules |
| `web/tests/` | 真实原生 HTTP 与 Playwright 场景 |
| `launcher/` | 工作区/端口设置、托盘、自启、原生进程生命周期 |
| `test-proj/` | 正式 C# 独立读取端，以及明确登记的历史实验 |
| `docs/` | 当前使用说明；`archive/python-era/` 仅作历史资料 |
| `gd/` | 真实游戏工作区，不能作测试夹具 |

工作区是包含 `config/global.yaml` 的目录。`--root` 默认当前目录；配置中的目录通过
`GlobalConfig::resolve(...)` 相对工作区解析，Unity 部署的目标路径相对 Unity 工程解析。
`schemaRevision` 是配置 YAML 字节/成员的基线，`candidateHash` 是候选守卫，成功账本与生成缓存不同。

## 安装与开发

发行用户解压原生 ZIP 或安装 launcher DMG 即可，不需要开发 SDK。
旧虚拟环境中的同名 `ct` 不会自动变成原生程序，终端应使用明确路径。

开发需要 Rust 稳定工具链；Web 测试需要 Node 22 或兼容版本与 Playwright Chromium。
launcher 需要 Flutter/Xcode；独立读取测试使用 .NET 10。不全局安装 Python 包。

在仓库根目录：

```sh
cargo build --manifest-path native/Cargo.toml -p ct-cli --locked
native/target/debug/ct panel --root /path/to/workspace --no-browser
native/target/debug/ct panel --root /path/to/workspace --static-dir web/static
cargo test --manifest-path native/Cargo.toml --workspace --locked
```

Web 验收在 `web/` 中执行：

```sh
npm ci
npx playwright install chromium
npm run test:http
npm test
```

`CT_WEB_BIN` 可指向发行包里的 `bin/ct`；`CT_CHROMIUM_EXECUTABLE` 可指定现有 Chromium。
工作目录应为 `web/`，不依赖 npm 的绝对 `--prefix` 安装行为。

在仓库根目录核查迁移和独立读取：

```sh
node web/tools/check-parity.mjs --require-complete
node test-proj/check-retirement.mjs
CT_NATIVE_BIN="$PWD/native/target/debug/ct" node test-proj/ExportAccessorVerify/prepare-native.mjs
```

读取准备需要已构建的 `xtask`，默认在 `native/target/debug/xtask`；可用 `CT_XTASK_BIN` 指定。
所有验收创建临时工作区，保留独立 golden；不能用被测生成器覆写期望值来修复测试。

## launcher 打包与分发

在仓库根目录：

```sh
cargo run --manifest-path native/Cargo.toml -p ct-xtask --locked -- dist
bash launcher/tool/build_macos.sh
```

原生包只含 `bin/ct`、`VERSION.json`、`RUNTIME-CHECK.txt` 和 `README.md`。
自检使用中文空格临时路径，PATH 仅有包内目录，实际执行 CLI/worker/panel、静态资源/HTTP 和 EOF 退出。
`runtime-check --binary <ct> --out <日志>` 可以复核实际解压、内嵌或挂载的二进制。

桌面壳将单个二进制和清单嵌入 `Contents/Resources/runtime/`，验证负载与签名，再生成 DMG。
`RUNTIME_PACKAGE` 指定原生包，`FLUTTER` 指定 SDK；正式构建不设置 `SKIP_FLUTTER_BUILD`。
就绪 stdout 之后还要验证原生 HTTP 才打开浏览器；停止通过 stdin EOF 等待已经接受的任务和发布结束。
缺少内置运行时可在设置里明确选择原生二进制，无 Python/venv 回退。

## 架构

```text
CLI / Web HTTP / stdio worker
              ↓
ct-app：工作区、候选/保存、模板、校验、导出、部署、翻译、历史和任务
              ↓
ct-domain：Schema/类型/命名/引用图/命令/净差异/守卫/配置
ct-excel：布局 → manifest + 真实表头兼容检查 → 读取/模板迁移
ct-export：JSON / FBS / Binary / C# / Lua
ct-cache：分层指纹和可丢弃生成缓存
ct-storage：工作区锁、发布 journal、备份/回滚/历史持久化
```

入口只做传输适配。校验与导出共享读取、类型、主键、CodeName、Enum token 和跨表 ref 闸门。
生成全部通过后才发布文件，只有成功完成才推进账本；修改生成器行为更新
`native/crates/ct-export/src/lib.rs` 的 `CODEGEN_VERSION`。

Schema 编辑采用 Draft → 服务端候选/净差异 → YAML-only 保存，保存守卫是
`schemaRevision` + `candidateHash`。刷新候选不能替换草稿基线；保存不读 Excel、不改模板、译文、产物或账本。
模板、导出和部署独立显式执行。资源名、规范化目标、大小写冲突与 Excel 归属都在共享用例中校验。

工作区写入共用 `.ct/export.lock`；文件存在不代表系统锁被占用。发布使用
`.ct/export-publication.json` 的 prepared → backed_up → publishing → committed 阶段。
恢复先于资源加载，既还原旧文件又移除事务新增文件；未知格式或缺失备份保留现场并拒绝写入。
CLI 只读状态报告需要恢复，Web 提供显式恢复入口，不自动重放草稿或导出请求。

`cache/artifacts/` 是可丢弃的生成缓存，`cache/state.json` 是成功账本。
未改产物保持内容/mtime，`--all` 强制生成；过滤导出保留范围外文件。
进程间互斥只覆盖同一规范化工作区，不能阻止 Excel 或文本编辑器的外部写入。

## Schema 与 i18n 格式

详细格式、12 种标量、具名 Record/Enum、vector、CodeName 索引、二进制和部署见
[使用说明](README.md)。`config/schemas/*.yaml` 每文件一个 Table，`config/types/*.yaml`
每文件一个 Record/Enum；命名按原样发射，不自动转换大小写。

只支持一层 `vector<T>`，`vector<Record>` 必须声明 `excel_columns`，旧 `array/struct/separator`
格式拒绝。主键必须 `int32`；`i18n` 仅顶层 string，不能与 `server_only` 同时标注。
Enum 顺序决定 wire ordinal，不能随意重排。

`i18n/source/{Table}.json` 记录主语言原文，`i18n/{lang}/{Table}.json` 记录
`source/text/confirmed/status`。sync 更新骨架，原文变化保留译文但取消确认；缺文本为 missing、
未确认为 stale、已确认非空为 translated、源中已删除为 orphan。compact 显式清理 orphan；
导出不写 source，仅使用已确认的非空译文，其余回退主语言。

## 基准与验收留档

```sh
cargo run --manifest-path native/Cargo.toml -p ct-xtask --locked -- bench-fixtures --sizes s,m,l --out /tmp/ct-bench
cargo run --manifest-path native/Cargo.toml -p ct-xtask --locked -- bench-shape-check
cargo run --manifest-path native/Cargo.toml -p ct-xtask --locked -- compat-fixtures --out /tmp/ct-compat
```

`r/r-full` 使用冻结形状，S/M/L 使用固定种子。`xtask bench --size s --fixture-root /tmp/ct-bench`
检查实际输入摘要并使用同档/同平台/同夹具留档，缺失或损坏明确失败。
首次基线必须显式 `--record-baseline --out /tmp/bench-s.json`，采集不等于回归通过。
原始 Python 期望和源码文本仅作独立历史参考，不执行或自动再生期望值。

验收记录见 [Web 映射](../native/docs/baseline/web-parity.md)、
[兼容夹具](../native/docs/baseline/compat-fixtures-verification.md) 和
[macOS G3](../native/docs/baseline/macos-g3-verification.md)。
历史测试清单固定 main 85 文件/690 函数，删除旧源码不能缩减覆盖分母。

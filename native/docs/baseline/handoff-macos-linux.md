# macOS / Linux 交接清单（跨平台未完成项）

分支 `feat/native-workbench-cutover` 已把 Windows 侧能独立验证的全部收口：`cargo test --workspace` 277 passed、
`flutter test` 307 全绿、`fingerprint --check` 一致、S/M/L 三档 Windows 配对测量留档、profile 帧时间留档、
桌面负载经 `check_payload.ps1` 复核无 Python。2026-09-24 已在 Apple Silicon macOS 上开始实机验收；
本文件保留尚未完成的跨平台步骤和判定口径。

## 0. 一句话现状

- 验收路径已零 Python 依赖（改名演练实测：无 `ct/` 时 cargo 277、flutter 283、`dist` 自检、负载校验全通过）。
- 常规构建、测试、发行与留档回归不需要 Python。基准夹具由 `xtask bench-fixtures` 生成；
  同机配对测量需要一个参照 `ct` 入口，缺参照时走本机留档回归判定。

## 1. 先修代码再上真机（不需要 mac，但 mac 上必须用到）

| # | 缺口 | 位置 | 为什么要先修 |
|---|---|---|---|
| a | **POSIX RSS 采样已接入，仍需性能实测** | `native/crates/ct-xtask/src/bench.rs` 用 `ps` 轮询进程树 RSS，并向 worker 传入 stdin；采不到 RSS 直接失败，不以空值判通过 | macOS/Linux 的 6.5 仍须提交配对报告；不同 OS 的 RSS 数值只与同机 Python 参照比较 |
| b | **减少动态效果已覆盖工作台显式动画，仍需真机确认** | `launcher/lib/ui/tokens.dart` 的统一函数让面板折叠、导航与标题栏过渡、弹出菜单及键盘选择滚动在 `MediaQuery.disableAnimations` 下即时完成；widget 测试钉住面板和菜单路径 | 5.1 仍须检查系统偏好切换、中文输入法与焦点遍历 |
| c | **macOS DMG 脚本已接入，发行验收未完成** | `launcher/tool/build_macos.sh` 生成 `.app` 和带 Applications 快捷方式的 DMG；本地为 ad-hoc 签名 | 5.3 仍需验证安装、启动、卸载，并在正式外部分发前完成开发者身份签名与公证 |
| d | 夹具生成器 Rust 化（可选） | `native/fixtures/bench/generate.py` + `xtask bench-fixtures` | 彻底去掉最后一条 Python 路径。代价：新夹具与旧存档不同分布，S/M/L 三档需重跑配对测量以重钉参照数字（L 一档约 2.2 小时） |

2026-09-24 macOS 已完成 S 档 5 轮配对测量：`native/docs/baseline/bench-s-macos.json` 的
冷全量/热 CLI/改单表/改译文均为 `pass`（默认 3 worker，时间比 0.197–0.240、RSS 比 0.399–0.512），
Rust/Python 各场景 67 个产物摘要一致，`realWorkspaceUntouched.unchanged=true`。
`hot-worker` 没有 Python 对照，按设计记 `no-baseline`，不能算配对通过。
M 档首轮使用默认 8 worker 时 RSS 比 2.56–2.95，保留失败报告
`native/docs/baseline/bench-m-macos-8workers.json`。将 macOS 默认并发限制为 3 后，
`native/docs/baseline/bench-m-macos.json` 的 5 轮配对测量四个可比场景均为 `pass`：
时间比 0.287–0.307、RSS 比 1.826–2.404、Rust 峰值中位 846–985 MiB；
两侧各场景 307 个产物摘要一致，`gd/` 无改动。M 档 `hot-worker` 同样无 Python 对照。

## 2. 每台 macOS / Linux 机器上的执行清单

```bash
git clone <repo> && cd ct-tool
# 前置：Rust 工具链；Flutter 仅 macOS 需要（Linux GUI 不在首发范围，Linux 只跑 CLI/worker）

# 1) 任务 1.3：三平台编译 + 独立 CLI/worker smoke
cd native
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace                 # 期望全绿；内含真实 worker 子进程用例
cargo build --release -p ct-cli
./target/release/ct --version
./target/release/ct status --root ../gd         # 只读，期望 exit 0
./target/release/ct validate --root ../gd       # 只读闸门，期望 exit 0/1，不得崩溃
printf '{"type":"hello","protocolVersion":1,"coreVersion":"probe","capabilities":["workspace"]}\n' \
  | ./target/release/ct worker | head -n 1      # 期望第一行 hello，protocolVersion=1

# 2) 任务 6.6：本平台独立运行时包 + 无 Python 自检
cargo run -p ct-xtask --release -- dist
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
node tools/bench/isolation-check.mjs "dist/ct-native-0.0.0-$TRIPLE"

# 3) 任务 6.5：四场景测量
#   3a 同机配对（最强证据；需要参照 `ct` 入口，缺参照时跳过）
cargo run -p ct-xtask --release -- bench-fixtures --sizes s
cargo run -p ct-xtask --release -- bench --size s --runs 5 \
    --python ../ct/.venv/bin/ct --out docs/baseline/bench-s-macos.json
#   3b 零 Python：相对本机留档做回归判定，输出到 target/ 避免覆盖配对报告
cargo run -p ct-xtask --release -- bench --size s --runs 5 \
    --against docs/baseline/bench-s-macos.json --out target/bench/bench-s-regression.json
cargo run -p ct-xtask --release -- bench-recheck --report docs/baseline/bench-s-macos.json

# 4) 验收快照指纹（验收/发布前重算并提交；日常提交不再要求同步，
#    CI 只把当前源码树摘要写进运行摘要，漂移不阻塞）
cargo run -p ct-xtask --release -- fingerprint
cargo run -p ct-xtask --release -- fingerprint --check

# 5) 桌面壳（macOS）
cd ../launcher
flutter pub get
dart format --output=none --set-exit-if-changed lib test integration_test test_driver
flutter analyze
flutter test
CT_WORKER_BIN=../native/target/release/ct flutter test integration_test -d macos
```

## 3. 判定表：什么输出 = 可以勾哪一项

| 观察到的结果 | 结论 |
|---|---|
| `cargo test --workspace` 全绿 + `dist` 自检「通过」+ `ct status/validate` 在中文带空格路径下 exit ≤1 且不崩 | 1.3、6.6 该平台部分成立 |
| `bench` 报告 `thresholds.*.verdict` 全为 `pass`（同机配对）或 `regression-pass`（本机留档），且 `realWorkspaceUntouched.unchanged=true` | 6.5 该平台场景达标 |
| 出现 `no-baseline` | 该平台既无参照也无留档：**不算通过**，先做 3a 或用 `--against` 指定基准 |
| 出现 `regression-fail` 且 `medianRatio` 为空 | 相对本机留档变慢 >1.25× 或产物摘要变了：必须查因，不得默认放宽 |
| `responsiveness-<mode>.md` 三阶段 build p95 <8ms、max <34ms、raster p95 <33.4ms | 5.2 该平台部分成立 |
| mac 上 `build_macos.sh` 第 4/5 步报「包内无解释器 + 隔离环境 status 通过」 | 5.6 的「安装包不含/不启动 Python」该平台成立 |

## 4. 已知平台差异与坑（本仓库实测过的）

- **RSS 口径不可比**：Windows 用 `Process.PeakWorkingSet64`，且真值是进程树 `peakTreeRssKb`（venv 的 `ct.exe` 是控制台存根，单进程会少算）。补 POSIX 采样必须同样按进程树统计，否则与 Windows 存档数字不可比。
- **golden PNG 不能跨平台复用**：字体与栅格化不同。mac 上跑 `test/workbench_golden_test.dart` 与 `e2e_workbench_chain_screens_test.dart` 需单独生成一套（evidence 建议加 `-darwin` 后缀），否则会把「平台差异」误报成「界面坏了」。上一轮已因同机像素比对含真实耗时的面板，把全链截图改成「只产出不比对」。
- **NFD 文件名**：macOS 会把中日韩文件名归一成 NFD，Windows 是 NFC。i18n 语言目录与产物名要做一次显式对照。
- **单实例锁**：`single_instance_lock.dart` 对「查不出来」是 fail-open（并在 stderr 说明），只有 `TimeoutException` 才判「真被别进程持有」。mac 验证双启动时若看到第二个实例，先确认走的不是 fail-open 分支。
- **deploy 目标**：`unity_project` 支持绝对路径与相对工作区根解析；mac 上路径分隔符与大小写敏感性与 Windows 不同，独立部署要比对**落盘文件清单**而不是只看 exit 0。
- **真实 `gd/` 会被"顺手"当工作区**：`SettingsStore._inferDefaults()` 从可执行文件上溯找到
  `launcher/pubspec.yaml` + `lib` 就把**同级 `gd/`** 当默认工作区。`flutter build/drive` 出来的
  `ct_launcher.exe` 位于 `launcher/build/...` 下，上溯必然命中——所以任何真机集成跑（drive、
  `-d windows/macos` 的 integration test、手工启动的包）**默认就开着真实 gd**，点导出/同步就是写真实数据。
  自动化用例必须显式传 root（`worker.start(workspaceRoot: ...)`），并已加
  `node native/tools/gd-guard.mjs -- <命令>` 作为守卫：命令跑完 `git status --porcelain gd` 非空即失败。
  **已按构造收紧**（2026-09-21）：`SettingsStore.inferWorkspacePath()` 在可执行文件位于包内 `build/` 之下、
  或环境带 `FLUTTER_TEST`/`CT_INTEGRATION_TEST` 时**一律不推断**，界面显示「尚未绑定工作区 · 在「设置」里选择配表工作区」。
  代价（已确认接受）：开发者用 `flutter run`/`drive` 起的实例不再自动指向仓库 `gd/`，要手选一次（选完持久保存）；
  发行包（放在游戏仓库里、没有 `pubspec.yaml` 祖先）本来也命中不了推断，行为不变。
- **`ct-tests.yml`** 已改为仅 `workflow_dispatch`：它跑不跑都不影响验收，别当门禁用。

## 5. 收尾顺序（跨平台完成后）

1. RSS 采样与减少动态效果的代码路径已接入；先完成 macOS 实测与真机交互检查，再核 Linux。
2. 6.5 三平台齐 → 6.6 各平台包齐 → 勾 5.6（它只差「内核验收通过后」这个前置）。
3. 6.7：按已定方针**不删 `ct/`**；勾选时要把「验收后删除 Python 实现」显式改写为「Python 已退出验收路径」，不得默认放宽。
4. 6.8：最后做规格同步与归档——`openspec/specs/launcher/spec.md` 的 Purpose 仍写「内置冻结 ct panel 运行时 + 外部工具目录回退」，必须在桌面验收成立后改写；归档不能代替验收。

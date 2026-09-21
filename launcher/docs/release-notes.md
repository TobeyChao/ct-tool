# ct 配表工作台 · 发行说明与已知限制

面向使用者与验收者的一页说明。数字与结论都来自本仓库可复算的检查，不做无法验证的承诺。

## 当前交付形态

| 项 | 结论 |
| --- | --- |
| 桌面壳 | Flutter 桌面应用，版本 `0.1.0+1`（`launcher/pubspec.yaml`） |
| 内核 | Rust 单二进制 `ct`（`ct 0.0.0`，release），经 stdio NDJSON 协议 `ct worker` 提供全部业务能力 |
| Windows 产物 | `launcher/build/windows/x64/runner/Release/` 整目录即分发（`ct_launcher.exe` + 同级 `runtime\ct.exe`，27 个文件） |
| macOS 产物 | `launcher/tool/build_macos.sh` 产 `.app`（运行时在 `Contents/Resources/runtime/ct`），**必须在 macOS 上构建** |
| 运行时来源 | 只有两条：包内 `runtime/ct(.exe)` → 设置里的显式路径。**没有 Python/venv/Web 服务回退** |
| 安装前置 | 目标机器不需要 Python、不需要仓库、不需要网络服务；路径含中文与空格已实测可用 |

## 怎么装、怎么跑

1. 把整目录拷到任意位置（不需要管理员权限，也不需要安装）。
2. 双击 `ct_launcher.exe`。
3. 首次进入「设置」把工作区指到含 `config/global.yaml` 的配表工作区——应用**不会自动绑定**任何目录，
   选一次后会记住。
4. 常规链路：Schema 页编辑（只进草稿）→ 保存（只写 YAML）→ 模板预检/生成 → 导出页「校验」→「导出」→
   「独立部署」；翻译页做 sync 与逐条保存；底部任务区看任务/日志/历史。
5. 卸载 = 删掉应用目录。用户数据只在应用支持目录：
   `%APPDATA%\com.ct\ct_launcher\shared_preferences.json`（偏好）、`ct_launcher.lock`（单实例锁）、
   `ct\drafts\`（未保存的 Schema 草稿信封，按工作区与基线隔离）。不留服务、不留计划任务。

## 快捷键

`Ctrl+P` Quick Open ｜ `Ctrl+S` 保存 Schema 草稿 ｜ `Ctrl+Z` / `Ctrl+Shift+Z` 撤销/重做草稿 ｜
`Ctrl+Shift+D` 净差异 ｜ `F1` 帮助。输入框聚焦时 `Ctrl+Z` 让给文本撤销。

## 本版界面变化（对齐 Web 面板）

- 颜色与字号逐值取自 Web 面板 `tokens.css`（22 个常量）。
- 导航改为 236px 文字侧栏（模块分组 + 底部「导出文档 / 帮助与反馈 / 关于」），整窗窄于 740 收成图标栏。
- 顶部草稿条收成 4 个动作（撤销 / 重做 / 放弃草稿 / 保存变更）+ 状态点 + 一句可点摘要，
  「步骤」与「净差异」进同一个两页弹层；无草稿且无撤销历史时整条不占位。
- 资源区动作收进两个菜单（「新建」「选中资源」），未选中资源时后者整体禁用。
- 属性区分组为「资源 / 字段 / 枚举 / 危险操作」，字段与枚举注明「顺序即 ordinal，会改既有数据 wire 值」。

## 已验证到什么程度

- 内核：`cargo test --workspace` 277 例全绿；`cargo clippy --workspace --all-targets -- -D warnings`、`cargo fmt --check` 干净。
- 桌面：`flutter test` 315 例全绿（含真实 `ct worker` 的协议串测、全链截图与六模块矩阵用例）、`flutter analyze` 0 issues、`dart format` 无差异。
- 负载：`pwsh launcher/tool/check_payload.ps1` 在「PATH 只剩包内 runtime、`PYTHON*`/`VIRTUAL_ENV`/`CONDA_PREFIX` 全清」的
  隔离环境里真跑 `ct --version`、`status`、`validate` 全 exit 0，负载内 Python/Flask 痕迹 0 处。
- 布局：1440x900 / 1280x800 / 1024x700 × 100%/125%/150% 金标矩阵（Schema 模块）+ 六个模块在 1024x700 的
  100%/150% 逐模块截图（`launcher/test/evidence/matrix-*.png`），无 RenderFlex 溢出。
- 真实数据工作区（`gd/`）在以上所有自动化中 0 行改动（守卫 `node native/tools/gd-guard.mjs`）。

## 已知限制（如实列出）

1. **没有安装器与代码签名**：Windows 只交付目录包，未做 MSIX/Inno，也未签名 → 首次运行会有 SmartScreen 提示，
   也不存在「升级安装」路径（换版本 = 换目录）。对应任务 5.3 未完成。
2. **macOS / Linux 未做真机验收**：这两平台的构建脚本、运行时包与负载复核只在 CI 定义与脚本里存在，
   本机无对应平台。跨平台编译（1.3）、配对性能测量（6.5）、平台运行时包（6.6）都还开着。
3. **截图矩阵里中文是方块**：`flutter_tester` 不带 CJK 字体，PNG 只能验布局与遮挡；字体度量、换行与
   行高以真机运行为准。
4. **输入法、焦点遍历与「减少动态效果」未在真机核**：中文 IME 组合、Tab 焦点顺序、系统动画偏好
   （任务 5.1）需要人工在 Windows/macOS 上确认。
5. **单实例 / 开机自启 / 托盘的真机行为未验收**：代码路径与偏好读写有测试覆盖，双启动不增 worker、
   系统自启状态一致性属真机项（任务 2.5）。
6. **内存门槛按档给**：绝对上限为 M 档 ≤1.25 GiB、L 档 ≤7.5 GiB（L 档 10 倍数据下 Rust 峰值 5.6–7.0 GiB），
   与 Python 的比值（≤2.5×）才是真实约束；这是显式修订过的口径，不是「已达绝对低内存」。
7. **旧设置迁移只做清理不做搬运**：`tool_dir`、`port`、`python_path` 等 Python 面板时代的键在检测到时
   清除并一次性提示，不尝试转换成新配置。
8. **草稿基线不跨版本**：保存要求 `schemaRevision` + `candidateHash` 双守卫，工作区基线变了旧草稿会被拒绝，
   需要重算候选——这是防覆盖设计，不是缺陷，但升级后重开旧草稿会看到「基线已变」。
9. **导出/部署面板含真实耗时**：这些数字每次不同，因此截图证据不做像素比对（见 `launcher/test/evidence/chain-text-log.md`
   的同源文字留档）。

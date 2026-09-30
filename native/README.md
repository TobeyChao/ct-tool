# ct 原生内核

Rust 内核提供 CLI、原生 Web 服务和 stdio worker，三者复用 `ct-app` 用例。
main 保留浏览器 Web 界面及原有 Flutter 启动壳；没有迁入分支中的 Flutter 工作台。

## 启动与开发

在仓库根目录运行：

```sh
cargo build --manifest-path native/Cargo.toml -p ct-cli
native/target/debug/ct panel --root /path/to/workspace --no-browser
# 静态资源开发模式（发行版默认嵌入资源）
native/target/debug/ct panel --root /path/to/workspace --static-dir web/static
```

Windows 二进制为 `native/target/debug/ct.exe`。`panel` 默认监听 `127.0.0.1:8000`，
可指定 `--host`、`--port`；端口冲突会报错退出，不自动换端口。
无效工作区仍能打开页面查看诊断。Ctrl+C/终止信号会等待请求和正在进行的发布结束。
launcher 用 stdin EOF 请求跨平台安全退出。

`--root` 指向游戏工作区，路径按配置中的 `resolve` 规则解析。测试使用临时夹具，勿对真实 `gd/` 做测试导出。
旧虚拟环境内的同名 `ct` 仍是 Python 版本；请使用明确的原生二进制路径。

## 目录

- `ct-domain`：Schema、命令、候选、净差异和校验。
- `ct-app`：工作区、保存、模板、导出、翻译、历史和任务编排。
- `ct-storage`：共享锁与可恢复文件发布。
- `ct-excel` / `ct-export` / `ct-cache`：Excel、产物生成和缓存。
- `ct-web`：HTTP 边界与嵌入 `web/static`，直接调用应用用例。
- `ct-cli` / `ct-worker` / `ct-protocol`：命令行与 stdio 协议。
- `ct-xtask`：基准、夹具、指纹和原生运行时发行。

## 验证

```sh
cargo test --manifest-path native/Cargo.toml --workspace
npm ci --prefix web
npm run test:http --prefix web
npx --prefix web playwright install chromium
npm test --prefix web
node web/tools/check-parity.mjs
cd launcher && flutter test
```

`check-parity --require-complete` 是 Web 迁移门槛，当前 146/146 个旧场景已覆盖。
Python 的业务、测试和部分再生脚本暂留作为对照，不能将“原生运行不需要 Python”解释为“仓库已完全去 Python”。
对等清单及执行证据见 [web-parity.md](docs/baseline/web-parity.md)。

## 发行

```sh
cd native
cargo run -p ct-xtask -- dist
```

发行包在 `native/dist/`，只包含原生运行时，静态资源已嵌入二进制。
自检在中文空格临时路径及无 Python 的 PATH 下执行 CLI、worker、panel HTTP 与安全退出，
结果保存在包内 `RUNTIME-CHECK.txt`。桌面打包见 [launcher](../launcher/README.md)。

## 迁移与剩余门槛

保持原浏览器 origin（协议/主机/端口）才能读取旧 IndexedDB 草稿。
已知路径分隔符差异可接续；未知草稿格式保留并阻止覆盖，旧基线冲突不会自动重放。
`panel_history.json` 导入到原生 `history.json`，原文件保留、标记与条目一次原子落盘。
旧 Apply journal 不猜测恢复；保留材料并阻止写入。

`docs/baseline/` 中从 `2d7dfc9` 引入的工作台、性能和平台记录是该分支历史证据，不能充当 main 新 Web 的验收。
S/M/L 与 `r/r-full` 基准夹具由 Rust `xtask bench-fixtures` 生成；部分 golden 再生仍使用历史 Python 脚本。
新旧 S/M/L 夹具分布不同，旧性能留档不能用于回归判定；`xtask bench` 会检查夹具摘要。
完整去 Python 需等 G1/G2/G3 全部通过，详见 OpenSpec `native-web-python-retirement`。

# Native Web

静态资源由 `native/crates/ct-web/build.rs` 嵌入原生 `ct`。开发可用 `ct panel --static-dir web/static`。
HTTP 适配器直接调用 `ct-app`；不启动 Python 或 stdio worker 代理。

先 `cargo build --manifest-path native/Cargo.toml -p ct-cli`，再 `npm ci --prefix web`。
运行 `npm run test:http --prefix web` 和 `npm test --prefix web`；后者需要先安装 Playwright Chromium。
可用 `CT_WEB_BIN` 指定待验收二进制，`CT_CHROMIUM_EXECUTABLE` 指定已有浏览器。
所有测试创建临时工作区，不修改真实 `gd/`。

迁移覆盖检查：`node web/tools/check-parity.mjs`；加 `--require-complete` 会在旧场景未全部承接时失败。
旧 Python Web 在验收完成前保留。原生构建和上述验收不依赖 Python，但尚未完成全仓 Python 退役。

升级时沿用原来的浏览器配置、host 和端口，才能读取同源 IndexedDB 草稿。
已知路径分隔符/末尾斜杠别名会接续；冲突或未知格式保留原记录并提供查看入口。
发现未完成发布时，顶部显示恢复入口；恢复前拒绝展示半套资源，恢复成功后手动
刷新重新读取。未知旧 Apply 或缺失备份会保留材料并说明阻塞原因。

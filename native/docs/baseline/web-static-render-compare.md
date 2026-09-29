# 旧 Web 与原生 panel 的静态迁移对照

2026-09-28 在 macOS arm64 上，以同一临时 `workspace`（`config/global.yaml`、`config/schemas/Item.yaml`，无真实 `gd/` 数据）分别启动 main 旧 `create_app(root)` 和原生 `ct panel --root root --port 0 --no-browser`。旧服务只用于迁移期对照，由 `ct/.venv/bin/python` 启动；正式 Node/Playwright 测试不启动 Python。两端由同一 Chromium headless shell 1234 访问 `/#/export`，视口 1280×900，开启 reduced motion。

同一浏览器脚本采集投影、五项导航、首屏标题/徽标/按钮及禁用状态、进度文案、四个样式链接、sidebar/main 的 display 与整数像素尺寸，以及页面脚本错误。原始两份值与比较结果见 [web-static-render-compare.json](web-static-render-compare.json)，`match: true`。这证明当前首屏关键结构与尺寸一致；不替代 6.4 的完整视口、缩放与截图矩阵。

源文件清单及每项旧 SHA-256 固定在 `web/static-manifest.json`：23 个文件中 17 个保持字节相同，6 个适配文件有具体说明。`node web/tools/check-static-assets.mjs --live-old` 可在迁移期重新核对旧树；不传此参数时检查只需 `web/`，可在旧 `ct/` 删除后继续运行。`web/tests/static-assets.test.mjs` 逐个从原生 HTTP 读取全部 23 个文件并检查模块导入，`web/tests/static-initial.spec.mjs` 在无 Python 的真实浏览器里继续核对冻结的旧首屏关键值。

# Flask + Vue 3 本地面板技术栈调研报告

> 调研日期：2026-08-09
> 目的：为 ct 配表工具的「网页面板」（策划在本机浏览器操作：导出 / 校验 / i18n 进度 / 表格管理）确定 Flask + Vue 3 组合的具体使用方式。
> 背景约束：本地单用户、Windows/macOS 双平台、轻量方便、尽量少让策划碰命令行；已倾向 Flask（后端，只出 JSON）+ Vue 3（前端，不用 npm/vite 构建链，用全局构建/ESM 单文件）。
> 方法：以一手来源为主（官方文档、官方源码、标准库文档），社区教程/真实项目为补充。检索量见文末附录。

---

## TL;DR 结论摘要

1. **Flask 官方文档专门有一节「Single-Page Applications」模式**：把前端静态文件放进 `static` 子目录，加一个 catch-all 路由返回 `index.html`，即可和 API 共存。这是 Flask 托管 Vue 单页的标准姿势。[来源：Flask 官方文档](https://flask.palletsprojects.com/en/stable/patterns/singlepageapplications/)
2. **Vue 3 官方明确支持无构建链使用**：`<script>` 加载全局构建（`vue.global.js`）或 ESM + import map；无构建时用 `setup()` 选项而非 `<script setup>`；生产环境必须换 `.prod.js` 版本。[来源：Vue 官方 Quick Start](https://vuejs.org/guide/quick-start.html) [来源：Vue 官方 Production Deployment](https://vuejs.org/guide/best-practices/production-deployment.html)
3. **体积可接受**：`vue.global.prod.js` ≈ 159 KB（gzip ≈ 58 KB），`vue-router.global.prod.js` 同理提供全局版，本地托管无感。[来源：vuejs/core PR #11904 体积表](https://github.com/vuejs/core/pull/11904#event-14265764240) [来源：Vue Router 官方 Installation](https://router.vuejs.org/installation)
4. **进度推送用 SSE 而不是 WebSocket**：Flask 官方 streaming 文档支持生成器流式响应；浏览器 `EventSource` 单向接收、自动重连，本地单用户一个连接足够。Flask 1.0+ 开发服务器默认 threaded，可以支撑「SSE 挂一个线程 + 其他请求并发」。[来源：Flask streaming 文档](https://flask.palletsprojects.com/en/stable/patterns/streaming/) [来源：MDN EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource) [来源：Flask API 文档 run()](https://flask.palletsprojects.com/en/stable/api/)
5. **后台任务用 `threading` + 内存状态即可**：单用户本地工具不需要 Celery/RQ/Redis；线程安全用标准库 `queue.Queue`，取消用 `threading.Event`。社区对低流量场景的明确结论是 threading 可行。[来源：Stack Overflow 讨论](https://stackoverflow.com/revisions/9e57999e-feb4-4b88-b19b-161aa7907d68/view-source)
6. **本地服务安全基线**：绑定 `127.0.0.1`、不开 debug（官方警告 debugger 可执行任意代码）、前端由同一 origin 托管所以不需要 CORS。[来源：Flask Quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)
7. **真实项目验证**：Enferno 是「Flask + Vue 3 + Vuetify 3，零构建链、无 node_modules」的成熟开源项目；grip、flaskwebgui 演示了「Python 本地 server + 自动开浏览器」模式。[来源：Enferno](https://github.com/level09/enferno) [来源：flaskwebgui wiki](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-flask-and-flaskwebgui/26c6b8ac80e5d6c4682c373cc8671efc628780db)
8. **跨平台打开浏览器用标准库 `webbrowser`**：Windows/macOS/Linux 都支持打开默认浏览器（macOS 走 `MacOSXOSAScript`，Windows 走 `windows-default`）。启动脚本惯例：Windows `.bat`（`CALL .venv\Scripts\activate`）、macOS `.command`（`source .venv/bin/activate`）。[来源：Python 官方 webbrowser 文档](https://docs.python.org/3/library/webbrowser.html)
9. **职责边界有官方模板**：Flask 的 error handler 可以把 HTTP 错误统一转成 JSON（官方「Returning API Errors as JSON」一节），自定义业务异常（如我们的校验错误）同理可序列化；Flask 只出 JSON、Vue 只负责渲染。[来源：Flask errorhandling 文档](https://flask.palletsprojects.com/en/stable/errorhandling/)

---

## 1. Vue 3 无构建链：官方支持，生产可用

### 1.1 两种官方加载方式

Vue 官方 Quick Start 明确给了「Using Vue from CDN」章节，两种方式都无需构建步骤：

**方式 A：全局构建（Global Build）**

```html
<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
<div id="app">{{ message }}</div>
<script>
  const { createApp, ref } = Vue
  createApp({
    setup() {
      const message = ref('Hello vue!')
      return { message }
    }
  }).mount('#app')
</script>
```

官方原文：「When using Vue from a CDN, there is no "build step" involved. This makes the setup a lot simpler, and is suitable for enhancing static HTML or integrating with a backend framework.」同时官方提醒：无构建时**不能使用 SFC 语法（`.vue` 文件）**，Composition API 要用 `setup()` 选项形式（`<script setup>` 需要构建工具）。

**方式 B：ES Module + Import Map**

```html
<script type="importmap">
  {
    "imports": {
      "vue": "https://unpkg.com/vue@3/dist/vue.esm-browser.js"
    }
  }
</script>
<div id="app">{{ message }}</div>
<script type="module">
  import { createApp, ref } from 'vue'
  createApp({
    setup() {
      const message = ref('Hello vue!')
      return { message }
    }
  }).mount('#app')
</script>
```

官方还提供了「Splitting Up the Modules」模式：可以拆成多个普通 `.js` 文件（ES module 互相 `import`），无构建链也能模块化组织代码——页签/表格/i18n 等每个视图一个文件。

关键限制（官方原文）：**ES modules 不能通过 `file://` 协议打开，必须走 `http://` 本地服务器**。这正好与我们的 Flask 服务模式天然契合；Import Maps 需要 Safari 16.4+（Chrome/Edge/Firefox 早已支持）。

来源：
- Vue 官方 Quick Start（CDN / Global Build / ESM / Import Maps / Splitting Up the Modules）：https://vuejs.org/guide/quick-start.html

### 1.2 生产构建要求

Vue 官方 Production Deployment 文档「Without Build Tools」一节原文：

> If you are using Vue without a build tool by loading it from a CDN or self-hosted script, make sure to use the production build (dist files that end in `.prod.js`) when deploying to production.
> - If using global build: use `vue.global.prod.js`.
> - If using ESM build: use `vue.esm-browser.prod.js`.

结论：我们把 `vue.global.prod.js` 下载进工具包、本地自托管（不依赖外网 CDN），就是官方认可的生产形态。开发/调试时可临时用 `vue.global.js`（带警告与 devtools 支持）。

来源：
- Vue 官方 Production Deployment：https://vuejs.org/guide/best-practices/production-deployment.html

### 1.3 体积数据（一手数据）

`vuejs/core` 仓库 PR 的 CI 体积表（多次 PR 数值稳定）：

| 文件 | 原始 | gzip | brotli |
|---|---|---|---|
| `vue.global.prod.js` | ≈ 158–159 KB | ≈ 57.6–58.6 KB | ≈ 51.3–52.1 KB |
| `runtime-dom.global.prod.js` | ≈ 100–101 KB | ≈ 37.7–38.5 KB | ≈ 34–34.6 KB |

我们用的是 full build（`vue.global.prod.js`，含模板编译器），因为无构建链下模板是运行时编译的。约 160 KB 本地文件，浏览器加载毫秒级，符合「轻量」目标。

来源：
- vuejs/core PR #11904：https://github.com/vuejs/core/pull/11904#event-14265764240
- vuejs/core PR #13915：https://github.com/vuejs/core/pull/13915

### 1.4 页签/路由是否需要 vue-router

Vue Router 官方 Installation 文档确认：**无 bundler 也能用**，提供 ES module 与 global 两种构建，生产用 `vue-router.global.prod.js`，并强调要 pin 版本：

```html
<script src="https://unpkg.com/vue@3.5.40/dist/vue.global.js"></script>
<script src="https://unpkg.com/vue-router@5.2.0/dist/vue-router.global.js"></script>
<script>
  const { createApp } = Vue
  const { createRouter } = VueRouter
  // ...
</script>
```

如果我们的面板页签只是「顶部几个 Tab 切换视图」，也可以不用 vue-router，直接响应式切换组件（Vue 官方 Dynamic Components 模式）；若以后需要可分享的 URL 或深层导航再加 vue-router（同样是本地一个文件）。

来源：
- Vue Router 官方 Installation：https://router.vuejs.org/installation

### 1.5 无构建链的边界（如实记录）

- 不能用 `.vue` 单文件组件与 `<script setup>` 语法糖（官方 Quick Start 明确说明）。
- 模板写在 JS 字符串或 HTML 内联模板里，靠运行时编译器（full build）。
- 不经过打包，无法用 tree-shaking——`vue.global.prod.js` 是整体全量版本，但对单页本地工具完全够用。
- 社区无构建 Vue 项目（如 Enferno）证明：页面逻辑组件化、模板字符串、ES module 拆分是成熟可行的。

---

## 2. Flask 托管 Vue 单页：官方模式

### 2.1 官方 SPA 模式（重点）

Flask 官方文档有一节专门的 **Single-Page Applications**，原文给出了与 API 共存的完整示例：

```python
from flask import Flask, jsonify

app = Flask(__name__, static_folder='app', static_url_path="/app")

@app.route("/heartbeat")
def heartbeat():
    return jsonify({"status": "healthy"})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return app.send_static_file("index.html")
```

要点：
- 前端产物放 `app/`（或任意子目录）作为 `static_folder`；
- catch-all 路由把所有非 API 路径都送回 `index.html`，交给 Vue 处理（Vue Router history 模式同样需要这个 fallback，见 Vue Router 官方 History Mode 文档）；
- API 路由（如 `/heartbeat`）照常注册，Flask 路由优先于 catch-all 匹配。

对 Vue Router history 模式的补充（Vue Router 官方 History Mode 文档）：服务器需要「catch-all fallback 让所有路由跳转到 index.html」，Flask 里正是上述写法。

来源：
- Flask 官方 Single-Page Applications：https://flask.palletsprojects.com/en/stable/patterns/singlepageapplications/
- Vue Router 官方 History Mode：https://router.vuejs.org/guide/essentials/history-mode.html

### 2.2 静态文件与模板（官方 API）

- `Flask(..., static_folder='...')` 指定静态目录，`app.send_static_file('index.html')` 服务其中的文件（Flask API 文档 `send_static_file`）。
- Flask 默认提供 `/static` 静态路由（Quickstart「Static Files」一节），`url_for('static', filename=...)` 生成 URL。
- 若要走 Jinja 模板（比如 index.html 里注入启动配置），`render_template('index.html')` 即可；但按「职责边界」约定我们更推荐 Flask 只出 JSON、页面纯静态由 Vue 渲染（见第 7 节）。

来源：
- Flask API 文档（Flask 类、send_static_file、run）：https://flask.palletsprojects.com/en/stable/api/
- Flask Quickstart（Static Files / Rendering Templates）：https://flask.palletsprojects.com/en/stable/quickstart/

### 2.3 CORS：同源托管就不需要

页面由 Flask 自己托管（`http://127.0.0.1:<port>/`），API 也在同一 origin（`/api/...`），浏览器视为同源请求，**无需 CORS 配置、无需额外依赖**。只有跨 origin（如前端单独起 dev server）才需要 flask-cors。

---

## 3. 后台任务与进度上报

### 3.1 方案对比

导出是秒级到分钟级任务，需要：启动 → 显示步骤进度 → 完成/失败 →（必要时）取消。

| 方案 | 实现 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| 轮询 | 任务跑后台线程，前端每 500ms GET 一次状态 | 最简单、无长连接 | 有延迟、多几次请求 | 可接受，最简单 |
| **SSE** | 后台线程写状态，`text/event-stream` 流推给浏览器 | 实时、自动重连、浏览器原生 | 单向（我们只需要单向） | **推荐** |
| WebSocket | flask-sock 双向通道 | 双向实时 | 多一个依赖、双向用不上 | 不需要 |

社区对比结论（JS 教程类二手来源）：性能上 WebSocket 更快，但 SSE 兼容性更好、实现更简单；单用户本地工具实时性需求（秒级）SSE 绰绰有余。

### 3.2 Flask 官方 streaming 支持（一手）

Flask 官方 Streaming Contents 文档：用生成器 + Response 即可流式输出，每次 `yield` 直接推给浏览器：

```python
@app.route('/large.csv')
def generate_large_csv():
    def generate():
        for row in iter_all_rows():
            yield f"{','.join(row)}\n"
    return generate(), {"Content-Type": "text/csv"}
```

SSE 就是 `Content-Type: text/event-stream` 的流式响应，协议格式为 `data: ...\n\n`。若生成器需要访问 `request` 上下文，官方提供 `stream_with_context()` 包装。

来源：
- Flask 官方 Streaming Contents：https://flask.palletsprojects.com/en/stable/patterns/streaming/

### 3.3 浏览器消费：EventSource（MDN，一手）

MDN EventSource 文档要点：
- 建立持久 HTTP 连接，服务器按 `text/event-stream` 格式推送；
- **单向**：数据只从服务器到客户端——「makes them an excellent choice when there's no need to send data from the client to the server in message form」；
- **自动重连**：连接断开浏览器自动重试（本地服务偶发中断可自愈）；
- 限制：HTTP/1.1 下每个浏览器每个域名最多 6 个连接（Chrome/Firefox 明确不改）。单用户单标签页 1 个 SSE 连接完全无压力；
- 支持命名事件：`evtSource.addEventListener('update', ...)`。

```js
const evtSource = new EventSource("/api/export/events")
evtSource.addEventListener("progress", (e) => {
  updateProgress(JSON.parse(e.data))
})
evtSource.addEventListener("done", (e) => { ... })
evtSource.addEventListener("error", (e) => { ... })
```

来源：
- MDN EventSource：https://developer.mozilla.org/en-US/docs/Web/API/EventSource

### 3.4 threaded 模式（重要细节）

- Flask `app.run()` 文档：「Threaded mode is enabled by default.」（Flask 1.0 起），即开发服务器默认每个请求一个线程。这意味着 SSE 流挂起一个线程时，其他 API 请求仍可并发处理。
- 社区维护的 flask-sse 扩展文档曾警告「SSE 在 Flask 内置开发服务器上不工作，因为它一次只处理一个请求」——这是基于 Flask 0.x 单线程的旧结论；现在默认 threaded，单用户场景可用，但生产/多用户仍建议 gunicorn+gevent 等（对我们不适用，我们是本地单用户）。
- 我们在设计上仍然建议：**SSE 端点只做「读状态流」，导出任务本身跑在独立后台线程**，避免占用请求线程。

来源：
- Flask API 文档 run()：https://flask.palletsprojects.com/en/stable/api/
- flask-sse 文档（注意事项）：https://github.com/faruqsandi/flask-sse/blob/main/docs/quickstart.rst

### 3.5 后台任务 + 取消（标准库模式）

单用户本地工具的标准做法（多个真实项目一致，含 CGE、flask-rabbitmq-sse、claude-multi-agent-bridge 等）：

```python
import threading
import queue

class ExportJob:
    def __init__(self):
        self.status = {"step": "idle", "progress": 0}
        self.events: queue.Queue = queue.Queue()   # 线程安全
        self.cancel = threading.Event()            # 取消信号

    def run(self):
        for step in ("读取Excel", "校验", "导出JSON", "打包Binary"):
            if self.cancel.is_set():
                self.events.put({"type": "cancelled"}); return
            self.status["step"] = step
            self.events.put({"type": "progress", "step": step})
        self.events.put({"type": "done"})

job = ExportJob()
threading.Thread(target=job.run, daemon=True).start()   # daemon：进程退出不阻塞
```

要点：
- 任务线程与请求线程之间用 `queue.Queue`（Python 标准库线程安全）做生产者-消费者；
- 取消用 `threading.Event`，任务在步骤边界检查（与我们的 `CancelToken` 概念完全一致，直接复用即可）；
- 任务线程 `daemon=True`：用户 Ctrl+C 或关进程时不会卡住退出（Python 文档惯例）。
- 官方对高并发场景推荐 Celery/RQ（Flask Patterns 有 Celery 一节），但社区明确结论：**低流量场景 threading 是 viable alternative**，无需引入消息队列。

来源：
- Python 标准库 threading / queue 文档：https://docs.python.org/3/library/threading.html
- 社区结论（低流量 threading 可行）：https://stackoverflow.com/revisions/9e57999e-feb4-4b88-b19b-161aa7907d68/view-source

### 3.6 结论：SSE + 内存状态 + threading

推荐组合：
1. `POST /api/export` 启动后台线程，返回 job id；
2. `GET /api/export/status?job=...` 轮询兜底（页面刚打开/重连时拉一次快照）；
3. `GET /api/export/events?job=...` SSE 流实时推送步骤名/进度/完成/失败；
4. `POST /api/export/cancel` 设置 `threading.Event`；
5. 所有状态存内存（单用户进程内足够），不落库。

---

## 4. 本地服务运行模式

### 4.1 绑定 127.0.0.1

- Flask `run()` 默认 host 就是 `127.0.0.1`（Flask API 文档），即仅本机可访问。
- 官方 Quickstart 明确警告：debug 模式下用户可执行任意 Python 代码，默认只本机访问正是为安全考虑；不要用 `--host=0.0.0.0`。

来源：
- Flask Quickstart / API 文档（同上）

### 4.2 端口选择：5000 的坑 + 动态端口

- Flask 默认端口 5000；**macOS Monterey 及以后，5000 被系统「AirPlay Receiver」服务占用**（Flask 官方 Development Server 文档专门写了这一条）。所以本地面板**不要用 5000**。
- 端口冲突时报 `OSError: [Errno 98] Address already in use` / Windows `WinError 10013`（Flask 官方文档）。
- 动态端口：`socket.bind(('127.0.0.1', 0))` 让系统分配空闲端口，取 `getsockname()[1]`；这是社区与多个项目（mcp-use、pytorch 等）验证的标准写法。

```python
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
```

建议：固定一个非常用端口（如 8787）为主、占用时自动回落动态端口；打开浏览器时用实际端口。

来源：
- Flask 官方 Development Server（端口冲突 / AirPlay）：https://flask.palletsprojects.com/en/stable/server/
- Python socket 找空闲端口惯例：https://socket.dev/pypi/package/port-for/overview/0.7.2/tar-gz

### 4.3 关闭 debug

本地给策划用的形态必须是 `debug=False`（不启用 reloader、不启用交互式 debugger），否则有任意代码执行风险（官方 Quickstart 警告）。错误信息由我们自己的 JSON error handler 呈现（见第 7 节），策划看到的是可读的校验错误而不是 traceback——这正是最初「错误提示清楚一些」的需求。

### 4.4 自动打开浏览器：标准库 webbrowser（一手）

Python 官方 `webbrowser` 模块文档：`webbrowser.open(url, new=2)` 用默认浏览器打开新标签页；跨平台支持 Windows（`windows-default`）、macOS（`macosx`）、Unix。**不需要第三方库。**

```python
import threading, time, webbrowser

def _open_later(url):
    time.sleep(0.5)          # 等服务真正起来
    webbrowser.open(url, new=2)

threading.Thread(target=_open_later, args=(url,), daemon=True).start()
app.run(host="127.0.0.1", port=port, debug=False)
```

真实项目参考：
- grip（本地 Markdown 预览工具）：`Grip.run(..., open_browser=True)`，源码里 `wait_for_server` 等待端口监听后再 `webbrowser.open`（Debian 源码 browser.py）。
- flaskwebgui（PyInstaller wiki）：`webbrowser.open('http://localhost:8080')` + `app.run(...)`；并强调打包后 `os.chdir(app.root_path)` 保证 static/templates 能找到。

来源：
- Python 官方 webbrowser：https://docs.python.org/3/library/webbrowser.html
- grip README / Debian 源码：https://github.com/joeyespo/grip （browser.py 见 Debian sources：https://sources.debian.org/src/grip/4.6.1-2/grip/browser.py/）
- flaskwebgui wiki：https://github.com/pyinstaller/pyinstaller/wiki/Recipe-flask-and-flaskwebgui/26c6b8ac80e5d6c4682c373cc8671efc628780db

### 4.5 进程生命周期与「关页面提示」

- **关闭浏览器窗口不会杀掉本地服务进程**（Jupyter/ipython 的经验文档明确：`Closing the browser ... will not stop the server`）。我们的场景：终端窗口开着 = 服务活着；策划直接关掉终端/窗口即 Ctrl+C 退出。
- 导出进行中关页面的提示：前端 `beforeunload` 事件（浏览器原生弹「确定离开？」），并结合我们的取消接口：用户确认离开时 `POST /api/export/cancel`；SSE 连接断开后端也兜底停止任务（生成器 `finally` 里清任务）。社区同样做法见「Detect browser closure to kill webserver」讨论（unload 时发最后请求）。
- 服务端要能优雅退出：任务线程 `daemon=True`，主线程捕获 KeyboardInterrupt 关闭。

来源：
- Jupyter 经验（关浏览器不杀 server）：https://wiki.lsce.ipsl.fr/pmip3/doku.php/other:uvcdat:cdat_conda:ipnb
- 浏览器关闭检测讨论：https://stackoverflow.com/feeds/question/26307897

---

## 5. 真实项目参考

### 5.1 Enferno（最贴近我们技术形态）

「Modern Flask framework with zero-config frontend (Vue 3 + Vuetify 3) ... **No webpack, no node_modules, just Python**」。README 原话：

> Zero build step - Vue 3 + Vuetify 3 run directly in browser. Delete your `node_modules`

它证明了「Flask 后端 + Vue 3 无构建前端 + 浏览器直接运行」是成熟可落地的组合，甚至配套了数据表格、对话框、通知、暗色主题等 UI 能力。我们的面板（表格管理、i18n 表格、批量操作、进度条）与它的 UI 形态高度相似。

来源：https://github.com/level09/enferno

### 5.2 grip

Python 写的小工具：本地起 server 渲染 Markdown 预览，`open_browser=True` 自动开浏览器，端口 6419。这是「给非技术用户一个本地面板」的经典形态（轻量、默认 127.0.0.1、端口可配）。

来源：https://github.com/joeyespo/grip

### 5.3 flaskwebgui

把 Flask 应用当作桌面程序：自动起浏览器 + 保持进程。PyInstaller 打包 wiki 提到 `os.chdir(app.root_path)` 的关键坑——**打包后当前目录会变，必须切到应用根目录才能找到 static/templates**。我们目前不做打包（基于 venv 运行），但若未来给策划做双击即用的发行版可参考。

来源：https://github.com/pyinstaller/pyinstaller/wiki/Recipe-flask-and-flaskwebgui/26c6b8ac80e5d6c4682c373cc8671efc628780db

### 5.4 Jupyter（模式参照）

「命令行启动 → 本地 127.0.0.1 + 端口 → 自动开浏览器 → 网页操作」的模式被 Jupyter 大规模验证过；它的安全模型（本地绑定 + token）也说明这类工具的正确基线。我们不需要 token/密码（本机单用户、不暴露局域网即可）。

来源：https://jupyter-notebook.readthedocs.io/en/5.7.1/public_server.html

---

## 6. Windows / macOS 双平台

### 6.1 venv 差异（AGENTS.md 已有，调研确认）

| 平台 | 创建 | 激活 | 脚本目录 |
|---|---|---|---|
| macOS/Linux | `python3 -m venv .venv` | `source .venv/bin/activate` | `bin/` |
| Windows | `py -3 -m venv .venv` | `.venv\Scripts\activate`（.bat） | `Scripts/` |

代码里定位 venv 内解释器/脚本时用相对路径 + 平台判断（如 `Path(sys.executable)` 而不是硬编码）。

### 6.2 双击启动脚本惯例

**Windows `启动面板.bat`**（社区标准写法）：

```bat
@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate (
  echo 首次使用请先安装: py -3 -m venv .venv ^&^& .venv\Scripts\pip install -e tool
  pause & exit /b 1
)
call .venv\Scripts\activate
python -m ct.cli panel
pause
```

**macOS `启动面板.command`**：

```bash
#!/bin/zsh
cd "$(dirname "$0")"
source .venv/bin/activate
python -m ct.cli panel
```

（macOS `.command` 双击会开 Terminal 执行；如需退到 Finder 可加 `osascript -e 'tell application "Terminal" to close front window'`，非必需。）

### 6.3 webbrowser 跨平台

官方文档确认 `webbrowser.open()` 在 Windows/macOS 都调用系统默认浏览器，无需平台分支。

### 6.4 路径处理与打包注意

- 所有资源路径基于 `Path(__file__).parent` / `app.root_path` 解析，**不依赖 cwd**（flaskwebgui 的 `os.chdir(app.root_path)` 教训）。
- Flask static/templates 目录随包走（`Flask(__name__)` 自动定位），避免相对路径。

来源：
- Windows venv .bat：https://stackoverflow.com/questions/56510437/start-flask-with-venv-using-a-bat-file/56510574
- macOS .command：https://stackoverflow.com/questions/71716335
- flaskwebgui wiki（os.chdir 教训）：同上

---

## 7. 职责边界与错误格式

### 7.1 Flask 只出 JSON、Vue 只渲染

- Flask 侧：所有 `/api/*` 路由返回 `jsonify(...)`；不渲染业务页面 HTML（index.html 纯静态托管）。
- Vue 侧：用 `fetch`/EventSource 消费 JSON；页面渲染、状态管理全在浏览器。
- 这样「同一套用例逻辑 CLI 和面板共用」的架构不变：面板后端只是把 `ct/app` 的返回序列化成 JSON。

### 7.2 统一错误 JSON（官方模板）

Flask 官方 errorhandling 文档「Returning API Errors as JSON」提供两个可直接用的模板：

**HTTP 错误统一 JSON：**

```python
from flask import json
from werkzeug.exceptions import HTTPException

@app.errorhandler(HTTPException)
def handle_exception(e):
    response = e.get_response()
    response.data = json.dumps({
        "code": e.code,
        "name": e.name,
        "description": e.description,
    })
    response.content_type = "application/json"
    return response
```

**自定义业务异常（校验错误正好适用）：**

```python
class InvalidAPIUsage(Exception):
    status_code = 400
    def __init__(self, message, status_code=None, payload=None):
        super().__init__()
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

@app.errorhandler(InvalidAPIUsage)
def invalid_api_usage(e):
    return jsonify(e.to_dict()), e.status_code
```

我们的 `ValidationIssue`（含 excel_row/column/value 的结构化信息）可以直接挂进 payload，前端表格展示「Excel 第N行 · 列X · 当前值」。

来源：
- Flask 官方 errorhandling：https://flask.palletsprojects.com/en/stable/errorhandling/

### 7.3 本地安全与 CSRF

- 服务只绑 127.0.0.1，恶意网站无法直接访问（跨站请求会发向 127.0.0.1 的场景理论上存在，即 DNS rebinding；本地单用户工具的现实威胁极低）。
- 关闭 debug（见 4.3）。
- JSON API 天然有 CORS preflight 保护（浏览器跨源 JSON POST 需预检）；如稳妥可再加一层 `request.headers.get("Origin")` 校验，仅放行本服务 origin。
- 涉及修改类操作（compact 清理、模板重建、表格管理）时前端二次确认 + 后端幂等/预览（dry-run）机制，双保险。

---

## 8. Flask 的短板与边界（如实记录）

1. **开发服务器不是生产服务器**（Flask 官方明确）：不适合高并发、多用户、公网。我们本地单用户，这正是它的适用区，不算缺陷。
2. **WSGI 同步模型**：长连接（SSE）会占一个线程；Flask 1.0+ 默认 threaded 可并发，但每个浏览器最多 6 个 SSE 连接（HTTP/1.1）。单用户 1 个连接没问题。
3. **无内置 async/WebSocket**：需要 SSE（生成器）或加 flask-sock。我们的单向进度推送用 SSE 足够。
4. **内置开发服务器无生产级静态文件优化**：本地小文件无感知。
5. 备选对照（已有数据支撑）：FastAPI 使用率第一但 async/OpenAPI 对我们无用；Django 过重；stdlib http.server 开发成本高。Flask 是「用得广 + 轻量」的最优解（PyPI 下载量 15.7 亿次/年，使用率 34% 前三）。

---

## 9. 给 ct 面板的落地建议（综合）

**技术组合**：Flask（1 个后端依赖，含自带 Werkzeug/Jinja2）+ Vue 3 全局构建 `vue.global.prod.js`（本地托管，1 个前端文件）+ 原生 JS/fetch + EventSource。可选 vue-router 全局版（页签复杂化时再加）。

**依赖增量**：仅 `flask`。前端零 npm、零构建、零 node_modules。

**启动方式**：`ct panel` 子命令：动态端口 → 起 Flask（debug=False, threaded）→ `webbrowser.open` 自动开浏览器；外加 Windows `.bat` / macOS `.command` 双击脚本。

**目录结构草案**：

```
python/ct/
├── panel/
│   ├── app.py            # Flask 应用工厂 + 路由 + error handlers
│   ├── jobs.py           # ExportJob：threading + queue.Queue + CancelToken 桥接
│   ├── static/           # Vue 前端
│   │   ├── index.html
│   │   ├── vue.global.prod.js
│   │   ├── app.js        # Vue 应用 + 页签
│   │   └── views/*.js    # 导出 / i18n / 表格管理各视图（ES module 拆分）
│   └── api.py            # /api/* 路由：薄封装 ct/app 用例
```

**风险点（实现时验证）**：
- SSE 在 Flask threaded dev server 上的实际表现（预计可用，需冒烟测试确认）；
- macOS 5000 端口占用 → 固定非常用端口 + 动态回落；
- Windows 下 EventSource / import map 的浏览器兼容（现代 Chrome/Edge 均支持）；
- 同一时间多标签页打开面板时 job 状态共享（内存单例即可）。

---

## 附录：检索量记录

**搜索查询**：共 4 轮 × 10 条 = 40 条查询（覆盖：Vue 无构建/CDN/import maps/体积、Flask SPA fallback/静态托管、SSE/streaming/threaded/EventSource、后台任务/取消、本地服务/端口/webbrowser、真实案例、双平台脚本、CSRF/错误 JSON 等）。

**精读页面清单（一手优先）**：

| 来源 | 类型 |
|---|---|
| https://vuejs.org/guide/quick-start.html | Vue 官方文档（一手） |
| https://vuejs.org/guide/best-practices/production-deployment.html | Vue 官方文档（一手） |
| https://router.vuejs.org/installation | Vue Router 官方文档（一手） |
| https://router.vuejs.org/guide/essentials/history-mode.html | Vue Router 官方文档（一手） |
| https://github.com/vuejs/core/pull/11904 | Vue 官方体积数据（一手） |
| https://flask.palletsprojects.com/en/stable/patterns/singlepageapplications/ | Flask 官方文档（一手） |
| https://flask.palletsprojects.com/en/stable/patterns/streaming/ | Flask 官方文档（一手） |
| https://flask.palletsprojects.com/en/stable/errorhandling/ | Flask 官方文档（一手） |
| https://flask.palletsprojects.com/en/stable/quickstart/ | Flask 官方文档（一手） |
| https://flask.palletsprojects.com/en/stable/server/ | Flask 官方文档（一手） |
| https://flask.palletsprojects.com/en/stable/api/ | Flask 官方 API 文档（一手） |
| https://docs.python.org/3/library/webbrowser.html | Python 官方文档（一手） |
| https://developer.mozilla.org/en-US/docs/Web/API/EventSource | MDN（一手） |
| https://github.com/level09/enferno | 真实项目（一手代码/README） |
| https://github.com/joeyespo/grip | 真实项目（一手代码） |
| https://github.com/pyinstaller/pyinstaller/wiki/Recipe-flask-and-flaskwebgui | 真实项目 wiki（一手） |
| https://github.com/faruqsandi/flask-sse/blob/main/docs/quickstart.rst | 扩展官方文档（一手） |
| https://github.com/a11mut3d/CGE/blob/main/app.py | 真实项目 SSE+threading 示例 |
| https://github.com/israelshp/flask-rabbitmq-sse | 真实项目 SSE+Queue 示例 |
| https://stackoverflow.com/questions/56510437/start-flask-with-venv-using-a-bat-file | Windows 脚本惯例（二手，社区标准） |
| https://stackoverflow.com/questions/71716335 | macOS .command 惯例（二手，社区标准） |

> 注：AGENTS.md 偏好 anysearch MCP，但当前环境未提供该 MCP，本次调研使用内置 search + open_page 完成。

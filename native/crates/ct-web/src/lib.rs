//! HTTP transport and static hosting; canonical business operations live in ct-app.
use axum::{
    body::{to_bytes, Body},
    extract::{Request, State},
    http::{header, Method, StatusCode},
    response::{IntoResponse, Response},
    Router,
};
use ct_app::panel::{self, PanelError};
use ct_app::panel_tasks as tasks;
use serde_json::{json, Value};
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::sync::Semaphore;
include!(concat!(env!("OUT_DIR"), "/assets.rs"));

#[derive(Clone)]
struct App {
    root: PathBuf,
    tasks: Arc<tasks::Tasks>,
    gate: Arc<Semaphore>,
    views: Arc<tokio::sync::Mutex<()>>,
    stopping: Arc<AtomicBool>,
    instance: String,
    port: u16,
    host: String,
    static_dir: Option<PathBuf>,
}
fn response(status: u16, mut value: Value) -> Response {
    ct_protocol::bigint::encode_value(&mut value);
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
        [
            (header::CONTENT_TYPE, "application/json; charset=utf-8"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        value.to_string(),
    )
        .into_response()
}
fn error(e: PanelError) -> Response {
    response(e.status, e.payload)
}
fn ok(data: Value) -> Response {
    response(200, json!({"ok":true,"data":data}))
}
fn valid_host(app: &App, authority: &str) -> bool {
    let Ok(url) = url::Url::parse(&format!("http://{authority}")) else {
        return false;
    };
    if url.port_or_known_default() != Some(app.port)
        || !url.username().is_empty()
        || url.password().is_some()
        || url.path() != "/"
    {
        return false;
    }
    let host = url.host_str().unwrap_or("");
    host == app.host
        || matches!(host, "127.0.0.1" | "localhost" | "[::1]")
        || ((app.host == "0.0.0.0" || app.host == "::") && host.parse::<std::net::IpAddr>().is_ok())
}
async fn handle(State(app): State<App>, request: Request) -> Response {
    let method = request.method().clone();
    let uri = request.uri().clone();
    let headers = request.headers();
    let host = headers
        .get(header::HOST)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if !valid_host(&app, host) {
        return error(PanelError::new(403, "请求 Host 不被允许"));
    }
    if let Some(origin) = headers.get(header::ORIGIN) {
        if origin.to_str().ok() != Some(&format!("http://{host}")) {
            return error(PanelError::new(403, "不允许跨源请求"));
        }
    }
    let path = uri.path().to_string();
    if !path.starts_with("/api/") {
        if method != Method::GET && method != Method::HEAD {
            return error(PanelError::new(405, "方法不支持"));
        }
        let key = if path == "/" {
            "index.html"
        } else {
            path.strip_prefix("/static/").unwrap_or("")
        };
        return match ASSETS.iter().find(|(name, _)| *name == key) {
            Some((name, bytes)) => {
                let development = app.static_dir.as_ref().and_then(|dir| {
                    let path = dir.join(name).canonicalize().ok()?;
                    if !path.starts_with(dir) {
                        return None;
                    }
                    std::fs::read(path).ok()
                });
                let mime = if name.ends_with(".js") {
                    "text/javascript; charset=utf-8"
                } else if name.ends_with(".css") {
                    "text/css; charset=utf-8"
                } else {
                    "text/html; charset=utf-8"
                };
                Response::builder()
                    .status(200)
                    .header(header::CONTENT_TYPE, mime)
                    .header(header::CACHE_CONTROL, "no-cache")
                    .body(if method == Method::HEAD {
                        Body::empty()
                    } else {
                        development
                            .map(Body::from)
                            .unwrap_or_else(|| Body::from(*bytes))
                    })
                    .unwrap()
            }
            None => error(PanelError::new(404, "资源不存在")),
        };
    }
    if method != Method::GET && method != Method::POST {
        return error(PanelError::new(405, "方法不支持"));
    }
    if app.stopping.load(Ordering::SeqCst) {
        return error(PanelError::new(503, "服务正在安全关闭"));
    }
    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("");
    if method == Method::POST && content_type != "application/json" {
        return error(PanelError::new(415, "写请求需要 application/json"));
    }
    let bytes = match to_bytes(request.into_body(), 4 * 1024 * 1024).await {
        Ok(b) => b,
        Err(_) => return error(PanelError::new(413, "请求体过大或读取失败")),
    };
    let mut data = if bytes.is_empty() {
        json!({})
    } else {
        match serde_json::from_slice::<Value>(&bytes) {
            Ok(v) if v.is_object() => v,
            _ => return error(PanelError::new(400, "请求必须是 JSON 对象")),
        }
    };
    if method == Method::GET {
        for (key, value) in url::form_urlencoded::parse(uri.query().unwrap_or("").as_bytes()) {
            data[key.as_ref()] = value.into_owned().into();
        }
    }
    ct_protocol::bigint::decode_value(&mut data);
    // Control/status requests must stay responsive while all business slots
    // are occupied by candidates or workbook operations.
    if matches!(
        (method.as_str(), path.as_str()),
        ("GET", "/api/export/progress" | "/api/tasks" | "/api/logs")
            | (
                "POST",
                "/api/export/cancel" | "/api/tasks/canonical-export/dismiss"
            )
    ) {
        return match dispatch(&app, method.as_str(), &path, &data) {
            Ok(data) => ok(data),
            Err(e) => error(e),
        };
    }
    let permit = match app.gate.clone().try_acquire_owned() {
        Ok(p) => p,
        Err(_) => return error(PanelError::new(409, "服务忙碌，请稍后重试")),
    };
    // Batch page loads issue several views together. Serialize those inside
    // this service so read/read contention is not reported as a writer busy.
    // The outer semaphore bounds waiters; cross-process writers still get the
    // canonical immediate busy result from the workspace lock.
    let view_guard =
        if method == Method::GET || path.ends_with("/candidate") || path.ends_with("/validate") {
            Some(app.views.clone().lock_owned().await)
        } else {
            None
        };
    match tokio::task::spawn_blocking(move || {
        let _permit = permit;
        let _view_guard = view_guard;
        dispatch(&app, method.as_str(), &path, &data)
    })
    .await
    {
        Ok(Ok(value)) => ok(value),
        Ok(Err(e)) => error(e),
        Err(_) => error(PanelError::new(500, "内部任务错误，请查看服务日志")),
    }
}
fn dispatch(app: &App, method: &str, path: &str, data: &Value) -> panel::Result<Value> {
    let root = &app.root;
    match (method, path) {
        ("GET", "/api/service") => Ok(
            json!({"instanceId":app.instance,"coreVersion":env!("CARGO_PKG_VERSION"),"kernel":"native","recovery":ct_app::workspace::recovery_needed(root)}),
        ),
        ("GET", "/api/workspace") => panel::overview(root),
        ("GET", "/api/schema-workspace") => panel::snapshot(root),
        ("POST", "/api/schema-workspace/candidate") => panel::candidate(root, data, false),
        ("POST", "/api/schema-workspace/validate") => panel::candidate(root, data, true),
        ("POST", "/api/schema-workspace/save") => panel::save(root, data),
        ("POST", "/api/schema-workspace/gen-template") => {
            let result = panel::generate_template(root, data);
            app.tasks.log(
                "模板",
                if result.is_ok() { "INFO" } else { "ERROR" },
                &format!("生成模板：{}", data["table"]),
            );
            result
        }
        ("POST", "/api/workspace/recover") => ct_app::workspace::recover_workspace(root)
            .map(|r| json!({"recovery":r.note,"schemaRevision":r.revision}))
            .map_err(|e| PanelError::new(409, e)),
        ("POST", "/api/export") => app
            .tasks
            .start(root.clone(), data["forced"].as_bool().unwrap_or(false)),
        ("GET", "/api/export/progress") => Ok(app.tasks.progress()),
        ("POST", "/api/export/cancel") => Ok(app.tasks.cancel()),
        ("GET", "/api/tasks") => Ok(app.tasks.list()),
        ("POST", "/api/tasks/canonical-export/dismiss") => Ok(app.tasks.dismiss()),
        ("GET", "/api/logs") => Ok(app.tasks.logs(data["module"].as_str().unwrap_or("all"))),
        ("GET", "/api/history") => {
            let _read_lock = ct_storage::lock::WorkspaceLock::acquire(root)
                .map_err(|e| PanelError::new(409, e))?;
            if let Some(note) = ct_app::workspace::recovery_needed(root) {
                return Err(PanelError::new(409, note));
            }
            if let Err(e) = ct_app::history::import_legacy_history(root) {
                app.tasks.log("系统", "WARN", &e.to_string());
            }
            Ok(json!(ct_app::history::read_history(root)
                .into_iter()
                .rev()
                .collect::<Vec<_>>()))
        }
        (method, path) if path.starts_with("/api/i18n/") => {
            let action = path.trim_start_matches("/api/i18n/");
            let write = matches!(action, "entry" | "sync" | "compact");
            if (write && method != "POST") || (!write && method != "GET") {
                return Err(PanelError::new(405, "方法不支持"));
            }
            let result = panel::translations(root, action, data);
            if write && result.is_ok() {
                app.tasks
                    .log("i18n", "INFO", &format!("翻译操作完成：{action}"));
            }
            result
        }
        _ => Err(PanelError::new(404, "接口不存在")),
    }
}
pub struct Options {
    pub root: PathBuf,
    pub host: String,
    pub port: u16,
    pub open_browser: bool,
    pub shutdown_on_stdin: bool,
    pub static_dir: Option<PathBuf>,
}
pub fn run(options: Options) -> std::result::Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(serve(options))
}
async fn serve(
    options: Options,
) -> std::result::Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let listener = tokio::net::TcpListener::bind((options.host.as_str(), options.port)).await?;
    let port = listener.local_addr()?.port();
    let root = std::path::absolute(&options.root)?;
    let root = root.canonicalize().unwrap_or(root);
    let app = App {
        root,
        tasks: Arc::new(tasks::Tasks::default()),
        gate: Arc::new(Semaphore::new(8)),
        views: Arc::new(tokio::sync::Mutex::new(())),
        stopping: Arc::new(AtomicBool::new(false)),
        instance: format!(
            "{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        ),
        port,
        host: options.host.clone(),
        static_dir: options.static_dir.map(|p| p.canonicalize()).transpose()?,
    };
    app.tasks.log("系统", "INFO", "原生面板服务启动");
    let router = Router::new().fallback(handle).with_state(app.clone());
    let host = if options.host.contains(':') {
        format!("[{}]", options.host.trim_matches(['[', ']']))
    } else {
        options.host.clone()
    };
    let url = format!("http://{host}:{port}");
    println!("面板已启动: {url}（Ctrl+C 停止）");
    if options.open_browser {
        open_browser(&url);
    }
    let (stdin_tx, stdin_rx) = tokio::sync::oneshot::channel();
    if options.shutdown_on_stdin {
        std::thread::spawn(move || {
            use std::io::Read;
            let mut byte = [0];
            while std::io::stdin().read(&mut byte).unwrap_or(0) > 0 {}
            let _ = stdin_tx.send(());
        });
    }
    let shutdown_app = app.clone();
    axum::serve(listener,router).with_graceful_shutdown(async move {
        #[cfg(unix)] {let mut term=tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("SIGTERM");tokio::select!{_ = tokio::signal::ctrl_c()=>{},_ = term.recv()=>{},_ = stdin_rx,if options.shutdown_on_stdin=>{}}}
        #[cfg(not(unix))] {tokio::select!{_ = tokio::signal::ctrl_c()=>{},_ = stdin_rx,if options.shutdown_on_stdin=>{}}}
        shutdown_app.stopping.store(true,Ordering::SeqCst);
    }).await?;
    tokio::task::spawn_blocking(move || app.tasks.wait()).await?;
    Ok(())
}
fn open_browser(url: &str) {
    #[cfg(target_os = "macos")]
    let command = ("open", vec![url]);
    #[cfg(target_os = "windows")]
    let command = ("rundll32", vec!["url.dll,FileProtocolHandler", url]);
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let command = ("xdg-open", vec![url]);
    if let Err(e) = std::process::Command::new(command.0)
        .args(command.1)
        .spawn()
    {
        eprintln!("无法自动打开浏览器，请手动访问 {url}：{e}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn control_routes_respond_when_business_capacity_is_exhausted() {
        let root = tempfile::tempdir().unwrap();
        let app = App {
            root: root.path().to_path_buf(),
            tasks: Arc::new(tasks::Tasks::default()),
            gate: Arc::new(Semaphore::new(0)),
            views: Arc::new(tokio::sync::Mutex::new(())),
            stopping: Arc::new(AtomicBool::new(false)),
            instance: "test".into(),
            port: 8000,
            host: "127.0.0.1".into(),
            static_dir: None,
        };
        for (method, path) in [
            (Method::GET, "/api/export/progress"),
            (Method::GET, "/api/tasks"),
            (Method::GET, "/api/logs"),
            (Method::POST, "/api/export/cancel"),
            (Method::POST, "/api/tasks/canonical-export/dismiss"),
        ] {
            let request = Request::builder()
                .method(method)
                .uri(path)
                .header(header::HOST, "127.0.0.1:8000")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from("{}"))
                .unwrap();
            assert_eq!(
                handle(State(app.clone()), request).await.status(),
                StatusCode::OK,
                "{path}"
            );
        }
        let request = Request::builder()
            .uri("/api/workspace")
            .header(header::HOST, "127.0.0.1:8000")
            .body(Body::empty())
            .unwrap();
        assert_eq!(
            handle(State(app), request).await.status(),
            StatusCode::CONFLICT
        );
    }
}

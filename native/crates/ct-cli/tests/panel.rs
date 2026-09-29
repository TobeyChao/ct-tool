//! Real HTTP/CLI acceptance in temporary workspaces, without Python or source assets.
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc,
    time::Duration,
};
struct Panel {
    child: Child,
    port: u16,
    root: tempfile::TempDir,
}
impl Panel {
    fn start(valid: bool) -> Self {
        Self::start_options(valid, true)
    }
    fn start_options(valid: bool, explicit_root: bool) -> Self {
        Self::start_browser_options(valid, explicit_root, true)
    }
    fn start_browser_options(valid: bool, explicit_root: bool, no_browser: bool) -> Self {
        Self::start_bind_options(valid, explicit_root, no_browser, Some(0), true)
    }
    fn start_bind_options(
        valid: bool,
        explicit_root: bool,
        no_browser: bool,
        port: Option<u16>,
        explicit_host: bool,
    ) -> Self {
        let root = tempfile::Builder::new()
            .prefix("ct 面板 测试 ")
            .tempdir()
            .unwrap();
        if valid {
            write(
                root.path(),
                "config/global.yaml",
                "primary_lang: zh\nsecondary_langs: [en]\n",
            );
            write(root.path(),"config/schemas/Item.yaml","table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n    i18n: true\n");
        }
        let mut command = Command::new(env!("CARGO_BIN_EXE_ct"));
        command.arg("panel");
        if explicit_root {
            command.arg("--root").arg(root.path());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let bin = root.path().join("browser-bin");
            std::fs::create_dir_all(&bin).unwrap();
            for name in ["open", "xdg-open"] {
                let opener = bin.join(name);
                std::fs::write(
                    &opener,
                    "#!/bin/sh\nprintf '%s' \"$1\" > \"$CT_BROWSER_MARKER\"\n",
                )
                .unwrap();
                std::fs::set_permissions(&opener, std::fs::Permissions::from_mode(0o755)).unwrap();
            }
            command.env(
                "PATH",
                format!(
                    "{}:{}",
                    bin.display(),
                    std::env::var("PATH").unwrap_or_default()
                ),
            );
            command.env("CT_BROWSER_MARKER", root.path().join("browser-opened.txt"));
        }
        if explicit_host {
            command.args(["--host", "127.0.0.1"]);
        }
        if let Some(port) = port {
            command.args(["--port", &port.to_string()]);
        }
        if no_browser {
            command.arg("--no-browser");
        }
        let mut child = command
            .arg("--shutdown-on-stdin-eof")
            .current_dir(root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let _ = tx.send(line.unwrap());
            }
        });
        let line = rx.recv_timeout(Duration::from_secs(15)).unwrap();
        let port = line
            .split("http://127.0.0.1:")
            .nth(1)
            .unwrap()
            .split('（')
            .next()
            .unwrap()
            .parse()
            .unwrap();
        Self { child, port, root }
    }
    fn raw(&self, path: &str, body: Option<&str>, headers: &str) -> (u16, Vec<u8>) {
        let mut stream = TcpStream::connect(("127.0.0.1", self.port)).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        write!(
            stream,
            "{} {path} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n{}{}\r\n{}",
            if body.is_some() { "POST" } else { "GET" },
            self.port,
            body.map(|b| format!(
                "Content-Type: application/json\r\nContent-Length: {}\r\n",
                b.len()
            ))
            .unwrap_or_default(),
            headers,
            body.unwrap_or("")
        )
        .unwrap();
        let mut bytes = vec![];
        stream.read_to_end(&mut bytes).unwrap();
        let split = bytes.windows(4).position(|w| w == b"\r\n\r\n").unwrap();
        let status = std::str::from_utf8(&bytes[..split])
            .unwrap()
            .split_whitespace()
            .nth(1)
            .unwrap()
            .parse()
            .unwrap();
        (status, bytes[split + 4..].to_vec())
    }
    fn api(&self, path: &str, body: Option<Value>) -> (u16, Value) {
        let text = body.map(|b| b.to_string());
        let (s, b) = self.raw(path, text.as_deref(), "");
        (s, serde_json::from_slice(&b).unwrap())
    }
}
#[test]
fn panel_process_uses_current_directory_by_default_and_accepts_unicode_root() {
    let p = Panel::start_options(true, false);
    let (status, workspace) = p.api("/api/workspace", None);
    assert_eq!(status, 200, "{workspace}");
    assert_eq!(
        workspace["data"]["root"],
        p.root
            .path()
            .canonicalize()
            .unwrap()
            .to_string_lossy()
            .as_ref()
    );
    assert!(p.root.path().to_string_lossy().contains("面板 测试"));
    assert_eq!(p.api("/api/schema-workspace", None).0, 200);
}

#[test]
fn panel_process_uses_explicit_port_and_default_bind_address() {
    let reserved = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = reserved.local_addr().unwrap().port();
    drop(reserved);
    let p = Panel::start_bind_options(true, true, true, Some(port), false);
    assert_eq!(p.port, port);
    assert_eq!(p.api("/api/service", None).0, 200);
}

#[test]
fn panel_process_defaults_to_port_8000_when_available() {
    let Ok(reserved) = std::net::TcpListener::bind(("127.0.0.1", 8000)) else {
        eprintln!("port 8000 is occupied; default-port process check cannot run here");
        return;
    };
    drop(reserved);
    let p = Panel::start_bind_options(true, false, true, None, false);
    assert_eq!(p.port, 8000);
    assert_eq!(p.api("/api/workspace", None).0, 200);
}

#[cfg(unix)]
#[test]
fn browser_opens_only_after_successful_listen_and_no_browser_suppresses_it() {
    let headless = Panel::start_browser_options(true, true, true);
    assert_eq!(headless.api("/api/service", None).0, 200);
    assert!(!headless.root.path().join("browser-opened.txt").exists());
    let visible = Panel::start_browser_options(true, true, false);
    let marker = visible.root.path().join("browser-opened.txt");
    for _ in 0..100 {
        if marker.is_file() {
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(
        std::fs::read_to_string(marker).unwrap(),
        format!("http://127.0.0.1:{}", visible.port)
    );
    assert_eq!(visible.api("/api/service", None).0, 200);
}

#[test]
fn invalid_cli_parameters_fail_without_starting_a_panel() {
    for args in [vec!["--port", "65536"], vec!["--host", "bad/host"]] {
        let out = Command::new(env!("CARGO_BIN_EXE_ct"))
            .arg("panel")
            .args(&args)
            .arg("--no-browser")
            .output()
            .unwrap();
        assert!(!out.status.success(), "{args:?}");
        assert!(!out.stderr.is_empty(), "{args:?}");
        assert!(out.stdout.is_empty(), "{args:?}");
    }
}
impl Drop for Panel {
    fn drop(&mut self) {
        drop(self.child.stdin.take());
        for _ in 0..200 {
            if self.child.try_wait().unwrap().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        panic!("panel did not shut down after stdin EOF")
    }
}
fn write(root: &Path, path: &str, text: &str) {
    let p = root.join(path);
    std::fs::create_dir_all(p.parent().unwrap()).unwrap();
    std::fs::write(p, text).unwrap();
}
#[test]
fn embedded_assets_and_invalid_workspace_remain_accessible() {
    let p = Panel::start(false);
    for path in ["/", "/static/index.html", "/static/js/app-shell.js"] {
        let (status, _) = p.raw(path, None, "");
        assert_eq!(status, 200, "{path}")
    }
    assert_eq!(p.raw("/static/%2e%2e/Cargo.toml", None, "").0, 404);
    assert_eq!(p.api("/api/service", None).1["data"]["kernel"], "native");
    assert_eq!(p.api("/api/workspace", None).0, 400);
}
#[test]
fn request_boundaries_and_port_conflict() {
    let p = Panel::start(true);
    assert_eq!(
        p.raw("/api/export", Some("{}"), "Origin: http://evil.example\r\n")
            .0,
        403
    );
    assert_eq!(p.raw("/api/export", Some("{"), "").0, 400);
    assert_eq!(p.raw("/api/export", Some("[]"), "").0, 400);
    assert_eq!(
        p.raw("/api/export", Some(&"x".repeat(4 * 1024 * 1024 + 1)), "")
            .0,
        413
    );
    assert_eq!(p.api("/api/service", None).0, 200);
    let mut conflict = Command::new(env!("CARGO_BIN_EXE_ct"));
    conflict.args(["panel", "--port", &p.port.to_string()]);
    #[cfg(unix)]
    {
        conflict.env(
            "PATH",
            format!(
                "{}:{}",
                p.root.path().join("browser-bin").display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        );
        conflict.env(
            "CT_BROWSER_MARKER",
            p.root.path().join("browser-opened.txt"),
        );
    }
    let out = conflict.output().unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("无法启动面板"));
    assert!(out.stdout.is_empty());
    #[cfg(unix)]
    assert!(!p.root.path().join("browser-opened.txt").exists());
}
#[test]
fn schema_guards_candidate_undo_and_yaml_only_save() {
    let p = Panel::start(true);
    let (_, s) = p.api("/api/schema-workspace", None);
    let revision = &s["data"]["schemaRevision"];
    let commands = json!([{"type":"set_property","payload":{"owner":"table:Item","name":"Name","property":"comment","value":"注释"}}]);
    let body =
        json!({"schemaRevision":revision,"commands":commands,"cursor":1,"draftGeneration":9});
    let (code, c) = p.api("/api/schema-workspace/candidate", Some(body.clone()));
    assert_eq!(code, 200, "{c}");
    assert_eq!(c["data"]["netDiff"]["changedResources"], 1);
    let mut undo = body.clone();
    undo["cursor"] = json!(0);
    assert_eq!(
        p.api("/api/schema-workspace/candidate", Some(undo)).1["data"]["netDiff"]["isNoOp"],
        true
    );
    let mut save = body.clone();
    save["candidateHash"] = json!("wrong");
    assert_eq!(
        p.api("/api/schema-workspace/save", Some(save.clone())).0,
        409
    );
    save["candidateHash"] = c["data"]["candidateHash"].clone();
    assert_eq!(p.api("/api/schema-workspace/save", Some(save)).0, 200);
    assert!(!p.root.path().join("excel").exists());
    assert!(!p.root.path().join("output").exists());
    assert_eq!(p.api("/api/schema-workspace/candidate", Some(body)).0, 409);
}
#[test]
fn legacy_history_import_is_idempotent_and_preserves_source() {
    let p = Panel::start(true);
    let old = json!([{"time":"2026-01-01 10:00:00","result":"成功","tables":1}]).to_string();
    write(p.root.path(), "cache/panel_history.json", &old);
    let lock = ct_storage::lock::WorkspaceLock::acquire(p.root.path()).unwrap();
    assert_eq!(p.api("/api/history", None).0, 409);
    assert!(!p.root.path().join("cache/history.json").exists());
    drop(lock);
    for _ in 0..2 {
        let (code, h) = p.api("/api/history", None);
        assert_eq!(code, 200, "{h}");
        assert_eq!(h["data"].as_array().unwrap().len(), 1);
        assert_eq!(h["data"][0]["result"], "success")
    }
    assert_eq!(
        std::fs::read_to_string(p.root.path().join("cache/panel_history.json")).unwrap(),
        old
    );
    write(
        p.root.path(),
        "cache/history.json",
        &json!({"format":"desktop-history/1","entries":[],"legacyPanelImported":true}).to_string(),
    );
    assert_eq!(p.api("/api/history", None).1["data"], json!([]));
}
#[test]
fn damaged_legacy_history_or_import_write_failure_warns_without_losing_source() {
    let p = Panel::start(true);
    let source = p.root.path().join("cache/panel_history.json");
    write(p.root.path(), "cache/panel_history.json", "not JSON");
    assert_eq!(p.api("/api/history", None).0, 200);
    assert_eq!(p.api("/api/history", None).1["data"], json!([]));
    assert_eq!(std::fs::read_to_string(&source).unwrap(), "not JSON");
    let (_, logs) = p.api("/api/logs?module=系统", None);
    assert!(logs["data"].as_array().unwrap().iter().any(
        |line| line["level"] == "WARN" && line["message"].as_str().unwrap().contains("旧历史")
    ));

    let original = json!([{"time":"2026-01-01 00:00:00","result":"成功","tables":1}]).to_string();
    write(p.root.path(), "cache/panel_history.json", &original);
    std::fs::create_dir_all(p.root.path().join("cache/history.json")).unwrap();
    assert_eq!(p.api("/api/history", None).1["data"], json!([]));
    assert_eq!(std::fs::read_to_string(&source).unwrap(), original);
    let (_, logs) = p.api("/api/logs?module=系统", None);
    assert!(logs["data"]
        .as_array()
        .unwrap()
        .iter()
        .any(|line| line["level"] == "WARN"
            && line["message"].as_str().unwrap().contains("历史写入失败")));
    std::fs::remove_dir(p.root.path().join("cache/history.json")).unwrap();
    assert_eq!(
        p.api("/api/history", None).1["data"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
#[test]
fn legacy_apply_blocks_writes_and_survives_recovery_attempt() {
    let p = Panel::start(true);
    write(p.root.path(), "cache/apply.journal.json", "{unknown}");
    assert_eq!(
        p.api(
            "/api/schema-workspace/gen-template",
            Some(json!({"table":"Item"}))
        )
        .0,
        409
    );
    assert_eq!(p.api("/api/workspace/recover", Some(json!({}))).0, 409);
    assert_eq!(
        std::fs::read_to_string(p.root.path().join("cache/apply.journal.json")).unwrap(),
        "{unknown}"
    );
    assert!(!p.root.path().join("excel/Item.xlsx").exists());
}
#[test]
fn translations_recompute_stale_and_reject_unsynchronized_save() {
    let p = Panel::start(true);
    write(
        p.root.path(),
        "i18n/source/Item.json",
        r#"{"1.Name":"新原文"}"#,
    );
    write(
        p.root.path(),
        "i18n/en/Item.json",
        r#"{"1.Name":{"source":"旧原文","text":"Sword","confirmed":true,"status":"translated"}}"#,
    );
    let (_, v) = p.api("/api/i18n/entries?table=Item&lang=en", None);
    assert_eq!(v["data"][0]["status"], "stale", "{v}");
    assert_eq!(
        p.api(
            "/api/i18n/entry",
            Some(json!({"table":"Item","lang":"en","key":"2.Name","text":"x","confirmed":true}))
        )
        .0,
        400
    );
    assert_eq!(
        p.api(
            "/api/i18n/entry",
            Some(json!({"table":"Item","lang":"en","key":"1.Name","text":"","confirmed":false}))
        )
        .1["data"]["status"],
        "missing"
    );
}

#[test]
fn shared_lock_blocks_web_reads_and_cli_template_writes() {
    let p = Panel::start(true);
    let independent = Panel::start(true);
    let _lock = ct_storage::lock::WorkspaceLock::acquire(p.root.path()).unwrap();
    assert_eq!(p.api("/api/schema-workspace", None).0, 409);
    assert_eq!(
        p.api(
            "/api/schema-workspace/gen-template",
            Some(json!({"table":"Item"}))
        )
        .0,
        409
    );
    for (path, body) in [
        ("/api/i18n/sync", json!({"table":"Item","lang":"en"})),
        (
            "/api/i18n/compact",
            json!({"table":"Item","lang":"en","dry_run":true}),
        ),
        (
            "/api/i18n/entry",
            json!({"table":"Item","lang":"en","key":"1.Name","text":"X"}),
        ),
    ] {
        let (status, response) = p.api(path, Some(body));
        assert_eq!(status, 409, "{path}: {response}");
        assert_eq!(response["busy"], true, "{path}: {response}");
    }
    let out = Command::new(env!("CARGO_BIN_EXE_ct"))
        .args(["gen-template", "--all", "--root"])
        .arg(p.root.path())
        .output()
        .unwrap();
    assert!(!out.status.success());
    let export = Command::new(env!("CARGO_BIN_EXE_ct"))
        .args(["export", "--root"])
        .arg(p.root.path())
        .output()
        .unwrap();
    assert!(!export.status.success());
    assert!(
        String::from_utf8_lossy(&export.stderr).contains("请稍后重试"),
        "{}",
        String::from_utf8_lossy(&export.stderr)
    );
    let (accepted, _) = p.api("/api/export", Some(json!({})));
    assert_eq!(accepted, 200);
    let mut progress = json!({});
    for _ in 0..100 {
        progress = p.api("/api/export/progress", None).1["data"].clone();
        if progress["status"] == "error" {
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(progress["status"], "error", "{progress}");
    assert!(
        progress["message"]
            .as_str()
            .unwrap_or_default()
            .contains("请稍后重试"),
        "{progress}"
    );
    assert!(!p.root.path().join("excel/Item.xlsx").exists());
    assert_eq!(p.api("/api/export/progress", None).0, 200);
    assert_eq!(independent.api("/api/schema-workspace", None).0, 200);
    assert_eq!(
        independent
            .api(
                "/api/schema-workspace/gen-template",
                Some(json!({"table":"Item"}))
            )
            .0,
        200
    );
    assert!(independent.root.path().join("excel/Item.xlsx").exists());
}

#[test]
fn schema_save_reports_busy_without_losing_yaml_when_cli_holds_lock() {
    let p = Panel::start(true);
    let (_, snapshot) = p.api("/api/schema-workspace", None);
    let revision = snapshot["data"]["schemaRevision"].clone();
    let body = json!({"schemaRevision":revision,"commands":[{"type":"set_property","payload":{"owner":"table:Item","name":"Name","property":"comment","value":"pending"}}]});
    let (_, candidate) = p.api("/api/schema-workspace/candidate", Some(body.clone()));
    let mut save = body;
    save["candidateHash"] = candidate["data"]["candidateHash"].clone();
    let path = p.root.path().join("config/schemas/Item.yaml");
    let before = std::fs::read(&path).unwrap();
    let lock = ct_storage::lock::WorkspaceLock::acquire(p.root.path()).unwrap();
    let (status, result) = p.api("/api/schema-workspace/save", Some(save));
    assert_eq!(status, 409, "{result}");
    assert_eq!(result["busy"], true);
    assert_eq!(std::fs::read(&path).unwrap(), before);
    drop(lock);
    assert_eq!(p.api("/api/schema-workspace", None).0, 200);
}

#[test]
fn unknown_host_is_rejected_before_routing() {
    let p = Panel::start(true);
    let mut stream = TcpStream::connect(("127.0.0.1", p.port)).unwrap();
    write!(
        stream,
        "GET /api/service HTTP/1.1\r\nHost: attacker.invalid:{}\r\nConnection: close\r\n\r\n",
        p.port
    )
    .unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    assert!(response.starts_with("HTTP/1.1 403"));
    assert_eq!(p.api("/api/service", None).0, 200);
}

#[test]
fn explicit_http_recovery_consumes_frozen_python_journals_before_loading_config() {
    use ct_test_support::journal_builder::{
        assert_python_publication_recovered, install_python_publication, python_publication_cases,
    };
    for case in python_publication_cases() {
        let p = Panel::start(true);
        install_python_publication(p.root.path(), &case);
        let journal_path = p.root.path().join(".ct/export-publication.json");
        let journal = std::fs::read(&journal_path).unwrap();
        let (_, service) = p.api("/api/service", None);
        assert!(service["data"]["recovery"].is_string(), "{service}");
        assert_eq!(p.api("/api/schema-workspace", None).0, 409);
        assert_eq!(
            std::fs::read(&journal_path).unwrap(),
            journal,
            "reads must not recover"
        );
        let (status, recovered) = p.api("/api/workspace/recover", Some(json!({})));
        // The committed fixture intentionally committed a malformed config:
        // recovery keeps that version and reports its load error after cleanup.
        let committed = case["journal"]["phase"] == "committed";
        assert_eq!(status, if committed { 409 } else { 200 }, "{recovered}");
        assert_python_publication_recovered(p.root.path(), &case);
        let (_, service) = p.api("/api/service", None);
        assert!(service["data"]["recovery"].is_null());
        p.api("/api/workspace/recover", Some(json!({})));
        assert_python_publication_recovered(p.root.path(), &case);
        if !committed {
            assert_eq!(p.api("/api/schema-workspace", None).0, 200);
        }
    }
}

#[test]
fn missing_python_backup_refuses_recovery_and_preserves_journal() {
    use ct_test_support::journal_builder::{install_python_publication, python_publication_cases};
    let p = Panel::start(true);
    let cases = python_publication_cases();
    let case = cases.iter().find(|c| c["name"] == "publishing-4").unwrap();
    install_python_publication(p.root.path(), case);
    let journal_path = p.root.path().join(".ct/export-publication.json");
    let journal = std::fs::read(&journal_path).unwrap();
    let data: Value = serde_json::from_slice(&journal).unwrap();
    std::fs::remove_file(data["entries"][0]["backup"].as_str().unwrap()).unwrap();
    let config = std::fs::read(p.root.path().join("config/global.yaml")).unwrap();
    let (status, result) = p.api("/api/workspace/recover", Some(json!({})));
    assert_eq!(status, 409, "{result}");
    assert_eq!(std::fs::read(&journal_path).unwrap(), journal);
    assert_eq!(
        std::fs::read(p.root.path().join("config/global.yaml")).unwrap(),
        config
    );
    assert!(p.root.path().join("output/create.txt").is_file());
    assert_eq!(p.api("/api/schema-workspace", None).0, 409);
}

#[test]
fn validate_reports_unknown_commands_without_publishing() {
    let p = Panel::start(true);
    let (_, snapshot) = p.api("/api/schema-workspace", None);
    let body = json!({"schemaRevision":snapshot["data"]["schemaRevision"],"commands":[{"type":"frobnicate","payload":{}}]});
    let (status, response) = p.api("/api/schema-workspace/validate", Some(body.clone()));
    assert_eq!(status, 200, "{response}");
    assert_eq!(response["data"]["valid"], false);
    assert_eq!(response["data"]["issues"][0]["location"], "commands[0]");
    let (status, response) = p.api("/api/schema-workspace/candidate", Some(body));
    assert_eq!(status, 400);
    assert_eq!(response["issues"][0]["location"], "commands[0]");
}

#[test]
fn malformed_resource_commands_have_domain_field_locations_on_all_endpoints() {
    let p = Panel::start(true);
    let (_, snapshot) = p.api("/api/schema-workspace", None);
    let cases = [
        ("struct", json!({"name":"X"}), "payload.kind"),
        (
            "enum",
            json!({"kind":"record","name":"X","values":[{"name":"A","comment":""}]}),
            "payload.resource.kind",
        ),
        (
            "table",
            json!({"primary":"Id","fields":[]}),
            "payload.resource.table",
        ),
        (
            "table",
            json!({"table":"X","primary":"Id","fields":[{"name":"Id","type":"int32","oops":1}]}),
            "payload.resource.fields[0].oops",
        ),
        (
            "enum",
            json!({"kind":"enum","name":"E","values":["Common"]}),
            "payload.resource",
        ),
        (
            "table",
            json!({"table":"X","primary":"Id","fields":[{"name":"Id","type":"enum"}]}),
            "payload.resource",
        ),
        ("enum", json!({}), "payload.resource.name"),
    ];
    let before = std::fs::read(p.root.path().join("config/schemas/Item.yaml")).unwrap();
    for (kind, resource, location) in cases {
        let body = json!({"schemaRevision":snapshot["data"]["schemaRevision"],"candidateHash":"invalid-candidate","commands":[{"type":"add_resource","payload":{"kind":kind,"resource":resource}}]});
        for action in ["validate", "candidate", "save"] {
            let (status, result) = p.api(
                &format!("/api/schema-workspace/{action}"),
                Some(body.clone()),
            );
            assert_eq!(
                status,
                if action == "validate" { 200 } else { 400 },
                "{action}: {result}"
            );
            let issues = if action == "validate" {
                assert_eq!(result["data"]["valid"], false);
                &result["data"]["issues"]
            } else {
                &result["issues"]
            };
            assert_eq!(
                issues[0]["location"],
                format!("commands[0].{location}"),
                "{action}: {result}"
            );
            assert!(!issues[0]["message"].as_str().unwrap().is_empty());
        }
    }
    assert_eq!(
        std::fs::read(p.root.path().join("config/schemas/Item.yaml")).unwrap(),
        before
    );
    assert_eq!(
        std::fs::read_dir(p.root.path().join("config/schemas"))
            .unwrap()
            .count(),
        1
    );
    assert!(!p.root.path().join("config/types/X.yaml").exists());
}

#[test]
fn create_three_resource_kinds_and_roundtrip_net_noop() {
    let p = Panel::start(true);
    let (_, snapshot) = p.api("/api/schema-workspace", None);
    let commands = json!([
 {"type":"add_resource","payload":{"kind":"enum","resource":{"kind":"enum","name":"ItemRarity","values":[{"name":"Common"}]}}},
 {"type":"add_resource","payload":{"kind":"record","resource":{"kind":"record","name":"DropReward","fields":[{"name":"Amount","type":"int32"}]}}},
 {"type":"add_resource","payload":{"kind":"table","resource":{"table":"Quest","primary":"Id","fields":[{"name":"Id","type":"int32"},{"name":"Rarity","type":"ItemRarity"},{"name":"Reward","type":"DropReward"}]}}}]);
    let mut body = json!({"schemaRevision":snapshot["data"]["schemaRevision"],"commands":commands});
    let (status, validation) = p.api("/api/schema-workspace/validate", Some(body.clone()));
    assert_eq!(status, 200);
    assert_eq!(validation["data"]["valid"], true, "{validation}");
    assert_eq!(validation["data"]["netDiff"]["changedResources"], 3);
    body["candidateHash"] = validation["data"]["candidateHash"].clone();
    let (status, saved) = p.api("/api/schema-workspace/save", Some(body));
    assert_eq!(status, 200, "{saved}");
    assert_eq!(saved["data"]["written"].as_array().unwrap().len(), 3);
    for file in [
        "config/types/ItemRarity.yaml",
        "config/types/DropReward.yaml",
        "config/schemas/Quest.yaml",
    ] {
        assert!(p.root.path().join(file).exists());
    }
    let mut noop = json!({"schemaRevision":saved["data"]["schemaRevision"],"commands":[{"type":"add_resource","payload":{"kind":"record","resource":{"kind":"record","name":"Temporary","fields":[{"name":"Amount","type":"int32"}]}}},{"type":"delete_resource","payload":{"name":"record:Temporary"}}]});
    let (_, candidate) = p.api("/api/schema-workspace/candidate", Some(noop.clone()));
    assert_eq!(candidate["data"]["netDiff"]["isNoOp"], true, "{candidate}");
    noop["candidateHash"] = candidate["data"]["candidateHash"].clone();
    assert_eq!(
        p.api("/api/schema-workspace/save", Some(noop)).1["data"]["isNoOp"],
        true
    );
    assert!(!p.root.path().join("config/types/Temporary.yaml").exists());
}

#[test]
fn candidate_applies_only_active_cursor_prefix() {
    let p = Panel::start(true);
    let (_, snapshot) = p.api("/api/schema-workspace", None);
    let mut body = json!({"schemaRevision":snapshot["data"]["schemaRevision"],"commands":[{"type":"set_property","payload":{"owner":"table:Item","name":"Name","property":"comment","value":"active"}},{"type":"future-unknown-redo","payload":{}}],"cursor":1});
    let (status, response) = p.api("/api/schema-workspace/candidate", Some(body.clone()));
    assert_eq!(status, 200, "{response}");
    assert_eq!(response["data"]["netDiff"]["changedResources"], 1);
    body["cursor"] = json!(2);
    assert_eq!(p.api("/api/schema-workspace/candidate", Some(body)).0, 400);
}

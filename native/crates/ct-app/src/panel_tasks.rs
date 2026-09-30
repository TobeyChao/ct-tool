use crate::export::{CompletionPolicy, ExportRequest, Reporter};
use crate::panel::{PanelError, Result};
use crate::task::CancelFlag;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

pub struct Tasks {
    progress: Mutex<Value>,
    logs: Mutex<VecDeque<Value>>,
    cancel: Mutex<CancelFlag>,
    handle: Mutex<Option<std::thread::JoinHandle<()>>>,
    dismissed: AtomicBool,
    settled: Mutex<Option<Instant>>,
}
impl Default for Tasks {
    fn default() -> Self {
        Self {
            progress: Mutex::new(
                json!({"status":"idle","steps":["解析校验","JSON","Accessor","FBS","Bundle"],"step_index":-1,"step_name":"","errors":[],"message":"","tables_exported":0,"elapsed":0,"forced":false,"cancelled":false}),
            ),
            logs: Mutex::new(VecDeque::new()),
            cancel: Mutex::new(CancelFlag::new()),
            handle: Mutex::new(None),
            dismissed: AtomicBool::new(false),
            settled: Mutex::new(None),
        }
    }
}
impl Tasks {
    pub fn log(&self, module: &str, level: &str, message: &str) {
        let level = match level.to_uppercase().as_str() {
            "WARN" | "WARNING" => "WARN",
            "ERROR" | "CRITICAL" => "ERROR",
            _ => "INFO",
        };
        let time = chrono::Local::now().format("%H:%M:%S").to_string();
        let mut logs = self.logs.lock().unwrap();
        if logs.len() >= 2000 {
            logs.pop_front();
        }
        logs.push_back(json!({"time":time,"module":module,"level":level,"message":message}));
    }
    pub fn logs(&self, module: &str) -> Value {
        json!(self
            .logs
            .lock()
            .unwrap()
            .iter()
            .filter(|l| module == "all" || l["module"] == module)
            .cloned()
            .collect::<Vec<_>>())
    }
    pub fn progress(&self) -> Value {
        self.progress.lock().unwrap().clone()
    }
    pub fn list(&self) -> Value {
        let p = self.progress();
        if p["status"] == "error"
            && self
                .settled
                .lock()
                .unwrap()
                .is_some_and(|at| at.elapsed() > Duration::from_secs(15))
        {
            return json!([]);
        }
        if (p["status"] == "running" || p["status"] == "error")
            && !self.dismissed.load(Ordering::SeqCst)
        {
            let message = match p["step_name"].as_str() {
                Some(step) if !step.is_empty() => {
                    format!("{step} · {}", p["message"].as_str().unwrap_or_default())
                }
                _ => p["message"].as_str().unwrap_or_default().to_string(),
            };
            json!([{"id":"canonical-export","kind":"导出","scope":"全部表 × 全量语言","status":p["status"],"message":message,"target":"/logs","started_at":p["started_at"]}])
        } else {
            json!([])
        }
    }
    pub fn dismiss(&self) -> Value {
        let can = self.progress()["status"] == "error";
        if can {
            self.dismissed.store(true, Ordering::SeqCst);
        }
        json!({"dismissed":can})
    }
    pub fn cancel(&self) -> Value {
        if self.progress()["status"] == "running" {
            self.cancel.lock().unwrap().cancel();
            self.progress.lock().unwrap()["message"] = "正在取消，发布阶段将先安全完成".into();
        }
        self.progress()
    }
    pub fn start(self: &Arc<Self>, root: PathBuf, forced: bool) -> Result<Value> {
        let mut p = self.progress.lock().unwrap();
        if p["status"] == "running" {
            return Err(PanelError::new(409, "已有导出任务进行中"));
        }
        if let Some(handle) = self.handle.lock().unwrap().take() {
            let _ = handle.join();
        }
        let cancel = CancelFlag::new();
        *self.cancel.lock().unwrap() = cancel.clone();
        self.dismissed.store(false, Ordering::SeqCst);
        *self.settled.lock().unwrap() = None;
        *p = json!({"status":"running","steps":["解析校验","JSON","Accessor","FBS","Bundle"],"step_index":-1,"step_name":"","message":"导出进行中…","errors":[],"tables_exported":0,"elapsed":0,"forced":forced,"cancelled":false,"started_at":SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs_f64()});
        let initial = p.clone();
        let tasks = self.clone();
        *self.handle.lock().unwrap() = Some(std::thread::spawn(move || {
            let request = ExportRequest {
                root,
                forced,
                table_filter: None,
                lang_filter: None,
            };
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                crate::export::run_export(
                    &request,
                    CompletionPolicy::export_only(),
                    Some(&cancel),
                    Some(tasks.clone()),
                    true,
                )
            }));
            let mut p = tasks.progress.lock().unwrap();
            *tasks.settled.lock().unwrap() = Some(Instant::now());
            match result {
                Ok(Ok((result, _, _))) => {
                    p["status"] = "done".into();
                    p["tables_exported"] = result.tables.into();
                    p["elapsed"] = json!(result.elapsed);
                    p["message"] =
                        format!("成功 · {} 张表 · {:.2}s", result.tables, result.elapsed).into();
                    p["step_index"] = 5.into();
                    tasks.log("导出", "INFO", p["message"].as_str().unwrap_or("导出完成"));
                }
                Ok(Err(crate::export::RunError::Cancelled(_))) => {
                    p["status"] = "cancelled".into();
                    p["cancelled"] = true.into();
                    p["message"] = "导出已取消".into();
                    tasks.log("导出", "WARN", "导出已取消");
                }
                failure => {
                    let message = match failure {
                        Ok(Err(e)) => e.to_string(),
                        _ => "导出任务发生内部错误".into(),
                    };
                    p["status"] = "error".into();
                    p["message"] = message.clone().into();
                    tasks.log("导出", "ERROR", &message);
                }
            }
        }));
        Ok(initial)
    }
    pub fn wait(&self) {
        let handle = self.handle.lock().unwrap().take();
        if let Some(handle) = handle {
            let _ = handle.join();
        }
    }
}
impl Reporter for Tasks {
    fn log(&self, line: &str, err: bool) {
        self.log("导出", if err { "ERROR" } else { "INFO" }, line);
    }
    fn stage(&self, name: &str, index: usize, _total: usize) {
        let mut p = self.progress.lock().unwrap();
        p["step_index"] = index.into();
        p["step_name"] = if name == "publish" {
            "发布中".into()
        } else {
            p["steps"][index].clone()
        };
    }
    fn issues(&self, issues: &[ct_domain::diagnostics::ValidationIssue]) {
        let texts: Vec<_> = issues.iter().map(|i| i.render()).collect();
        self.progress.lock().unwrap()["errors"] = json!(texts);
        for text in texts {
            self.log("校验", "ERROR", &text);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn state(status: &str) -> Tasks {
        let tasks = Tasks::default();
        *tasks.progress.lock().unwrap() =
            json!({"status":status,"started_at":1.25,"message":"test","errors":["problem"]});
        tasks
    }
    #[test]
    fn running_stays_projected_and_cannot_be_dismissed() {
        let tasks = state("running");
        *tasks.settled.lock().unwrap() = Some(Instant::now() - Duration::from_secs(60));
        assert_eq!(tasks.list()[0]["started_at"], 1.25);
        assert_eq!(tasks.dismiss()["dismissed"], false);
        assert_eq!(tasks.list().as_array().unwrap().len(), 1);
    }
    #[test]
    fn fresh_error_can_be_dismissed_without_losing_details() {
        let tasks = state("error");
        *tasks.settled.lock().unwrap() = Some(Instant::now());
        assert_eq!(tasks.list()[0]["status"], "error");
        assert_eq!(tasks.list()[0]["started_at"], 1.25);
        assert_eq!(tasks.dismiss()["dismissed"], true);
        assert_eq!(tasks.list(), json!([]));
        assert_eq!(tasks.progress()["errors"], json!(["problem"]));
    }
    #[test]
    fn expired_error_leaves_projection_but_remains_queryable() {
        let tasks = state("error");
        *tasks.settled.lock().unwrap() = Some(Instant::now() - Duration::from_secs(16));
        assert_eq!(tasks.list(), json!([]));
        assert_eq!(tasks.progress()["status"], "error");
    }
    #[test]
    fn log_buffer_is_bounded_normalizes_levels_and_filters_modules() {
        let tasks = Tasks::default();
        for i in 0..2005 {
            tasks.log("导出", "INFO", &i.to_string())
        }
        tasks.log("i18n", "WARNING", "one");
        tasks.log("校验", "CRITICAL", "two");
        assert_eq!(tasks.logs("all").as_array().unwrap().len(), 2000);
        assert_eq!(tasks.logs("i18n")[0]["level"], "WARN");
        assert_eq!(tasks.logs("i18n").as_array().unwrap().len(), 1);
        assert_eq!(tasks.logs("校验")[0]["level"], "ERROR");
    }
    #[test]
    fn native_log_categories_and_level_names_match_panel_filters() {
        let tasks = Tasks::default();
        for module in ["导出", "校验", "i18n", "模板", "系统"] {
            tasks.log(module, "INFO", module);
            let rows = tasks.logs(module);
            assert_eq!(rows.as_array().unwrap().len(), 1);
            assert_eq!(rows[0]["module"], module);
        }
        for (input, expected) in [
            ("INFO", "INFO"),
            ("WARNING", "WARN"),
            ("WARN", "WARN"),
            ("ERROR", "ERROR"),
            ("CRITICAL", "ERROR"),
            ("", "INFO"),
        ] {
            tasks.log("系统", input, input);
            assert_eq!(
                tasks.logs("系统").as_array().unwrap().last().unwrap()["level"],
                expected
            );
        }
    }
}

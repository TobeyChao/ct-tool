//! `ct export`：默认增量复用，`--all` 强制重建；成功后按配置部署并记账。

use std::path::PathBuf;

use clap::Args as ClapArgs;

use ct_app::export::{run_export, CompletionPolicy, ExportRequest, Reporter, RunError};

#[derive(Debug, ClapArgs)]
pub struct Args {
    /// 强制重建所有选中产物，绕过解析/校验/生成缓存
    #[arg(long)]
    pub all: bool,
    /// 仅导出单张表（精确匹配，不接受逗号列表）
    #[arg(long)]
    pub table: Option<String>,
    /// 仅导出单种语言
    #[arg(long)]
    pub lang: Option<String>,
    /// 部署时包含 build_targets
    #[arg(long = "for-build")]
    pub for_build: bool,
    /// 工作区根目录（默认当前目录）
    #[arg(long)]
    pub root: Option<String>,
    /// DEBUG 日志
    #[arg(long)]
    pub verbose: bool,
}

struct CliReporter;

impl Reporter for CliReporter {
    fn log(&self, line: &str, err: bool) {
        if err {
            eprintln!("{line}");
        } else {
            println!("{line}");
        }
    }
}

fn root_of(root: Option<String>) -> anyhow::Result<PathBuf> {
    Ok(match root {
        Some(r) => PathBuf::from(r),
        None => std::env::current_dir()?,
    })
}

pub fn run(args: Args) -> anyhow::Result<()> {
    let root = root_of(args.root)?;
    let request = ExportRequest {
        root,
        table_filter: args.table,
        lang_filter: args.lang,
        forced: args.all,
    };
    let reporter = CliReporter;
    match run_export(
        &request,
        CompletionPolicy::export_then_deploy(args.for_build),
        None,
        Some(std::sync::Arc::new(reporter)),
        // CLI 不追加桌面历史
        false,
    ) {
        Ok((result, deploy_logs, _recovery)) => {
            if std::env::var_os("CT_PROFILE").is_some() {
                // 阶段 profile 只走 stderr，保持默认 CLI 文本与 golden 一致
                for (name, ms) in &result.stages {
                    eprintln!("[profile] {name}: {ms}ms");
                }
                eprintln!(
                    "[profile] written={} reused={} cache_hits={} cache_misses={}",
                    result.written.len(),
                    result.reused.len(),
                    result.cache_hits,
                    result.cache_misses
                );
            }
            println!("\n导出完成: {} 张表", result.tables);
            if deploy_used(args.for_build, &deploy_logs) {
                echo_deploy_result(&deploy_logs);
            }
            Ok(())
        }
        Err(RunError::Validation(text, _)) => {
            eprint!("{text}");
            std::process::exit(1);
        }
        Err(RunError::Busy(message))
        | Err(RunError::Cancelled(message))
        | Err(RunError::Other(message)) => {
            eprintln!("[export error] {message}");
            std::process::exit(1);
        }
        Err(RunError::Publish(message)) => {
            eprintln!("[publish error] {message}");
            std::process::exit(1);
        }
        Err(RunError::Deploy(message)) => {
            eprintln!("[deploy error] {message}");
            std::process::exit(1);
        }
    }
}

/// 只有配置了部署目标时才有部署输出；无日志表示未启用/未配置（跳过）。
fn deploy_used(_for_build: bool, logs: &[String]) -> bool {
    logs.iter().any(|l| l.starts_with("[deploy]"))
}

fn echo_deploy_result(logs: &[String]) {
    for line in logs {
        // 未配置/未启用的跳过提示走 stderr（与 Python 一致）
        if line.contains("跳过") {
            eprintln!("{line}");
        } else {
            println!("{line}");
        }
    }
    let changed = logs
        .iter()
        .filter(|l| l.starts_with("[deploy] 写入") || l.starts_with("[deploy] 删除"))
        .count();
    if changed > 0 {
        println!("[deploy] 完成：{changed} 个文件已同步");
    } else {
        println!("[deploy] 无文件变更");
    }
}

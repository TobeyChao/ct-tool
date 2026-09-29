//! `ct deploy`：独立部署当前产物，不触发导出、不更新成功账本。

use std::path::PathBuf;

use clap::Args as ClapArgs;

use ct_storage::workspace::{TransactionError, WorkspaceTransaction};

#[derive(Debug, ClapArgs)]
pub struct Args {
    /// 追加构建目标（StreamingAssets）
    #[arg(long = "for-build")]
    pub for_build: bool,
    #[arg(long)]
    pub root: Option<String>,
}

pub fn run(args: Args) -> anyhow::Result<()> {
    let root = match args.root {
        Some(r) => PathBuf::from(r),
        None => std::env::current_dir()?,
    };
    // 与工作区写操作共用同一把锁与恢复流程
    let transaction = match WorkspaceTransaction::begin(&root) {
        Ok(transaction) => transaction,
        Err(TransactionError::Busy(busy)) => {
            eprintln!("[deploy error] {busy}");
            std::process::exit(1);
        }
        Err(TransactionError::Recovery(message)) => {
            eprintln!("[publish error] {message}");
            std::process::exit(1);
        }
    };
    if let Some(recovery) = &transaction.recovery {
        eprintln!("[发布恢复] {recovery}");
    }
    let config = match ct_domain::config::GlobalConfig::load(&root) {
        Ok(config) => config,
        Err(error) => {
            eprintln!("[deploy error] {error}");
            std::process::exit(1);
        }
    };
    let (changed, logs) = match ct_export::deploy::deploy(&config, args.for_build) {
        Ok(ok) => ok,
        Err(error) => {
            eprintln!("[deploy error] {error}");
            std::process::exit(1);
        }
    };
    for line in logs {
        if line.contains("跳过") {
            eprintln!("{line}");
        } else {
            println!("{line}");
        }
    }
    if changed > 0 {
        println!("[deploy] 完成：{changed} 个文件已同步");
    } else {
        println!("[deploy] 无文件变更");
    }
    Ok(())
}

//! `ct recover`：显式恢复未完成的发布（共享锁下），返回新基线；不保存草稿、不导出、不记账。

use std::path::PathBuf;

use clap::Args as ClapArgs;

#[derive(Debug, ClapArgs)]
pub struct Args {
    #[arg(long)]
    pub root: Option<String>,
    /// 输出 JSON（供桌面/脚本消费）
    #[arg(long = "json")]
    pub json_out: bool,
}

pub fn run(args: Args) -> anyhow::Result<()> {
    let root = match args.root {
        Some(r) => PathBuf::from(r),
        None => std::env::current_dir()?,
    };
    let report =
        ct_app::workspace::recover_workspace(&root).map_err(|message| anyhow::anyhow!(message))?;
    if args.json_out {
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "recovered": report.note.is_some(),
                "note": report.note,
                "schemaRevision": report.revision,
            }))
            .unwrap()
        );
        return Ok(());
    }
    match &report.note {
        Some(note) => println!("[recover] {note}"),
        None => println!("[recover] 无待恢复事务"),
    }
    println!(
        "[recover] 新基线 schemaRevision {}",
        &report.revision[..12.min(report.revision.len())]
    );
    Ok(())
}

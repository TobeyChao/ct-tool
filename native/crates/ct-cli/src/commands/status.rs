//! `ct status`：数据变更 / 模板漂移 / 未完成的发布（只读）。

use std::path::PathBuf;

use clap::Args as ClapArgs;

#[derive(Debug, ClapArgs)]
pub struct Args {
    #[arg(long)]
    pub root: Option<String>,
}

pub fn run(args: Args) -> anyhow::Result<()> {
    let root = match args.root {
        Some(r) => PathBuf::from(r),
        None => std::env::current_dir()?,
    };
    let _read_lock = ct_storage::lock::WorkspaceLock::acquire(&root)?;
    // A journal can leave schema and output files at different publication stages.
    // Check under the read lock before loading either resource set.
    if let Some(note) = ct_app::workspace::recovery_needed(&root) {
        anyhow::bail!("[recovery-needed] {note}");
    }
    let workspace = match ct_app::workspace::Workspace::open(&root) {
        Ok(workspace) => workspace,
        Err(error) => {
            // 未完成发布可能让磁盘处于混合状态：报 recovery-needed，
            // 不返回「看似健康」的快照结论
            if let Some(note) = ct_app::workspace::recovery_needed(&root) {
                eprintln!("[recovery-needed] {note}");
                eprintln!("[error] {error}");
                std::process::exit(1);
            }
            anyhow::bail!("[error] {error}");
        }
    };
    let report = ct_app::status::canonical_status(&workspace);
    if !report.missing.is_empty() {
        println!("缺失文件:");
        for name in &report.missing {
            println!("  [missing] {name}");
        }
    }
    if !report.changed.is_empty() {
        println!("数据变更（待导出）:");
        for name in &report.changed {
            println!("  [changed] {name}");
        }
    }
    if !report.drifted.is_empty() {
        println!("模板已过时（schema 修改后未重建）:");
        for name in &report.drifted {
            println!("  [template-stale] {name}  (建议: ct gen-template --table {name})");
        }
    }
    if let Some(publication) = &report.publication {
        println!("未完成的发布:");
        println!("  [publication] {publication}");
        println!("  [recovery-needed] 请先执行 ct recover 恢复，再使用状态结果");
    }
    if report.missing.is_empty()
        && report.changed.is_empty()
        && report.drifted.is_empty()
        && report.publication.is_none()
    {
        println!("[OK] 所有表已是最新（数据 + 模板）");
    }
    Ok(())
}

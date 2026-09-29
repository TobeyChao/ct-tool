//! `ct validate`：只读校验，不写持久缓存。

use std::path::PathBuf;

use clap::Args as ClapArgs;

#[derive(Debug, ClapArgs)]
pub struct Args {
    #[arg(long)]
    pub table: Option<String>,
    #[arg(long)]
    pub root: Option<String>,
}

pub fn run(args: Args) -> anyhow::Result<()> {
    let root = match args.root {
        Some(r) => PathBuf::from(r),
        None => std::env::current_dir()?,
    };
    let _read_lock = ct_storage::lock::WorkspaceLock::acquire(&root)?;
    // 未完成发布意味着磁盘可能是混合状态：不给出「看似健康」的校验结论
    if let Some(note) = ct_app::workspace::recovery_needed(&root) {
        eprintln!("[recovery-needed] {note}");
        std::process::exit(1);
    }
    let workspace =
        ct_app::workspace::Workspace::open(&root).map_err(|e| anyhow::anyhow!("[error] {e}"))?;
    let issues = ct_app::validate::canonical_validate(&workspace, args.table.as_deref());
    if issues.is_empty() {
        println!("校验通过");
        return Ok(());
    }
    eprintln!(
        "
验证发现 {} 个错误：",
        issues.len()
    );
    for issue in &issues {
        eprintln!("  ✗ {}", issue.render());
    }
    eprintln!();
    anyhow::bail!("校验失败：{} 个错误", issues.len())
}

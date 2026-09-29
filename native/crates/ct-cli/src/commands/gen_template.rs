//! `ct gen-template`：生成/迁移 Excel 模板。

use std::path::PathBuf;

use clap::Args as ClapArgs;

#[derive(Debug, ClapArgs)]
pub struct Args {
    #[arg(long)]
    pub table: Option<String>,
    /// 生成所有表模板
    #[arg(long)]
    pub all: bool,
    #[arg(long)]
    pub root: Option<String>,
}

pub fn run(args: Args) -> anyhow::Result<()> {
    let root = match args.root {
        Some(r) => PathBuf::from(r),
        None => std::env::current_dir()?,
    };
    let _transaction = ct_storage::workspace::WorkspaceTransaction::begin(&root)?;
    let workspace =
        ct_app::workspace::Workspace::open(&root).map_err(|e| anyhow::anyhow!("[error] {e}"))?;
    let messages = match ct_app::template::gen_template(&workspace, args.table.as_deref(), args.all)
    {
        Ok(messages) => messages,
        Err(error) => {
            // Python 行为：错误文本原样到 stderr，退出码 1（不加前缀）
            eprintln!("{}", error.0);
            std::process::exit(1);
        }
    };
    for message in messages {
        println!("{message}");
    }
    Ok(())
}

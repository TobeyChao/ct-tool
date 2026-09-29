//! `ct i18n`：翻译 sync / status / compact（文本与 Python CLI 逐字一致）。

use std::path::PathBuf;

use clap::Subcommand;
use serde_json::Value;

const BAR_WIDTH: usize = 10;

#[derive(Debug, Subcommand)]
pub enum Command {
    /// 从 Excel 同步译文骨架
    Sync {
        /// 只更新该语言的 lang 文件（source 仍全量刷新）
        #[arg(long)]
        lang: Option<String>,
        /// 只处理指定表
        #[arg(long)]
        table: Option<String>,
        /// 输出每个写入文件的路径与变更条目数
        #[arg(long)]
        verbose: bool,
        #[arg(long)]
        root: Option<String>,
    },
    /// 翻译进度概览
    Status {
        /// 只显示指定语言
        #[arg(long)]
        lang: Option<String>,
        /// 按表细分
        #[arg(long = "by-table")]
        by_table: bool,
        /// 输出 JSON
        #[arg(long = "json")]
        json_out: bool,
        #[arg(long)]
        root: Option<String>,
    },
    /// 清理 orphan 条目
    Compact {
        /// 只处理指定语言
        #[arg(long)]
        lang: Option<String>,
        /// 只处理指定表
        #[arg(long)]
        table: Option<String>,
        /// 仅打印将被删除的条目，不修改文件
        #[arg(long = "dry-run")]
        dry_run: bool,
        #[arg(long)]
        root: Option<String>,
    },
}

struct WorkspaceAccess {
    _transaction: Option<ct_storage::workspace::WorkspaceTransaction>,
    _read_lock: Option<ct_storage::lock::WorkspaceLock>,
}
fn workspace(
    root: Option<String>,
    write: bool,
) -> anyhow::Result<(ct_app::workspace::Workspace, WorkspaceAccess)> {
    let root = root.map(PathBuf::from).unwrap_or(std::env::current_dir()?);
    let access = if write {
        WorkspaceAccess {
            _transaction: Some(ct_storage::workspace::WorkspaceTransaction::begin(&root)?),
            _read_lock: None,
        }
    } else {
        let lock = ct_storage::lock::WorkspaceLock::acquire(&root)?;
        if let Some(note) = ct_app::workspace::recovery_needed(&root) {
            anyhow::bail!("[recovery-needed] {note}");
        }
        WorkspaceAccess {
            _transaction: None,
            _read_lock: Some(lock),
        }
    };
    let ws = ct_app::workspace::Workspace::open(&root).map_err(|e| anyhow::anyhow!("{e}"))?;
    Ok((ws, access))
}

/// 友好失败：不打堆栈，退出码 1（前缀按子命令）。
fn fail(prefix: &str, message: impl std::fmt::Display) -> ! {
    eprintln!("{prefix} {message}");
    std::process::exit(1)
}

fn progress_line(label: &str, counts: &Value) -> String {
    let total = counts["total"].as_u64().unwrap_or(0) as usize;
    let orphan = counts["orphan"].as_u64().unwrap_or(0) as usize;
    let active = total as i64 - orphan as i64;
    let progress = counts["progress"].as_f64().unwrap_or(0.0);
    let filled = (progress.clamp(0.0, 1.0) * BAR_WIDTH as f64).round() as usize;
    let bar = format!("{}{}", "█".repeat(filled), "░".repeat(BAR_WIDTH - filled));
    format!(
        "{label}  {}% [{bar}] {}/{} translated, {} missing, {} stale, {} orphan",
        (progress * 100.0).round(),
        counts["translated"].as_u64().unwrap_or(0),
        active,
        counts["missing"].as_u64().unwrap_or(0),
        counts["stale"].as_u64().unwrap_or(0),
        counts["orphan"].as_u64().unwrap_or(0),
    )
}

pub fn run(command: Command) -> anyhow::Result<()> {
    match command {
        Command::Sync {
            lang,
            table,
            verbose,
            root,
        } => {
            let (ws, _transaction) = workspace(root, true)?;
            let messages = ct_app::i18n::i18n_sync(&ws, table.as_deref(), lang.as_deref())
                .map_err(|e| anyhow::anyhow!(e.0))
                .unwrap_or_else(|e| fail("[i18n sync]", e));
            for message in messages {
                if verbose || !message.starts_with("  ") {
                    eprintln!("[i18n sync] {message}");
                }
            }
        }
        Command::Status {
            lang,
            by_table,
            json_out,
            root,
        } => {
            let (ws, _transaction) = workspace(root, false)?;
            let report = ct_app::i18n::i18n_status(&ws);
            if let Some(lang) = &lang {
                if !report.contains_key(lang) {
                    let mut langs: Vec<&String> = report.keys().collect();
                    langs.sort();
                    let available = if langs.is_empty() {
                        "无".to_string()
                    } else {
                        langs
                            .iter()
                            .map(|s| s.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    };
                    fail(
                        "[i18n status]",
                        format!("语言 '{lang}' 不在 secondary_langs 中（可用: {available}）"),
                    );
                }
            }
            let mut names: Vec<&String> = report.keys().collect();
            names.sort();
            let selected: Vec<&String> = names
                .into_iter()
                .filter(|name| lang.is_none() || lang.as_deref() == Some(name.as_str()))
                .collect();
            if json_out {
                let mut map = serde_json::Map::new();
                for name in &selected {
                    map.insert((*name).clone(), report[*name].clone());
                }
                println!(
                    "{}",
                    serde_json::to_string_pretty(&serde_json::json!({"langs": map})).unwrap()
                );
                return Ok(());
            }
            for name in selected {
                let counts = &report[name];
                println!("{}", progress_line(&format!("[{name}]"), counts));
                if by_table {
                    if let Some(tables) = counts["tables"].as_object() {
                        let mut table_names: Vec<&String> = tables.keys().collect();
                        table_names.sort();
                        for table_name in table_names {
                            println!(
                                "{}",
                                progress_line(&format!("  {table_name}"), &tables[table_name])
                            );
                        }
                    }
                }
            }
        }
        Command::Compact {
            lang,
            table,
            dry_run,
            root,
        } => {
            let (ws, _transaction) = workspace(root, true)?;
            let result =
                ct_app::i18n::i18n_compact(&ws, table.as_deref(), lang.as_deref(), dry_run)
                    .map_err(|e| anyhow::anyhow!(e.0))
                    .unwrap_or_else(|e| fail("[compact]", e));
            let verb = if dry_run { "将移除" } else { "移除" };
            if let Some(files) = result["files"].as_array() {
                for item in files {
                    let keys = item["removed_keys"].as_array().cloned().unwrap_or_default();
                    println!(
                        "[compact] {}/{}: {verb} {} 条 orphan",
                        item["lang"].as_str().unwrap_or_default(),
                        item["table"].as_str().unwrap_or_default(),
                        keys.len()
                    );
                    if dry_run {
                        let joined = keys
                            .iter()
                            .map(|k| k.as_str().unwrap_or_default())
                            .collect::<Vec<_>>()
                            .join("、");
                        println!("  {joined}");
                    }
                }
            }
            let total = result["total_removed"].as_u64().unwrap_or(0);
            if total == 0 {
                println!("[compact] 无 orphan 条目，无需操作");
            } else if dry_run {
                println!("[compact] 共 {total} 条 orphan 待移除（dry-run，未修改任何文件）");
            } else {
                println!("[compact] 共 {total} 条 orphan 已移除");
            }
        }
    }
    Ok(())
}

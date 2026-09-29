//! ct 命令行入口：薄壳，只做参数解析与输出；业务逻辑在 `ct-app`。

mod commands;
mod output;

use clap::Parser;

use crate::commands::Command;

#[derive(Parser)]
#[command(name = "ct", version, about = "ct 配表导出工具（原生内核）")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

fn main() {
    let cli = Cli::parse();
    if let Err(error) = commands::run(cli.command) {
        // 薄壳：错误文本原样到 stderr，退出码 1（Python CLI 同语义）
        eprintln!("{error}");
        std::process::exit(1);
    }
}

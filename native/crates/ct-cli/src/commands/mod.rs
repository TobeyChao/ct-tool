//! 子命令定义与分发。

pub mod deploy;
pub mod export;
pub mod gen_template;
pub mod i18n;
pub mod panel;
pub mod recover;
pub mod status;
pub mod validate;
pub mod worker;

use clap::Subcommand;

#[derive(Debug, Subcommand)]
pub enum Command {
    /// 增量导出（--all 强制重建）
    Export(export::Args),
    /// 只读校验
    Validate(validate::Args),
    /// 工作区状态概览
    Status(status::Args),
    /// 生成/迁移 Excel 模板
    GenTemplate(gen_template::Args),
    /// 翻译管理
    #[command(subcommand)]
    I18n(i18n::Command),
    /// 独立部署
    Deploy(deploy::Args),
    /// 显式恢复未完成的发布（返回新基线）
    Recover(recover::Args),
    /// 原生 Web 面板
    Panel(panel::Args),
    /// stdio worker（供 Flutter 工作台）
    Worker(worker::Args),
}

pub fn run(command: Command) -> anyhow::Result<()> {
    match command {
        Command::Export(args) => export::run(args),
        Command::Validate(args) => validate::run(args),
        Command::Status(args) => status::run(args),
        Command::GenTemplate(args) => gen_template::run(args),
        Command::I18n(cmd) => i18n::run(cmd),
        Command::Deploy(args) => deploy::run(args),
        Command::Recover(args) => recover::run(args),
        Command::Panel(args) => panel::run(args),
        Command::Worker(args) => worker::run(args),
    }
}

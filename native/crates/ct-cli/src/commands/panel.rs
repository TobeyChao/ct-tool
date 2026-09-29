//! 原生 Web 面板入口。
use clap::Args as ClapArgs;
#[derive(Debug, ClapArgs)]
pub struct Args {
    #[arg(long)]
    pub root: Option<String>,
    #[arg(long, default_value = "127.0.0.1")]
    pub host: String,
    #[arg(long, default_value_t = 8000)]
    pub port: u16,
    #[arg(long = "no-browser")]
    pub no_browser: bool,
    /// 开发时从此目录加载 Web 静态资源
    #[arg(long)]
    pub static_dir: Option<std::path::PathBuf>,
    /// Launcher closes stdin to request a safe cross-platform shutdown.
    #[arg(long, hide = true)]
    pub shutdown_on_stdin_eof: bool,
}
pub fn run(args: Args) -> anyhow::Result<()> {
    ct_web::run(ct_web::Options {
        root: args
            .root
            .map(Into::into)
            .unwrap_or(std::env::current_dir()?),
        host: args.host,
        port: args.port,
        open_browser: !args.no_browser,
        shutdown_on_stdin: args.shutdown_on_stdin_eof,
        static_dir: args.static_dir,
    })
    .map_err(|e| anyhow::anyhow!("无法启动面板：{e}"))
}

//! `ct worker`：stdio worker 入口（协议见 `docs/protocol/v1.md`）。

use clap::Args as ClapArgs;

#[derive(Debug, ClapArgs)]
pub struct Args {}

pub fn run(_args: Args) -> anyhow::Result<()> {
    ct_worker::runtime::run()
}

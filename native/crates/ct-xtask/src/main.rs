//! 自动化任务入口：`cargo run -p ct-xtask -- <cmd>`。
//!
//! 统一收口夹具生成、基准与打包，避免脚本散落（xtask 模式）。

mod accessor_fixtures;
mod bench;
mod dist;
mod fingerprint;
mod fixtures;
mod real_fixture;
mod samples;
mod shape;

use std::path::PathBuf;

use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "xtask")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// 生成 S/M/L 与真实形状（r/r-full）基准夹具（只写 target/，不触碰真实 gd）
    BenchFixtures {
        /// s / m / l / r / r-full，可重复；all 表示 s,m,l
        #[arg(long, value_delimiter = ',')]
        sizes: Vec<String>,
        /// 输出目录（默认 native/target/bench）
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// 冻结真实形状清单（一次性 provenance 步骤，需要两份外部留档）
    BenchShapeFreeze {
        /// ref_table_shapes.json（运行时表形状 dump）
        #[arg(long)]
        shapes: PathBuf,
        /// ExcelRecord.json（导表期类清单与字段语法）
        #[arg(long)]
        records: PathBuf,
        /// 输出路径（默认 native/fixtures/bench/shape-r.json）
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// 只读自检形状清单：计数、分层、档位构成与未建模维度登记
    BenchShapeCheck {
        /// 清单路径（默认 native/fixtures/bench/shape-r.json）
        #[arg(long)]
        manifest: Option<PathBuf>,
    },
    /// 运行原生性能留档回归（冷全量/热 CLI/热 worker/改单表/改译文）
    Bench {
        #[arg(long, default_value = "s")]
        size: String,
        /// 每个场景的正式样本数（另加一次预热）
        #[arg(long, default_value_t = 5)]
        runs: usize,
        #[arg(long)]
        rust: Option<PathBuf>,
        #[arg(long)]
        fixture_root: Option<PathBuf>,
        #[arg(long)]
        out: Option<PathBuf>,
        /// 原生回归判定基准（默认取本机留档 bench-<尺寸>-<平台>.json）
        #[arg(long)]
        against: Option<PathBuf>,
        /// 显式采集新基线（仅留档，不算回归通过）
        #[arg(long, conflicts_with = "against")]
        record_baseline: bool,
    },
    /// 用当前门槛常量重算既有基准报告的 verdict（不重跑测量、不改样本）
    BenchRecheck {
        /// 报告路径，可重复；默认拒收通配符，需显式列出
        #[arg(long)]
        report: Vec<PathBuf>,
    },
    /// 生成协议 golden samples
    ProtocolSamples,
    /// 独立读取 OOXML，与冻结 openpyxl 模板语义逐项比较
    TemplateCompare {
        workbook: PathBuf,
        expected: PathBuf,
    },
    /// 从冻结 OOXML 输入重建六个 Excel 读取夹具，不修改任何期望值
    CompatFixtures {
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// 用冻结标量输入生成 Binary/C#，先对照独立旧产物，不覆写参照
    AccessorFixtures {
        #[arg(long)]
        out: PathBuf,
        /// 显式源码包，避免重用构建缓存时误读另一 checkout 的参照
        #[arg(long)]
        root: Option<PathBuf>,
    },
    /// 构建平台独立运行时包并做无 Python 自检（任务 6.6）
    Dist {
        /// 额外目标三元组（可重复）；默认只构建本机目标
        #[arg(long)]
        target: Vec<String>,
        /// 输出目录（默认 native/dist）
        #[arg(long)]
        out: Option<PathBuf>,
        /// 跳过运行时自检（仅 CI 里已经单独跑过时使用）
        #[arg(long)]
        skip_check: bool,
    },
    /// 自检解压或 launcher 内置的原生二进制（隔离 PATH，CLI/worker/panel）
    RuntimeCheck {
        #[arg(long)]
        binary: PathBuf,
        #[arg(long)]
        out: PathBuf,
    },
    /// 固定/校验基线源码树指纹与测试清单（任务 1.1）
    Fingerprint {
        /// 只校验现有基线文件是否仍然一致
        #[arg(long)]
        check: bool,
        /// 显式源码 checkout（默认当前仓库，供无旧 ct/ 的独立验收）
        #[arg(long)]
        root: Option<PathBuf>,
        /// 输出路径（默认覆写仓库内的验收快照 `native/docs/baseline/source-tree.json`）
        #[arg(long)]
        out: Option<PathBuf>,
    },
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::BenchFixtures { sizes, out } => fixtures::generate(&sizes, out),
        Command::BenchShapeFreeze {
            shapes,
            records,
            out,
        } => shape::freeze(
            &shapes,
            &records,
            &out.unwrap_or_else(|| repo_root().join("native/fixtures/bench/shape-r.json")),
        ),
        Command::BenchShapeCheck { manifest } => shape::check(
            &manifest.unwrap_or_else(|| repo_root().join("native/fixtures/bench/shape-r.json")),
        ),
        Command::Bench {
            size,
            runs,
            rust,
            fixture_root,
            out,
            against,
            record_baseline,
        } => bench::run(bench::Options {
            size,
            runs,
            fixture_root: fixture_root.unwrap_or_else(|| repo_root().join("native/target/bench")),
            rust: rust.unwrap_or_else(|| {
                repo_root().join(if cfg!(windows) {
                    "native/target/release/ct.exe"
                } else {
                    "native/target/release/ct"
                })
            }),
            out,
            against,
            record_baseline,
        }),
        Command::BenchRecheck { report } => {
            if report.is_empty() {
                anyhow::bail!("bench-recheck 需要至少一个 --report <json>");
            }
            for path in &report {
                bench::recheck(path)?;
            }
            Ok(())
        }
        Command::ProtocolSamples => samples::generate(),
        Command::TemplateCompare { workbook, expected } => {
            ct_test_support::xlsx_semantics::compare(&workbook, &expected)?;
            println!("{}: 模板语义一致", workbook.display());
            Ok(())
        }
        Command::CompatFixtures { out } => {
            let root = repo_root().join("native/fixtures");
            let verified = ct_test_support::fixture_archive::verify_compat(&root)?;
            let out =
                out.unwrap_or_else(|| repo_root().join("native/target/compat-fixtures/excel"));
            let files =
                ct_test_support::fixture_archive::regenerate_excel(&root.join("excel"), &out)?;
            println!(
                "已校验 {verified} 份冻结输入/期望值，重建 {} 个 Excel 夹具：{}",
                files.len(),
                out.display()
            );
            Ok(())
        }
        Command::AccessorFixtures { out, root } => {
            accessor_fixtures::generate(&root.unwrap_or_else(repo_root), &out)
        }
        Command::Dist {
            target,
            out,
            skip_check,
        } => dist::run(&target, out, skip_check),
        Command::RuntimeCheck { binary, out } => dist::check_binary(&binary, &out),
        Command::Fingerprint { check, root, out } => fingerprint::run(check, root, out),
    }
}

/// 仓库根目录（xtask 位于 native/crates/ct-xtask）。
fn repo_root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

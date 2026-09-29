//! 基准夹具生成：固定种子，只写 target/（绝不触碰真实 gd/）。
//!
//! - s/m/l：复用仓库里的 Python 参照脚本 `native/fixtures/bench/generate.py`
//!   （它只是「造输入」，不是产品运行依赖）。
//! - r/r-full（真实形状档）：走 `crate::real_fixture` 的原生生成路径，
//!   只读冻结的 `native/fixtures/bench/shape-r.json`，不需要 `ct/` 在位。
//!
//! 测量与判定全部在 Rust 侧。

use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{bail, Context, Result};

const SIZES: &[&str] = &["s", "m", "l"];
/// 真实形状档：原生生成，与 s/m/l 的 Python 生成路径互不影响。
const REAL_SIZES: &[&str] = &["r", "r-full"];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn venv_python() -> Option<PathBuf> {
    [
        "ct/.venv/Scripts/python.exe",
        "ct/.venv/bin/python",
        "ct/.venv/bin/python3",
    ]
    .iter()
    .map(|candidate| repo_root().join(candidate))
    .find(|path| path.is_file())
}

pub fn generate(sizes: &[String], out: Option<PathBuf>) -> Result<()> {
    // 相对路径按仓库根解析，避免 cwd 不同把夹具写进 native/native/...
    let out_dir = match out {
        Some(path) if path.is_absolute() => path,
        Some(path) => repo_root().join(path),
        None => repo_root().join("native/target/bench"),
    };
    let all = sizes.is_empty() || sizes.iter().any(|size| size == "all");
    let wanted: Vec<&str> = if sizes.is_empty() {
        SIZES.to_vec()
    } else {
        sizes.iter().map(String::as_str).collect()
    };
    for size in &wanted {
        if !SIZES.contains(size) && !REAL_SIZES.contains(size) && *size != "all" {
            bail!(
                "未知尺寸 {size}（可选 {}、{}，或 all = s,m,l）",
                SIZES.join("/"),
                REAL_SIZES.join("/")
            );
        }
    }
    if all {
        return generate_python_sizes(SIZES, &out_dir);
    }
    let (real, python): (Vec<&str>, Vec<&str>) =
        wanted.iter().partition(|size| REAL_SIZES.contains(size));
    if !python.is_empty() {
        generate_python_sizes(&python, &out_dir)?;
    }
    if !real.is_empty() {
        crate::real_fixture::generate(
            &real.iter().map(|s| s.to_string()).collect::<Vec<_>>(),
            Some(out_dir.clone()),
        )?;
    }
    Ok(())
}

fn generate_python_sizes(sizes: &[&str], out_dir: &Path) -> Result<()> {
    std::fs::create_dir_all(out_dir)?;
    let python = venv_python()
        .context("找不到 ct/.venv 的 Python；夹具脚本只在隔离 venv 里运行，不做全局安装")?;
    let script = repo_root().join("native/fixtures/bench/generate.py");
    for size in sizes {
        let status = Command::new(&python)
            .args([
                &script.to_string_lossy(),
                "--size",
                size,
                "--out",
                &out_dir.to_string_lossy(),
            ])
            .current_dir(repo_root())
            .status()
            .with_context(|| format!("启动夹具生成器失败：{}", python.display()))?;
        if !status.success() {
            bail!("生成 {size} 尺寸夹具失败（退出码 {:?}）", status.code());
        }
        let marker = fixture_marker(out_dir, size);
        println!(
            "夹具 {size}：{}（{}）",
            marker.display(),
            std::fs::read_to_string(&marker)?.trim()
        );
    }
    Ok(())
}

fn fixture_marker(out_dir: &Path, size: &str) -> PathBuf {
    out_dir.join(format!("bench-{size}")).join("FIXTURE.json")
}

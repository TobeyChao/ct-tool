//! 性能基准（任务 1.2 / 6.5）：S/M/L 夹具上的四种场景配对测量。
//!
//! 只读夹具 + 写系统临时副本，绝不写真实 `gd/`；报告落盘到
//! `native/docs/baseline/bench-<尺寸>-<平台>.json`，含硬件、种子、原始样本、
//! 中位数/尾部、峰值 RSS、产物摘要与门槛比较。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use anyhow::{bail, Context, Result};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

pub struct Options {
    pub size: String,
    pub runs: usize,
    pub fixture_root: PathBuf,
    pub rust: PathBuf,
    pub python: Option<PathBuf>,
    pub out: Option<PathBuf>,
    /// 无 Python 参照时用于回归判定的本机留档报告（默认取
    /// `native/docs/baseline/bench-<尺寸>-<平台>.json`）。
    pub against: Option<PathBuf>,
    pub record_baseline: bool,
}

const SCENARIOS: &[&str] = &["cold", "hot-cli", "hot-worker", "table", "i18n"];

fn platform_tag() -> &'static str {
    if cfg!(windows) {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    }
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn measure_script() -> PathBuf {
    repo_root().join("native/tools/bench/measure.ps1")
}

/// Python 参照必须跑在真正的解释器进程里：venv 的 `ct.exe` 是控制台脚本存根，
/// 采样到的内存不是真实工作集，因此改走 `python.exe tools/bench/python-entry.py`。
fn python_engine(exe: &Path) -> (PathBuf, String) {
    let entry = repo_root().join("native/tools/bench/python-entry.py");
    let name = exe
        .file_name()
        .map(|text| text.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    let python = if name.starts_with("python") {
        Some(exe.to_path_buf())
    } else {
        let sibling = exe.with_file_name(if cfg!(windows) {
            "python.exe"
        } else {
            "python"
        });
        if sibling.is_file() {
            Some(sibling)
        } else {
            None
        }
    };
    match (python, entry.is_file()) {
        (Some(python), true) => (python, format!("{} ", entry.display())),
        _ => (exe.to_path_buf(), String::new()),
    }
}

fn fixture_dir(root: &Path, size: &str) -> PathBuf {
    root.join(format!("bench-{size}"))
}

fn copy_tree(src: &Path, dst: &Path) -> Result<()> {
    std::fs::create_dir_all(dst).with_context(|| format!("创建 {}", dst.display()))?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

fn git_lines(args: &[&str]) -> Vec<String> {
    Command::new("git")
        .args(args)
        .current_dir(repo_root())
        .output()
        .ok()
        .filter(|out| out.status.success())
        .map(|out| {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn command_version(exe: &Path) -> String {
    Command::new(exe)
        .arg("--version")
        .output()
        .map(|out| {
            let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if text.is_empty() {
                "unknown".to_string()
            } else {
                text
            }
        })
        .unwrap_or_else(|_| "unknown".to_string())
}

/// `output/**` 的产物数量与聚合摘要（键统一小写，忽略 Windows 大小写归一差异）。
fn output_digest(root: &Path) -> (usize, String) {
    let base = root.join("output");
    let mut files: BTreeMap<String, String> = BTreeMap::new();
    let mut stack = vec![base.clone()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path.clone());
                continue;
            }
            let relative = path
                .strip_prefix(&base)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/")
                .to_ascii_lowercase();
            let mut hasher = Sha256::new();
            if let Ok(bytes) = std::fs::read(&path) {
                hasher.update(&bytes);
            }
            files.insert(relative, format!("{:x}", hasher.finalize()));
        }
    }
    let mut aggregate = Sha256::new();
    for (name, hash) in &files {
        aggregate.update(format!("{name}\t{hash}\n").as_bytes());
    }
    (files.len(), format!("{:x}", aggregate.finalize()))
}

fn powershell_available() -> bool {
    for program in ["powershell", "pwsh"] {
        if Command::new(program)
            .arg("-NoProfile")
            .arg("-Version")
            .arg("2")
            .output()
            .is_ok_and(|out| out.status.success())
        {
            return true;
        }
    }
    false
}

fn powershell_program() -> &'static str {
    if Command::new("powershell")
        .arg("-NoProfile")
        .arg("-Version")
        .arg("2")
        .output()
        .is_ok_and(|out| out.status.success())
    {
        "powershell"
    } else {
        "pwsh"
    }
}

#[cfg(unix)]
fn tree_rss_kb(ps_output: &str, root_pid: u32) -> (u64, u64) {
    let processes: Vec<(u32, u32, u64)> = ps_output
        .lines()
        .filter_map(|line| {
            let mut columns = line.split_whitespace();
            Some((
                columns.next()?.parse().ok()?,
                columns.next()?.parse().ok()?,
                columns.next()?.parse().ok()?,
            ))
        })
        .collect();
    let own = processes
        .iter()
        .find(|(pid, _, _)| *pid == root_pid)
        .map_or(0, |(_, _, rss)| *rss);
    let mut seen = std::collections::BTreeSet::from([root_pid]);
    loop {
        let old_len = seen.len();
        for (pid, parent, _) in &processes {
            if seen.contains(parent) {
                seen.insert(*pid);
            }
        }
        if seen.len() == old_len {
            break;
        }
    }
    let total = processes
        .iter()
        .filter(|(pid, _, _)| seen.contains(pid))
        .map(|(_, _, rss)| *rss)
        .sum();
    (own, total)
}

/// Windows 使用 measure.ps1；POSIX 按进程树轮询 RSS，且两边都向 worker 传入 stdin。
fn measure(
    exe: &Path,
    args: &str,
    workspace: &Path,
    stdin_file: Option<&Path>,
    use_powershell: bool,
) -> Result<Value> {
    let started = std::time::Instant::now();
    if use_powershell {
        let mut command = Command::new(powershell_program());
        command
            .args([
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                &measure_script().to_string_lossy(),
                "-Exe",
                &exe.to_string_lossy(),
                "-ExeArgs",
                args,
                "-Workspace",
                &workspace.to_string_lossy(),
            ])
            .current_dir(repo_root());
        if let Some(stdin) = stdin_file {
            command.arg("-StdinFile").arg(stdin);
        }
        let output = command.output().context("启动测量脚本失败")?;
        let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let value: Value = serde_json::from_str(&text).with_context(|| {
            format!(
                "测量脚本输出不是 JSON：{text} / {}",
                String::from_utf8_lossy(&output.stderr)
            )
        })?;
        if value["exit"].as_i64() != Some(0) {
            bail!("被测命令退出码非 0：{value}");
        }
        return Ok(value);
    }
    let stdout = tempfile::NamedTempFile::new().context("创建测量 stdout 暂存失败")?;
    let stderr = tempfile::NamedTempFile::new().context("创建测量 stderr 暂存失败")?;
    let mut command = Command::new(exe);
    command
        .args(args.split_whitespace())
        .current_dir(workspace)
        .stdout(Stdio::from(stdout.reopen()?))
        .stderr(Stdio::from(stderr.reopen()?));
    if let Some(path) = stdin_file {
        command.stdin(Stdio::from(std::fs::File::open(path)?));
    }
    let mut child = command.spawn().context("启动被测命令失败")?;
    #[cfg(unix)]
    let (mut peak_rss_kb, mut peak_tree_rss_kb) = (0, 0);
    loop {
        #[cfg(unix)]
        {
            let output = Command::new("ps")
                .args(["-axo", "pid=,ppid=,rss="])
                .output()?;
            if !output.status.success() {
                let _ = child.kill();
                let _ = child.wait();
                bail!("ps 采样失败：{}", String::from_utf8_lossy(&output.stderr));
            }
            let (own, tree) = tree_rss_kb(&String::from_utf8_lossy(&output.stdout), child.id());
            peak_rss_kb = peak_rss_kb.max(own);
            peak_tree_rss_kb = peak_tree_rss_kb.max(tree);
        }
        if let Some(status) = child.try_wait()? {
            let stderr_text = std::fs::read_to_string(stderr.path())?;
            if !status.success() {
                bail!("被测命令失败（{status}）：{}", stderr_text.trim());
            }
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    #[cfg(unix)]
    if peak_rss_kb == 0 || peak_tree_rss_kb == 0 {
        bail!("未采到被测进程 RSS，不能据此判定内存门槛");
    }
    #[cfg(unix)]
    let (peak_rss_value, peak_tree_rss_value) = (json!(peak_rss_kb), json!(peak_tree_rss_kb));
    #[cfg(not(unix))]
    let (peak_rss_value, peak_tree_rss_value) = (Value::Null, Value::Null);
    Ok(json!({
        "wallMs": started.elapsed().as_millis(),
        "peakRssKb": peak_rss_value,
        "peakTreeRssKb": peak_tree_rss_value,
        "exit": 0,
    }))
}

fn worker_script(workspace: &Path, path: &Path) -> Result<()> {
    let root = workspace.to_string_lossy().replace('\\', "\\\\");
    let text = format!(
        "{{\"type\":\"hello\",\"protocolVersion\":1,\"coreVersion\":\"bench\",\"capabilities\":[\"workspace\",\"export\",\"shutdown\"]}}\n\
         {{\"type\":\"request\",\"requestId\":1,\"method\":\"workspace.open\",\"workspaceRoot\":\"{root}\",\"params\":{{}}}}\n\
         {{\"type\":\"request\",\"requestId\":2,\"method\":\"export\",\"workspaceRoot\":\"{root}\",\"params\":{{\"all\":false}}}}\n\
         {{\"type\":\"request\",\"requestId\":3,\"method\":\"shutdown\",\"workspaceRoot\":\"{root}\",\"params\":{{}}}}\n"
    );
    std::fs::write(path, text)?;
    Ok(())
}

fn stats(values: &[Value], field: &str) -> Value {
    let mut numbers: Vec<f64> = values
        .iter()
        .filter_map(|value| value[field].as_f64())
        .collect();
    if numbers.is_empty() {
        return Value::Null;
    }
    numbers.sort_by(|a, b| a.partial_cmp(b).expect("有限浮点"));
    let middle = numbers[numbers.len() / 2];
    json!({
        "median": middle,
        "min": numbers.first().copied(),
        "max": numbers.last().copied(),
        "samples": numbers,
    })
}

/// 一个引擎在一种场景下的测量上下文（避免十几个散参数）。
struct Runner<'a> {
    engine: &'a str,
    prefix: String,
    exe: &'a Path,
    pristine: &'a Path,
    warm: &'a Path,
    fixture: &'a Path,
    mutation: &'a Value,
    runs: usize,
    use_powershell: bool,
    scratch: &'a Path,
}

impl Runner<'_> {
    /// 预热一次，再取 runs 个正式样本（design.md：每场景至少五次测量）。
    fn scenario(&self, scenario: &str) -> Result<Value> {
        let (engine, exe, pristine, warm, fixture, mutation, runs, use_powershell, scratch) = (
            self.engine,
            self.exe,
            self.pristine,
            self.warm,
            self.fixture,
            self.mutation,
            self.runs,
            self.use_powershell,
            self.scratch,
        );
        let workspace = scratch.join(format!("{engine}-{scenario}"));
        let _ = std::fs::remove_dir_all(&workspace);
        let base = if scenario == "cold" { pristine } else { warm };
        copy_tree(base, &workspace)?;
        let args = format!("{}export", self.prefix);
        let mut samples = Vec::new();
        let mut digest = String::new();
        let mut artifact_count = 0usize;
        let stdin_path = scratch.join(format!("{engine}-{scenario}.ndjson"));
        for index in 0..=runs {
            // 第 0 次是预热，之后才是正式样本（design.md：预热一次再至少五次测量）
            let _ = std::fs::remove_dir_all(&workspace);
            copy_tree(base, &workspace)?;
            let mut stdin_file = None;
            let effective_args = match scenario {
                "hot-worker" => {
                    worker_script(&workspace, &stdin_path)?;
                    stdin_file = Some(stdin_path.as_path());
                    "worker".to_string()
                }
                "table" => {
                    let target = mutation["tableSource"]
                        .as_str()
                        .context("mutations.json 缺少 tableSource")?;
                    std::fs::copy(
                        fixture
                            .join("mutations")
                            .join(target.split('/').next_back().unwrap_or_default()),
                        workspace.join(target),
                    )?;
                    args.clone()
                }
                "i18n" => {
                    let target = mutation["i18nTarget"]
                        .as_str()
                        .context("mutations.json 缺少 i18nTarget")?;
                    let name = target.split('/').next_back().unwrap_or_default();
                    std::fs::copy(fixture.join("mutations").join(name), workspace.join(target))?;
                    args.clone()
                }
                _ => args.clone(),
            };
            let sample = measure(exe, &effective_args, &workspace, stdin_file, use_powershell)?;
            if index == 0 {
                let (count, hash) = output_digest(&workspace);
                artifact_count = count;
                digest = hash;
                continue;
            }
            samples.push(sample);
        }
        Ok(json!({
            "engine": engine,
            "scenario": scenario,
            "runs": samples.len(),
            "artifacts": artifact_count,
            "outputSha256": digest,
            "wallMs": stats(&samples, "wallMs"),
            "peakRssKb": stats(&samples, "peakRssKb"),
            "peakTreeRssKb": stats(&samples, "peakTreeRssKb"),
        }))
    }
}

pub fn run(options: Options) -> Result<()> {
    let fixture_root = options.fixture_root.clone();
    let fixture = fixture_dir(&fixture_root, &options.size);
    if !fixture.join("FIXTURE.json").is_file() {
        let hint = format!(
            "cargo run -p ct-xtask -- bench-fixtures --sizes {} --out {}",
            options.size,
            fixture_root.display()
        );
        bail!("缺少 {} 夹具（先运行 {hint}）", fixture.display());
    }
    if !options.rust.is_file() {
        bail!(
            "缺少原生二进制 {}（先 cargo build --release -p ct-cli）",
            options.rust.display()
        );
    }
    let meta: Value =
        serde_json::from_str(&std::fs::read_to_string(fixture.join("FIXTURE.json"))?)?;
    let expected_digest = meta["inputDigest"]
        .as_str()
        .context("夹具缺少 inputDigest；先用原生 bench-fixtures 重新生成")?;
    let actual_digest = crate::real_fixture::input_digest(&fixture)?;
    if actual_digest != expected_digest {
        bail!("夹具输入摘要不匹配（记录 {expected_digest}，实际 {actual_digest}）；请重新生成");
    }
    let mutation: Value = serde_json::from_str(&std::fs::read_to_string(
        fixture.join("mutations/mutations.json"),
    )?)?;
    let pristine = fixture.clone();
    let scratch =
        std::env::temp_dir().join(format!("ct-bench-{}-{}", options.size, std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch)?;
    let use_powershell = powershell_available();
    let gd_before = git_lines(&["status", "--porcelain", "gd"]);

    let mut engines: Vec<(&'static str, PathBuf, String)> =
        vec![("rust", options.rust.clone(), String::new())];
    if let Some(python) = options.python.clone() {
        if python.is_file() {
            let (exe, prefix) = python_engine(&python);
            engines.push(("python", exe, prefix));
        } else {
            bail!("显式 Python 参照入口不存在：{}", python.display());
        }
    }
    // 参照实现不在位时，不谎称「无法判定」：改用本机留档做回归判定。
    let reference_path = options.against.clone().unwrap_or_else(|| {
        let suffix = if ["s", "m", "l"].contains(&options.size.as_str()) {
            "-native"
        } else {
            ""
        };
        repo_root().join(format!(
            "native/docs/baseline/bench-{}-{}{suffix}.json",
            options.size,
            platform_tag()
        ))
    });
    let reference = if engines.len() > 1 || options.record_baseline {
        None // 配对或显式记录新基线；记录本身不宣称回归通过
    } else {
        Some(
            load_reference(&reference_path, meta["inputDigest"].as_str(), &options.size).context(
                "原生基准留档不可用；回归不能跳过，首次采集请显式使用 --record-baseline",
            )?,
        )
    };

    let mut results = Vec::new();
    for (name, exe, prefix) in &engines {
        let warm = scratch.join(format!("warm-{name}"));
        let _ = std::fs::remove_dir_all(&warm);
        copy_tree(&pristine, &warm)?;
        // 建立「成功状态」快照：一次不计时的导出（缓存、账本、产物齐备）
        measure(exe, &format!("{prefix}export"), &warm, None, use_powershell)?;
        for scenario in SCENARIOS {
            if *scenario == "hot-worker" && *name != "rust" {
                // Python 参照没有 worker 入口，只记录原生侧
                continue;
            }
            let runner = Runner {
                engine: name,
                exe,
                pristine: &pristine,
                warm: &warm,
                fixture: &fixture,
                mutation: &mutation,
                runs: options.runs,
                use_powershell,
                prefix: prefix.clone(),
                scratch: &scratch,
            };
            results.push(runner.scenario(scenario)?);
        }
    }
    let gd_after = git_lines(&["status", "--porcelain", "gd"]);

    let thresholds = judge(&options.size, &results, reference.as_ref());

    let report = json!({
        "schema": "ct-bench/1",
        "size": options.size,
        "seed": meta["seed"],
        "fixture": meta,
        "host": {
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
            "family": platform_tag(),
            "logicalCores": std::thread::available_parallelism()
                .ok()
                .map(|count| count.get()),
            "measuredWithPowershell": use_powershell,
            "rssMethod": if use_powershell { "Process.PeakWorkingSet64" } else if cfg!(unix) { "ps process-tree RSS polling" } else { "unavailable" },
        },
        "git": {
            "commit": git_lines(&["rev-parse", "HEAD"])
                .into_iter()
                .next()
                .unwrap_or_default(),
            "dirtyPaths": git_lines(&["status", "--porcelain"]).len(),
        },
        "engines": {
            "rust": { "path": options.rust, "version": command_version(&engines[0].1), "argv": "export" },
            "python": engines
                .iter()
                .find(|(name, _, _)| *name == "python")
                .map(|(_, path, prefix)| json!({
                    "path": path,
                    "version": command_version(path),
                    "argv": format!("{prefix}export"),
                }))
        },
        "warmupRuns": 1,
        "measuredRuns": options.runs,
        "realWorkspaceUntouched": {
            "gdDirtyBefore": gd_before.len(),
            "gdDirtyAfter": gd_after.len(),
            "unchanged": gd_before == gd_after,
        },
        "results": results,
        "thresholds": thresholds,
    });
    let out = options.out.unwrap_or_else(|| {
        repo_root().join(format!(
            "native/target/bench-results/bench-{}-{}.json",
            options.size,
            report["host"]["family"].as_str().unwrap_or("unknown")
        ))
    });
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&out, serde_json::to_string_pretty(&report)? + "\n")?;
    let _ = std::fs::remove_dir_all(&scratch);
    println!("{}", serde_json::to_string_pretty(&report["thresholds"])?);
    println!("基准报告已写入 {}", out.display());
    if report["thresholds"]
        .as_object()
        .unwrap()
        .values()
        .any(|row| matches!(row["verdict"].as_str(), Some("fail" | "regression-fail")))
    {
        bail!("基准未通过，原始报告已保留");
    }
    Ok(())
}

/// 时间上限：随夹具档位给定（2026-09-19 显式修订口径，见 design.md 与本文件注释）。
/// S 档回退用 `max(基线10%, 50ms)` 表达，倍率上限取 1.1 作硬约束。
fn time_limit(size: &str, scenario: &str) -> Option<f64> {
    let big = matches!(size, "m" | "l");
    match scenario {
        "cold" if big => Some(0.5),
        "hot-cli" | "table" | "i18n" if big => Some(0.35),
        "cold" | "hot-cli" | "table" | "i18n" => Some(1.1),
        _ => None,
    }
}

/// 峰值 RSS 判定参数：`(比值上限, 绝对上限 KiB)`。
///
/// 绝对上限 SHALL 随档位给定：1.25GiB 是按 M 档实测（682–926MiB）定的，L 档是 10 倍数据量
/// （实测 Rust 峰值 5.6–7.0GiB、Python 2.9–3.8GiB、比值仅 1.85–1.94），共用常量会把
/// 「常量不随数据量缩放」的口径缺陷误判成实现退步。2026-09-19 采纳显式修订：L 档 7.5GiB。
fn rss_limits(size: &str) -> (f64, Option<f64>) {
    let ratio_limit = if size == "s" { 1.2_f64 } else { 2.5_f64 };
    let abs_limit_kb = match size {
        "m" => Some(1.25 * 1024.0 * 1024.0),
        "l" => Some(7.5 * 1024.0 * 1024.0),
        _ => None,
    };
    (ratio_limit, abs_limit_kb)
}

fn median_wall(rows: &[serde_json::Value], engine: &str, scenario: &str) -> Option<f64> {
    rows.iter()
        .find(|row| {
            row["engine"].as_str() == Some(engine) && row["scenario"].as_str() == Some(scenario)
        })
        .and_then(|row| row["wallMs"]["median"].as_f64())
}

/// 树峰值优先：venv 的 `ct.exe` 是控制台脚本存根，单进程 RSS 会低估 Python 真实驻留。
fn median_rss(rows: &[serde_json::Value], engine: &str, scenario: &str) -> Option<f64> {
    rows.iter()
        .find(|row| {
            row["engine"].as_str() == Some(engine) && row["scenario"].as_str() == Some(scenario)
        })
        .and_then(|row| {
            row["peakTreeRssKb"]["median"]
                .as_f64()
                .or_else(|| row["peakRssKb"]["median"].as_f64())
        })
}

/// 门槛判定：只读测量结果，不产生任何新数据；测量与判定共用同一函数，
/// 因此「重算 verdict」不需要重跑几小时的配对测量。
pub fn judge(
    size: &str,
    rows: &[serde_json::Value],
    reference: Option<&Map<String, Value>>,
) -> Map<String, Value> {
    let (rss_limit, rss_abs_limit_kb) = rss_limits(size);
    let mut thresholds = Map::new();
    for scenario in SCENARIOS {
        let ratio = match (
            median_wall(rows, "rust", scenario),
            median_wall(rows, "python", scenario),
        ) {
            (Some(rust), Some(python)) if python > 0.0 => Some(rust / python),
            _ => None,
        };
        let rss = match (
            median_rss(rows, "rust", scenario),
            median_rss(rows, "python", scenario),
        ) {
            (Some(rust), Some(python)) if python > 0.0 => Some(rust / python),
            _ => None,
        };
        let limit = time_limit(size, scenario);
        // 时间与峰值内存任一超标即 fail：不得只报好看的那一项。
        let over_peak = median_rss(rows, "rust", scenario)
            .is_some_and(|kb| rss_abs_limit_kb.is_some_and(|cap| kb > cap));
        let (verdict, mode) = match (ratio, rss) {
            (Some(time), Some(memory)) => {
                let over_time = limit.is_some_and(|cap| time > cap);
                let over_ratio = memory > rss_limit || over_peak;
                (
                    if over_time || over_ratio {
                        "fail"
                    } else {
                        "pass"
                    },
                    "paired",
                )
            }
            // 无同机参照实现：只做「比本机上一次留档慢多少」的回归判定，
            // 外加产物摘要一致与绝对峰值上限；不得记成配对测量。
            (None, _) => match regression_against_reference(rows, reference, scenario, over_peak) {
                Some((ok, artifacts_match)) => {
                    let pass = ok && artifacts_match.unwrap_or(true);
                    (
                        if pass {
                            "regression-pass"
                        } else {
                            "regression-fail"
                        },
                        "archived-run",
                    )
                }
                None => (if over_peak { "fail" } else { "no-baseline" }, "none"),
            },
            (Some(_), None) => ("recorded", "paired"),
        };
        thresholds.insert(
            (*scenario).to_string(),
            json!({
                "medianRatio": ratio,
                "limit": limit,
                "peakRssRatio": rss,
                "peakRssLimit": rss_limit,
                "peakRssAbsLimitKb": rss_abs_limit_kb,
                "verdict": verdict,
                "baselineMode": mode,
                "allowedSlowdown": allowed_slowdown(),
            }),
        );
    }
    thresholds
}

/// 回归判定容差：同一台机器、同一份夹具下，允许的中位耗时上浮比例。
fn allowed_slowdown() -> f64 {
    1.25
}

/// 读留档报告，得到每个场景的 Rust 中位耗时/产物摘要（不读 Python 数字：跨机器不可比）。
fn load_reference(
    path: &Path,
    current_digest: Option<&str>,
    size: &str,
) -> Result<Map<String, Value>> {
    let text = std::fs::read_to_string(path)
        .with_context(|| format!("留档报告不可读：{}", path.display()))?;
    let value: Value = serde_json::from_str(&text).context("留档报告不是合法 JSON")?;
    if value["schema"] != "ct-bench/1"
        || value["size"] != size
        || value["host"]["os"] != std::env::consts::OS
        || value["host"]["arch"] != std::env::consts::ARCH
    {
        bail!("留档格式、档位或平台与当前回归环境不匹配");
    }
    let saved_digest = value["fixture"]["inputDigest"].as_str();
    if saved_digest.is_none() || saved_digest != current_digest {
        bail!(
            "留档夹具摘要与当前夹具不一致（留档 {:?}，当前 {:?}）；需重新测量同一生成器夹具",
            saved_digest,
            current_digest
        );
    }
    let rows = value["results"]
        .as_array()
        .context("留档报告缺少 results 数组")?
        .clone();
    let mut map = Map::new();
    for row in rows
        .iter()
        .filter(|row| row["engine"].as_str() == Some("rust"))
    {
        let scenario = row["scenario"].as_str().context("留档场景名称缺失")?;
        if !SCENARIOS.contains(&scenario)
            || map.contains_key(scenario)
            || !row["wallMs"]["median"]
                .as_f64()
                .is_some_and(|n| n.is_finite() && n > 0.0)
            || !row["outputSha256"]
                .as_str()
                .is_some_and(ct_test_support::reference_inventory::valid_sha256)
        {
            bail!("留档场景重复、未知或样本/产物摘要损坏：{scenario}");
        }
        map.insert(
            scenario.to_string(),
            json!({
                "wallMs": row["wallMs"]["median"],
                "outputSha256": row["outputSha256"],
            }),
        );
    }
    if map.len() != SCENARIOS.len() {
        bail!("留档必须包含全部五个原生场景：{}", path.display());
    }
    Ok(map)
}

/// 与留档比较：耗时不得显著变慢，产物摘要必须不变。返回 `(两项都成立?, 摘要是否一致)`。
fn regression_against_reference(
    rows: &[serde_json::Value],
    reference: Option<&Map<String, Value>>,
    scenario: &str,
    over_peak: bool,
) -> Option<(bool, Option<bool>)> {
    let reference = reference?;
    let saved = reference.get(scenario)?;
    let previous = saved["wallMs"].as_f64()?;
    let now = median_wall(rows, "rust", scenario)?;
    if previous <= 0.0 {
        return None;
    }
    let not_slower = now <= previous * allowed_slowdown();
    let artifacts_match = match (
        saved["outputSha256"].as_str(),
        rows.iter().find(|row| {
            row["engine"].as_str() == Some("rust") && row["scenario"].as_str() == Some(scenario)
        }),
    ) {
        (Some(wanted), Some(row)) => Some(row["outputSha256"].as_str() == Some(wanted)),
        _ => None,
    };
    Some((not_slower && !over_peak, artifacts_match))
}

/// 用当前门槛常量重算既有报告的 `thresholds`（原地写回，样本一字不改）。
pub fn recheck(report: &Path) -> Result<()> {
    let text = std::fs::read_to_string(report)
        .with_context(|| format!("读取基准报告失败：{}", report.display()))?;
    let mut value: Value = serde_json::from_str(&text)
        .with_context(|| format!("基准报告不是合法 JSON：{}", report.display()))?;
    let size = value["size"]
        .as_str()
        .context("报告缺少 size 字段")?
        .to_string();
    let rows = value["results"]
        .as_array()
        .context("报告缺少 results 数组")?
        .clone();
    // 重算只按报告内已有数据判定：不引入外部参照，避免把回归判定伪装成配对测量。
    let recomputed = Value::Object(judge(&size, &rows, None));
    let previous = value["thresholds"].clone();
    value["thresholds"] = recomputed.clone();
    std::fs::write(report, serde_json::to_string_pretty(&value)? + "\n")?;
    println!("重算门槛判定：{}（size={size}）", report.display());
    for scenario in SCENARIOS {
        let old = previous[*scenario]["verdict"]
            .as_str()
            .unwrap_or("-")
            .to_string();
        let now = recomputed[*scenario]["verdict"]
            .as_str()
            .unwrap_or("-")
            .to_string();
        let ratio = recomputed[*scenario]["peakRssRatio"]
            .as_f64()
            .map(|v| format!("{v:.3}"))
            .unwrap_or_else(|| "-".to_string());
        let abs = recomputed[*scenario]["peakRssAbsLimitKb"]
            .as_f64()
            .map(|v| format!("{:.2}GiB", v / 1024.0 / 1024.0))
            .unwrap_or_else(|| "无".to_string());
        let mark = if old == now { " " } else { "*" };
        println!("  {mark} {scenario:<11} {old:>11} -> {now:<11} RSS比 {ratio} 绝对上限 {abs}");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{judge, load_reference, rss_limits, time_limit, SCENARIOS};
    use serde_json::json;

    #[cfg(unix)]
    #[test]
    fn posix_rss_includes_nested_child_processes() {
        let sample = " 1 0 100\n 2 1 200\n 3 2 300\n 4 9 400\n";
        assert_eq!(super::tree_rss_kb(sample, 1), (100, 600));
    }

    #[cfg(unix)]
    #[test]
    fn posix_measure_feeds_worker_input_and_records_memory() {
        use std::os::unix::fs::PermissionsExt;

        let dir = tempfile::tempdir().unwrap();
        let script = dir.path().join("worker.sh");
        let input = dir.path().join("worker.ndjson");
        std::fs::write(&script, "#!/bin/sh\ncat > received.ndjson\nsleep 0.2\n").unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::fs::write(&input, "{\"type\":\"hello\"}\n").unwrap();

        let sample = super::measure(&script, "", dir.path(), Some(&input), false).unwrap();
        assert_eq!(
            std::fs::read_to_string(dir.path().join("received.ndjson")).unwrap(),
            "{\"type\":\"hello\"}\n"
        );
        assert!(sample["peakRssKb"].as_u64().unwrap() > 0);
        assert!(sample["peakTreeRssKb"].as_u64().unwrap() >= sample["peakRssKb"].as_u64().unwrap());
    }

    fn row(engine: &str, scenario: &str, wall: f64, tree_rss_kb: f64) -> serde_json::Value {
        json!({
            "engine": engine,
            "scenario": scenario,
            "wallMs": { "median": wall },
            "peakRssKb": { "median": tree_rss_kb },
            "peakTreeRssKb": { "median": tree_rss_kb }
        })
    }

    #[test]
    fn absolute_memory_limits_are_size_banded() {
        // 绝对上限必须随档位给：共用 1.25GiB 会在 L 档（10 倍数据）误判。
        assert_eq!(rss_limits("s"), (1.2, None));
        assert_eq!(rss_limits("m"), (2.5, Some(1.25 * 1024.0 * 1024.0)));
        assert_eq!(rss_limits("l"), (2.5, Some(7.5 * 1024.0 * 1024.0)));
    }

    #[test]
    fn time_limits_unchanged_by_the_memory_revision() {
        assert_eq!(time_limit("l", "cold"), Some(0.5));
        assert_eq!(time_limit("l", "table"), Some(0.35));
        assert_eq!(time_limit("s", "cold"), Some(1.1));
        assert_eq!(time_limit("m", "hot-worker"), None);
    }

    #[test]
    fn measured_l_numbers_pass_revised_caps() {
        // 取自 bench-l-windows.json 的实测中位数：RSS 比 1.85–1.94、绝对峰值 5.6–7.0GiB。
        let rows = vec![
            row("rust", "cold", 101303.0, 7_015.0 * 1024.0),
            row("python", "cold", 306192.0, 3_797.0 * 1024.0),
        ];
        let t = judge("l", &rows, None);
        assert_eq!(t["cold"]["verdict"], "pass", "{t:?}");
        // 同一份样本按旧的 M 档常量（1.25GiB）判定必然 fail —— 这正是修订的原因。
        let as_m = judge("m", &rows, None);
        assert_eq!(as_m["cold"]["verdict"], "fail", "{as_m:?}");
    }

    #[test]
    fn over_band_peak_still_fails() {
        let rows = vec![
            row("rust", "table", 100.0, 9_000.0 * 1024.0),
            row("python", "table", 300.0, 3_000.0 * 1024.0),
        ];
        let t = judge("l", &rows, None);
        assert_eq!(
            t["table"]["verdict"], "fail",
            "L 档超 7.5GiB 仍须 fail：{t:?}"
        );
    }

    #[test]
    fn missing_python_baseline_is_recorded_not_passing() {
        let rows = vec![row("rust", "hot-worker", 100.0, 1000.0)];
        let t = judge("l", &rows, None);
        assert_eq!(t["hot-worker"]["verdict"], "no-baseline");
        assert_eq!(SCENARIOS.len(), 5);
    }

    #[test]
    fn archived_regression_requires_the_same_fixture_digest() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("reference.json");
        let report = json!({
            "schema": "ct-bench/1", "size": "s",
            "host": {"os": std::env::consts::OS, "arch": std::env::consts::ARCH},
            "fixture": {"inputDigest": "sha256:new-fixture"},
            "results": SCENARIOS.iter().map(|scenario| json!({
                "engine": "rust", "scenario": scenario,
                "wallMs": {"median": 100.0}, "outputSha256": "a".repeat(64)
            })).collect::<Vec<_>>()
        });
        std::fs::write(&path, serde_json::to_vec(&report).unwrap()).unwrap();
        assert!(load_reference(&path, Some("sha256:new-fixture"), "s").is_ok());
        assert!(load_reference(&path, Some("sha256:old-fixture"), "s").is_err());
        assert!(load_reference(&path, None, "s").is_err());
        assert!(load_reference(&path, Some("sha256:new-fixture"), "m").is_err());
        for field in ["scenario", "wallMs", "outputSha256"] {
            let mut broken = report.clone();
            broken["results"][0][field] = serde_json::Value::Null;
            std::fs::write(&path, serde_json::to_vec(&broken).unwrap()).unwrap();
            assert!(
                load_reference(&path, Some("sha256:new-fixture"), "s").is_err(),
                "{field}"
            );
        }
        let mut missing = report.clone();
        missing["results"].as_array_mut().unwrap().pop();
        std::fs::write(&path, serde_json::to_vec(&missing).unwrap()).unwrap();
        assert!(load_reference(&path, Some("sha256:new-fixture"), "s").is_err());
    }

    fn reference(wall: f64, sha: &str) -> serde_json::Map<String, serde_json::Value> {
        let mut map = serde_json::Map::new();
        map.insert(
            "table".to_string(),
            json!({ "wallMs": wall, "outputSha256": sha }),
        );
        map
    }

    #[test]
    fn regression_verdict_needs_no_python() {
        // 只有 rust 侧样本 + 本机留档：必须给出回归判定，而不是 no-baseline。
        let rows = vec![json!({
            "engine": "rust",
            "scenario": "table",
            "wallMs": { "median": 100.0 },
            "peakTreeRssKb": { "median": 1_000.0 },
            "outputSha256": "sha-a",
        })];
        let t = judge("l", &rows, Some(&reference(110.0, "sha-a")));
        assert_eq!(t["table"]["verdict"], "regression-pass", "{t:?}");
        assert_eq!(t["table"]["baselineMode"], "archived-run");
    }

    #[test]
    fn regression_fails_on_slowdown_or_changed_artifacts() {
        let rows = vec![json!({
            "engine": "rust",
            "scenario": "table",
            "wallMs": { "median": 200.0 },
            "peakTreeRssKb": { "median": 1_000.0 },
            "outputSha256": "sha-b",
        })];
        // 慢一倍 > 1.25 容差 → fail
        assert_eq!(
            judge("l", &rows, Some(&reference(100.0, "sha-b")))["table"]["verdict"],
            "regression-fail"
        );
        // 即便耗时不变，产物摘要变了也必须 fail
        let same_speed = vec![json!({
            "engine": "rust",
            "scenario": "table",
            "wallMs": { "median": 100.0 },
            "peakTreeRssKb": { "median": 1_000.0 },
            "outputSha256": "sha-changed",
        })];
        assert_eq!(
            judge("l", &same_speed, Some(&reference(100.0, "sha-b")))["table"]["verdict"],
            "regression-fail",
            "产物摘要变化不得被回归判定放过"
        );
    }

    #[test]
    fn regression_still_respects_the_absolute_peak_cap() {
        // 耗时与摘要都合格，但绝对峰值越档 → 仍然 fail。
        let rows = vec![json!({
            "engine": "rust",
            "scenario": "table",
            "wallMs": { "median": 100.0 },
            "peakTreeRssKb": { "median": 9_000.0 * 1024.0 },
            "outputSha256": "sha-a",
        })];
        assert_eq!(
            judge("l", &rows, Some(&reference(100.0, "sha-a")))["table"]["verdict"],
            "regression-fail"
        );
    }
}

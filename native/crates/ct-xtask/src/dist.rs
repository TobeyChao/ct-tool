//! 平台独立运行时包（任务 6.6）：release 构建 → 版本信息 → 无 Python 环境自检 → zip。
//!
//! 只打包原生 `ct` 单二进制（CLI + `ct worker`），不含任何 Python 运行时；
//! 打包后立即用「中文与空格路径 + 清洗过的 PATH」真跑一遍 CLI 与 worker 握手，
//! 结果写进包内 `RUNTIME-CHECK.txt`，供桌面壳与人工验收核对。

use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{bail, Context, Result};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use zip::write::SimpleFileOptions;
use zip::CompressionMethod;

/// 运行时包名里的产物前缀。
const PACKAGE_PREFIX: &str = "ct-native";

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn native_dir() -> PathBuf {
    repo_root().join("native")
}

/// 需要抹掉的解释器/虚拟环境痕迹。
const ENV_DENY: &[&str] = &[
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONEXECUTABLE",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
];

/// 子进程环境隔离：PATH 只保留包内 bin 目录，并清掉解释器/虚拟环境变量。
fn isolate_env(cmd: &mut Command, bin_dir: &Path) {
    for key in ENV_DENY {
        cmd.env_remove(key);
    }
    cmd.env("PATH", bin_dir);
}

/// 以隔离环境启动打包后的二进制（不依赖任何外部解释器或运行时）。
fn isolated(binary: &Path) -> Command {
    let mut command = Command::new(binary);
    isolate_env(
        &mut command,
        binary.parent().unwrap_or_else(|| Path::new(".")),
    );
    command
}

fn command_text(program: &str, args: &[&str], cwd: Option<&Path>) -> Option<String> {
    let mut command = Command::new(program);
    command.args(args);
    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn host_triple() -> Result<String> {
    let text = command_text("rustc", &["-vV"], None).context("无法执行 rustc -vV")?;
    text.lines()
        .find_map(|line| line.strip_prefix("host:"))
        .map(|rest| rest.trim().to_string())
        .context("rustc -vV 里没有 host 行")
}

fn workspace_version() -> Result<String> {
    let manifest = std::fs::read_to_string(native_dir().join("Cargo.toml"))
        .context("缺少 native/Cargo.toml")?;
    let line = manifest
        .lines()
        .find(|line| line.starts_with("version ="))
        .context("workspace 版本未定义")?;
    Ok(line
        .split('=')
        .nth(1)
        .unwrap_or_default()
        .trim()
        .trim_matches('"')
        .to_string())
}

fn sha256_of(path: &Path) -> Result<String> {
    let bytes = std::fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

fn exe_name(target: &str) -> String {
    if target.contains("windows") {
        "ct.exe".to_string()
    } else {
        "ct".to_string()
    }
}

fn cargo_build(target: &str) -> Result<PathBuf> {
    let status = Command::new("cargo")
        .args(["build", "--release", "-p", "ct-cli", "--target", target])
        .current_dir(native_dir())
        .status()
        .with_context(|| format!("无法启动 cargo（目标 {target}）"))?;
    if !status.success() {
        bail!("cargo build --release --target {target} 失败");
    }
    let binary = native_dir()
        .join("target")
        .join(target)
        .join("release")
        .join(exe_name(target));
    if !binary.is_file() {
        bail!("构建成功但找不到产物 {}", binary.display());
    }
    Ok(binary)
}

/// 把导出流水线夹具复制到 `dst`（真跑用，绝不写真实 gd/）。
fn copy_fixture(dst: &Path) -> Result<PathBuf> {
    let src = native_dir().join("fixtures/export_pipeline/workspace");
    if !src.is_dir() {
        bail!("缺少导出夹具 {}", src.display());
    }
    let root = dst.join("配表工作区");
    fn walk(src: &Path, dst: &Path) -> Result<()> {
        std::fs::create_dir_all(dst)?;
        for entry in std::fs::read_dir(src)? {
            let entry = entry?;
            let target = dst.join(entry.file_name());
            if entry.path().is_dir() {
                walk(&entry.path(), &target)?;
            } else {
                std::fs::copy(entry.path(), &target)?;
            }
        }
        Ok(())
    }
    walk(&src, &root)?;
    Ok(root)
}

fn run_step(label: &str, binary: &Path, args: &[&str], cwd: &Path) -> Result<String> {
    let mut command = isolated(binary);
    command.args(args).current_dir(cwd);
    let output = command
        .output()
        .with_context(|| format!("无法启动 {label}（打包后的二进制不该依赖外部运行时）"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    let text = format!(
        "[{label}] ct {} => 退出码 {}\n--- stdout ---\n{}--- stderr ---\n{}",
        args.join(" "),
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "signal".to_string()),
        stdout,
        stderr
    );
    if !output.status.success() {
        bail!("{text}");
    }
    Ok(text)
}

/// worker 握手：hello → workspace.open → shutdown，全部在清洗过的环境里跑。
fn run_worker_step(binary: &Path, cwd: &Path, workspace: &Path) -> Result<String> {
    let mut command = isolated(binary);
    command
        .arg("worker")
        .current_dir(cwd)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    let mut child = command.spawn().context("无法启动 ct worker")?;
    {
        let stdin = child.stdin.as_mut().context("worker 没有 stdin")?;
        let capabilities = json!([
            "workspace",
            "schema",
            "template",
            "validate",
            "export",
            "deploy",
            "i18n",
            "history",
            "logs",
            "tasks",
            "cancel",
            "shutdown"
        ]);
        writeln!(
            stdin,
            "{}",
            json!({"type":"hello","protocolVersion":1,"coreVersion":"dist-check","capabilities":capabilities})
        )?;
        writeln!(
            stdin,
            "{}",
            json!({"type":"request","requestId":1,"method":"workspace.open","workspaceRoot":workspace,"params":{}})
        )?;
        writeln!(
            stdin,
            "{}",
            json!({"type":"request","requestId":2,"method":"shutdown","workspaceRoot":workspace,"params":{}})
        )?;
        stdin.flush()?;
    }
    let output = child
        .wait_with_output()
        .context("等待 ct worker 退出失败")?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let hello_ok = stdout.contains("\"type\":\"hello\"");
    let opened_ok = stdout.contains("\"requestId\":1");
    let shutdown_ok = stdout.contains("\"requestId\":2");
    let text = format!(
        "[ct worker] 握手+workspace.open+shutdown => 退出码 {}；hello={hello_ok} open={opened_ok} shutdown={shutdown_ok}\n--- stdout ---\n{stdout}",
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "signal".to_string())
    );
    if !(output.status.success() && hello_ok && opened_ok && shutdown_ok) {
        bail!(
            "{text}\nstderr: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
    Ok(text)
}

/// 报告隔离环境并确认包内目录没有解释器（原始 PATH 条目数一并留档，便于复核）。
fn python_free_path_report(bin_dir: &Path) -> Result<String> {
    let original = std::env::var_os("PATH")
        .map(|raw| std::env::split_paths(&raw).count())
        .unwrap_or(0);
    const INTERPRETERS: &[&str] = &[
        "python.exe",
        "python3.exe",
        "py.exe",
        "py3.exe",
        "python",
        "python3",
    ];
    let mut leftovers = Vec::new();
    if let Ok(dir_entries) = std::fs::read_dir(bin_dir) {
        for entry in dir_entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_ascii_lowercase();
            if INTERPRETERS.iter().any(|wanted| name == *wanted) {
                leftovers.push(entry.path().display().to_string());
            }
        }
    }
    if !leftovers.is_empty() {
        bail!("包内 bin 目录不该出现解释器：{leftovers:?}");
    }
    Ok(format!(
        "PATH 从 {original} 个目录收敛为包内单目录 {}；其中没有 python/py 可执行文件，PYTHONHOME/PYTHONPATH/VIRTUAL_ENV 等变量已清除",
        bin_dir.display()
    ))
}

/// 在中文+空格路径下真跑打包二进制，返回自检文本。
fn runtime_check(binary: &Path, triple: &str) -> Result<String> {
    let scratch = std::env::temp_dir().join(format!(
        "{PACKAGE_PREFIX} 运行时 验证 {triple} {}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch)
        .with_context(|| format!("创建中文空格路径失败 {}", scratch.display()))?;
    let workspace = copy_fixture(&scratch)?;
    let no_python = python_free_path_report(binary.parent().unwrap_or_else(|| Path::new(".")))?;
    let mut steps = Vec::new();
    steps.push(format!("[无 Python 环境] {no_python}"));
    steps.push(run_step("ct --version", binary, &["--version"], &scratch)?);
    steps.push(run_step(
        "ct validate",
        binary,
        &["validate", "--root", "."],
        &workspace,
    )?);
    steps.push(run_step(
        "ct status",
        binary,
        &["status", "--root", "."],
        &workspace,
    )?);
    steps.push(run_step(
        "ct export",
        binary,
        &["export", "--root", "."],
        &workspace,
    )?);
    if !workspace.join("output/json/Item_zh.json").is_file() {
        bail!("导出后缺少 output/json/Item_zh.json");
    }
    steps.push("[产物] output/json/Item_zh.json 已生成".to_string());
    steps.push(run_worker_step(binary, &scratch, &workspace)?);
    steps.push(run_panel_step(binary, &workspace)?);
    let _ = std::fs::remove_dir_all(&scratch);
    Ok(steps.join("\n") + "\n")
}

fn version_info(triple: &str, binary: &Path, version: &str) -> Result<Value> {
    let root = repo_root();
    let mut files = Map::new();
    for (label, path) in [
        ("binary", binary.to_path_buf()),
        ("cargoLock", native_dir().join("Cargo.lock")),
    ] {
        files.insert(label.to_string(), json!({
            "path": path.file_name().map(|name| name.to_string_lossy().to_string()).unwrap_or_default(),
            "sha256": sha256_of(&path)?,
            "bytes": std::fs::metadata(&path)?.len(),
        }));
    }
    Ok(json!({
        "schema": "ct-runtime-package/1",
        "name": PACKAGE_PREFIX,
        "version": version,
        "target": triple,
        "family": if triple.contains("windows") { "win32" } else if triple.contains("darwin") { "macos" } else { "linux" },
        "pythonRuntimeRequired": false,
        "commit": command_text("git", &["rev-parse", "HEAD"], Some(&root)).unwrap_or_default(),
        "dirtyPaths": command_text("git", &["status", "--porcelain"], Some(&root)).map(|t| t.lines().count()).unwrap_or(0),
        "toolchain": {
            "rustc": command_text("rustc", &["-V"], None).unwrap_or_default(),
            "cargoLockSha256": sha256_of(&native_dir().join("Cargo.lock"))?,
        },
        "cliVersionOutput": command_text(binary.to_string_lossy().as_ref(), &["--version"], None).unwrap_or_default(),
        "contents": ["bin/ct", "VERSION.json", "RUNTIME-CHECK.txt", "README.md"],
        "files": files,
    }))
}

fn write_package_readme(path: &Path, triple: &str, version: &str) -> Result<()> {
    let text = format!(
        "# {PACKAGE_PREFIX} {version}（{triple}）\n\n\
         独立原生运行时包：单个 `ct` 二进制同时提供命令行与 `ct worker` stdio 协议入口，\n\
         **不需要 Python**（不下载、不调用、也不回退到旧工具链）。\n\n\
         ## 用法\n\n\
         ```sh\n\
         bin/ct export --root <游戏配表工作区>\n\
         bin/ct validate --root <工作区> --json\n\
         bin/ct worker   # 桌面壳通过 stdin/stdout 的 NDJSON 协议驱动\n\
         ```\n\n\
         ## 自检\n\n\
         `RUNTIME-CHECK.txt` 是打包时在同一次运行里真跑 CLI/worker 的输出：\n\
         中文与空格路径、清洗过 PATH 与 `PYTHON*` 变量的环境、以及 `--version` 文本。\n\
         换平台后请重新执行 `cargo run -p ct-xtask -- dist`，不要复用别的平台的自检结论。\n"
    );
    std::fs::write(path, text)?;
    Ok(())
}

fn zip_package(pkg_dir: &Path, zip_path: &Path) -> Result<()> {
    let file = std::fs::File::create(zip_path)?;
    let mut writer = zip::ZipWriter::new(std::io::BufWriter::new(file));
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    let mut entries: BTreeMap<String, PathBuf> = BTreeMap::new();
    fn walk(dir: &Path, base: &Path, out: &mut BTreeMap<String, PathBuf>) -> Result<()> {
        for entry in std::fs::read_dir(dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                walk(&path, base, out)?;
            } else {
                let relative = path
                    .strip_prefix(base)
                    .context("文件不在包目录内")?
                    .to_string_lossy()
                    .replace('\\', "/");
                out.insert(relative, path);
            }
        }
        Ok(())
    }
    walk(pkg_dir, pkg_dir, &mut entries)?;
    for (relative, path) in &entries {
        writer.start_file(relative, options)?;
        let bytes = std::fs::read(path)?;
        writer.write_all(&bytes)?;
    }
    let mut finished = writer.finish()?;
    finished.flush()?;
    drop(finished);
    Ok(())
}

pub fn run(extra_targets: &[String], out: Option<PathBuf>, skip_check: bool) -> Result<()> {
    let host = host_triple()?;
    let version = workspace_version()?;
    let mut targets = vec![host.clone()];
    for target in extra_targets {
        if !targets.iter().any(|known| known == target) {
            targets.push(target.clone());
        }
    }
    let out_dir = out.unwrap_or_else(|| native_dir().join("dist"));
    std::fs::create_dir_all(&out_dir)?;
    let mut report = Vec::new();
    for target in &targets {
        let is_host = target == &host;
        let binary = match cargo_build(target) {
            Ok(path) => path,
            Err(error) => {
                if is_host {
                    return Err(error);
                }
                eprintln!("[dist] 跳过 {target}：{error}");
                report.push(format!("{target}: 跳过（缺工具链）"));
                continue;
            }
        };
        let package = format!("{PACKAGE_PREFIX}-{version}-{target}");
        let pkg_dir = out_dir.join(&package);
        let _ = std::fs::remove_dir_all(&pkg_dir);
        std::fs::create_dir_all(pkg_dir.join("bin"))?;
        let staged = pkg_dir.join("bin").join(exe_name(target));
        std::fs::copy(&binary, &staged)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&staged, std::fs::Permissions::from_mode(0o755))?;
        }
        std::fs::write(
            pkg_dir.join("VERSION.json"),
            serde_json::to_string_pretty(&version_info(target, &staged, &version)?)? + "\n",
        )?;
        write_package_readme(&pkg_dir.join("README.md"), target, &version)?;
        let check_text = if skip_check {
            "（本次以 --skip-check 跳过运行时自检）\n".to_string()
        } else {
            runtime_check(&staged, target)?
        };
        std::fs::write(pkg_dir.join("RUNTIME-CHECK.txt"), check_text)?;
        let zip_path = out_dir.join(format!("{package}.zip"));
        zip_package(&pkg_dir, &zip_path)?;
        report.push(format!(
            "{target}: {}（zip {} 字节，自检 {}）",
            pkg_dir.display(),
            std::fs::metadata(&zip_path)?.len(),
            if skip_check { "跳过" } else { "通过" }
        ));
    }
    println!("{}", report.join("\n"));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn package_names_follow_target_family() {
        assert_eq!(exe_name("x86_64-pc-windows-msvc"), "ct.exe");
        assert_eq!(exe_name("aarch64-apple-darwin"), "ct");
        assert_eq!(exe_name("x86_64-unknown-linux-gnu"), "ct");
    }

    #[test]
    fn isolated_environment_only_keeps_the_package_bin_dir() {
        let package_bin = if cfg!(windows) {
            Path::new("C:\\pkg\\bin")
        } else {
            Path::new("/tmp/pkg/bin")
        };
        let command = isolated(&package_bin.join(if cfg!(windows) { "ct.exe" } else { "ct" }));
        let mut keys = Vec::new();
        let mut path_value = String::new();
        for (key, value) in command.get_envs() {
            if value.is_some() {
                keys.push(key.to_string_lossy().to_ascii_uppercase());
            }
            if key == "PATH" {
                path_value =
                    value.map_or_else(String::new, |entry| entry.to_string_lossy().to_string());
            }
        }
        assert_eq!(
            path_value,
            std::env::join_paths([package_bin.to_path_buf()])
                .expect("拼接测试路径")
                .to_string_lossy(),
            "PATH 应只剩包内 bin 目录"
        );
        assert!(
            !keys.contains(&"PYTHONHOME".to_string()),
            "PYTHONHOME 应被清除：{keys:?}"
        );
    }
}

/// Verify embedded panel assets and safe stdin-EOF shutdown in the isolated package.
fn run_panel_step(binary: &Path, workspace: &Path) -> Result<String> {
    use std::io::{BufRead, BufReader, Read};
    use std::process::Stdio;
    use std::time::{Duration, Instant};
    let mut child = isolated(binary)
        .args([
            "panel",
            "--port",
            "0",
            "--no-browser",
            "--shutdown-on-stdin-eof",
        ])
        .current_dir(workspace)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .context("启动打包 panel")?;
    let stdout = child.stdout.take().context("panel stdout")?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let _ = BufReader::new(stdout).read_line(&mut line);
        let _ = tx.send(line);
    });
    let result = (|| -> Result<String> {
        let line = rx
            .recv_timeout(Duration::from_secs(20))
            .context("panel 就绪超时")?;
        let port: u16 = line
            .split("http://127.0.0.1:")
            .nth(1)
            .context("缺少就绪地址")?
            .split('（')
            .next()
            .context("端口")?
            .parse()?;
        for (path, expected) in [
            ("/", "module-registry.js"),
            ("/api/service", "\"kernel\":\"native\""),
        ] {
            let mut socket = std::net::TcpStream::connect(("127.0.0.1", port))?;
            socket.set_read_timeout(Some(Duration::from_secs(10)))?;
            write!(
                socket,
                "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
            )?;
            let mut response = String::new();
            socket.read_to_string(&mut response)?;
            if !response.starts_with("HTTP/1.1 200") || !response.contains(expected) {
                bail!("打包 panel 响应不符合契约: {path}");
            }
        }
        Ok("[ct panel] 嵌入静态资源、原生 HTTP 与 stdin EOF 安全退出通过".into())
    })();
    drop(child.stdin.take());
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if let Some(status) = child.try_wait()? {
            if !status.success() {
                bail!("panel 非正常退出: {status}");
            }
            break;
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            let _ = child.wait();
            bail!("panel 安全退出超时");
        }
        std::thread::sleep(Duration::from_millis(25));
    }
    result
}

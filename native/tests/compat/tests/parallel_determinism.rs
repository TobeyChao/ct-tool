//! 有界并行确定性对照（rust-native-core 任务 5.4）：
//! 不同并发度下产物字节与诊断顺序一致，并记录峰值内存。

use std::path::Path;

use ct_app::export::{run_pipeline, ExportRequest};
use ct_app::workspace::Workspace;

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content.replace("\r\n", "\n")).unwrap();
}

/// 3 表工作区（Item/Buff/Quest），模板与 manifest 由 gen_template 生成。
fn setup() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(
        &root.join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs:\n  - en\n",
    );
    for (file, table) in [
        ("item.yaml", "Item"),
        ("buff.yaml", "Buff"),
        ("quest.yaml", "Quest"),
    ] {
        write(
            &root.join("config/schemas").join(file),
            &format!(
                "table: {table}\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Title\n    type: string\n    i18n: true\nindexes:\n  - kind: codename\n"
            ),
        );
    }
    write(
        &root.join("config/types/rarity.yaml"),
        "kind: enum\nname: Rarity\nvalues:\n  - name: Common\n  - name: Rare\n",
    );
    let ws = Workspace::open(root).unwrap();
    ct_app::template::gen_template(&ws, None, true).unwrap();
    // 每表填一行数据（表头两行：第 2 行为 "名称\n类型"）
    for table in ["Item", "Buff", "Quest"] {
        write_workbook(root, table, &[vec!["1", "cn", "标题"]]);
    }
    let _ = ws;
    dir
}

/// 写规范表头 + 数据行的工作簿（表头两行，数据从第 3 行开始）。
fn write_workbook(root: &Path, table: &str, rows: &[Vec<&str>]) {
    let mut workbook = rust_xlsxwriter::Workbook::new();
    let ws1 = workbook.add_worksheet();
    ws1.set_name(table).unwrap();
    let headers = ["Id\nint32", "CodeName\nstring", "Title\nstring"];
    for (col, text) in headers.iter().enumerate() {
        ws1.write_string(1, col as u16, *text).unwrap();
    }
    for (r, row) in rows.iter().enumerate() {
        for (col, text) in row.iter().enumerate() {
            if col == 0 {
                ws1.write_number((2 + r) as u32, 0, text.parse::<f64>().unwrap())
                    .unwrap();
            } else {
                ws1.write_string((2 + r) as u32, col as u16, *text).unwrap();
            }
        }
    }
    std::fs::write(
        root.join("excel").join(format!("{table}.xlsx")),
        workbook.save_to_buffer().unwrap(),
    )
    .unwrap();
}

fn run(root: &Path) -> (String, Vec<String>) {
    let result = run_pipeline(
        &ExportRequest {
            root: root.to_path_buf(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        None,
        None,
    )
    .map_err(|e| e.to_string())
    .unwrap_or_else(|msg| panic!("导出失败: {msg}"));
    let mut digest = Vec::new();
    for (rel, bytes) in collect(&root.join("output")) {
        digest.extend(rel.as_bytes());
        digest.extend(sha256_hex_local(&bytes).as_bytes());
    }
    (sha256_hex_local(&digest), result.written)
}

fn sha256_hex_local(data: &[u8]) -> String {
    ct_domain::hashing::sha256_hex(data)
}

fn collect(root: &Path) -> std::collections::BTreeMap<String, Vec<u8>> {
    let mut out = std::collections::BTreeMap::new();
    for entry in std::fs::read_dir(root).unwrap().flatten() {
        let path = entry.path();
        if path.is_dir() {
            for (k, v) in collect(&path) {
                out.insert(
                    format!("{}/{k}", path.file_name().unwrap().to_string_lossy()),
                    v,
                );
            }
        } else {
            out.insert(
                path.file_name().unwrap().to_string_lossy().to_string(),
                std::fs::read(&path).unwrap(),
            );
        }
    }
    out
}

#[test]
fn same_bytes_under_different_concurrency() {
    let dir = setup();
    let root = dir.path();

    std::env::set_var("CT_MAX_WORKERS", "1");
    let (serial_digest, mut serial_written) = run(root);
    std::env::remove_var("CT_MAX_WORKERS");

    // 清空产物与缓存，模拟冷启动并发跑
    let _ = std::fs::remove_dir_all(root.join("output"));
    let _ = std::fs::remove_dir_all(root.join("cache"));
    std::env::set_var("CT_MAX_WORKERS", "4");
    let (parallel_digest, mut parallel_written) = run(root);
    std::env::remove_var("CT_MAX_WORKERS");

    serial_written.sort();
    parallel_written.sort();
    assert_eq!(serial_digest, parallel_digest, "并发度不得改变产物字节");
    assert_eq!(serial_written, parallel_written, "written 清单必须一致");
}

#[test]
fn diagnostics_order_stable_under_concurrency() {
    // 三表都有非法数据：问题顺序必须始终按表序（Item→Buff→Quest 的 schema 顺序）
    let dir = setup();
    let root = dir.path();
    // 破坏主键唯一性：每表写两行相同 Id
    for table in ["Item", "Buff", "Quest"] {
        write_workbook(root, table, &[vec!["7", "a", "甲"], vec!["7", "b", "乙"]]);
    }
    let mut digests = Vec::new();
    for workers in ["1", "3"] {
        std::env::set_var("CT_MAX_WORKERS", workers);
        let err = run_pipeline(
            &ExportRequest {
                root: root.to_path_buf(),
                table_filter: None,
                lang_filter: None,
                forced: false,
            },
            None,
            None,
        )
        .map(|_| String::new())
        .map_err(|e| e.to_string())
        .unwrap_err();
        std::env::remove_var("CT_MAX_WORKERS");
        digests.push(err);
    }
    assert!(digests[0].contains("校验失败"), "{}", digests[0]);
    assert_eq!(digests[0], digests[1], "诊断文本与顺序必须与并发度无关");
}

#[test]
fn peak_memory_recorded_for_bounded_parallelism() {
    // 记录峰值 RSS（供 6.5 基线对照）；有界并行不得让峰值随表数线性膨胀
    let dir = setup();
    let root = dir.path();
    std::env::set_var("CT_MAX_WORKERS", "4");
    let before = peak_rss_kb();
    run(root);
    let after = peak_rss_kb();
    std::env::remove_var("CT_MAX_WORKERS");
    eprintln!("峰值内存参考: before={before:?}KB after={after:?}KB");
}

/// 尽力读取进程峰值 RSS（Linux /proc/self/status；其它平台返回 None）。
fn peak_rss_kb() -> Option<u64> {
    let text = std::fs::read_to_string("/proc/self/status").ok()?;
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("VmHWM:") {
            return rest.split_whitespace().next()?.parse().ok();
        }
    }
    None
}

//! 增量与强制重建契约矩阵（任务 5.6）：对每个增量场景比较
//! 「成功/失败一致、产物字节一致、mtime 契约」，并给出缓存绕过的可观测证据。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use ct_app::export::{run_export, CompletionPolicy, ExportRequest, ExportResult};

fn copy_dir(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).expect("创建目录");
    for entry in std::fs::read_dir(src).expect("读取夹具").flatten() {
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).expect("复制夹具文件");
        }
    }
}

fn fixture_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace")
}

fn workspace() -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("临时目录");
    copy_dir(&fixture_root(), dir.path());
    dir
}

fn run(root: &Path, forced: bool, table: Option<&str>) -> Result<ExportResult, String> {
    let request = ExportRequest {
        root: root.to_path_buf(),
        table_filter: table.map(str::to_string),
        lang_filter: None,
        forced,
    };
    run_export(&request, CompletionPolicy::export_only(), None, None, false)
        .map(|(result, _logs, _recovery)| result)
        .map_err(|e| e.to_string())
}

fn export(root: &Path, forced: bool) -> Result<ExportResult, String> {
    run(root, forced, None)
}

/// 正式产物快照：字节 + mtime（键为相对路径，统一正斜杠）。
struct Snapshot {
    bytes: BTreeMap<String, Vec<u8>>,
    times: BTreeMap<String, SystemTime>,
}

fn snapshot(root: &Path) -> Snapshot {
    let mut bytes: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let mut times: BTreeMap<String, SystemTime> = BTreeMap::new();
    let mut stack = vec![root.join("output")];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(meta) = entry.metadata() else {
                continue;
            };
            if meta.is_dir() {
                stack.push(path.clone());
                continue;
            }
            let relative = path
                .strip_prefix(root)
                .expect("相对路径")
                .to_string_lossy()
                .replace('\\', "/");
            bytes.insert(relative.clone(), std::fs::read(&path).expect("读取产物"));
            times.insert(relative, meta.modified().expect("mtime"));
        }
    }
    assert!(!bytes.is_empty(), "工作区没有产出任何产物");
    Snapshot { bytes, times }
}

fn changed_bytes(before: &Snapshot, after: &Snapshot) -> Vec<String> {
    before
        .bytes
        .iter()
        .filter(|(name, payload)| after.bytes[*name] != **payload)
        .map(|(name, _)| name.clone())
        .collect()
}

fn touched_times(before: &Snapshot, after: &Snapshot) -> Vec<String> {
    before
        .times
        .iter()
        .filter(|(name, stamp)| after.times[*name] != **stamp)
        .map(|(name, _)| name.clone())
        .collect()
}

/// 产物名在不同平台的发布大小写可能不同（Python normcase 会把名字小写），
/// 因此按大小写不敏感解析实际键名。
fn key_of(snap: &Snapshot, wanted: &str) -> String {
    let lowered = wanted.to_lowercase();
    snap.bytes
        .keys()
        .find(|key| key.to_lowercase() == lowered)
        .unwrap_or_else(|| {
            panic!(
                "产物里没有 {wanted}：{:?}",
                snap.bytes.keys().collect::<Vec<_>>()
            )
        })
        .clone()
}

/// 先做一次干净导出，再按场景改写输入，返回工作区与改写前的产物快照。
fn prepared<F>(mutate: F) -> (tempfile::TempDir, Snapshot)
where
    F: FnOnce(&Path),
{
    let dir = workspace();
    export(dir.path(), false).expect("基线导出应成功");
    mutate(dir.path());
    let before = snapshot(dir.path());
    (dir, before)
}

fn write_enum_without_used_values(root: &Path) {
    std::fs::write(
        root.join("config/types/rarity.yaml"),
        "kind: enum\nname: Rarity\nvalues:\n  - name: Epic\n",
    )
    .expect("改写枚举");
}

#[test]
fn python_ledger_survives_native_export_in_custom_paths() {
    let dir = workspace();
    let root = dir.path();
    let config_path = root.join("config/global.yaml");
    let mut config = std::fs::read_to_string(&config_path).unwrap();
    config.push_str("cache_dir: 'cache 自定义'\noutput_dir: 'output 自定义'\n");
    std::fs::write(&config_path, config).unwrap();
    let cache_dir = root.join("cache 自定义");
    std::fs::create_dir_all(&cache_dir).unwrap();
    std::fs::copy(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/cache/python-state.json"),
        cache_dir.join("state.json"),
    )
    .unwrap();

    let old = ct_cache::state::load_state(&cache_dir).expect("旧 Python 成功账本必须可读");
    assert_eq!(old.tables["LegacyOnly"].schema, "legacy-schema");
    assert_eq!(old.tables["LegacyOnly"].i18n["en"], "legacy-en");
    assert_eq!(old.bundles["ja"], "legacy-bundle-ja");
    assert_eq!(old.excel_hashes["LegacyOnly"], "legacy-excel-sha256");

    let first = export(root, false).expect("原生导出应接续旧账本");
    assert!(first.cache_misses > 0);
    let state_path = cache_dir.join("state.json");
    let after = ct_cache::state::load_state(&cache_dir).expect("导出后账本必须有效");
    assert_eq!(after.tables["LegacyOnly"], old.tables["LegacyOnly"]);
    assert_eq!(after.bundles["ja"], old.bundles["ja"]);
    assert_eq!(
        after.excel_hashes["LegacyOnly"],
        old.excel_hashes["LegacyOnly"]
    );
    assert!(after.excel_hashes.contains_key("Item"));
    assert!(after.bundles.contains_key("zh"));
    assert!(after.bundles.contains_key("en"));
    assert!(!root.join("cache/state.json").exists());
    assert!(!root.join("output").exists());
    let json = root.join("output 自定义/json/Item_zh.json");
    assert!(json.exists());
    let before_bytes = std::fs::read(&json).unwrap();
    let before_mtime = std::fs::metadata(&json).unwrap().modified().unwrap();
    let second = export(root, false).expect("原生增量应复用自定义缓存");
    assert!(second.cache_hits > 0);
    assert!(second.written.is_empty());
    assert_eq!(std::fs::read(&json).unwrap(), before_bytes);
    assert_eq!(
        std::fs::metadata(&json).unwrap().modified().unwrap(),
        before_mtime
    );

    let ledger_before_failure = std::fs::read(&state_path).unwrap();
    write_enum_without_used_values(root);
    assert!(export(root, false).is_err(), "校验失败不得推进旧账本");
    assert_eq!(std::fs::read(&state_path).unwrap(), ledger_before_failure);
    assert_eq!(
        std::fs::metadata(&json).unwrap().modified().unwrap(),
        before_mtime
    );
}

#[test]
fn unchanged_inputs_keep_bytes_and_mtime_but_all_rewrites() {
    let dir = workspace();
    let first = export(dir.path(), false).expect("首次导出成功");
    let before = snapshot(dir.path());
    assert!(first.cache_misses > 0, "首次必须计算：{first:?}");

    // 增量：内容不变 → 不重写、mtime 保留、命中生成缓存
    let again = export(dir.path(), false).expect("二次导出成功");
    let after = snapshot(dir.path());
    assert_eq!(after.bytes, before.bytes, "增量产物字节必须不变");
    assert_eq!(
        after.times, before.times,
        "内容未变的正式产物必须保留 mtime"
    );
    assert!(again.cache_hits > 0, "二次导出必须命中缓存：{again:?}");

    // --all：绕过全部计算缓存并强制写出，字节仍与增量一致
    let forced = export(dir.path(), true).expect("--all 导出成功");
    let forced_snap = snapshot(dir.path());
    assert_eq!(
        forced_snap.bytes, before.bytes,
        "--all 与增量产物字节必须相同"
    );
    assert_eq!(forced.cache_hits, 0, "--all 不得复用缓存：{forced:?}");
    assert!(forced.cache_misses > 0, "--all 必须重新计算：{forced:?}");
    assert_eq!(
        touched_times(&after, &forced_snap).len(),
        before.times.len(),
        "--all 必须重写全部选中产物"
    );

    // --all 之后回到增量：内容一致 → 仍不重写
    export(dir.path(), false).expect("--all 后增量成功");
    let settled = snapshot(dir.path());
    assert_eq!(settled.bytes, before.bytes);
    assert_eq!(settled.times, forced_snap.times, "内容一致时不得改写 mtime");
}

#[test]
fn effective_translation_change_updates_only_that_language() {
    let (dir, before) = prepared(|root| {
        let path = root.join("i18n/en/Item.json");
        let text = std::fs::read_to_string(&path).expect("读取译文");
        let patched = text
            .replace("\"confirmed\": false", "\"confirmed\": true")
            .replace("\"status\": \"missing\"", "\"status\": \"confirmed\"")
            .replace("\"text\": \"\"", "\"text\": \"Iron Shield\"");
        std::fs::write(&path, patched).expect("写入译文");
    });
    export(dir.path(), false).expect("译文变更后导出成功");
    let after = snapshot(dir.path());
    let changed = changed_bytes(&before, &after);
    assert!(
        changed.contains(&key_of(&before, "output/json/item_en.json")),
        "en JSON 必须更新：{changed:?}"
    );
    assert!(
        changed.contains(&key_of(&before, "output/binary/data_en.bin")),
        "en Bundle 必须更新：{changed:?}"
    );
    for untouched in [
        key_of(&before, "output/json/item_zh.json"),
        key_of(&before, "output/binary/data_zh.bin"),
    ] {
        assert!(
            !changed.contains(&untouched),
            "{untouched} 不应因 en 译文变化而改变：{changed:?}"
        );
        assert_eq!(
            before.times[untouched.as_str()],
            after.times[untouched.as_str()],
            "{untouched} 的 mtime 必须保留"
        );
    }
    let forced = export(dir.path(), true).expect("--all 成功");
    assert_eq!(
        snapshot(dir.path()).bytes,
        after.bytes,
        "--all 与增量必须字节一致：{forced:?}"
    );
    assert_eq!(forced.cache_hits, 0, "--all 不得复用：{forced:?}");
}

#[test]
fn inert_translation_metadata_does_not_rebuild_anything() {
    let (dir, before) = prepared(|root| {
        // 只改排版：有效合并行不变
        let path = root.join("i18n/en/Item.json");
        let text = std::fs::read_to_string(&path).expect("读取译文");
        std::fs::write(&path, text.replace("\n  ", "\n      ")).expect("写入译文");
    });
    export(dir.path(), false).expect("排版变化后导出成功");
    let after = snapshot(dir.path());
    assert_eq!(after.bytes, before.bytes, "无效元信息变化不得改变产物");
    assert_eq!(after.times, before.times, "无效元信息变化不得改写 mtime");
}

#[test]
fn missing_or_rewritten_output_is_repaired_identically() {
    let clean = workspace();
    export(clean.path(), false).expect("参考导出成功");
    let reference = snapshot(clean.path());

    let (dir, _) = prepared(|root| {
        std::fs::write(root.join("output/json/item_zh.json"), b"garbage").expect("改写产物");
        std::fs::remove_file(root.join("output/json/item_en.json")).expect("删除产物");
    });
    export(dir.path(), false).expect("修复导出成功");
    assert_eq!(
        snapshot(dir.path()).bytes,
        reference.bytes,
        "缺失/被改写的正式产物必须恢复成正确内容"
    );
}

#[test]
fn corrupt_cache_and_unknown_ledger_version_rebuild_without_changing_bytes() {
    let (dir, before) = prepared(|root| {
        let mut stack = vec![root.join("cache/artifacts")];
        let mut broken = 0usize;
        while let Some(path) = stack.pop() {
            let Ok(entries) = std::fs::read_dir(&path) else {
                continue;
            };
            for entry in entries.flatten() {
                let item = entry.path();
                if item.is_dir() {
                    stack.push(item.clone());
                } else if item.extension().is_some_and(|ext| ext == "json") {
                    std::fs::write(
                        &item,
                        b"{\"kind\":\"text\",\"sha256\":\"dead\",\"payload\":\"AAAA\"}",
                    )
                    .expect("破坏缓存");
                    broken += 1;
                }
            }
        }
        assert!(broken > 0, "夹具应已写入生成缓存条目");
        let state = root.join("cache/state.json");
        let text = std::fs::read_to_string(&state).expect("读取账本");
        std::fs::write(
            &state,
            text.replace("canonical-cache/1", "canonical-cache/999"),
        )
        .expect("改写账本版本");
    });
    let rebuilt = export(dir.path(), false).expect("缓存损坏/版本不识别必须自动重建");
    assert_eq!(rebuilt.cache_hits, 0, "损坏缓存不得命中：{rebuilt:?}");
    let after = snapshot(dir.path());
    assert_eq!(after.bytes, before.bytes, "重建后的产物字节必须与基线一致");
    assert_eq!(
        after.times, before.times,
        "重算但字节相同的文件在默认模式下必须保留 mtime"
    );
    // 账本恢复识别版本：下一次增量重新可用
    let settled = export(dir.path(), false).expect("二次增量成功");
    assert!(
        settled.cache_hits > 0,
        "账本必须已按当前版本重写：{settled:?}"
    );
}

#[test]
fn illegal_data_fails_both_modes_and_touches_nothing() {
    let (dir, before) = prepared(write_enum_without_used_values);
    let incremental = export(dir.path(), false).expect_err("热缓存下非法数据仍必须失败");
    let forced = export(dir.path(), true).expect_err("--all 也必须失败");
    assert!(incremental.contains("Quality"), "{incremental}");
    assert_eq!(
        forced.lines().count(),
        incremental.lines().count(),
        "--all 与增量的失败结论必须一致：\n{forced}\n---\n{incremental}"
    );
    let after = snapshot(dir.path());
    assert_eq!(after.bytes, before.bytes, "失败不得改变任何产物字节");
    assert_eq!(after.times, before.times, "失败不得改写任何产物 mtime");
    assert!(
        !dir.path().join(".ct/export-publication.json").exists(),
        "失败不得留下未清理的发布材料"
    );
}

#[test]
fn filtered_export_produces_the_same_selected_artifacts_as_full_export() {
    let (dir, before) = prepared(|_root| {});
    let filtered = run(dir.path(), false, Some("Item")).expect("过滤导出成功");
    assert_eq!(filtered.tables, 1, "{filtered:?}");
    let after = snapshot(dir.path());
    assert_eq!(
        after.bytes, before.bytes,
        "过滤导出不得改变共享 Bundle 内容"
    );
    assert_eq!(after.times, before.times, "内容未变的过滤导出不得重写文件");
    let forced_filtered = run(dir.path(), true, Some("Item")).expect("--all 过滤导出成功");
    assert_eq!(forced_filtered.cache_hits, 0, "{forced_filtered:?}");
    assert_eq!(
        snapshot(dir.path()).bytes,
        before.bytes,
        "--all 过滤导出字节必须仍与基线一致"
    );
}

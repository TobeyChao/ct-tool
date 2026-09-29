//! 生成缓存对照（rust-native-core 任务 5.1）：
//! 内容寻址、版本/校验和校验、损坏/缺失/版本升级重建、同 mtime 内容变更、
//! forced 绕过、prune 只清理未使用条目。

use std::path::Path;

use ct_cache::artifacts::ArtifactCache;

fn cache(root: &Path, version: &str) -> ArtifactCache {
    ArtifactCache::new(root, version, false)
}

#[test]
fn hit_after_first_compute() {
    let dir = tempfile::tempdir().unwrap();
    let mut calls = 0;
    {
        let mut c = cache(dir.path(), "v1");
        let out = c
            .call_text("gen", &serde_json::json!(["a", 1]), || {
                calls += 1;
                Ok("hello".to_string())
            })
            .unwrap();
        assert_eq!(out, "hello");
        assert_eq!((c.hits, c.misses), (0, 1));
    }
    // 新实例（模拟新进程）同键命中
    let mut c = cache(dir.path(), "v1");
    let out = c
        .call_text("gen", &serde_json::json!(["a", 1]), || {
            calls += 1;
            Ok("hello".to_string())
        })
        .unwrap();
    assert_eq!(out, "hello");
    assert_eq!((c.hits, c.misses), (1, 0));
    assert_eq!(calls, 1);
}

#[test]
fn bytes_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let mut c = cache(dir.path(), "v1");
    let payload: Vec<u8> = (0..=255u8).collect();
    c.call_bytes("bin", &serde_json::json!([1]), || Ok(payload.clone()))
        .unwrap();
    let got = c
        .call_bytes("bin", &serde_json::json!([1]), || Ok(vec![]))
        .unwrap();
    assert_eq!(got, payload);
}

#[test]
fn corrupted_and_tampered_entries_rebuild() {
    let dir = tempfile::tempdir().unwrap();
    let mut c = cache(dir.path(), "v1");
    c.call_text("gen", &serde_json::json!(["x"]), || Ok("v".to_string()))
        .unwrap();
    let entry_dir = dir.path().join("artifacts/gen");
    let entry = std::fs::read_dir(&entry_dir)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();

    // 损坏 JSON
    std::fs::write(&entry, b"not json").unwrap();
    let mut c = cache(dir.path(), "v1");
    let mut rebuilt = false;
    c.call_text("gen", &serde_json::json!(["x"]), || {
        rebuilt = true;
        Ok("v".to_string())
    })
    .unwrap();
    assert!(rebuilt, "损坏条目必须重建");

    // 校验和篡改（payload 换了但 sha256 字段不变 → 校验失败重建）
    let mut value: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&entry).unwrap()).unwrap();
    value["payload"] = serde_json::Value::String("AAAA".to_string());
    std::fs::write(&entry, serde_json::to_string(&value).unwrap()).unwrap();
    let mut c = cache(dir.path(), "v1");
    let mut rebuilt = false;
    c.call_text("gen", &serde_json::json!(["x"]), || {
        rebuilt = true;
        Ok("v".to_string())
    })
    .unwrap();
    assert!(rebuilt, "校验和不符必须重建");

    // 未知类型
    let mut value: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&entry).unwrap()).unwrap();
    value["kind"] = serde_json::Value::String("executable".to_string());
    std::fs::write(&entry, serde_json::to_string(&value).unwrap()).unwrap();
    let mut c = cache(dir.path(), "v1");
    let mut rebuilt = false;
    c.call_text("gen", &serde_json::json!(["x"]), || {
        rebuilt = true;
        Ok("v".to_string())
    })
    .unwrap();
    assert!(rebuilt, "不认识的类型必须重建");
}

#[test]
fn version_bump_invalidates() {
    let dir = tempfile::tempdir().unwrap();
    let mut c = cache(dir.path(), "v1");
    c.call_text("gen", &serde_json::json!(["a"]), || Ok("old".to_string()))
        .unwrap();
    let mut c2 = cache(dir.path(), "v2");
    let got = c2
        .call_text("gen", &serde_json::json!(["a"]), || Ok("new".to_string()))
        .unwrap();
    assert_eq!(got, "new", "版本升级必须重建");
    assert_eq!((c2.hits, c2.misses), (0, 1));
}

#[test]
fn same_mtime_content_change_recomputes() {
    // 键只含内容摘要，与 mtime 无关：内容变 → 键变 → 重建
    let dir = tempfile::tempdir().unwrap();
    let mut c = cache(dir.path(), "v1");
    c.call_text("gen", &serde_json::json!(["content-A"]), || {
        Ok("A".to_string())
    })
    .unwrap();
    let mut c = cache(dir.path(), "v1");
    let got = c
        .call_text("gen", &serde_json::json!(["content-B"]), || {
            Ok("B".to_string())
        })
        .unwrap();
    assert_eq!(got, "B");
    assert_eq!(c.misses, 1);
}

#[test]
fn forced_bypasses_cache() {
    let dir = tempfile::tempdir().unwrap();
    let mut c = cache(dir.path(), "v1");
    c.call_text(
        "gen",
        &serde_json::json!(["a"]),
        || Ok("cached".to_string()),
    )
    .unwrap();
    let mut forced = ArtifactCache::new(dir.path(), "v1", true);
    let got = forced
        .call_text("gen", &serde_json::json!(["a"]), || Ok("fresh".to_string()))
        .unwrap();
    assert_eq!(got, "fresh", "forced 必须绕过缓存");
    assert_eq!(forced.misses, 1);
}

#[test]
fn prune_drops_only_unused() {
    let dir = tempfile::tempdir().unwrap();
    let mut c = cache(dir.path(), "v1");
    c.call_text("gen", &serde_json::json!(["keep"]), || Ok("k".to_string()))
        .unwrap();
    // 手工放一个孤儿条目
    let orphan = dir.path().join("artifacts/gen/orphan.json");
    std::fs::write(&orphan, b"{}").unwrap();
    c.prune();
    assert!(!orphan.exists());
    assert_eq!(
        std::fs::read_dir(dir.path().join("artifacts/gen"))
            .unwrap()
            .count(),
        1
    );
}

#[test]
fn pipeline_second_run_uses_cache_and_stays_byte_identical() {
    // 集成：fixture 工作区连跑两次，第二次全部缓存命中且产物字节一致
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace");
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_dir(&fixture, &root);

    let request = ct_app::export::ExportRequest {
        root: root.clone(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    let first = ct_app::export::run_pipeline(&request, None, None).unwrap();
    assert_eq!(first.cache_hits, 0);
    assert!(first.cache_misses > 0);
    let snapshot: std::collections::BTreeMap<String, Vec<u8>> = collect(&root.join("output"));

    let second = ct_app::export::run_pipeline(&request, None, None).unwrap();
    assert!(second.cache_hits > 0, "第二次必须命中缓存");
    assert_eq!(
        snapshot,
        collect(&root.join("output")),
        "缓存命中后产物字节必须一致"
    );

    // 损坏一个缓存条目：重建后产物仍一致
    let artifacts = root.join("cache/artifacts");
    let victim = std::fs::read_dir(&artifacts)
        .unwrap()
        .flatten()
        .flat_map(|entry| {
            std::fs::read_dir(entry.path())
                .unwrap()
                .flatten()
                .map(|f| f.path())
                .collect::<Vec<_>>()
        })
        .next()
        .expect("缓存目录应有条目");
    std::fs::write(&victim, b"broken").unwrap();
    let third = ct_app::export::run_pipeline(&request, None, None).unwrap();
    assert_eq!(
        snapshot,
        collect(&root.join("output")),
        "损坏缓存重建后产物字节一致"
    );
    let _ = third;

    // forced（--all 语义前置）：全量重建
    let forced = ct_app::export::ExportRequest {
        forced: true,
        ..request
    };
    let fourth = ct_app::export::run_pipeline(&forced, None, None).unwrap();
    assert_eq!(fourth.cache_hits, 0, "forced 不得命中缓存");
    assert_eq!(snapshot, collect(&root.join("output")));
}

fn copy_dir(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).unwrap();
    for entry in std::fs::read_dir(src).unwrap() {
        let entry = entry.unwrap();
        let name = entry.file_name().to_string_lossy().to_string();
        if name == "output" || name == "cache" {
            continue;
        }
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).unwrap();
        }
    }
}

fn collect(root: &Path) -> std::collections::BTreeMap<String, Vec<u8>> {
    let mut out = std::collections::BTreeMap::new();
    if !root.exists() {
        return out;
    }
    for entry in std::fs::read_dir(root).unwrap().flatten() {
        let path = entry.path();
        if path.is_dir() {
            for (k, v) in collect(&path) {
                let rel = format!("{}/{k}", path.file_name().unwrap().to_string_lossy());
                out.insert(rel, v);
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
fn translation_metadata_change_does_not_rebuild() {
    // 只改 i18n 条目的 status/source（无效元信息）：缓存键不变 → 全命中
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace");
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_dir(&fixture, &root);
    let request = ct_app::export::ExportRequest {
        root: root.clone(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    ct_app::export::run_pipeline(&request, None, None).unwrap();
    let before = collect(&root.join("output"));

    // 仅改派生元信息（status/source），text/confirmed 不动
    let en = root.join("i18n/en/Item.json");
    let mut data: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&en).unwrap()).unwrap();
    data["1001.Name"]["status"] = serde_json::Value::String("stale".into());
    data["1001.Name"]["source"] = serde_json::Value::String("改写过的来源记录".into());
    std::fs::write(&en, serde_json::to_string_pretty(&data).unwrap()).unwrap();

    let second = ct_app::export::run_pipeline(&request, None, None).unwrap();
    assert!(
        second.cache_hits >= second.cache_misses && second.cache_hits > 0,
        "无效元信息变化不得导致重建: hits={} misses={}",
        second.cache_hits,
        second.cache_misses
    );
    assert_eq!(before, collect(&root.join("output")), "产物字节不得变化");
}

#[test]
fn missing_or_rewritten_output_is_repaired() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace");
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_dir(&fixture, &root);
    let request = ct_app::export::ExportRequest {
        root: root.clone(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    ct_app::export::run_pipeline(&request, None, None).unwrap();
    let before = collect(&root.join("output"));

    // 删除一个产物 + 改写另一个
    std::fs::remove_file(root.join("output/json/Item_zh.json")).unwrap();
    std::fs::write(root.join("output/fbs/Item.fbs"), b"tampered").unwrap();

    let second = ct_app::export::run_pipeline(&request, None, None).unwrap();
    assert!(second.cache_hits > 0, "缓存命中但输出必须被修复");
    assert_eq!(
        before,
        collect(&root.join("output")),
        "修复后产物必须回到一致状态"
    );
}

#[test]
fn forced_all_rewrites_and_incremental_preserves_mtime() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace");
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_dir(&fixture, &root);
    let base = ct_app::export::ExportRequest {
        root: root.clone(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    ct_app::export::run_pipeline(&base, None, None).unwrap();
    let json = root.join("output/json/Item_zh.json");

    // 增量重跑：内容一致 → 不重写（mtime 不变）
    let mtime_before = std::fs::metadata(&json).unwrap().modified().unwrap();
    std::thread::sleep(std::time::Duration::from_millis(20));
    let incremental = ct_app::export::run_pipeline(&base, None, None).unwrap();
    assert!(incremental.written.is_empty());
    assert_eq!(
        std::fs::metadata(&json).unwrap().modified().unwrap(),
        mtime_before,
        "增量重跑不得触碰内容一致的产物"
    );

    // forced（--all）：绕过缓存且强制写出（mtime 前进、字节一致）
    let bytes_before_forced = std::fs::read(&json).unwrap();
    std::thread::sleep(std::time::Duration::from_millis(20));
    let forced = ct_app::export::ExportRequest {
        forced: true,
        ..base.clone()
    };
    let rerun = ct_app::export::run_pipeline(&forced, None, None).unwrap();
    assert_eq!(rerun.cache_hits, 0);
    assert!(!rerun.written.is_empty(), "forced 必须写出");
    assert!(
        std::fs::metadata(&json).unwrap().modified().unwrap() > mtime_before,
        "forced 必须重写产物（mtime 前进）"
    );
    assert_eq!(bytes_before_forced, std::fs::read(&json).unwrap());
}

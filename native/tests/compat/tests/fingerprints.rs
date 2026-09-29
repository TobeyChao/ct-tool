//! 分层指纹对照（rust-native-core 任务 5.2）：
//! 与 Python fingerprints.py 逐值一致 + 失效矩阵（Record/Enum/主键变更）。

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use ct_cache::fingerprint::{
    data_fingerprint, decide_artifact_reuse, effective_translation_semantics, i18n_fingerprint,
    schema_fingerprint, ArtifactFingerprints,
};

fn golden() -> serde_json::Value {
    let path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/fingerprints/golden.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn fingerprints_match_python() {
    let golden = golden();
    let inputs = &golden["inputs"];
    let table = inputs["table"].clone();
    let deps: Vec<serde_json::Value> =
        serde_json::from_value(inputs["dependencies"].clone()).unwrap();
    let indexes: Vec<serde_json::Value> =
        serde_json::from_value(inputs["indexes"].clone()).unwrap();
    let codegen = inputs["codegen"].as_str().unwrap();

    let schema_fp = schema_fingerprint(&table, &deps, &indexes, codegen);
    assert_eq!(
        schema_fp,
        golden["schemaFingerprint"].as_str().unwrap(),
        "schema 指纹不一致"
    );

    let data_fp = data_fingerprint(
        &schema_fp,
        inputs["excelHash"].as_str().unwrap(),
        &inputs["parsing"],
    );
    assert_eq!(data_fp, golden["dataFingerprint"].as_str().unwrap());

    let entries: BTreeMap<String, serde_json::Value> =
        serde_json::from_value(inputs["entries"].clone()).unwrap();
    let valid_keys: BTreeSet<String> = serde_json::from_value(inputs["validKeys"].clone()).unwrap();
    let i18n_fp = i18n_fingerprint(
        &data_fp,
        inputs["lang"].as_str().unwrap(),
        inputs["primaryLang"].as_str().unwrap(),
        &serde_json::from_value::<Vec<String>>(inputs["enabledLangs"].clone()).unwrap(),
        &valid_keys,
        &entries,
    );
    assert_eq!(i18n_fp, golden["i18nFingerprint"].as_str().unwrap());

    // 有效语义：仅有效 key 的 text/confirmed；派生 status/source 不参与
    let semantics = effective_translation_semantics(&entries, &valid_keys);
    let expected: Vec<(String, String, bool)> = golden["semantics"]
        .as_array()
        .unwrap()
        .iter()
        .map(|item| {
            (
                item[0].as_str().unwrap().to_string(),
                item[1].as_str().unwrap().to_string(),
                item[2].as_bool().unwrap(),
            )
        })
        .collect();
    assert_eq!(semantics, expected);
}

#[test]
fn semantics_ignore_derived_metadata() {
    // 同一 text/confirmed 不同的 status/source → 语义不变（翻译无效元信息不触发重建）
    let mut a = BTreeMap::new();
    a.insert(
        "1.Name".to_string(),
        serde_json::json!({"text": "X", "confirmed": true, "status": "confirmed", "source": "剑"}),
    );
    let mut b = BTreeMap::new();
    b.insert(
        "1.Name".to_string(),
        serde_json::json!({"text": "X", "confirmed": true, "status": "stale", "source": "别的来源"}),
    );
    let keys: BTreeSet<String> = ["1.Name".to_string()].into_iter().collect();
    assert_eq!(
        effective_translation_semantics(&a, &keys),
        effective_translation_semantics(&b, &keys)
    );
}

#[test]
fn reuse_decision_matrix() {
    let langs = vec!["en".to_string(), "ja".to_string()];
    let previous = ArtifactFingerprints {
        schema: "s1".into(),
        data: "d1".into(),
        i18n: [("en".to_string(), "i1".to_string())].into_iter().collect(),
    };
    // 无历史 → 全不 reuse
    let decision = decide_artifact_reuse(None, &previous, &langs);
    assert!(!decision.schema_reusable && !decision.data_reusable);

    // 完全相同 → 全 reuse；缺 ja 语言指纹 → ja 不 reuse
    let decision = decide_artifact_reuse(Some(&previous), &previous, &langs);
    assert!(decision.schema_reusable && decision.data_reusable);
    assert!(decision.i18n_reusable["en"]);
    assert!(!decision.i18n_reusable["ja"]);

    // schema 变（Record/Enum/索引变更）→ schema 产物失效，data 可复用
    let changed_schema = ArtifactFingerprints {
        schema: "s2".into(),
        ..previous.clone()
    };
    let decision = decide_artifact_reuse(Some(&previous), &changed_schema, &langs);
    assert!(!decision.schema_reusable && decision.data_reusable);

    // data 变（Excel/解析输入变更）→ data 与全部 i18n 失效
    let changed_data = ArtifactFingerprints {
        data: "d2".into(),
        ..previous.clone()
    };
    let decision = decide_artifact_reuse(Some(&previous), &changed_data, &langs);
    assert!(decision.schema_reusable && !decision.data_reusable);
    assert!(decision.i18n_reusable.values().all(|v| !*v));
}

#[test]
fn ref_target_primary_key_change_invalidates_schema() {
    // ref 目标表主键删除：依赖它的表必须失效（schema 指纹含传递依赖）
    let golden = golden();
    let inputs = &golden["inputs"];
    let deps: Vec<serde_json::Value> =
        serde_json::from_value(inputs["dependencies"].clone()).unwrap();
    let indexes: Vec<serde_json::Value> =
        serde_json::from_value(inputs["indexes"].clone()).unwrap();
    let base = schema_fingerprint(
        &inputs["table"],
        &deps,
        &indexes,
        inputs["codegen"].as_str().unwrap(),
    );
    // 依赖内容变化 → 指纹变化
    let mut changed = deps.clone();
    changed[0]["values"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::json!({"name": "Epic"}));
    let after = schema_fingerprint(
        &inputs["table"],
        &changed,
        &indexes,
        inputs["codegen"].as_str().unwrap(),
    );
    assert_ne!(base, after, "Record/Enum 依赖变更必须失效");
}

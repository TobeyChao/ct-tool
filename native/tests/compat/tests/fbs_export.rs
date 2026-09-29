//! FBS 文本对照（rust-native-core 任务 3.2）：types.fbs 与单表 fbs
//! 与 Python golden 逐字节一致；结构检查覆盖重复符号/缺失类型。

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;

use ct_domain::graph::resource_topological_order;
use ct_domain::repository::{Resource, YamlResourceRepository};
use ct_domain::schema::TableResource;
use ct_export::fbs::{table_fbs_text, types_fbs_text, validate_canonical_fbs};
use serde_json::Value;

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/template")
}

/// 用与 Python 生成器相同的仓库加载路径构建解析态资源。
fn load_resources() -> (Vec<Resource>, tempfile::TempDir) {
    let dir = tempfile::tempdir().unwrap();
    let schemas_dir = dir.path().join("config/schemas");
    let types_dir = dir.path().join("config/types");
    std::fs::create_dir_all(&schemas_dir).unwrap();
    std::fs::create_dir_all(&types_dir).unwrap();

    let schema: Value = serde_json::from_str(
        &std::fs::read_to_string(fixtures_dir().join("schema_v1.json")).unwrap(),
    )
    .unwrap();
    std::fs::write(
        schemas_dir.join("item.yaml"),
        serde_json::to_string_pretty(&schema["table"]).unwrap(),
    )
    .unwrap();
    let buff: Value = serde_json::from_str(
        &std::fs::read_to_string(fixtures_dir().join("schema_buff.json")).unwrap(),
    )
    .unwrap();
    std::fs::write(
        schemas_dir.join("buff.yaml"),
        serde_json::to_string_pretty(&buff["table"]).unwrap(),
    )
    .unwrap();
    for (name, spec) in schema["records"].as_object().unwrap() {
        let mut doc = spec.clone();
        doc["kind"] = Value::String("record".into());
        doc["name"] = Value::String(name.clone());
        std::fs::write(
            types_dir.join(format!("{name}.yaml")),
            serde_json::to_string_pretty(&doc).unwrap(),
        )
        .unwrap();
    }
    let enums_doc: Value =
        serde_json::from_str(&std::fs::read_to_string(fixtures_dir().join("enums.json")).unwrap())
            .unwrap();
    for (name, spec) in enums_doc.as_object().unwrap() {
        let mut doc = spec.clone();
        doc["kind"] = Value::String("enum".into());
        doc["name"] = Value::String(name.clone());
        std::fs::write(
            types_dir.join(format!("{name}.yaml")),
            serde_json::to_string_pretty(&doc).unwrap(),
        )
        .unwrap();
    }

    let repo = YamlResourceRepository::new(schemas_dir, types_dir);
    let ws = repo.load().unwrap();
    let resources: Vec<Resource> = ws
        .tables
        .iter()
        .cloned()
        .map(Resource::Table)
        .chain(ws.records.iter().cloned().map(Resource::Record))
        .chain(ws.enums.iter().cloned().map(Resource::Enum))
        .collect();
    (resources, dir)
}

#[test]
fn types_fbs_matches_python() {
    let (resources, _dir) = load_resources();
    let order = resource_topological_order(&resources).unwrap();
    let map: BTreeMap<String, Resource> = resources
        .iter()
        .map(|r| (r.resource_id(), r.clone()))
        .collect();
    let text = types_fbs_text(&order, &map);
    let golden =
        std::fs::read_to_string(fixtures_dir().join("expected").join("types.fbs.txt")).unwrap();
    assert_eq!(text, golden, "types.fbs 不一致");
}

#[test]
fn table_fbs_matches_python() {
    let (resources, _dir) = load_resources();
    let map: HashMap<String, TableResource> = resources
        .iter()
        .filter_map(|r| match r {
            Resource::Table(t) => Some((t.table.clone(), t.clone())),
            _ => None,
        })
        .collect();
    for name in ["Item", "Buff"] {
        let text = table_fbs_text(&map[name]);
        let golden = std::fs::read_to_string(
            fixtures_dir()
                .join("expected")
                .join(format!("{name}.fbs.txt")),
        )
        .unwrap();
        assert_eq!(text, golden, "{name}.fbs 不一致");
    }
}

#[test]
fn structural_validation() {
    let (resources, _dir) = load_resources();
    let order = resource_topological_order(&resources).unwrap();
    let map: BTreeMap<String, Resource> = resources
        .iter()
        .map(|r| (r.resource_id(), r.clone()))
        .collect();
    let types_text = types_fbs_text(&order, &map);
    let table_texts: HashMap<String, String> = resources
        .iter()
        .filter_map(|r| match r {
            Resource::Table(t) => Some((t.table.clone(), table_fbs_text(t))),
            _ => None,
        })
        .collect();
    validate_canonical_fbs(&types_text, &table_texts, &resources).unwrap();

    // 重复符号被拒绝
    let dup = format!("{types_text}\nenum Dup : byte {{ A = 0 }}\nenum Dup : byte {{ B = 0 }}\n");
    let err = validate_canonical_fbs(&dup, &table_texts, &resources).unwrap_err();
    assert!(err.contains("重复符号"), "{err}");

    // types.fbs 不得 include
    let err = validate_canonical_fbs("include \"x.fbs\";", &table_texts, &resources).unwrap_err();
    assert!(err.contains("include"), "{err}");
}

//! canonical hash / revision / candidateHash / netDiff / dump_yaml 的
//! Python 逐值对照（rust-native-core 任务 3.12）。
//!
//! golden 由 `native/fixtures/schema_state/generate.py` 用 Python 实现计算；
//! 工作区文件与 commands.json 两侧共享（fixture 目录强制 LF，见 .gitattributes）。

use std::collections::BTreeMap;
use std::path::PathBuf;

use ct_app::schema::{build_schema_revision, capture_schema_contents, dump_yaml, SchemaSession};
use ct_domain::commands::Command;
use ct_domain::hashing::{compute_resource_hash, compute_schema_hash};
use ct_domain::repository::Resource;

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/schema_state")
}

fn golden() -> serde_json::Value {
    let text = std::fs::read_to_string(fixture_dir().join("golden.json")).unwrap();
    serde_json::from_str(&text).unwrap()
}

fn commands() -> Vec<Command> {
    let text = std::fs::read_to_string(fixture_dir().join("commands.json")).unwrap();
    let entries: Vec<serde_json::Value> = serde_json::from_str(&text).unwrap();
    entries
        .into_iter()
        .map(|entry| Command {
            kind: entry["kind"].as_str().unwrap().to_string(),
            payload: entry["payload"].clone(),
        })
        .collect()
}

fn open_session() -> SchemaSession {
    SchemaSession::open(&fixture_dir().join("workspace")).unwrap()
}

#[test]
fn schema_revision_matches_python() {
    let session = open_session();
    let golden = golden();
    let expected = &golden["schemaRevision"];
    assert_eq!(
        session.revision.revision,
        expected["revision"].as_str().unwrap(),
        "schemaRevision 不一致（注意 fixture 必须 LF 落盘）"
    );
    assert_eq!(
        session.revision.config_digest,
        golden["configDigest"].as_str().unwrap()
    );
    let expected_members: BTreeMap<String, String> = expected["members"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
        .collect();
    assert_eq!(session.revision.members, expected_members);

    // 同一输入重复计算必须稳定（升级/重启不误报 drifted）
    let again = build_schema_revision(&session.config, &capture_schema_contents(&session.config));
    assert_eq!(again.revision, session.revision.revision);
}

#[test]
fn resource_and_schema_hashes_match_python() {
    let session = open_session();
    let golden = golden();
    let expected = golden["resourceHashes"].as_object().unwrap();
    for resource in &session.resources {
        let actual = compute_resource_hash(resource);
        let expected_hash = expected
            .get(&resource.resource_id())
            .unwrap_or_else(|| panic!("golden 缺少 {}", resource.resource_id()))
            .as_str()
            .unwrap();
        assert_eq!(
            actual,
            expected_hash,
            "{} 哈希不一致",
            resource.resource_id()
        );
    }

    let item = session
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Item")
        .unwrap();
    let Resource::Table(item_table) = item else {
        panic!("Item 必须是 Table");
    };
    assert_eq!(
        compute_schema_hash(item_table, &session.resources),
        golden["schemaHashItem"].as_str().unwrap(),
        "canonical schema hash 不一致（默认值省略/键排序规则漂移）"
    );
}

#[test]
fn candidate_hash_and_netdiff_match_python() {
    let session = open_session();
    let commands = commands();
    let cursor = commands.len();
    let candidate = session.candidate(&commands, cursor).unwrap();
    assert!(candidate.issues.is_empty(), "{:?}", candidate.issues);

    let golden = golden();
    assert_eq!(
        candidate.hash,
        golden["candidateHash"].as_str().unwrap(),
        "candidateHash 不一致"
    );

    let actual_diff = candidate.net_diff.to_payload();
    let expected_diff = &golden["netDiff"];
    assert_eq!(
        serde_json::to_string_pretty(&ct_domain::hashing::sort_keys(&actual_diff)).unwrap(),
        serde_json::to_string_pretty(&ct_domain::hashing::sort_keys(expected_diff)).unwrap(),
        "netDiff 负载不一致"
    );
}

#[test]
fn dump_yaml_matches_python_bytes() {
    let session = open_session();
    let commands = commands();
    let cursor = commands.len();
    let candidate = session.candidate(&commands, cursor).unwrap();
    let golden = golden();

    let goods = candidate
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Goods")
        .expect("候选应包含改名后的 Goods");
    let actual = dump_yaml(&ct_domain::hashing::resource_to_data(goods));
    assert_eq!(
        actual,
        golden["goodsYaml"].as_str().unwrap(),
        "Goods 表 YAML 字节不一致"
    );

    let rarity = candidate
        .resources
        .iter()
        .find(|r| r.resource_id() == "enum:Rarity")
        .unwrap();
    let actual = dump_yaml(&ct_domain::hashing::resource_to_data(rarity));
    assert_eq!(
        actual,
        golden["rarityYaml"].as_str().unwrap(),
        "Rarity 枚举 YAML 字节不一致"
    );
}

#[test]
fn hash_ignores_serialization_jitter() {
    // 同一资源的不同 YAML 拼写（键序/显式默认值）→ 相同哈希，不误报 drifted
    let a = "kind: record\nname: Bonus\nfields:\n  - name: Rate\n    type: float\n";
    let b = "kind: record\ncomment: \"\"\nname: Bonus\nfields:\n  - type: float\n    name: Rate\n    i18n: false\n";
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    for (name, content) in [("a", a), ("b", b)] {
        std::fs::create_dir_all(root.join(name).join("config/types")).unwrap();
        std::fs::write(
            root.join(name).join("config/global.yaml"),
            "primary_lang: zh\n",
        )
        .unwrap();
        std::fs::write(root.join(name).join("config/types/bonus.yaml"), content).unwrap();
    }
    let hash = |name: &str| {
        let session = SchemaSession::open(&root.join(name)).unwrap();
        compute_resource_hash(&session.resources[0])
    };
    assert_eq!(hash("a"), hash("b"), "序列化抖动不得改变 resourceHash");
}

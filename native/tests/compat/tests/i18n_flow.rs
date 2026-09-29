//! i18n 流程对照（rust-native-core 任务 3.7/3.8）：
//! 合并状态机、sync 骨架、四态统计、compact dry-run 与真实清理。

use std::collections::HashMap;
use std::path::Path;

use ct_app::i18n::{i18n_compact, i18n_status, i18n_sync};
use ct_app::workspace::Workspace;
use ct_domain::schema::{FieldDef, TableResource};
use ct_domain::types::TypeExpr;
use ct_excel::layout::build_layout;
use ct_excel::manifest::LayoutManifest;
use ct_excel::template::{EnumDoc, EnumItemDoc, EnumMap, TemplateWriter};
use ct_export::i18n::{compute_status, merge_lang_entry, serialize_i18n_object, LangStatus};
use serde_json::{Map, Value};

// ---- 纯函数状态机 ----

#[test]
fn status_machine() {
    assert_eq!(compute_status("", false, true), LangStatus::Missing);
    assert_eq!(compute_status("x", false, true), LangStatus::Stale);
    assert_eq!(compute_status("x", true, true), LangStatus::Translated);
    assert_eq!(compute_status("x", true, false), LangStatus::Orphan);
}

#[test]
fn merge_entry_rules() {
    // 新建
    let e = merge_lang_entry(Some("铁剑"), None);
    assert_eq!(e["status"], "missing");
    assert_eq!(e["source"], "铁剑");
    assert_eq!(e["confirmed"], false);

    // source 变化 → confirmed 重置
    let old = Map::from_iter([
        ("source".into(), Value::String("旧".into())),
        ("text".into(), Value::String("Old".into())),
        ("confirmed".into(), Value::Bool(true)),
    ]);
    let e = merge_lang_entry(Some("新"), Some(&old));
    assert_eq!(e["source"], "新");
    assert_eq!(e["text"], "Old"); // 保留译文
    assert_eq!(e["confirmed"], false);
    assert_eq!(e["status"], "stale");

    // orphan
    let e = merge_lang_entry(None, Some(&old));
    assert_eq!(e["status"], "orphan");
    assert_eq!(e["text"], "Old");
}

#[test]
fn serialize_format_matches_python() {
    // 与 merger._serialize_object 同形态：每 key 一行、键序按 id+字段序、值带空格分隔
    let mut data = HashMap::new();
    for (key, source, text, confirmed) in [
        ("2.Desc", "红药", "Potion", true),
        ("10.Desc", "大剑", "", false),
        ("1.Desc", "铁剑", "Sword", true),
    ] {
        let mut entry = Map::new();
        entry.insert("source".into(), Value::String(source.into()));
        entry.insert("text".into(), Value::String(text.into()));
        entry.insert("confirmed".into(), Value::Bool(confirmed));
        entry.insert("status".into(), Value::String("x".into()));
        data.insert(key.to_string(), entry);
    }
    let text = serialize_i18n_object(&data, &["Desc".to_string()]);
    let expected = "{\n  \"1.Desc\": {\"source\": \"铁剑\", \"text\": \"Sword\", \"confirmed\": true, \"status\": \"x\"},\n  \"2.Desc\": {\"source\": \"红药\", \"text\": \"Potion\", \"confirmed\": true, \"status\": \"x\"},\n  \"10.Desc\": {\"source\": \"大剑\", \"text\": \"\", \"confirmed\": false, \"status\": \"x\"}\n}\n";
    assert_eq!(text, expected);
}

// ---- 工作区级流程 ----

fn buff_table() -> TableResource {
    let f = |name: &str, t: &str, i18n: bool| FieldDef {
        name: name.into(),
        type_expr: TypeExpr::parse(t).unwrap(),
        i18n,
        ref_: None,
        server_only: false,
        comment: String::new(),
        excel_columns: None,
    };
    TableResource {
        table: "Buff".into(),
        primary: "Id".into(),
        fields: vec![f("Id", "int32", false), f("Desc", "string", true)],
        json_key: None,
        excel_file: None,
        indexes: vec![],
        uniform: true,
    }
}

fn setup_workspace() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    std::fs::create_dir_all(root.join("config/schemas")).unwrap();
    std::fs::create_dir_all(root.join("config/types")).unwrap();
    std::fs::write(
        root.join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs: [en, ja]\n",
    )
    .unwrap();
    std::fs::write(
        root.join("config/schemas/buff.yaml"),
        "table: Buff\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Desc\n    type: string\n    i18n: true\n",
    )
    .unwrap();

    // Excel：模板 + 两行数据
    let table = buff_table();
    let layout = build_layout(&table, "sha256:i18n", &HashMap::new());
    let enums: EnumMap = [(
        "ItemRarity".to_string(),
        EnumDoc {
            comment: String::new(),
            values: vec![EnumItemDoc {
                name: "Common".into(),
                comment: String::new(),
            }],
        },
    )]
    .into_iter()
    .collect();
    let mut workbook = rust_xlsxwriter::Workbook::new();
    {
        let ws = workbook.add_worksheet();
        let mut writer = TemplateWriter::new(&layout, &enums, "Id");
        writer.write_sheet(ws).unwrap();
        for (i, (id, desc)) in [(1.0, "铁剑"), (2.0, "红药")].iter().enumerate() {
            let row = layout.header_rows + i as u32;
            ws.write_number(row, 0, *id).unwrap();
            ws.write_string(row, 1, *desc).unwrap();
        }
    }
    let bytes = workbook.save_to_buffer().unwrap();
    std::fs::create_dir_all(root.join("excel/layout_manifests")).unwrap();
    std::fs::write(root.join("excel/Buff.xlsx"), bytes).unwrap();
    let manifest = LayoutManifest::from_layout(&layout, &[]);
    std::fs::write(
        root.join("excel/layout_manifests/Buff.json"),
        serde_json::to_string_pretty(&manifest.payload()).unwrap(),
    )
    .unwrap();
    dir
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

#[test]
fn sync_status_compact_roundtrip() {
    let dir = setup_workspace();
    let root = dir.path();

    // 1) sync：生成 source + 两语言骨架
    let ws = Workspace::open(root).unwrap();
    let messages = i18n_sync(&ws, None, None).unwrap();
    assert!(
        messages.last().unwrap().contains("1 张表 × 2 语言"),
        "{messages:?}"
    );
    let source = read_json(&root.join("i18n/source/Buff.json"));
    assert_eq!(source["1.Desc"], "铁剑");
    assert_eq!(source["2.Desc"], "红药");
    let en = read_json(&root.join("i18n/en/Buff.json"));
    assert_eq!(en["1.Desc"]["status"], "missing");

    // 2) 翻译一条（手工编辑 en 文件）→ status 反映
    let mut en_map: Map<String, Value> = en.as_object().unwrap().clone();
    let mut entry = en_map["1.Desc"].as_object().unwrap().clone();
    entry.insert("text".into(), Value::String("Sword".into()));
    entry.insert("confirmed".into(), Value::Bool(true));
    en_map.insert("1.Desc".into(), Value::Object(entry));
    std::fs::write(
        root.join("i18n/en/Buff.json"),
        serialize_i18n_object(
            &en_map
                .into_iter()
                .map(|(k, v)| {
                    let inner = v.as_object().unwrap().clone();
                    (k, inner)
                })
                .collect::<HashMap<String, Map<String, Value>>>(),
            &["Desc".to_string()],
        ),
    )
    .unwrap();
    let ws = Workspace::open(root).unwrap();
    let status = i18n_status(&ws);
    let en_status = &status["en"];
    assert_eq!(en_status["translated"], 1);
    assert_eq!(en_status["missing"], 1);
    assert_eq!(en_status["progress"], 0.5);

    // 3) compact：orphan dry-run 不动文件，真实执行清理
    let mut with_orphan = read_json(&root.join("i18n/ja/Buff.json"));
    with_orphan["99.Desc"] =
        serde_json::json!({"source": "x", "text": "y", "confirmed": true, "status": "orphan"});
    std::fs::write(
        root.join("i18n/ja/Buff.json"),
        serde_json::to_string_pretty(&with_orphan).unwrap(),
    )
    .unwrap();
    let ws = Workspace::open(root).unwrap();
    let dry = i18n_compact(&ws, None, None, true).unwrap();
    assert_eq!(dry["total_removed"], 1);
    assert!(
        read_json(&root.join("i18n/ja/Buff.json"))["99.Desc"].is_object(),
        "dry-run 不应写文件"
    );
    let real = i18n_compact(&ws, None, None, false).unwrap();
    assert_eq!(real["total_removed"], 1);
    assert!(read_json(&root.join("i18n/ja/Buff.json"))["99.Desc"].is_null());
}

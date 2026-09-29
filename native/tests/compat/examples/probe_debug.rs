use ct_domain::schema::{FieldDef, TableResource};
use ct_domain::types::TypeExpr;
use ct_excel::layout::build_layout;
use ct_excel::reader::probe_xlsx;
use ct_excel::template::{EnumDoc, EnumItemDoc, EnumMap, TemplateWriter};
use std::collections::HashMap;

fn field(name: &str, t: &str) -> FieldDef {
    FieldDef {
        name: name.into(),
        type_expr: TypeExpr::parse(t).unwrap(),
        i18n: false,
        ref_: None,
        server_only: false,
        comment: String::new(),
        excel_columns: None,
    }
}

fn main() {
    let table = TableResource {
        table: "Item".into(),
        primary: "Id".into(),
        fields: vec![
            field("Id", "int32"),
            field("CodeName", "string"),
            field("Rarity", "ItemRarity"),
        ],
        json_key: None,
        excel_file: None,
        indexes: vec![ct_domain::schema::QueryIndex],
        uniform: true,
    };
    let layout = build_layout(&table, "sha256:test", &HashMap::new());
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
        ws.write_number(2, 0, 1.0).unwrap();
        ws.write_string(2, 1, "sword_iron").unwrap();
        ws.write_string(2, 2, "Common").unwrap();
    }
    let bytes = workbook.save_to_buffer().unwrap();
    let path = std::env::temp_dir().join("probe_debug.xlsx");
    std::fs::write(&path, bytes).unwrap();
    let report = probe_xlsx(&path).unwrap();
    for c in &report.cells {
        println!("row={} col={} {:?}", c.row, c.col, c.value);
    }
}

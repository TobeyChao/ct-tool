use ct_domain::schema::{FieldDef, TableResource};
use ct_domain::types::TypeExpr;
use ct_excel::layout::build_layout;
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
    println!("header_rows={}", layout.header_rows);
    for c in &layout.columns {
        println!("{} {} {}", c.index, c.stable_path, c.type_text);
    }
}

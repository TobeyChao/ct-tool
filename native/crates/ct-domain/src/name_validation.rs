//! 全局资源与生成 FlatBuffers 符号校验（对应 Python `ct/schema/name_validation.py`）。

use std::collections::BTreeMap;

use crate::repository::Resource;

/// 一处生成符号冲突。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedNameConflict {
    pub name: String,
    pub locations: Vec<String>,
    pub reason: String,
}

impl GeneratedNameConflict {
    pub fn render(&self) -> String {
        format!(
            "生成名称 '{}' {}: {}",
            self.name,
            self.reason,
            self.locations.join(", ")
        )
    }
}

/// 检查资源名/生成容器名/字段名在 FlatBuffers 符号空间里的冲突。
pub fn generated_name_conflicts(resources: &[Resource]) -> Vec<GeneratedNameConflict> {
    let mut symbols: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut add_symbol = |name: String, location: String| {
        symbols.entry(name).or_default().push(location);
    };

    let has_table = resources.iter().any(|r| matches!(r, Resource::Table(_)));
    for resource in resources {
        add_symbol(resource.name().to_string(), resource.resource_id());
        if let Resource::Table(table) = resource {
            add_symbol(
                format!("{}Table", table.table),
                format!("{}#container", table.resource_id()),
            );
            if table.fields.iter().any(|f| f.i18n) {
                add_symbol(
                    format!("{}I18nEntry", table.table),
                    format!("{}#i18n-entry", table.resource_id()),
                );
                add_symbol(
                    format!("{}I18nTable", table.table),
                    format!("{}#i18n-table", table.resource_id()),
                );
            }
        }
    }
    if has_table {
        add_symbol("IndexEntry".to_string(), "generated:index".to_string());
        add_symbol(
            "BundledTable".to_string(),
            "generated:bundle-entry".to_string(),
        );
        add_symbol(
            "DataBundle".to_string(),
            "generated:bundle-root".to_string(),
        );
    }

    let mut conflicts = Vec::new();
    for (name, locations) in &symbols {
        if locations.len() > 1 {
            let mut sorted = locations.clone();
            sorted.sort();
            conflicts.push(GeneratedNameConflict {
                name: name.clone(),
                locations: sorted,
                reason: "由多个类型生成".to_string(),
            });
        }
    }

    for resource in resources {
        let fields: &[crate::schema::FieldDef] = match resource {
            Resource::Table(t) => &t.fields,
            Resource::Record(r) => &r.fields,
            Resource::Enum(_) => continue,
        };
        for field in fields {
            let Some(type_locations) = symbols.get(&field.name) else {
                continue;
            };
            let mut locations = vec![format!("{}/{}", resource.resource_id(), field.name)];
            let mut sorted = type_locations.clone();
            sorted.sort();
            locations.extend(sorted);
            conflicts.push(GeneratedNameConflict {
                name: field.name.clone(),
                locations,
                reason: "同时用作字段名与 FlatBuffers 类型名".to_string(),
            });
        }
    }
    conflicts
}

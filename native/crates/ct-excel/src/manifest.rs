//! 布局 manifest（`ct/excel/layout_manifest.py`）：
//! `excel/layout_manifests/<table>.json` 的读写与格式闸门。
//!
//! 字段集合是 schema 的纯函数；定宽布局由 schema 的 uniform 声明决定，
//! 填充率不落盘 —— 改 Excel 数据不会让 manifest 变。

use serde_json::{json, Map, Value};

use crate::layout::Layout;

pub const MANIFEST_FORMAT: &str = "template-layout/2";

/// 布局 manifest。
#[derive(Debug, Clone, PartialEq)]
pub struct LayoutManifest {
    pub schema_hash: String,
    pub header_rows: u32,
    pub columns: Vec<Map<String, Value>>,
    pub nodes: Vec<Map<String, Value>>,
    /// slot → 行内字节偏移（仅定宽表有意义）。
    pub slot_offsets: Vec<(u32, u32)>,
}

impl LayoutManifest {
    /// 从布局构造（字段集合是 schema 的纯函数）。
    pub fn from_layout(layout: &Layout, slot_offsets: &[(u32, u32)]) -> Self {
        let columns = layout
            .columns
            .iter()
            .map(|c| {
                let mut map = Map::new();
                map.insert("index".into(), json!(c.index));
                map.insert("stablePath".into(), json!(c.stable_path));
                map.insert("typeExpr".into(), json!(c.type_text));
                map.insert("annotation".into(), json!(c.annotation));
                map.insert("leaf".into(), json!(c.leaf));
                map.insert("depth".into(), json!(c.depth));
                if let Some(g) = c.group_index {
                    map.insert("groupIndex".into(), json!(g));
                }
                map
            })
            .collect();
        let nodes = layout
            .nodes
            .iter()
            .map(|n| {
                let mut map = Map::new();
                map.insert("stablePath".into(), json!(n.stable_path));
                map.insert("displayName".into(), json!(n.display_name));
                map.insert("annotation".into(), json!(n.annotation));
                map.insert("comment".into(), json!(n.comment));
                map.insert("kind".into(), json!(n.kind));
                map.insert("depth".into(), json!(n.depth));
                map.insert("children".into(), json!(n.children));
                map.insert("slotIndex".into(), json!(n.slot_index));
                map.insert("leafStart".into(), json!(n.leaf_start));
                map.insert("leafEnd".into(), json!(n.leaf_end));
                map
            })
            .collect();
        LayoutManifest {
            schema_hash: layout.schema_hash.clone(),
            header_rows: layout.header_rows,
            columns,
            nodes,
            slot_offsets: {
                let mut v = slot_offsets.to_vec();
                v.sort();
                v
            },
        }
    }

    /// 解析（格式不符/损坏返回 None）。
    pub fn parse(data: &Value) -> Option<Self> {
        if data.get("format")?.as_str()? != MANIFEST_FORMAT {
            return None;
        }
        let columns = data
            .get("columns")?
            .as_array()?
            .iter()
            .filter_map(|c| c.as_object().cloned())
            .collect();
        let nodes = data
            .get("nodes")?
            .as_array()?
            .iter()
            .filter_map(|c| c.as_object().cloned())
            .collect();
        let slot_offsets = data
            .get("slot_offsets")?
            .as_array()?
            .iter()
            .filter_map(|pair| {
                let arr = pair.as_array()?;
                Some((arr.first()?.as_u64()? as u32, arr.get(1)?.as_u64()? as u32))
            })
            .collect();
        Some(LayoutManifest {
            schema_hash: data.get("schema_hash")?.as_str()?.to_string(),
            header_rows: data.get("header_rows")?.as_u64()? as u32,
            columns,
            nodes,
            slot_offsets,
        })
    }

    /// 从 manifest 重建旧布局（迁移用）。
    pub fn to_layout(&self, table_id: &str) -> crate::layout::Layout {
        let columns = self
            .columns
            .iter()
            .map(|c| crate::layout::Column {
                index: c.get("index").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                stable_path: c
                    .get("stablePath")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                type_text: c
                    .get("typeExpr")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                annotation: c
                    .get("annotation")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                leaf: c
                    .get("leaf")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                group_index: c
                    .get("groupIndex")
                    .and_then(|v| v.as_u64())
                    .map(|v| v as u32),
                depth: c.get("depth").and_then(|v| v.as_u64()).unwrap_or(1) as u32,
                comment: String::new(),
                field_comment: String::new(),
                field_annotation: String::new(),
                ref_: None,
                primary: false,
            })
            .collect();
        crate::layout::Layout {
            table_id: table_id.to_string(),
            schema_hash: self.schema_hash.clone(),
            header_rows: self.header_rows,
            columns,
            nodes: vec![],
        }
    }

    /// 序列化载荷（发布阶段收集 payload 用；键排序与缩进对齐 Python）。
    pub fn payload(&self) -> Value {
        json!({
            "format": MANIFEST_FORMAT,
            "schema_hash": self.schema_hash,
            "header_rows": self.header_rows,
            "columns": self.columns,
            "nodes": self.nodes,
            "slot_offsets": self.slot_offsets.iter().map(|(a, b)| json!([a, b])).collect::<Vec<_>>(),
        })
    }
}

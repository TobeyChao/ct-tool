//! 真实形状夹具生成（bench-real-shape 任务 3.x）：读冻结的 `shape-r.json`，
//! 用原生入口（ct-domain / ct-excel / ct-app）写出 schema、工作簿、布局 manifest 与
//! i18n 骨架，不依赖 `ct/` 在位，也不回退到 Python 参照。
//!
//! 数据值全部由「类名 + 行号 + 列号」的哈希确定性推出（不使用 PRNG 状态），因此同一份
//! 清单在任何机器上生成同一份输入。

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use ct_app::workspace::Workspace;
use ct_domain::hashing::{compute_schema_hash, python_json_pretty};
use ct_domain::repository::Resource;
use ct_domain::schema::{FieldDef, TableResource};
use ct_excel::layout::{build_layout, Layout};
use ct_excel::manifest::LayoutManifest;
use ct_excel::migrate::CellValue;
use ct_excel::template::{build_template_with_rows, EnumDoc, EnumItemDoc, EnumMap};
use ct_export::binary::plan_object_layout;
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::shape::{FieldShape, RecordShape, ShapeManifest, TableShape, SEED};

const SHAPE_FILE: &str = "native/fixtures/bench/shape-r.json";

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

pub fn generate(sizes: &[String], out: Option<PathBuf>) -> Result<()> {
    let shape_path = repo_root().join(SHAPE_FILE);
    let text = std::fs::read_to_string(&shape_path).with_context(|| {
        format!(
            "形状清单不可读：{}（先用 `cargo run -p ct-xtask -- bench-shape-freeze` 冻结）",
            shape_path.display()
        )
    })?;
    let manifest: ShapeManifest = serde_json::from_str(&text).context("形状清单不是合法 JSON")?;
    let out_dir = out.unwrap_or_else(|| repo_root().join("native/target/bench"));
    for size in sizes {
        generate_size(&manifest, size, &out_dir)?;
    }
    Ok(())
}

fn generate_size(manifest: &ShapeManifest, size: &str, out_dir: &Path) -> Result<()> {
    let tier = manifest
        .tiers
        .get(size)
        .with_context(|| format!("形状清单里没有档位 {size}"))?;
    let root = out_dir.join(format!("bench-{size}"));
    if root.exists() {
        std::fs::remove_dir_all(&root)
            .with_context(|| format!("清理旧夹具失败：{}", root.display()))?;
    }
    std::fs::create_dir_all(&root)?;

    let included: BTreeSet<String> = tier.tables.iter().cloned().collect();
    let tables: Vec<&TableShape> = tier
        .tables
        .iter()
        .map(|name| {
            manifest
                .tables
                .get(name)
                .with_context(|| format!("档位 {size} 引用了清单外的表 {name}"))
        })
        .collect::<Result<_>>()?;

    // ---- 1. config：全局配置 + 类型（record）+ 表 schema
    write_global_yaml(&root, manifest)?;
    let used_records = collect_used_records(manifest, &tables);
    write_types(&root, manifest, &used_records)?;
    write_schemas(&root, manifest, &tables, &included)?;

    // ---- 2. 装载工作区（与生产同一条 schema 解析路径）
    let ws = Workspace::open(&root).map_err(|e| anyhow::anyhow!("装载夹具工作区失败：{e}"))?;

    // ---- 3. 逐表写工作簿 + 布局 manifest
    let records_map = ws.resources.records_map();
    let enums = enum_map(&ws);
    let dep_resources: Vec<Resource> = ws
        .resources
        .records
        .iter()
        .cloned()
        .map(Resource::Record)
        .chain(ws.resources.enums.iter().cloned().map(Resource::Enum))
        .collect();
    let excel_dir = ws.excel_dir();
    std::fs::create_dir_all(&excel_dir)?;
    let manifest_dir = excel_dir.join("layout_manifests");
    std::fs::create_dir_all(&manifest_dir)?;

    let rows_by_table: BTreeMap<String, u64> = manifest
        .tables
        .iter()
        .map(|(name, shape)| (name.clone(), shape.rows))
        .collect();

    let mut written_cells = 0u64;
    for table in &ws.resources.tables {
        let shape = manifest
            .tables
            .get(&table.table)
            .with_context(|| format!("清单缺少表 {}", table.table))?;
        let schema_hash = compute_schema_hash(table, &dep_resources);
        let layout = build_layout(table, &schema_hash, &records_map);
        let (rows, cells) = build_rows(manifest, shape, &layout, &rows_by_table, &included, None)?;
        written_cells += cells;
        let (bytes, warnings) = build_template_with_rows(&layout, &enums, &table.primary, &rows)?;
        for warning in warnings {
            eprintln!("[fixture] {warning}");
        }
        std::fs::write(excel_dir.join(table.resolved_excel_file()), bytes)
            .with_context(|| format!("写入工作簿失败：{}", table.table))?;
        let doc = LayoutManifest::from_layout(&layout, &slot_offsets(&ws, table));
        std::fs::write(
            manifest_dir.join(format!("{}.json", table.table)),
            python_json_pretty(&doc.payload()) + "\n",
        )?;
    }
    println!(
        "[fixture] {size}：{} 张表 / {} 个数据单元格已写入 {}",
        ws.resources.tables.len(),
        written_cells,
        root.display()
    );

    // ---- 4. i18n 骨架（原生 sync，口径 A：每个 i18n 单元格一条）
    ct_app::i18n::i18n_sync(&ws, None, None).map_err(|e| anyhow::anyhow!("i18n sync 失败：{e}"))?;
    let translated = fill_translations(&root, manifest)?;

    // ---- 5. 变更场景素材
    let mutation = write_mutations(
        &ws,
        manifest,
        &included,
        &enums,
        &records_map,
        &rows_by_table,
    )?;

    // ---- 6. 清缓存/产物目录（保证两个引擎都从零缓存冷启动）
    for leftover in ["output", "cache", ".ct"] {
        let target = root.join(leftover);
        if target.exists() {
            std::fs::remove_dir_all(&target)?;
        }
    }

    let digest = input_digest(&root)?;
    let summary = json!({
        "schema": "ct-bench-fixture/1",
        "size": size,
        "seed": SEED,
        "tables": tier.totals.tables,
        "configTables": tier.totals.config_tables,
        "enumTables": tier.totals.enum_tables,
        "rows": tier.totals.rows,
        "rowsPerTable": null,
        "columnsPerTable": null,
        "dataCells": tier.totals.slots,
        "writtenCells": written_cells,
        "i18nFields": tier.totals.i18n_fields,
        "translatedEntries": translated,
        "translatedEntriesPerLang": tier.totals.i18n_slots,
        "vectorFields": tier.totals.vector_fields,
        "refEdges": tier.totals.ref_edges,
        "nestedRecords": tier.totals.nested_records,
        "maxHeaderRows": tier.totals.max_header_rows,
        "languages": std::iter::once(manifest.langs.primary.clone())
            .chain(manifest.langs.secondary.iter().cloned())
            .collect::<Vec<_>>(),
        "shape": "shape-r.json（冻结清单：行数取运行时 dump，字段语法取导表期类清单）",
        "uniform": "按冻结清单逐表形状生成：行数/字段数/嵌套深度/向量展开/enum 表/i18n 位置",
        "unmodelled": manifest.unmodelled,
        "mutation": mutation,
        "inputDigest": digest,
        "root": root.display().to_string(),
    });
    std::fs::write(
        root.join("FIXTURE.json"),
        serde_json::to_string_pretty(&summary)? + "\n",
    )?;
    println!(
        "[fixture] {size}：FIXTURE.json 已写入（输入摘要 {}）",
        &digest[..16.min(digest.len())]
    );
    Ok(())
}

// ---------------------------------------------------------------- schema 写入

fn write_global_yaml(root: &Path, manifest: &ShapeManifest) -> Result<()> {
    let dir = root.join("config");
    std::fs::create_dir_all(&dir)?;
    let mut text = format!(
        "primary_lang: {}\nsecondary_langs:\n",
        manifest.langs.primary
    );
    for lang in &manifest.langs.secondary {
        text.push_str(&format!("  - {lang}\n"));
    }
    std::fs::write(dir.join("global.yaml"), text)?;
    Ok(())
}

fn collect_used_records(manifest: &ShapeManifest, tables: &[&TableShape]) -> BTreeSet<String> {
    fn walk(manifest: &ShapeManifest, field: &FieldShape, used: &mut BTreeSet<String>) {
        let element = element_of(&field.ct_type).to_string();
        if let Some(record) = manifest.records.get(&element) {
            if used.insert(element.clone()) {
                for sub in &record.fields {
                    walk(manifest, sub, used);
                }
            }
        }
    }
    let mut used = BTreeSet::new();
    for table in tables {
        for field in &table.fields {
            walk(manifest, field, &mut used);
        }
    }
    used
}

fn write_types(root: &Path, manifest: &ShapeManifest, used: &BTreeSet<String>) -> Result<()> {
    let dir = root.join("config/types");
    std::fs::create_dir_all(&dir)?;
    let primaries: BTreeMap<&str, &str> = manifest
        .tables
        .iter()
        .map(|(name, shape)| (name.as_str(), shape.primary.as_str()))
        .collect();
    for name in used {
        let record: &RecordShape = manifest
            .records
            .get(name)
            .with_context(|| format!("清单缺少记录类型 {name}"))?;
        let mut text = String::from("kind: record\n");
        text.push_str(&format!("name: {name}\n"));
        text.push_str("fields:\n");
        for field in &record.fields {
            let target_primary = field
                .ref_target
                .as_deref()
                .and_then(|target| primaries.get(target).copied())
                .unwrap_or("Id");
            text.push_str(&field_yaml(field, 2, target_primary)?);
        }
        std::fs::write(dir.join(format!("{name}.yaml")), text)?;
    }
    Ok(())
}

fn write_schemas(
    root: &Path,
    manifest: &ShapeManifest,
    tables: &[&TableShape],
    included: &BTreeSet<String>,
) -> Result<()> {
    let dir = root.join("config/schemas");
    std::fs::create_dir_all(&dir)?;
    let primaries: BTreeMap<&str, &str> = manifest
        .tables
        .iter()
        .map(|(name, shape)| (name.as_str(), shape.primary.as_str()))
        .collect();
    let mut used_names: BTreeMap<String, String> = BTreeMap::new();
    for table in tables {
        let file = unique_file_name(&mut used_names, &table.class);
        let mut text = format!("table: {}\nprimary: {}\n", table.class, table.primary);
        text.push_str("fields:\n");
        for field in &table.fields {
            let mut field = field.clone();
            if let Some(target) = &field.ref_target {
                // 目标表不在本档位时不能声明 ref（否则 schema 拒绝）
                if !included.contains(target) {
                    field.ref_target = None;
                }
            }
            let target_primary = field
                .ref_target
                .as_deref()
                .and_then(|target| primaries.get(target).copied())
                .unwrap_or("Id");
            text.push_str(&field_yaml(&field, 2, target_primary)?);
        }
        // 有 CodeName 字段的表声明 codename 索引（值唯一且非空，见 build_rows）
        if table.fields.iter().any(|f| f.name == "CodeName") {
            text.push_str("indexes:\n  - kind: codename\n");
        }
        std::fs::write(dir.join(format!("{file}.yaml")), text)?;
    }
    Ok(())
}

/// 文件名去重（大小写不敏感）：表身份来自 YAML 内容，文件名只影响磁盘布局。
fn unique_file_name(used: &mut BTreeMap<String, String>, table: &str) -> String {
    let sanitized: String = table
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '_' })
        .collect();
    let key = sanitized.to_ascii_lowercase();
    match used.get(&key) {
        None => {
            used.insert(key, table.to_string());
            sanitized
        }
        Some(existing) if existing == table => sanitized,
        Some(_) => {
            let mut index = 2;
            loop {
                let candidate = format!("{sanitized}_{index}");
                let key = candidate.to_ascii_lowercase();
                if let std::collections::btree_map::Entry::Vacant(slot) = used.entry(key) {
                    slot.insert(table.to_string());
                    return candidate;
                }
                index += 1;
            }
        }
    }
}

fn field_yaml(field: &FieldShape, indent: usize, target_primary: &str) -> Result<String> {
    let pad = " ".repeat(indent);
    let mut text = format!("{pad}- name: {}\n", field.name);
    text.push_str(&format!("{pad}  type: {}\n", field.ct_type));
    if field.i18n {
        text.push_str(&format!("{pad}  i18n: true\n"));
    }
    if let Some(target) = &field.ref_target {
        text.push_str(&format!("{pad}  ref: {target}.{target_primary}\n"));
    }
    if let Some(width) = field.excel_columns {
        text.push_str(&format!("{pad}  excel_columns: {width}\n"));
    }
    Ok(text)
}

// ---------------------------------------------------------------- 行数据

fn element_of(ct_type: &str) -> &str {
    ct_type
        .strip_prefix("vector<")
        .and_then(|rest| rest.strip_suffix('>'))
        .unwrap_or(ct_type)
}

/// 为一个表生成数据行；返回 (行, 非空单元格数)。
fn build_rows(
    manifest: &ShapeManifest,
    shape: &TableShape,
    layout: &Layout,
    rows_by_table: &BTreeMap<String, u64>,
    included: &BTreeSet<String>,
    mutate: Option<usize>,
) -> Result<(Vec<Vec<Option<CellValue>>>, u64)> {
    let columns = &layout.columns;
    let row_count = shape.rows;
    let mut out = Vec::with_capacity(row_count as usize);
    let mut cells = 0u64;
    for row in 1..=row_count {
        let mut values: Vec<Option<CellValue>> = Vec::with_capacity(columns.len());
        for (index, column) in columns.iter().enumerate() {
            let value = cell_value(manifest, shape, column, row, index, rows_by_table, included)?;
            if value.is_some() {
                cells += 1;
            }
            values.push(value);
        }
        // 变更场景：改写一个非主键、非 i18n 的字符串列（只改一次）
        if let Some(target_row) = mutate {
            if target_row as u64 == row {
                if let Some(column) = mutation_column(shape, layout) {
                    values[column] = Some(CellValue::Text("bench-mutation".to_string()));
                }
            }
        }
        out.push(values);
    }
    Ok((out, cells))
}

/// 沿稳定路径解析出该列对应的**叶字段**（跨 record / 向量组下钻），用于判定单格 vector。
fn leaf_field<'a>(
    manifest: &'a ShapeManifest,
    shape: &'a TableShape,
    stable_path: &str,
) -> Option<&'a FieldShape> {
    let tail = stable_path.split_once('/').map(|(_, rest)| rest)?;
    let segments: Vec<&str> = tail.split('/').collect();
    let mut table_scope: Option<&TableShape> = Some(shape);
    let mut record_scope: Option<&RecordShape> = None;
    let mut result: Option<&FieldShape> = None;
    for (index, segment) in segments.iter().enumerate() {
        let name = segment.split('[').next().unwrap_or(segment);
        let fields: &[FieldShape] = match (table_scope, record_scope) {
            (Some(table), None) => &table.fields,
            (None, Some(record)) => &record.fields,
            _ => return None,
        };
        let found = fields.iter().find(|f| f.name == name)?;
        result = Some(found);
        if index + 1 == segments.len() {
            break;
        }
        let element = element_of(&found.ct_type);
        let record = manifest.records.get(element)?;
        table_scope = None;
        record_scope = Some(record);
    }
    result
}

/// 挑一个稳定的变更列：字符串、非主键、不属于 i18n 字段。
fn mutation_column(shape: &TableShape, layout: &Layout) -> Option<usize> {
    let i18n: BTreeSet<&str> = shape
        .fields
        .iter()
        .filter(|f| f.i18n)
        .map(|f| f.name.as_str())
        .collect();
    layout.columns.iter().position(|column| {
        if column.primary || column.type_text != "string" {
            return false;
        }
        let top = column
            .stable_path
            .split('/')
            .nth(1)
            .unwrap_or("")
            .split('[')
            .next()
            .unwrap_or("");
        !i18n.contains(top)
    })
}

fn cell_value(
    manifest: &ShapeManifest,
    shape: &TableShape,
    column: &ct_excel::layout::Column,
    row: u64,
    index: usize,
    rows_by_table: &BTreeMap<String, u64>,
    included: &BTreeSet<String>,
) -> Result<Option<CellValue>> {
    let key = splitmix64(SEED ^ fnv1a(&format!("{}.{}.{}", shape.class, row, index)));

    // 主键：行号（唯一、非空）
    if column.primary {
        return Ok(Some(CellValue::Number(row as f64)));
    }

    // 外键：目标表在本档位且有行时取合法 id，否则留空
    if let Some(ref_text) = &column.ref_ {
        let target = ref_text.split('.').next().unwrap_or("");
        if !included.contains(target) {
            return Ok(None);
        }
        let rows = rows_by_table.get(target).copied().unwrap_or(0);
        if rows == 0 {
            return Ok(None);
        }
        return Ok(Some(CellValue::Number((key % rows + 1) as f64)));
    }

    // 未分组的变长 vector：单格 [...] 文法（判定来自 schema，不看列上的组标记）
    let single_cell_vector = leaf_field(manifest, shape, &column.stable_path)
        .is_some_and(|field| field.ct_type.starts_with("vector<") && field.excel_columns.is_none());
    if single_cell_vector {
        let text = vector_cell(&column.type_text, shape, column, row, key);
        return Ok(Some(CellValue::Text(text)));
    }

    Ok(Some(scalar_cell(
        &column.type_text,
        shape,
        column,
        row,
        key,
    )))
}

fn vector_cell(
    element_text: &str,
    shape: &TableShape,
    column: &ct_excel::layout::Column,
    row: u64,
    key: u64,
) -> String {
    let count = 1 + (key % 3) as usize;
    let leaf = column.leaf.as_str();
    let items: Vec<String> = (0..count)
        .map(|i| match element_text {
            "string" => format!("\"{leaf}_{row}_{i}\""),
            "bool" => if (key >> i) % 2 == 0 { "TRUE" } else { "FALSE" }.to_string(),
            "float" | "double" => format!("{}", ((key >> i) % 1000) as f64 / 10.0),
            _ => format!("{}", (key >> i) % 1000),
        })
        .collect();
    let _ = shape;
    format!("[{}]", items.join(","))
}

fn scalar_cell(
    type_text: &str,
    shape: &TableShape,
    column: &ct_excel::layout::Column,
    row: u64,
    key: u64,
) -> CellValue {
    match type_text {
        "int8" | "int16" | "int32" | "int64" | "uint8" | "uint16" | "uint32" | "uint64" => {
            CellValue::Number((key % 100_000) as f64)
        }
        "float" | "double" => CellValue::Number(((key % 10_000) as f64) / 100.0),
        "bool" => CellValue::Bool(key % 2 == 0),
        "string" => {
            // 非空唯一文本：既满足 codename 唯一性，也保证 i18n source 每条都有内容
            CellValue::Text(format!("{}_{}_{}", column.leaf, shape.class, row))
        }
        other => CellValue::Text(format!("{other}_{row}")),
    }
}

// ---------------------------------------------------------------- i18n

fn fill_translations(root: &Path, manifest: &ShapeManifest) -> Result<u64> {
    let dir = root.join("i18n");
    let mut written = 0u64;
    for lang in &manifest.langs.secondary {
        let lang_dir = dir.join(lang);
        if !lang_dir.is_dir() {
            continue;
        }
        let mut files: Vec<PathBuf> = std::fs::read_dir(&lang_dir)?
            .filter_map(|entry| entry.ok().map(|e| e.path()))
            .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
            .collect();
        files.sort();
        for path in files {
            let text = std::fs::read_to_string(&path)?;
            let mut payload: serde_json::Map<String, serde_json::Value> =
                serde_json::from_str(&text)
                    .with_context(|| format!("i18n 骨架不是合法 JSON：{}", path.display()))?;
            for (_, entry) in payload.iter_mut() {
                let Some(object) = entry.as_object_mut() else {
                    continue;
                };
                let source = object
                    .get("source")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                object.insert(
                    "text".into(),
                    serde_json::Value::String(format!("[{lang}] {source}")),
                );
                object.insert("confirmed".into(), serde_json::Value::Bool(true));
                object.insert(
                    "status".into(),
                    serde_json::Value::String("confirmed".to_string()),
                );
                written += 1;
            }
            std::fs::write(&path, serde_json::to_string_pretty(&payload)? + "\n")?;
        }
    }
    Ok(written)
}

// ---------------------------------------------------------------- 变更素材

fn write_mutations(
    ws: &Workspace,
    manifest: &ShapeManifest,
    included: &BTreeSet<String>,
    enums: &EnumMap,
    records_map: &std::collections::HashMap<String, ct_domain::schema::RecordResource>,
    rows_by_table: &BTreeMap<String, u64>,
) -> Result<serde_json::Value> {
    // 变更目标：优先 ActivityRecharge，否则取行数适中的带 i18n 表
    let mut candidates: Vec<&TableShape> = included
        .iter()
        .filter_map(|name| manifest.tables.get(name))
        .filter(|table| table.kind == "config")
        .filter(|table| table.fields.iter().any(|f| f.i18n))
        .filter(|table| (20..=500).contains(&table.rows))
        .collect();
    candidates.sort_by(|a, b| {
        a.rows
            .abs_diff(175)
            .cmp(&b.rows.abs_diff(175))
            .then_with(|| a.class.cmp(&b.class))
    });
    let target = candidates
        .iter()
        .find(|table| table.class == "ActivityRecharge")
        .or_else(|| candidates.first())
        .context("档位里找不到可做变更场景的带 i18n 表")?
        .class
        .clone();

    let out = ws.root.join("mutations");
    std::fs::create_dir_all(&out)?;
    let table = ws
        .resources
        .tables
        .iter()
        .find(|t| t.table == target)
        .with_context(|| format!("工作区缺少表 {target}"))?;
    let schema_hash = compute_schema_hash(
        table,
        &ws.resources
            .records
            .iter()
            .cloned()
            .map(Resource::Record)
            .chain(ws.resources.enums.iter().cloned().map(Resource::Enum))
            .collect::<Vec<_>>(),
    );
    let layout = build_layout(table, &schema_hash, records_map);
    let shape = manifest
        .tables
        .get(&target)
        .with_context(|| format!("清单缺少表 {target}"))?;
    let (rows, _) = build_rows(manifest, shape, &layout, rows_by_table, included, Some(1))?;
    let (bytes, _) = build_template_with_rows(&layout, enums, &table.primary, &rows)?;
    std::fs::write(out.join(format!("{target}.xlsx")), bytes)?;

    // 译文变更：改第一个语言的第一条条目
    let lang = manifest
        .langs
        .secondary
        .first()
        .context("清单没有次语言")?
        .clone();
    let i18n_path = ws
        .root
        .join("i18n")
        .join(&lang)
        .join(format!("{target}.json"));
    let text = std::fs::read_to_string(&i18n_path)
        .with_context(|| format!("缺少 i18n 文件：{}", i18n_path.display()))?;
    let mut payload: serde_json::Map<String, serde_json::Value> = serde_json::from_str(&text)?;
    let mut mutated = false;
    for (_, entry) in payload.iter_mut() {
        if let Some(object) = entry.as_object_mut() {
            let current = object
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            object.insert(
                "text".into(),
                serde_json::Value::String(format!("{current}!")),
            );
            object.insert("confirmed".into(), serde_json::Value::Bool(false));
            object.insert(
                "status".into(),
                serde_json::Value::String("pending".to_string()),
            );
            mutated = true;
            break;
        }
    }
    if !mutated {
        bail!("表 {target} 的 i18n 骨架里没有可变更条目");
    }
    std::fs::write(
        out.join(format!("{target}.json")),
        serde_json::to_string_pretty(&payload)? + "\n",
    )?;

    let meta = json!({
        "table": target,
        "tableSource": format!("excel/{target}.xlsx"),
        "i18nLang": lang,
        "i18nTarget": format!("i18n/{lang}/{target}.json"),
    });
    std::fs::write(
        out.join("mutations.json"),
        serde_json::to_string_pretty(&meta)? + "\n",
    )?;
    Ok(meta)
}

// ---------------------------------------------------------------- 工具

fn enum_map(ws: &Workspace) -> EnumMap {
    ws.resources
        .enums
        .iter()
        .map(|e| {
            (
                e.name.clone(),
                EnumDoc {
                    comment: e.comment.clone(),
                    values: e
                        .values
                        .iter()
                        .map(|v| EnumItemDoc {
                            name: v.name.clone(),
                            comment: v.comment.clone(),
                        })
                        .collect(),
                },
            )
        })
        .collect()
}

/// 定宽表的 slot_offsets（与导出路径同源，与 `ct-app::template` 同一算法）。
fn slot_offsets(ws: &Workspace, table: &TableResource) -> Vec<(u32, u32)> {
    if !table.uniform {
        return Vec::new();
    }
    let records = ws.resources.records_map();
    let fields: Vec<&FieldDef> = table.client_fields().collect();
    let Ok(layout) = plan_object_layout(&fields, &records) else {
        return Vec::new();
    };
    (0..fields.len())
        .map(|i| (4 + 2 * i) as u32)
        .zip(layout.offsets.iter().copied())
        .collect()
}

/// 输入语义摘要：忽略 xlsx 里随时间变化的文档属性，只哈希单元格内容与其余文件字节。
fn input_digest(root: &Path) -> Result<String> {
    let mut hasher = Sha256::new();
    let mut entries: Vec<PathBuf> = Vec::new();
    collect_files(root, &mut entries)?;
    entries.sort();
    for path in entries {
        let rel = path
            .strip_prefix(root)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        if rel.starts_with("mutations/") {
            continue; // 变更素材由基准按场景单独复制，不进输入摘要
        }
        hasher.update(rel.as_bytes());
        if path.extension().is_some_and(|ext| ext == "xlsx") {
            let report = ct_excel::reader::probe_xlsx(&path)
                .map_err(|e| anyhow::anyhow!("探测夹具工作簿失败 {}: {e}", path.display()))?;
            let mut cells: Vec<String> = report
                .cells
                .iter()
                .map(|cell| {
                    format!(
                        "{}:{}:{:?}",
                        cell.row,
                        cell.col,
                        match &cell.value {
                            ct_excel::reader::ProbeValue::Text(t) => format!("s{t}"),
                            ct_excel::reader::ProbeValue::Number(n) => format!("n{n}"),
                            ct_excel::reader::ProbeValue::Bool(b) => format!("b{b}"),
                            ct_excel::reader::ProbeValue::DateTime(t) => format!("d{t}"),
                            ct_excel::reader::ProbeValue::Error(t) => format!("e{t}"),
                        }
                    )
                })
                .collect();
            cells.sort();
            for cell in cells {
                hasher.update(cell.as_bytes());
            }
        } else {
            hasher.update(std::fs::read(&path)?);
        }
    }
    Ok(format!("sha256:{:x}", hasher.finalize()))
}

fn collect_files(dir: &Path, out: &mut Vec<PathBuf>) -> Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(&path, out)?;
        } else {
            out.push(path);
        }
    }
    Ok(())
}

fn fnv1a(text: &str) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in text.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn splitmix64(mut state: u64) -> u64 {
    state = state.wrapping_add(0x9E3779B97F4A7C15);
    let mut z = state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

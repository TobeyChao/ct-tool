//! Independent OOXML inspection for frozen openpyxl template expectations.
//! This reader does not call ct-excel's layout, template writer, or cell reader.

use std::collections::BTreeMap;
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use anyhow::{bail, Context, Result};
use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;
use serde_json::{json, Map, Value};

#[derive(Default)]
struct Node {
    name: String,
    attrs: BTreeMap<String, String>,
    text: String,
    children: Vec<Node>,
}

impl Node {
    fn child(&self, name: &str) -> Option<&Node> {
        self.children.iter().find(|node| node.name == name)
    }

    fn required(&self, name: &str) -> Result<&Node> {
        self.child(name)
            .with_context(|| format!("OOXML 缺少 {} / {name}", self.name))
    }

    fn named<'a>(&'a self, name: &'a str) -> impl Iterator<Item = &'a Node> {
        self.children.iter().filter(move |node| node.name == name)
    }

    fn attr(&self, name: &str) -> Option<&str> {
        self.attrs.get(name).map(String::as_str)
    }

    fn texts(&self) -> String {
        if self.name == "t" {
            return self.text.clone();
        }
        self.children.iter().map(Node::texts).collect()
    }
}

fn start_node(event: &BytesStart<'_>, reader: &Reader<&[u8]>) -> Result<Node> {
    let mut node = Node {
        name: String::from_utf8(event.local_name().as_ref().to_vec())?,
        ..Node::default()
    };
    for attr in event.attributes() {
        let attr = attr?;
        let key = String::from_utf8(attr.key.as_ref().to_vec())?;
        let value = attr
            .decoded_and_normalized_value(quick_xml::XmlVersion::Explicit1_0, reader.decoder())?
            .into_owned();
        node.attrs.insert(key, value);
    }
    Ok(node)
}

fn parse_xml(text: &str) -> Result<Node> {
    let mut reader = Reader::from_str(text);
    let mut stack = vec![Node::default()];
    loop {
        match reader.read_event()? {
            Event::Start(event) => stack.push(start_node(&event, &reader)?),
            Event::Empty(event) => {
                let node = start_node(&event, &reader)?;
                stack
                    .last_mut()
                    .context("OOXML 根节点缺失")?
                    .children
                    .push(node);
            }
            Event::End(_) => {
                if stack.len() < 2 {
                    bail!("OOXML 结束标签无对应节点");
                }
                let node = stack.pop().unwrap();
                stack.last_mut().unwrap().children.push(node);
            }
            Event::Text(event) => {
                stack
                    .last_mut()
                    .unwrap()
                    .text
                    .push_str(&quick_xml::escape::unescape(
                        &event.xml_content(quick_xml::XmlVersion::Explicit1_0)?,
                    )?);
            }
            Event::CData(event) => stack
                .last_mut()
                .unwrap()
                .text
                .push_str(&event.xml_content(quick_xml::XmlVersion::Explicit1_0)?),
            Event::GeneralRef(event) => {
                let escaped = format!("&{};", event.decode()?);
                stack
                    .last_mut()
                    .unwrap()
                    .text
                    .push_str(&quick_xml::escape::unescape(&escaped)?);
            }
            Event::DocType(_) => bail!("OOXML 不接受 DTD"),
            Event::Eof => break,
            _ => {}
        }
    }
    if stack.len() != 1 {
        bail!("OOXML 节点未闭合");
    }
    let mut root = stack.pop().unwrap();
    if root.children.len() != 1 {
        bail!("OOXML 必须包含一个根节点");
    }
    Ok(root.children.remove(0))
}

fn xml_member(parts: &BTreeMap<String, String>, name: &str) -> Result<Node> {
    parse_xml(
        parts
            .get(name)
            .with_context(|| format!("工作簿缺少部件 {name}"))?,
    )
    .with_context(|| format!("解析部件失败 {name}"))
}

fn resolve_part(base: &str, target: &str) -> Result<String> {
    let path = if let Some(absolute) = target.strip_prefix('/') {
        PathBuf::from(absolute)
    } else {
        Path::new(base)
            .parent()
            .context("关系源缺少目录")?
            .join(target)
    };
    let mut clean = PathBuf::new();
    for part in path.components() {
        match part {
            Component::Normal(value) => clean.push(value),
            Component::CurDir => {}
            Component::ParentDir => {
                if !clean.pop() {
                    bail!("OOXML 关系路径越界");
                }
            }
            _ => bail!("OOXML 关系路径非法"),
        }
    }
    Ok(clean.to_string_lossy().replace('\\', "/"))
}

fn relationships(parts: &BTreeMap<String, String>, base: &str) -> Result<Node> {
    let base = Path::new(base);
    let relative = base.parent().unwrap().join("_rels").join(format!(
        "{}.rels",
        base.file_name().unwrap().to_string_lossy()
    ));
    let name = relative.to_string_lossy().replace('\\', "/");
    if !parts.contains_key(&name) {
        return Ok(Node::default());
    }
    xml_member(parts, &name)
}

fn coordinate(text: &str) -> Result<(u32, u32)> {
    let split = text
        .find(|ch: char| ch.is_ascii_digit())
        .context("单元格坐标缺少行号")?;
    let (letters, row) = text.split_at(split);
    let mut col = 0u32;
    for ch in letters.bytes() {
        if !ch.is_ascii_uppercase() {
            bail!("非法单元格列 {text}");
        }
        col = col
            .checked_mul(26)
            .and_then(|v| v.checked_add((ch - b'A' + 1) as u32))
            .context("单元格列号溢出")?;
    }
    let row: u32 = row.parse()?;
    if row == 0 || col == 0 {
        bail!("非法单元格坐标 {text}");
    }
    Ok((row, col))
}

fn key(text: &str) -> Result<String> {
    let (row, col) = coordinate(text)?;
    Ok(format!("{row},{col}"))
}

fn column_letter(mut index: u32) -> String {
    let mut letters = Vec::new();
    while index > 0 {
        index -= 1;
        letters.push((b'A' + (index % 26) as u8) as char);
        index /= 26;
    }
    letters.into_iter().rev().collect()
}

fn rich_runs(value: &Node) -> Vec<Value> {
    value
        .named("r")
        .map(|run| {
            let properties = run.child("rPr");
            let font = properties
                .and_then(|node| node.child("rFont"))
                .and_then(|node| node.attr("val"));
            let bold = properties
                .and_then(|node| node.child("b"))
                .is_some_and(|node| !matches!(node.attr("val"), Some("0" | "false")));
            json!({"text": run.texts(), "font": font, "bold": bold})
        })
        .collect()
}

/// Decode the active worksheet, preserving the full frozen semantic contract.
pub fn dump(path: &Path) -> Result<Value> {
    let mut archive = zip::ZipArchive::new(std::fs::File::open(path)?)?;
    let mut parts = BTreeMap::new();
    for index in 0..archive.len() {
        let mut file = archive.by_index(index)?;
        if !(file.name().ends_with(".xml") || file.name().ends_with(".rels")) {
            continue;
        }
        let mut text = String::new();
        file.read_to_string(&mut text)?;
        if parts.insert(file.name().to_string(), text).is_some() {
            bail!("工作簿包含重复部件");
        }
    }
    let workbook = xml_member(&parts, "xl/workbook.xml")?;
    let sheets: Vec<_> = workbook.required("sheets")?.named("sheet").collect();
    let active: usize = workbook
        .child("bookViews")
        .and_then(|node| node.child("workbookView"))
        .and_then(|node| node.attr("activeTab"))
        .unwrap_or("0")
        .parse()?;
    let sheet = sheets.get(active).context("活跃工作表不存在")?;
    let relation = sheet.attr("r:id").context("工作表缺少关系 ID")?;
    let rels = relationships(&parts, "xl/workbook.xml")?;
    let target = rels
        .named("Relationship")
        .find(|node| node.attr("Id") == Some(relation))
        .and_then(|node| node.attr("Target"))
        .context("工作表关系不存在")?;
    let sheet_path = resolve_part("xl/workbook.xml", target)?;
    let worksheet = xml_member(&parts, &sheet_path)?;
    let shared = if parts.contains_key("xl/sharedStrings.xml") {
        xml_member(&parts, "xl/sharedStrings.xml")?
    } else {
        Node::default()
    };
    let strings: Vec<_> = shared.named("si").collect();
    let styles = xml_member(&parts, "xl/styles.xml")?;
    let fills: Vec<_> = styles.required("fills")?.named("fill").collect();
    let formats: Vec<_> = styles.required("cellXfs")?.named("xf").collect();
    let mut cells = Map::new();
    let mut cell_fills = Map::new();
    let mut runs = Map::new();
    let mut heights = Map::new();
    for row in worksheet.required("sheetData")?.named("row") {
        if let (Some(index), Some(height)) = (row.attr("r"), row.attr("ht")) {
            heights.insert(index.into(), json!(height.parse::<f64>()?));
        }
        for cell in row.named("c") {
            let location = key(cell.attr("r").context("单元格缺少坐标")?)?;
            let value = match cell.attr("t") {
                Some("s") => {
                    let index: usize = cell.required("v")?.text.parse()?;
                    let string = strings.get(index).context("共享字符串索引越界")?;
                    let rich = rich_runs(string);
                    if !rich.is_empty() {
                        runs.insert(location.clone(), json!(rich));
                    }
                    Some(string.texts())
                }
                Some("inlineStr") => cell.child("is").map(|string| {
                    let rich = rich_runs(string);
                    if !rich.is_empty() {
                        runs.insert(location.clone(), json!(rich));
                    }
                    string.texts()
                }),
                Some("b") => cell
                    .child("v")
                    .map(|node| if node.text == "1" { "True" } else { "False" }.into()),
                _ => cell.child("v").map(|node| node.text.clone()),
            };
            let Some(value) = value else {
                continue;
            };
            cells.insert(location.clone(), Value::String(value));
            let style: usize = cell.attr("s").unwrap_or("0").parse()?;
            let format = formats.get(style).context("单元格样式索引越界")?;
            let fill: usize = format.attr("fillId").unwrap_or("0").parse()?;
            let fill = fills.get(fill).context("填充索引越界")?;
            if let Some(pattern) = fill
                .child("patternFill")
                .filter(|node| node.attr("patternType") == Some("solid"))
            {
                if let Some(color) = pattern.child("fgColor").and_then(|node| node.attr("rgb")) {
                    cell_fills.insert(location, json!(color));
                }
            }
        }
    }
    let mut merges: Vec<_> = worksheet
        .child("mergeCells")
        .into_iter()
        .flat_map(|node| node.named("mergeCell"))
        .filter_map(|node| node.attr("ref"))
        .collect();
    merges.sort_unstable();
    let freeze = worksheet
        .child("sheetViews")
        .and_then(|node| node.child("sheetView"))
        .and_then(|node| node.child("pane"))
        .and_then(|node| node.attr("topLeftCell"))
        .unwrap_or("None");
    let validations: Vec<_> = worksheet
        .child("dataValidations")
        .into_iter()
        .flat_map(|node| node.named("dataValidation"))
        .map(|node| {
            let kind = node.attr("type");
            let operator = node.attr("operator").or_else(|| match kind {
                Some("whole" | "decimal") => Some("between"),
                _ => None,
            });
            json!({"type": kind, "formula1": node.child("formula1").map(|n| &n.text),
                "formula2": node.child("formula2").map(|n| &n.text),
                "operator": operator, "sqref": node.attr("sqref")})
        })
        .collect();
    let mut widths = Map::new();
    for column in worksheet
        .child("cols")
        .into_iter()
        .flat_map(|node| node.named("col"))
    {
        let Some(width) = column.attr("width") else {
            continue;
        };
        let start: u32 = column.attr("min").context("列尺寸缺少 min")?.parse()?;
        let end: u32 = column.attr("max").context("列尺寸缺少 max")?.parse()?;
        if start == 0 || end > 16_384 || start > end {
            bail!("列尺寸范围非法");
        }
        for index in start..=end {
            widths.insert(column_letter(index), json!(width.parse::<f64>()?));
        }
    }
    let mut notes = Map::new();
    for relation in relationships(&parts, &sheet_path)?.named("Relationship") {
        if relation
            .attr("Type")
            .is_some_and(|kind| kind.ends_with("/comments"))
        {
            let name = resolve_part(
                &sheet_path,
                relation.attr("Target").context("批注关系缺少目标")?,
            )?;
            let comments = xml_member(&parts, &name)?;
            for comment in comments.required("commentList")?.named("comment") {
                notes.insert(
                    key(comment.attr("ref").context("批注缺少坐标")?)?,
                    json!(comment.texts()),
                );
            }
        }
    }
    let mut props = Map::new();
    if parts.contains_key("docProps/custom.xml") {
        for property in xml_member(&parts, "docProps/custom.xml")?.named("property") {
            let name = property.attr("name").context("自定义属性缺少名称")?;
            let child = property.children.first().context("自定义属性缺少值")?;
            let value = if name == "ct_generated_at" {
                json!("<timestamp>")
            } else if matches!(child.name.as_str(), "i4" | "int") {
                json!(child.text.parse::<i64>()?)
            } else if child.name == "bool" {
                json!(matches!(child.text.as_str(), "true" | "1"))
            } else {
                json!(child.text)
            };
            props.insert(name.into(), value);
        }
    }
    Ok(normalize(
        json!({"sheet": sheet.attr("name"), "cells": cells, "fills": cell_fills,
        "rich_runs": runs, "merges": merges, "freeze": freeze, "validations": validations,
        "notes": notes, "col_widths": widths, "row_heights": heights, "props": props}),
    ))
}

pub fn normalize(mut value: Value) -> Value {
    if let Some(fills) = value["fills"].as_object_mut() {
        for color in fills.values_mut() {
            if let Some(text) = color.as_str().filter(|text| text.len() == 8) {
                *color = json!(&text[2..]);
            }
        }
    }
    if let Some(widths) = value["col_widths"].as_object_mut() {
        for width in widths.values_mut() {
            if let Some(number) = width.as_f64() {
                if (number.fract() - 0.7109375).abs() < 0.01 {
                    *width = json!(number.trunc());
                }
            }
        }
    }
    if let Some(heights) = value["row_heights"].as_object_mut() {
        for height in heights.values_mut() {
            if let Some(number) = height.as_f64() {
                *height = json!(number.round());
            }
        }
    }
    value
}

pub fn compare(workbook: &Path, expected: &Path) -> Result<()> {
    let actual = dump(workbook)?;
    let expected = normalize(serde_json::from_slice(&std::fs::read(expected)?)?);
    let mut problems = Vec::new();
    diff(&actual, &expected, "$", &mut problems);
    if !problems.is_empty() {
        bail!(
            "模板语义存在 {} 处差异：\n{}",
            problems.len(),
            problems
                .iter()
                .take(20)
                .cloned()
                .collect::<Vec<_>>()
                .join("\n")
        );
    }
    Ok(())
}

fn diff(actual: &Value, expected: &Value, path: &str, problems: &mut Vec<String>) {
    match (actual, expected) {
        (Value::Object(a), Value::Object(b)) => {
            let keys: std::collections::BTreeSet<_> = a.keys().chain(b.keys()).collect();
            for key in keys {
                let sub = format!("{path}.{key}");
                match (a.get(key), b.get(key)) {
                    (Some(a), Some(b)) => diff(a, b, &sub, problems),
                    _ => problems.push(format!(
                        "{sub}: actual={:?}, expected={:?}",
                        a.get(key),
                        b.get(key)
                    )),
                }
            }
        }
        (Value::Array(a), Value::Array(b)) if a.len() == b.len() => {
            for (index, (a, b)) in a.iter().zip(b).enumerate() {
                diff(a, b, &format!("{path}[{index}]"), problems);
            }
        }
        _ if actual != expected => {
            problems.push(format!("{path}: actual={actual}, expected={expected}"))
        }
        _ => {}
    }
}

//! 表级 FlatBuffers 与 Bundle 生成（任务 1.7 原型）。
//!
//! 逐行为移植 `ct/export/canonical_binary.py`：uniform 定宽布局、
//! 默认值槽位省略、共享字符串、主键有序索引、idHash/CodeName 开放寻址桶。
//! 字节一致性对照见 `tests/compat/tests/binary_golden.rs`。

use std::collections::HashMap;

use anyhow::{bail, Result};
use serde_json::{Map, Value};

use ct_domain::schema::{EnumResource, FieldDef, RecordResource, TableResource, CODENAME_FIELD};
use ct_domain::types::TypeExpr;

use crate::flat_builder::{Builder, UOffset};

/// FNV-1a 64（`ct/export/index_query.py::production_hash` 的口径）。
fn fnv1a_64(text: &str) -> u64 {
    let mut value: u64 = 0xCBF29CE484222325;
    for byte in text.as_bytes() {
        value ^= u64::from(*byte);
        value = value.wrapping_mul(0x100000001B3);
    }
    value
}

/// 标量宽度/对齐（`_SCALAR_PREPENDS`）。
fn scalar_width(name: &str) -> Option<u32> {
    Some(match name {
        "int8" | "uint8" | "bool" => 1,
        "int16" | "uint16" => 2,
        "int32" | "uint32" | "float" => 4,
        "int64" | "uint64" | "double" => 8,
        _ => return None,
    })
}

/// Schema 推导的对象布局（`plan_object_layout`）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectLayout {
    pub offsets: Vec<u32>,
    pub widths: Vec<u32>,
    pub alignment: u32,
    pub size: u32,
}

pub fn plan_object_layout(
    fields: &[&FieldDef],
    records: &HashMap<String, RecordResource>,
) -> Result<ObjectLayout> {
    let mut offsets = Vec::with_capacity(fields.len());
    let mut widths = Vec::with_capacity(fields.len());
    let mut cursor = 4u32; // 有符号 vtable 引用
    let mut alignment = 4u32;
    for field in fields {
        let width = match &field.type_expr {
            TypeExpr::Scalar(name) if name != "string" => {
                scalar_width(name).ok_or_else(|| anyhow::anyhow!("不支持的标量类型 {name}"))?
            }
            TypeExpr::Named(named) if !records.contains_key(named.name()) => 1, // enum
            _ => 4, // string/vector/record
        };
        alignment = alignment.max(width);
        cursor = (cursor + width - 1) & !(width - 1);
        offsets.push(cursor);
        widths.push(width);
        cursor += width;
    }
    let size = (cursor + alignment - 1) & !(alignment - 1);
    if size > 65535 || 4 + 2 * fields.len() as u32 > 65535 {
        bail!("FlatBuffers object/vtable exceeds uint16 layout limit");
    }
    Ok(ObjectLayout {
        offsets,
        widths,
        alignment,
        size,
    })
}

type Row = Map<String, Value>;

fn as_i64(v: Option<&Value>) -> Option<i64> {
    match v {
        None | Some(Value::Null) => None,
        Some(Value::Number(n)) => n
            .as_i64()
            .or_else(|| n.as_u64().and_then(|u| i64::try_from(u).ok())),
        _ => None,
    }
}

fn as_u64(v: Option<&Value>) -> Option<u64> {
    match v {
        None | Some(Value::Null) => None,
        Some(Value::Number(n)) => n
            .as_u64()
            .or_else(|| n.as_i64().and_then(|i| u64::try_from(i).ok())),
        _ => None,
    }
}

fn as_f64(v: Option<&Value>) -> Option<f64> {
    match v {
        None | Some(Value::Null) => None,
        Some(Value::Number(n)) => n.as_f64(),
        _ => None,
    }
}

fn as_str(v: Option<&Value>) -> Option<&str> {
    match v {
        Some(Value::String(s)) => Some(s),
        _ => None,
    }
}

/// canonical 表二进制构建器。
pub struct BinaryBuilder<'a> {
    pub records: &'a HashMap<String, RecordResource>,
    pub enums: &'a HashMap<String, EnumResource>,
    pub uniform: bool,
}

impl BinaryBuilder<'_> {
    fn is_record_ref(&self, named: &ct_domain::types::NamedRef) -> bool {
        self.records.contains_key(named.name())
    }

    fn is_offset_type(&self, expr: &TypeExpr) -> bool {
        match expr {
            TypeExpr::Scalar(name) => name == "string",
            TypeExpr::Vector(_) => true,
            TypeExpr::Named(named) => self.is_record_ref(named),
        }
    }

    fn enum_index(&self, name: &str, value: Option<&Value>) -> Result<i8> {
        let Some(enum_res) = self.enums.get(name) else {
            bail!("Enum {name}: 未声明");
        };
        let text = as_str(value).unwrap_or("");
        if text.is_empty() {
            // 空格子沿用默认（ordinal 0）语义；域校验由数据闸门负责
            return Ok(0);
        }
        match enum_res.values.iter().position(|v| v.name == text) {
            Some(idx) => Ok(idx as i8),
            None => bail!("Enum {name}: 值 {text:?} 不在声明值中"),
        }
    }

    fn prepend_scalar_slot(
        &self,
        builder: &mut Builder,
        name: &str,
        value: Option<&Value>,
        slot: usize,
    ) -> Result<()> {
        match name {
            "int8" => builder.prepend_i8_slot(slot, as_i64(value).unwrap_or(0) as i8, 0),
            "uint8" => builder.prepend_u8_slot(slot, as_u64(value).unwrap_or(0) as u8, 0),
            "int16" => builder.prepend_i16_slot(slot, as_i64(value).unwrap_or(0) as i16, 0),
            "uint16" => builder.prepend_u16_slot(slot, as_u64(value).unwrap_or(0) as u16, 0),
            "int32" => builder.prepend_i32_slot(slot, as_i64(value).unwrap_or(0) as i32, 0),
            "uint32" => builder.prepend_u32_slot(slot, as_u64(value).unwrap_or(0) as u32, 0),
            "int64" => builder.prepend_i64_slot(slot, as_i64(value).unwrap_or(0), 0),
            "uint64" => builder.prepend_u64_slot(slot, as_u64(value).unwrap_or(0), 0),
            "float" => builder.prepend_f32_slot(slot, as_f64(value).unwrap_or(0.0) as f32, 0.0),
            "double" => builder.prepend_f64_slot(slot, as_f64(value).unwrap_or(0.0), 0.0),
            "bool" => {
                builder.prepend_bool_slot(slot, matches!(value, Some(Value::Bool(true))), false)
            }
            _ => bail!("不支持的标量类型 {name}"),
        }
        Ok(())
    }

    /// uniform：无条件写槽位（默认值也占位）。
    fn prepend_scalar_unconditional(
        &self,
        builder: &mut Builder,
        name: &str,
        value: Option<&Value>,
        slot: usize,
    ) -> Result<()> {
        match name {
            "int8" => builder.prepend_i8(as_i64(value).unwrap_or(0) as i8),
            "uint8" => builder.prepend_u8(as_u64(value).unwrap_or(0) as u8),
            "int16" => builder.prepend_i16(as_i64(value).unwrap_or(0) as i16),
            "uint16" => builder.prepend_u16(as_u64(value).unwrap_or(0) as u16),
            "int32" => builder.prepend_i32(as_i64(value).unwrap_or(0) as i32),
            "uint32" => builder.prepend_u32(as_u64(value).unwrap_or(0) as u32),
            "int64" => builder.prepend_i64(as_i64(value).unwrap_or(0)),
            "uint64" => builder.prepend_u64(as_u64(value).unwrap_or(0)),
            "float" => builder.prepend_f32(as_f64(value).unwrap_or(0.0) as f32),
            "double" => builder.prepend_f64(as_f64(value).unwrap_or(0.0)),
            "bool" => builder.prepend_bool(matches!(value, Some(Value::Bool(true)))),
            _ => bail!("uniform 布局不支持标量 {name}"),
        }
        builder.slot(slot);
        Ok(())
    }

    fn build_offset(
        &self,
        builder: &mut Builder,
        expr: &TypeExpr,
        value: Option<&Value>,
        required: bool,
    ) -> Result<Option<UOffset>> {
        match expr {
            TypeExpr::Scalar(name) if name == "string" => {
                let absent = value.is_none() || matches!(value, Some(Value::Null));
                if absent && !required {
                    return Ok(None);
                }
                let text = as_str(value).unwrap_or("");
                Ok(Some(builder.create_shared_string(text)))
            }
            TypeExpr::Scalar(_) | TypeExpr::Named(_) if !self.is_offset_type(expr) => Ok(None),
            TypeExpr::Vector(element) => {
                let values = match value {
                    Some(Value::Array(items)) => items.as_slice(),
                    _ => &[],
                };
                Ok(Some(self.build_vector(builder, element, values)?))
            }
            TypeExpr::Named(named) => {
                let record = &self.records[named.name()];
                self.build_record(builder, record, value)
            }
            _ => Ok(None),
        }
    }

    fn build_vector(
        &self,
        builder: &mut Builder,
        element: &TypeExpr,
        values: &[Value],
    ) -> Result<UOffset> {
        match element {
            TypeExpr::Named(named) if self.is_record_ref(named) => {
                let record = &self.records[named.name()];
                let mut offsets = Vec::with_capacity(values.len());
                for v in values {
                    let off = self.build_record(builder, record, Some(v))?;
                    offsets.push(off.unwrap_or(0));
                }
                builder.start_vector(4, offsets.len(), 4);
                for off in offsets.iter().rev() {
                    builder.prepend_uoffset(*off);
                }
                Ok(builder.end_vector())
            }
            TypeExpr::Named(named) => {
                builder.start_vector(1, values.len(), 1);
                for v in values.iter().rev() {
                    let idx = self.enum_index(named.name(), Some(v))?;
                    builder.prepend_u8(idx as u8);
                }
                Ok(builder.end_vector())
            }
            TypeExpr::Scalar(name) if name == "string" => {
                let mut offsets = Vec::with_capacity(values.len());
                for v in values {
                    offsets.push(builder.create_shared_string(as_str(Some(v)).unwrap_or("")));
                }
                builder.start_vector(4, offsets.len(), 4);
                for off in offsets.iter().rev() {
                    builder.prepend_uoffset(*off);
                }
                Ok(builder.end_vector())
            }
            TypeExpr::Scalar(name) => {
                let width = scalar_width(name)
                    .ok_or_else(|| anyhow::anyhow!("vector 不支持的元素标量类型 {name}"))?;
                builder.start_vector(width as usize, values.len(), width as usize);
                for v in values.iter().rev() {
                    self.prepend_scalar_element(builder, name, Some(v))?;
                }
                Ok(builder.end_vector())
            }
            TypeExpr::Vector(_) => bail!("不支持的嵌套 vector"),
        }
    }

    fn prepend_scalar_element(
        &self,
        builder: &mut Builder,
        name: &str,
        value: Option<&Value>,
    ) -> Result<()> {
        match name {
            "int8" => builder.prepend_i8(as_i64(value).unwrap_or(0) as i8),
            "uint8" => builder.prepend_u8(as_u64(value).unwrap_or(0) as u8),
            "int16" => builder.prepend_i16(as_i64(value).unwrap_or(0) as i16),
            "uint16" => builder.prepend_u16(as_u64(value).unwrap_or(0) as u16),
            "int32" => builder.prepend_i32(as_i64(value).unwrap_or(0) as i32),
            "uint32" => builder.prepend_u32(as_u64(value).unwrap_or(0) as u32),
            "int64" => builder.prepend_i64(as_i64(value).unwrap_or(0)),
            "uint64" => builder.prepend_u64(as_u64(value).unwrap_or(0)),
            "float" => builder.prepend_f32(as_f64(value).unwrap_or(0.0) as f32),
            "double" => builder.prepend_f64(as_f64(value).unwrap_or(0.0)),
            "bool" => builder.prepend_bool(matches!(value, Some(Value::Bool(true)))),
            _ => bail!("vector 不支持的元素标量类型 {name}"),
        }
        Ok(())
    }

    fn build_record(
        &self,
        builder: &mut Builder,
        record: &RecordResource,
        data: Option<&Value>,
    ) -> Result<Option<UOffset>> {
        let data_obj: Option<&Row> = match data {
            Some(Value::Object(map)) => Some(map),
            _ => None,
        };
        if data_obj.is_none() && !self.uniform {
            return Ok(None);
        }
        let empty;
        let data: &Row = match data_obj {
            Some(map) => map,
            None => {
                empty = Map::new();
                &empty
            }
        };
        let fields: Vec<&FieldDef> = record.fields.iter().collect();
        let mut offsets: HashMap<usize, UOffset> = HashMap::new();
        for (index, field) in fields.iter().enumerate() {
            if self.is_offset_type(&field.type_expr) {
                if let Some(off) = self.build_offset(
                    builder,
                    &field.type_expr,
                    data.get(&field.name),
                    self.uniform,
                )? {
                    offsets.insert(index, off);
                }
            }
        }
        if self.uniform {
            return Ok(Some(
                self.build_uniform_object(builder, &fields, data, &offsets)?,
            ));
        }
        builder.start_object(fields.len());
        for (index, field) in fields.iter().enumerate() {
            if let Some(&off) = offsets.get(&index) {
                builder.prepend_uoffset_slot(index, off, 0);
            } else if self.is_offset_type(&field.type_expr) {
                continue; // None 的 string/vector/record：槽位缺省
            } else {
                match &field.type_expr {
                    TypeExpr::Scalar(name) => {
                        self.prepend_scalar_slot(builder, name, data.get(&field.name), index)?
                    }
                    TypeExpr::Named(named) => {
                        let idx = self.enum_index(named.name(), data.get(&field.name))?;
                        builder.prepend_i8_slot(index, idx, 0);
                    }
                    TypeExpr::Vector(_) => unreachable!("vector 是 offset 类型"),
                }
            }
        }
        Ok(Some(builder.end_object()))
    }

    /// uniform 定宽对象：每个槽位无条件写出，全表共享同一 vtable。
    fn build_uniform_object(
        &self,
        builder: &mut Builder,
        fields: &[&FieldDef],
        data: &Row,
        offsets: &HashMap<usize, UOffset>,
    ) -> Result<UOffset> {
        let layout = plan_object_layout(fields, self.records)?;
        // 先对齐 END：外部填充不计入对象大小
        builder.prep(layout.alignment as usize, layout.size as usize);
        builder.start_object(fields.len());
        let mut cursor = layout.size;
        for index in (0..fields.len()).rev() {
            let field = fields[index];
            let position = layout.offsets[index];
            builder.pad((cursor - position - layout.widths[index]) as usize);
            if self.is_offset_type(&field.type_expr) {
                let off = *offsets
                    .get(&index)
                    .ok_or_else(|| anyhow::anyhow!("uniform 缺少 offset 槽位 {}", field.name))?;
                builder.prepend_uoffset(off);
                builder.slot(index);
            } else {
                match &field.type_expr {
                    TypeExpr::Scalar(name) => self.prepend_scalar_unconditional(
                        builder,
                        name,
                        data.get(&field.name),
                        index,
                    )?,
                    TypeExpr::Named(named) => {
                        let idx = self.enum_index(named.name(), data.get(&field.name))?;
                        builder.prepend_i8(idx);
                        builder.slot(index);
                    }
                    TypeExpr::Vector(_) => unreachable!("vector 是 offset 类型"),
                }
            }
            cursor = position;
        }
        builder.pad((cursor - 4) as usize);
        let result = builder.end_object();

        // 每个对象都回读校验实际布局（含嵌套 record）。
        // soffset 可正可负：vtable 去重后可能引用地址更高的既有 vtable。
        let buf = builder.output();
        let row = buf.len() - result as usize;
        let soffset = i32::from_le_bytes(buf[row..row + 4].try_into().unwrap());
        let vt = (row as isize - soffset as isize) as usize;
        let actual_size = u16::from_le_bytes(buf[vt + 2..vt + 4].try_into().unwrap());
        for (index, _) in fields.iter().enumerate() {
            let actual_off = u16::from_le_bytes(
                buf[vt + 4 + 2 * index..vt + 6 + 2 * index]
                    .try_into()
                    .unwrap(),
            );
            if actual_off as u32 != layout.offsets[index] {
                bail!("uniform vtable/object 与 schema 布局不符（槽位 {index}）");
            }
        }
        if result % layout.alignment != 0 || actual_size as u32 != layout.size {
            bail!("uniform vtable/object 与 schema 布局不符（size/alignment）");
        }
        Ok(result)
    }

    fn build_row(&self, builder: &mut Builder, fields: &[&FieldDef], row: &Row) -> Result<UOffset> {
        let mut offsets: HashMap<usize, UOffset> = HashMap::new();
        for (index, field) in fields.iter().enumerate() {
            if self.is_offset_type(&field.type_expr) {
                if let Some(off) = self.build_offset(
                    builder,
                    &field.type_expr,
                    row.get(&field.name),
                    self.uniform,
                )? {
                    offsets.insert(index, off);
                }
            }
        }
        if self.uniform {
            return self.build_uniform_object(builder, fields, row, &offsets);
        }
        builder.start_object(fields.len());
        for (index, field) in fields.iter().enumerate() {
            if let Some(&off) = offsets.get(&index) {
                builder.prepend_uoffset_slot(index, off, 0);
            } else if self.is_offset_type(&field.type_expr) {
                continue;
            } else {
                match &field.type_expr {
                    TypeExpr::Scalar(name) => {
                        self.prepend_scalar_slot(builder, name, row.get(&field.name), index)?
                    }
                    TypeExpr::Named(named) => {
                        let idx = self.enum_index(named.name(), row.get(&field.name))?;
                        builder.prepend_i8_slot(index, idx, 0);
                    }
                    TypeExpr::Vector(_) => unreachable!("vector 是 offset 类型"),
                }
            }
        }
        Ok(builder.end_object())
    }

    /// CodeName 索引：FNV-1a 桶表，桶里存 rowIndex+1（0 = 空）。
    fn build_code_index(&self, builder: &mut Builder, rows: &[Row]) -> UOffset {
        let mut slots = 1usize;
        while slots < (rows.len() * 10 + 6).div_ceil(7).max(8) {
            slots <<= 1;
        }
        let mask = slots - 1;
        let mut buckets = vec![0i32; slots];
        for (row_index, row) in rows.iter().enumerate() {
            let text = as_str(row.get(CODENAME_FIELD)).unwrap_or("");
            if text.is_empty() {
                continue;
            }
            let mut probe = (fnv1a_64(text) as usize) & mask;
            while buckets[probe] != 0 {
                probe = (probe + 1) & mask;
            }
            buckets[probe] = row_index as i32 + 1;
        }
        builder.start_vector(4, slots, 4);
        for v in buckets.iter().rev() {
            builder.prepend_i32(*v);
        }
        builder.end_vector()
    }

    /// 构建表级缓冲区（容器：items + 主键有序索引 + idHash + CodeName 索引）。
    pub fn build(&self, builder: &mut Builder, table: &TableResource, rows: &[Row]) -> Result<()> {
        let fields: Vec<&FieldDef> = table.client_fields().collect();
        let mut row_offsets = Vec::with_capacity(rows.len());
        for row in rows {
            row_offsets.push(self.build_row(builder, &fields, row)?);
        }

        builder.start_vector(4, row_offsets.len(), 4);
        for off in row_offsets.iter().rev() {
            builder.prepend_uoffset(*off);
        }
        let items_vec = builder.end_vector();

        let mut index_vec = None;
        let mut hash_vec = None;
        if let Some(primary) = table.primary_key() {
            let mut ordered: Vec<(usize, i32)> = rows
                .iter()
                .enumerate()
                .map(|(i, row)| (i, as_i64(row.get(primary)).unwrap_or(0) as i32))
                .collect();
            ordered.sort_by_key(|(_, key)| *key);

            builder.start_vector(8, ordered.len(), 4);
            for (original_index, key) in ordered.iter().rev() {
                builder.prepend_i32(*original_index as i32);
                builder.prepend_i32(*key);
            }
            index_vec = Some(builder.end_vector());

            // idHash：Knuth 乘法哈希 + 开放寻址，桶存「index 向量位置 + 1」
            let mut slots = 1usize;
            while slots < (rows.len() * 10 + 6).div_ceil(7).max(8) {
                slots <<= 1;
            }
            let mask = slots - 1;
            let mut buckets = vec![0i32; slots];
            for (pos, (original_index, _)) in ordered.iter().enumerate() {
                let key = as_i64(rows[*original_index].get(primary)).unwrap_or(0) as i32;
                let h = (key as u32).wrapping_mul(2654435761);
                let mut b = (h as usize) & mask;
                while buckets[b] != 0 {
                    b = (b + 1) & mask;
                }
                buckets[b] = pos as i32 + 1;
            }
            builder.start_vector(4, slots, 4);
            for v in buckets.iter().rev() {
                builder.prepend_i32(*v);
            }
            hash_vec = Some(builder.end_vector());
        }

        let code_vec = table
            .indexes
            .iter()
            .any(|_| true) // 当前仅 codename 一种索引
            .then(|| self.build_code_index(builder, rows));

        // vtable 槽位数覆盖最高用到的 slot
        let mut num_fields = 1;
        if index_vec.is_some() {
            num_fields = 2;
        }
        if hash_vec.is_some() {
            num_fields = 3;
        }
        if code_vec.is_some() {
            num_fields = 4;
        }
        builder.start_object(num_fields);
        builder.prepend_uoffset_slot(0, items_vec, 0);
        if let Some(v) = index_vec {
            builder.prepend_uoffset_slot(1, v, 0);
        }
        if let Some(v) = hash_vec {
            builder.prepend_uoffset_slot(2, v, 0);
        }
        if let Some(v) = code_vec {
            builder.prepend_uoffset_slot(3, v, 0);
        }
        let container = builder.end_object();
        builder.finish(container);
        Ok(())
    }
}

/// 表级二进制（server_only 字段不进入客户端缓冲区）。
pub fn build_canonical_table_bytes(
    table: &TableResource,
    rows: &[Row],
    builder_state: &BinaryBuilder,
) -> Result<Vec<u8>> {
    let mut builder = Builder::new(1024);
    builder_state.build(&mut builder, table, rows)?;
    Ok(builder.output().to_vec())
}

/// DataBundle：按表名排序打包。
/// `parts` 允许借用字节：bundle 组装只需要读，不必再把每表字节复制一份。
pub fn build_canonical_bundle<S: AsRef<[u8]>>(parts: &HashMap<String, S>) -> Vec<u8> {
    let mut builder = Builder::new(1024);
    let mut entries = Vec::with_capacity(parts.len());
    let mut names: Vec<&String> = parts.keys().collect();
    names.sort();
    for name in names {
        let data_vec = builder.create_byte_vector(parts[name].as_ref());
        let name_off = builder.create_string(name);
        builder.start_object(2);
        builder.prepend_uoffset_slot(0, name_off, 0);
        builder.prepend_uoffset_slot(1, data_vec, 0);
        entries.push(builder.end_object());
    }
    builder.start_vector(4, entries.len(), 4);
    for off in entries.iter().rev() {
        builder.prepend_uoffset(*off);
    }
    let tables_vec = builder.end_vector();
    builder.start_object(1);
    builder.prepend_uoffset_slot(0, tables_vec, 0);
    let root = builder.end_object();
    builder.finish(root);
    builder.output().to_vec()
}

/// 行 vtable 位置序列：(row_vtable_pos, vtable_len)。
fn row_vtables(data: &[u8]) -> Vec<(usize, usize)> {
    let i32_at = |pos: usize| i32::from_le_bytes(data[pos..pos + 4].try_into().unwrap());
    let u16_at = |pos: usize| u16::from_le_bytes(data[pos..pos + 2].try_into().unwrap());
    let sub = |pos: usize| (pos as isize - i32_at(pos) as isize) as usize;
    let container = i32_at(0) as usize;
    let cvt = sub(container);
    let cvt_len = u16_at(cvt) as usize;
    if 4 >= cvt_len {
        return Vec::new();
    }
    let items_off = u16_at(cvt + 4) as usize;
    if items_off == 0 {
        return Vec::new();
    }
    let items = container + items_off + i32_at(container + items_off) as usize;
    let count = i32_at(items) as usize;
    let mut rows = Vec::with_capacity(count);
    for index in 0..count {
        let element = items + 4 + index * 4;
        let row = element + i32_at(element) as usize;
        let vt = sub(row);
        rows.push((vt, u16_at(vt) as usize));
    }
    rows
}

/// 统计缓冲区中不同的行 vtable 数（uniform 必须为 1）。
pub fn count_vtables(data: &[u8]) -> usize {
    let mut seen = std::collections::HashSet::new();
    for (vt, vt_len) in row_vtables(data) {
        seen.insert(&data[vt..vt + vt_len]);
    }
    seen.len()
}

/// 已写出槽位比例（= 填充率），直接从产出字节统计，不复刻写入规则。
/// `client_field_count` 应传入客户端字段数（server_only 不进二进制）。
pub fn written_slot_ratio(data: &[u8], client_field_count: usize) -> f64 {
    let rows = row_vtables(data);
    if rows.is_empty() {
        return 1.0;
    }
    let mut total = 0usize;
    let mut written = 0usize;
    for (vt, vt_len) in rows {
        for index in 0..client_field_count {
            let slot = 4 + 2 * index;
            total += 1;
            if slot + 2 <= vt_len
                && u16::from_le_bytes(data[vt + slot..vt + slot + 2].try_into().unwrap()) != 0
            {
                written += 1;
            }
        }
    }
    written as f64 / total as f64
}
